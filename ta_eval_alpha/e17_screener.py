"""Gate E17: Deterministic Nightly Candidate Screener v1.

Cheap, deterministic, point-in-time safe market-data-only screener.
Three transparent opportunity lanes → round-robin top-30 candidates.

NO LLM calls. NO news/social/fundamental data. NO future returns.
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

OUTPUT_DIR = Path("evaluations/gate_e17_deterministic_screener")
UNIVERSE_PATH = Path("evaluations/gate_d_pilot/universe_snapshot.json")
BENCHMARK = "SPY"
MAX_CANDIDATES = 30
MAX_PER_LANE = 15
CONTROL_COHORT_SIZE = 10
MIN_HISTORY = 252
MIN_PRICE = 5.0
MIN_DOLLAR_VOLUME_20 = 20_000_000
BATCH_SIZE = 100  # yfinance batch download size


# ---------------------------------------------------------------------------
# RSI implementation (Wilder's smoothing, deterministic)
# ---------------------------------------------------------------------------


def compute_rsi(close: pd.Series, period: int = 14) -> float:
    """Compute RSI using Wilder's smoothing method.

    delta = close.diff()
    gain = max(delta, 0), loss = -min(delta, 0)
    avg_gain = ewm(alpha=1/period, min_periods=period).mean()
    avg_loss = same
    rs = avg_gain / avg_loss
    rsi = 100 - 100/(1+rs)

    When avg_loss is 0 (all gains), RSI = 100.
    When avg_gain is 0 (all losses), RSI = 0.

    Returns the last RSI value or np.nan if insufficient data.
    """
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    # Handle division by zero: all gains → RSI=100, all losses → RSI=0
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - 100 / (1 + rs)
    # When avg_loss is 0 but avg_gain > 0, RSI should be 100
    rsi = rsi.where(avg_loss > 0, 100.0)
    # When both avg_gain and avg_loss are 0, RSI is 50 (neutral)
    rsi = rsi.where((avg_gain > 0) | (avg_loss > 0), 50.0)
    return rsi.iloc[-1] if len(rsi) >= period else np.nan


# ---------------------------------------------------------------------------
# Feature computation
# ---------------------------------------------------------------------------


def compute_features(
    close: pd.Series, high: pd.Series, volume: pd.Series, spy_close: pd.Series
) -> dict | None:
    """Compute all screener features for a single ticker.

    Returns None if any required feature cannot be computed.
    """
    if len(close) < MIN_HISTORY:
        return None

    # Returns
    ret_5 = close.pct_change(5).iloc[-1]
    ret_20 = close.pct_change(20).iloc[-1]
    ret_60 = close.pct_change(60).iloc[-1]

    # SPY returns (aligned)
    spy_ret_20 = spy_close.pct_change(20).iloc[-1]
    spy_ret_60 = spy_close.pct_change(60).iloc[-1]

    # Relative strength
    rs_20 = ret_20 - spy_ret_20
    rs_60 = ret_60 - spy_ret_60

    # Moving averages
    sma_20 = close.rolling(20).mean().iloc[-1]
    sma_50 = close.rolling(50).mean().iloc[-1]
    sma_200 = close.rolling(200).mean().iloc[-1]

    if any(pd.isna(v) for v in [sma_20, sma_50, sma_200]):
        return None

    trend_50_200 = sma_50 / sma_200 - 1

    # 20-session high
    high_20 = high.rolling(20).max().iloc[-1]
    if pd.isna(high_20) or high_20 == 0:
        return None

    proximity_20_high = close.iloc[-1] / high_20
    pullback_20 = 1 - proximity_20_high

    # RSI
    rsi_14 = compute_rsi(close, 14)
    if pd.isna(rsi_14):
        return None

    # Dollar volume
    dollar_volume = close * volume
    avg_dv_5 = dollar_volume.rolling(5).mean().iloc[-1]
    avg_dv_20 = dollar_volume.rolling(20).mean().iloc[-1]  # MEAN per spec
    median_dv_20 = dollar_volume.rolling(20).median().iloc[-1]  # MEDIAN for eligibility

    if pd.isna(avg_dv_5) or pd.isna(avg_dv_20) or avg_dv_20 == 0:
        return None

    volume_ratio_5_20 = avg_dv_5 / avg_dv_20

    return {
        "close": close.iloc[-1],
        "ret_5": ret_5,
        "ret_20": ret_20,
        "ret_60": ret_60,
        "spy_ret_20": spy_ret_20,
        "spy_ret_60": spy_ret_60,
        "rs_20": rs_20,
        "rs_60": rs_60,
        "sma_20": sma_20,
        "sma_50": sma_50,
        "sma_200": sma_200,
        "trend_50_200": trend_50_200,
        "high_20": high_20,
        "proximity_20_high": proximity_20_high,
        "pullback_20": pullback_20,
        "rsi_14": rsi_14,
        "avg_dollar_volume_5": avg_dv_5,
        "avg_dollar_volume_20": avg_dv_20,
        "median_dollar_volume_20": median_dv_20,
        "volume_ratio_5_20": volume_ratio_5_20,
    }


# ---------------------------------------------------------------------------
# Lane eligibility and scoring
# ---------------------------------------------------------------------------


def lane_a_eligible(f: dict) -> bool:
    """Lane A — Trend Momentum."""
    return (
        f["close"] > f["sma_50"]
        and f["sma_50"] > f["sma_200"]
        and f["rs_20"] > 0
        and f["rs_60"] > 0
    )


def lane_b_eligible(f: dict) -> bool:
    """Lane B — Pullback in Established Uptrend."""
    return (
        f["close"] > f["sma_200"]
        and f["sma_50"] > f["sma_200"]
        and f["rs_60"] > 0
        and 0.03 <= f["pullback_20"] <= 0.12
        and 35 <= f["rsi_14"] <= 55
    )


def lane_c_eligible(f: dict) -> bool:
    """Lane C — Breakout / Acceleration Setup."""
    return (
        f["close"] > f["sma_50"]
        and f["sma_50"] > f["sma_200"]
        and f["proximity_20_high"] >= 0.98
        and f["ret_5"] > 0
        and f["rs_20"] > 0
        and f["volume_ratio_5_20"] >= 1.0
    )


def cross_sectional_percentile(series: pd.Series) -> pd.Series:
    """Deterministic percentile ranking.

    Uses pandas.rank(method='average', pct=True).
    Larger raw values → larger percentiles.
    NaN → 0.0 (treated as lowest).
    """
    ranked = series.rank(method="average", pct=True)
    return ranked.fillna(0.0)


def score_lane_a(features_df: pd.DataFrame) -> pd.Series:
    """Score Lane A eligible names."""
    eligible = features_df[features_df.apply(lane_a_eligible, axis=1)].copy()
    if eligible.empty:
        return pd.Series(dtype=float)
    p_rs20 = cross_sectional_percentile(eligible["rs_20"])
    p_rs60 = cross_sectional_percentile(eligible["rs_60"])
    p_trend = cross_sectional_percentile(eligible["trend_50_200"])
    p_vol = cross_sectional_percentile(eligible["volume_ratio_5_20"])
    return 0.35 * p_rs20 + 0.35 * p_rs60 + 0.20 * p_trend + 0.10 * p_vol


def score_lane_b(features_df: pd.DataFrame) -> pd.Series:
    """Score Lane B eligible names."""
    eligible = features_df[features_df.apply(lane_b_eligible, axis=1)].copy()
    if eligible.empty:
        return pd.Series(dtype=float)
    p_rs60 = cross_sectional_percentile(eligible["rs_60"])
    p_trend = cross_sectional_percentile(eligible["trend_50_200"])
    pullback_sweet = (1 - (eligible["pullback_20"] - 0.06).abs() / 0.06).clip(lower=0)
    rsi_sweet = (1 - (eligible["rsi_14"] - 45).abs() / 10).clip(lower=0)
    return 0.40 * p_rs60 + 0.25 * p_trend + 0.20 * pullback_sweet + 0.15 * rsi_sweet


def score_lane_c(features_df: pd.DataFrame) -> pd.Series:
    """Score Lane C eligible names."""
    eligible = features_df[features_df.apply(lane_c_eligible, axis=1)].copy()
    if eligible.empty:
        return pd.Series(dtype=float)
    p_rs20 = cross_sectional_percentile(eligible["rs_20"])
    p_vol = cross_sectional_percentile(eligible["volume_ratio_5_20"])
    p_trend = cross_sectional_percentile(eligible["trend_50_200"])
    p_prox = cross_sectional_percentile(eligible["proximity_20_high"])
    return 0.35 * p_rs20 + 0.25 * p_vol + 0.20 * p_trend + 0.20 * p_prox


# ---------------------------------------------------------------------------
# Round-robin candidate construction
# ---------------------------------------------------------------------------


def round_robin_candidates(
    lane_a: list[dict], lane_b: list[dict], lane_c: list[dict], max_candidates: int = MAX_CANDIDATES
) -> tuple[list[dict], list[dict]]:
    """Deterministic round-robin: A1, B1, C1, A2, B2, C2, ...

    Returns (candidates, skip_trace).
    Each candidate records all lanes in which it qualified.
    """
    candidates = []
    seen = set()
    skip_trace = []
    max_len = max(len(lane_a), len(lane_b), len(lane_c))

    # Build ticker → lane membership map for all qualifying lanes
    all_lane_memberships: dict[str, list[str]] = {}
    all_lane_ranks: dict[str, dict[str, int]] = {}
    all_lane_scores: dict[str, dict[str, float]] = {}
    for lane_name, lane_list in [("A", lane_a), ("B", lane_b), ("C", lane_c)]:
        for i, item in enumerate(lane_list):
            t = item["ticker"]
            all_lane_memberships.setdefault(t, []).append(lane_name)
            all_lane_ranks.setdefault(t, {})[lane_name] = i + 1
            all_lane_scores.setdefault(t, {})[lane_name] = item["lane_score"]

    for rank_idx in range(max_len):
        for lane_name, lane_list in [("A", lane_a), ("B", lane_b), ("C", lane_c)]:
            if rank_idx < len(lane_list):
                ticker = lane_list[rank_idx]["ticker"]
                if ticker not in seen:
                    seen.add(ticker)
                    candidates.append(
                        {
                            "ticker": ticker,
                            "final_priority": len(candidates) + 1,
                            "originating_lane": lane_name,
                            "all_qualifying_lanes": all_lane_memberships[ticker],
                            "best_lane_rank": min(all_lane_ranks[ticker].values()),
                            "lane_ranks": all_lane_ranks[ticker],
                            "lane_scores": all_lane_scores[ticker],
                            "features": lane_list[rank_idx].get("features", {}),
                        }
                    )
                    if len(candidates) >= max_candidates:
                        return candidates, skip_trace
                else:
                    skip_trace.append(
                        {
                            "lane": lane_name,
                            "rank": rank_idx + 1,
                            "ticker": ticker,
                            "reason": "already_selected",
                        }
                    )
    return candidates, skip_trace


# ---------------------------------------------------------------------------
# Control cohort
# ---------------------------------------------------------------------------


def select_control_cohort(
    eligible_tickers: list[str],
    screen_tickers: set[str],
    completed_session: str,
    size: int = CONTROL_COHORT_SIZE,
) -> list[str]:
    """Deterministic control cohort from screen-eligible names NOT in top candidates."""
    non_screen = [t for t in eligible_tickers if t not in screen_tickers]
    ranked = sorted(
        non_screen,
        key=lambda t: hashlib.sha256(f"E17CONTROL|{completed_session}|{t}".encode()).hexdigest(),
    )
    return ranked[:size]


# ---------------------------------------------------------------------------
# Batch market data fetch
# ---------------------------------------------------------------------------


def fetch_batch_ohlcv(
    tickers: list[str], start_date: str, end_date: str, batch_size: int = BATCH_SIZE
) -> dict[str, pd.DataFrame]:
    """Fetch OHLCV data for multiple tickers in batches.

    Returns dict of ticker → DataFrame with columns: Open, High, Low, Close, Volume.
    Uses auto_adjust=True for split/dividend-adjusted prices.
    """
    results = {}
    failed = []

    for i in range(0, len(tickers), batch_size):
        batch = tickers[i : i + batch_size]
        try:
            data = yf.download(
                batch,
                start=start_date,
                end=end_date,
                multi_level_index=False,
                progress=False,
                auto_adjust=True,
                group_by="ticker",
            )
            if data.empty:
                failed.extend(batch)
                continue

            for ticker in batch:
                try:
                    df = data.copy() if len(batch) == 1 else data[ticker].copy()
                    if "Close" not in df.columns or df.empty:
                        failed.append(ticker)
                        continue
                    df = df.dropna(subset=["Close"])
                    if not df.empty:
                        results[ticker] = df
                    else:
                        failed.append(ticker)
                except Exception:
                    failed.append(ticker)
        except Exception:
            failed.extend(batch)

    return results, list(set(failed))


def persist_market_cache(market_data: dict[str, pd.DataFrame], cache_dir: Path) -> str:
    """Persist market data to CSV files for reproducibility.

    Returns the cache hash (SHA256 of sorted ticker list).
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    for ticker, df in market_data.items():
        df.to_csv(cache_dir / f"{ticker}.csv", index_label="Date")
    cache_hash = hashlib.sha256(json.dumps(sorted(market_data.keys())).encode()).hexdigest()
    return cache_hash


def load_market_cache(cache_dir: Path) -> dict[str, pd.DataFrame]:
    """Load market data from persisted CSV cache."""
    results = {}
    for csv_path in sorted(cache_dir.glob("*.csv")):
        ticker = csv_path.stem
        df = pd.read_csv(csv_path, index_col="Date", parse_dates=True)
        results[ticker] = df
    return results


# ---------------------------------------------------------------------------
# Main screener
# ---------------------------------------------------------------------------


def run_screener(
    completed_session: str | None = None,
    decision_cutoff: str | None = None,
    next_session_open: str | None = None,
    is_early_close: bool = False,
    use_cache: bool = False,
) -> dict:
    """Run the deterministic screener.

    Returns a dict with all results and artifacts.
    When use_cache=True, loads persisted market data instead of fetching.
    """
    t_total_start = time.monotonic()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    cache_dir = OUTPUT_DIR / "market_data_cache"

    # Load universe
    with open(UNIVERSE_PATH) as f:
        universe = json.load(f)

    constituents = universe["constituents"]
    universe_hash_full = hashlib.sha256(json.dumps(sorted(constituents)).encode()).hexdigest()
    universe_hash_16 = universe_hash_full[:16]

    # Determine date range for data fetch
    if completed_session:
        end_date = completed_session
        # yfinance treats `end` as EXCLUSIVE, so add 1 day to include completed_session
        fetch_end_date = (pd.Timestamp(completed_session) + pd.Timedelta(days=1)).strftime(
            "%Y-%m-%d"
        )
        start_date = pd.Timestamp(completed_session) - pd.Timedelta(days=550)
        start_date = start_date.strftime("%Y-%m-%d")
    else:
        end_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        fetch_end_date = (pd.Timestamp(end_date) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        start_date = (pd.Timestamp(end_date) - pd.Timedelta(days=550)).strftime("%Y-%m-%d")

    # Fetch or load market data
    t_fetch_start = time.monotonic()

    if use_cache and cache_dir.exists():
        market_data = load_market_cache(cache_dir)
        spy_data = {BENCHMARK: market_data.get(BENCHMARK)}
        if BENCHMARK not in market_data:
            raise RuntimeError("SPY benchmark not in cache")
        fetch_failures = [t for t in constituents if t not in market_data]
        t_fetch_total = time.monotonic() - t_fetch_start
    else:
        # Fetch SPY benchmark
        spy_data, spy_failed = fetch_batch_ohlcv(
            [BENCHMARK], start_date, fetch_end_date, batch_size=1
        )
        if BENCHMARK not in spy_data:
            raise RuntimeError(f"SPY benchmark fetch failed: {spy_failed}")

        # Fetch all universe tickers in batches
        market_data, fetch_failures = fetch_batch_ohlcv(constituents, start_date, fetch_end_date)
        # Add SPY to cache
        market_data[BENCHMARK] = spy_data[BENCHMARK]
        t_fetch_total = time.monotonic() - t_fetch_start

        # Persist cache
        persist_market_cache(market_data, cache_dir)

    spy_close = spy_data[BENCHMARK]["Close"]
    # Clamp SPY to completed_session
    if completed_session:
        spy_close = spy_close[spy_close.index <= pd.Timestamp(completed_session)]

    # Compute features
    t_features_start = time.monotonic()
    features = {}
    eligibility_reasons = {}
    screen_eligible = []

    for ticker in constituents:
        if ticker not in market_data:
            eligibility_reasons[ticker] = "MARKET_DATA_FAILURE"
            continue

        df = market_data[ticker]
        # Clamp to completed_session
        if completed_session:
            df = df[df.index <= pd.Timestamp(completed_session)]

        if df.empty:
            eligibility_reasons[ticker] = "MARKET_DATA_FAILURE"
            continue

        close = df["Close"]
        high = df["High"]
        volume = df["Volume"]

        if len(close) < MIN_HISTORY:
            eligibility_reasons[ticker] = "INSUFFICIENT_HISTORY"
            continue

        # Basic eligibility: price
        latest_close = close.iloc[-1]
        if pd.isna(latest_close) or latest_close < MIN_PRICE:
            eligibility_reasons[ticker] = "PRICE_BELOW_MIN"
            continue

        # Basic eligibility: liquidity (median dollar volume per spec)
        dollar_volume = close * volume
        median_dv_20 = dollar_volume.rolling(20).median().iloc[-1]
        if pd.isna(median_dv_20) or median_dv_20 < MIN_DOLLAR_VOLUME_20:
            eligibility_reasons[ticker] = "LIQUIDITY_BELOW_MIN"
            continue

        # Compute features (includes both mean avg_dollar_volume_20 and median_dollar_volume_20)
        feat = compute_features(close, high, volume, spy_close)
        if feat is None:
            eligibility_reasons[ticker] = "FEATURE_COMPUTATION_FAILED"
            continue

        # Check all feature values are finite
        if not all(np.isfinite(v) for v in feat.values()):
            eligibility_reasons[ticker] = "NON_FINITE_FEATURES"
            continue

        feat["common_eligible"] = True
        features[ticker] = feat
        screen_eligible.append(ticker)
        eligibility_reasons[ticker] = "ELIGIBLE"

    t_features = time.monotonic() - t_features_start

    # Build features DataFrame
    features_df = pd.DataFrame(features).T
    features_df.index.name = "ticker"

    # Lane scoring
    t_ranking_start = time.monotonic()

    lane_a_scores = score_lane_a(features_df)
    lane_b_scores = score_lane_b(features_df)
    lane_c_scores = score_lane_c(features_df)

    # Uncapped eligible counts (before MAX_PER_LANE truncation)
    lane_a_uncapped = len(lane_a_scores)
    lane_b_uncapped = len(lane_b_scores)
    lane_c_uncapped = len(lane_c_scores)

    # Rank lanes with deterministic tie-breaking: score desc, ticker asc
    def sort_lane_scores(scores: pd.Series) -> pd.Series:
        """Sort by score descending, then ticker ascending for ties."""
        df = scores.reset_index()
        df.columns = ["ticker", "score"]
        df = df.sort_values(by=["score", "ticker"], ascending=[False, True], kind="stable")
        return pd.Series(df["score"].values, index=df["ticker"].values)

    lane_a_ranked = []
    if not lane_a_scores.empty:
        for ticker, score in sort_lane_scores(lane_a_scores).items():
            lane_a_ranked.append(
                {
                    "ticker": ticker,
                    "lane": "A",
                    "lane_rank": len(lane_a_ranked) + 1,
                    "lane_score": round(float(score), 6),
                    "features": features[ticker],
                }
            )
            if len(lane_a_ranked) >= MAX_PER_LANE:
                break

    lane_b_ranked = []
    if not lane_b_scores.empty:
        for ticker, score in sort_lane_scores(lane_b_scores).items():
            lane_b_ranked.append(
                {
                    "ticker": ticker,
                    "lane": "B",
                    "lane_rank": len(lane_b_ranked) + 1,
                    "lane_score": round(float(score), 6),
                    "features": features[ticker],
                }
            )
            if len(lane_b_ranked) >= MAX_PER_LANE:
                break

    lane_c_ranked = []
    if not lane_c_scores.empty:
        for ticker, score in sort_lane_scores(lane_c_scores).items():
            lane_c_ranked.append(
                {
                    "ticker": ticker,
                    "lane": "C",
                    "lane_rank": len(lane_c_ranked) + 1,
                    "lane_score": round(float(score), 6),
                    "features": features[ticker],
                }
            )
            if len(lane_c_ranked) >= MAX_PER_LANE:
                break

    # Round-robin top candidates
    candidates, skip_trace = round_robin_candidates(lane_a_ranked, lane_b_ranked, lane_c_ranked)

    # Control cohort
    screen_ticker_set = {c["ticker"] for c in candidates}
    control_cohort = select_control_cohort(
        screen_eligible, screen_ticker_set, completed_session or end_date
    )

    t_ranking = time.monotonic() - t_ranking_start
    t_total = time.monotonic() - t_total_start

    # Build summary
    # Count eligibility reasons
    reason_counts = {}
    for reason in eligibility_reasons.values():
        reason_counts[reason] = reason_counts.get(reason, 0) + 1

    summary = {
        "completed_session": completed_session or end_date,
        "decision_cutoff": decision_cutoff,
        "next_session_open": next_session_open,
        "is_early_close": is_early_close,
        "universe_source": universe.get("source", "Wikipedia List of S&P 500 companies"),
        "universe_size": len(constituents),
        "universe_hash_full": universe_hash_full,
        "universe_hash_16": universe_hash_16,
        "market_data_success": len(market_data),
        "market_data_failure": len(fetch_failures),
        "fetch_failures": sorted(fetch_failures),
        "insufficient_history": reason_counts.get("INSUFFICIENT_HISTORY", 0),
        "below_price_threshold": reason_counts.get("PRICE_BELOW_MIN", 0),
        "below_liquidity_threshold": reason_counts.get("LIQUIDITY_BELOW_MIN", 0),
        "invalid_feature_exclusion": reason_counts.get("FEATURE_COMPUTATION_FAILED", 0)
        + reason_counts.get("NON_FINITE_FEATURES", 0),
        "screen_eligible_count": len(screen_eligible),
        "lane_a_uncapped_eligible": lane_a_uncapped,
        "lane_b_uncapped_eligible": lane_b_uncapped,
        "lane_c_uncapped_eligible": lane_c_uncapped,
        "lane_a_ranked_output": len(lane_a_ranked),
        "lane_b_ranked_output": len(lane_b_ranked),
        "lane_c_ranked_output": len(lane_c_ranked),
        "unique_top_candidates": len(candidates),
        "control_cohort_count": len(control_cohort),
        "runtime": {
            "market_data_retrieval_s": round(t_fetch_total, 2),
            "feature_computation_s": round(t_features, 2),
            "ranking_output_s": round(t_ranking, 2),
            "total_s": round(t_total, 2),
        },
        "price_convention": "auto_adjusted (yfinance auto_adjust=True)",
        "rsi_implementation": "Wilder's smoothing (ewm alpha=1/14, adjust=False)",
        "percentile_method": "pandas rank(method='average', pct=True)",
        "tie_breaking": "score descending, ticker ascending (stable sort)",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # Persist artifacts
    # screen_config.json
    config = {
        "min_history": MIN_HISTORY,
        "min_price": MIN_PRICE,
        "min_dollar_volume_20": MIN_DOLLAR_VOLUME_20,
        "max_candidates": MAX_CANDIDATES,
        "max_per_lane": MAX_PER_LANE,
        "control_cohort_size": CONTROL_COHORT_SIZE,
        "benchmark": BENCHMARK,
        "lane_a_weights": {
            "rs_20": 0.35,
            "rs_60": 0.35,
            "trend_50_200": 0.20,
            "volume_ratio_5_20": 0.10,
        },
        "lane_b_weights": {
            "rs_60": 0.40,
            "trend_50_200": 0.25,
            "pullback_sweet": 0.20,
            "rsi_sweet": 0.15,
        },
        "lane_c_weights": {
            "rs_20": 0.35,
            "volume_ratio_5_20": 0.25,
            "trend_50_200": 0.20,
            "proximity_20_high": 0.20,
        },
        "lane_a_eligibility": "close > sma_50 AND sma_50 > sma_200 AND rs_20 > 0 AND rs_60 > 0",
        "lane_b_eligibility": "close > sma_200 AND sma_50 > sma_200 AND rs_60 > 0 AND 0.03 <= pullback_20 <= 0.12 AND 35 <= rsi_14 <= 55",
        "lane_c_eligibility": "close > sma_50 AND sma_50 > sma_200 AND proximity_20_high >= 0.98 AND ret_5 > 0 AND rs_20 > 0 AND volume_ratio_5_20 >= 1.0",
        "round_robin_order": "A → B → C",
    }
    with open(OUTPUT_DIR / "screen_config.json", "w") as f:
        json.dump(config, f, indent=2)

    # universe_provenance.json
    with open(OUTPUT_DIR / "universe_provenance.json", "w") as f:
        json.dump(
            {
                "source": universe.get("source", "Wikipedia List of S&P 500 companies"),
                "constituent_count": len(constituents),
                "canonicalization_method": "sorted(constituents) → JSON → SHA256",
                "full_sha256": universe_hash_full,
                "first_16_hex": universe_hash_16,
            },
            f,
            indent=2,
        )

    # market_data_provenance.json
    cache_hash = hashlib.sha256(json.dumps(sorted(market_data.keys())).encode()).hexdigest()
    # Preserve original retrieval timestamp when using cache
    provenance_path = OUTPUT_DIR / "market_data_provenance.json"
    if use_cache and provenance_path.exists():
        with open(provenance_path) as f:
            old_provenance = json.load(f)
        retrieval_ts = old_provenance.get(
            "retrieval_timestamp", datetime.now(timezone.utc).isoformat()
        )
    else:
        retrieval_ts = datetime.now(timezone.utc).isoformat()
    with open(provenance_path, "w") as f:
        json.dump(
            {
                "retrieval_timestamp": retrieval_ts,
                "completed_session": completed_session or end_date,
                "start_date": start_date,
                "end_date": end_date,
                "ticker_coverage": len(market_data),
                "failed_tickers": sorted(fetch_failures),
                "cache_hash": cache_hash[:16],
                "price_convention": "auto_adjusted (yfinance auto_adjust=True)",
                "benchmark": BENCHMARK,
            },
            f,
            indent=2,
        )

    # screen_features.csv
    if not features_df.empty:
        features_df.to_csv(OUTPUT_DIR / "screen_features.csv")

    # lane_rankings.json
    with open(OUTPUT_DIR / "lane_rankings.json", "w") as f:
        json.dump(
            {
                "lane_a": lane_a_ranked,
                "lane_b": lane_b_ranked,
                "lane_c": lane_c_ranked,
            },
            f,
            indent=2,
        )

    # nightly_candidates.json
    with open(OUTPUT_DIR / "nightly_candidates.json", "w") as f:
        json.dump(
            {
                "candidates": candidates,
                "skip_trace": skip_trace,
                "disclaimer": "Screening priority is NOT an investment recommendation.",
                "completed_session": completed_session or end_date,
            },
            f,
            indent=2,
        )

    # control_cohort.json
    with open(OUTPUT_DIR / "control_cohort.json", "w") as f:
        json.dump(
            {
                "control_cohort": control_cohort,
                "ranking_formula": 'SHA256("E17CONTROL|" + completed_session + "|" + ticker)',
                "completed_session": completed_session or end_date,
            },
            f,
            indent=2,
        )

    # screen_run_summary.json
    with open(OUTPUT_DIR / "screen_run_summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    return summary


if __name__ == "__main__":
    from ta_eval.decision_window import create_decision_window, is_valid_after_close_window

    valid, reason, completed_session = is_valid_after_close_window(require_same_evening=True)
    print(f"Valid window: {valid}, Reason: {reason}")

    if valid:
        dw = create_decision_window()
        result = run_screener(
            completed_session=dw.completed_session,
            decision_cutoff=dw.decision_cutoff,
            next_session_open=dw.next_session_open,
            is_early_close=dw.is_early_close,
        )
    else:
        # Run with just the completed session date if available
        result = run_screener(completed_session=completed_session)

    print("\n=== Screener Summary ===")
    print(f"Universe: {result['universe_size']}")
    print(f"Market data success: {result['market_data_success']}")
    print(f"Screen eligible: {result['screen_eligible_count']}")
    print(f"Lane A: {result['lane_a_eligible']}")
    print(f"Lane B: {result['lane_b_eligible']}")
    print(f"Lane C: {result['lane_c_eligible']}")
    print(f"Top candidates: {result['unique_top_candidates']}")
    print(f"Control cohort: {result['control_cohort_count']}")
    print(f"Total runtime: {result['runtime']['total_s']}s")

    # Print top candidates
    with open(OUTPUT_DIR / "nightly_candidates.json") as f:
        candidates_data = json.load(f)
    print("\nTop candidates:")
    for c in candidates_data["candidates"][:10]:
        print(
            f"  {c['final_priority']}. {c['ticker']} (lane {c['originating_lanes']}, rank {c['best_lane_rank']})"
        )
