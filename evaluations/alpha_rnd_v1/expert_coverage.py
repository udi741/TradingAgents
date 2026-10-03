#!/usr/bin/env python3
"""ALPHA_RND_EXPERT_DISCOVERY_COVERAGE_V1 — retrospective diagnostic.

Replays the FROZEN ALPHA discovery machinery at each expert BUY date using
only point-in-time-available data:
  - daily OHLCV truncated at decision date (all universe names, one bulk pull)
  - SEC EDGAR daily master index over the 10 business days ending at the date
  - SEC companyfacts filtered to filed<=decision date (pre-pool only)
Universe membership uses CURRENT lists — survivorship caveat flagged per case.
No LLM calls. No outcome data used.
"""

from __future__ import annotations

import json
import pickle
import socket
socket.setdefaulttimeout(20)
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from ta_eval_alpha import e17_screener as e17  # noqa: E402
from evaluations.alpha_rnd_v1 import discovery as disc  # noqa: E402

OUT = ROOT / "evaluations" / "alpha_rnd_v1" / "expert_coverage"
CACHE = OUT / "universe_daily_2023_2026.pkl"

CASES = [
    # NORMAL regime — E cohort from frozen X2/X3 artifacts (case_id date = expert decision date)
    ("UAMY", "2025-09-29", "NORMAL"), ("FIVE", "2025-10-01", "NORMAL"),
    ("FROG", "2025-10-03", "NORMAL"), ("DGXX", "2025-10-20", "NORMAL"),
    ("HUT", "2025-11-18", "NORMAL"), ("ZETA", "2025-12-02", "NORMAL"),
    ("MP", "2026-01-08", "NORMAL"), ("FLNC", "2026-03-03", "NORMAL"),
    ("LUNR", "2026-04-24", "NORMAL"), ("ASYS", "2026-05-04", "NORMAL"),
    ("BB", "2026-05-15", "NORMAL"), ("KEEL", "2026-05-22", "NORMAL"),
    ("IREN", "2026-08-14", "NORMAL"),
    # RISKIER_PATH_1 disclosures
    ("PANW", "2026-09-08", "RISKIER_PATH_1"), ("FTNT", "2026-09-08", "RISKIER_PATH_1"),
    ("AMAT", "2026-09-08", "RISKIER_PATH_1"),
]
EXCLUDED = [("SANM", "DATE_NOT_AVAILABLE (ambiguous buy date — documented in EXPERT_RND)"),
            ("IONQ", "DATE_NOT_AVAILABLE (two candidate dates 2026-09-23/24, no single authoritative buy date)")]


def business_days_ending(date: str, n: int = 10) -> list[str]:
    d = pd.Timestamp(date); out = []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.strftime("%Y-%m-%d"))
        d -= timedelta(days=1)
    return out


def eval_date(md: dict, tickers: list[str], spy_close_full: pd.Series, date: str):
    """Frozen eligibility + family evaluation at a single date."""
    D = pd.Timestamp(date)
    spy_close = spy_close_full[spy_close_full.index <= D]
    feats = {}
    for t in tickers:
        df = md.get(t)
        if df is None:
            continue
        df = df[df.index <= D]
        if df.empty:
            continue
        f = e17.compute_features(df["Close"], df["High"], df["Volume"], spy_close)
        if f is None or f["close"] < disc.MIN_PRICE or f["median_dollar_volume_20"] < disc.MIN_MEDIAN_DV20:
            continue
        f["ret_1"] = df["Close"].pct_change().iloc[-1]
        feats[t] = f
    fdf = pd.DataFrame(feats).T
    if fdf.empty:
        return feats, {}, {}, {}, pd.Series(dtype=float)
    laneA = e17.score_lane_a(fdf).sort_values(ascending=False)
    laneB = e17.score_lane_b(fdf).sort_values(ascending=False)
    laneC = e17.score_lane_c(fdf).sort_values(ascending=False)
    rs60_pct = fdf["rs_60"].rank(pct=True)
    rsl = fdf[(rs60_pct >= 0.97) & (fdf["rs_20"] > 0) & (fdf["close"] > fdf["sma_50"])]["rs_60"].sort_values(ascending=False)
    return feats, {"A": laneA, "B": laneB, "C": laneC, "RS": rsl}, fdf, rs60_pct


def rank_of(ser: pd.Series, t: str):
    if t in ser.index:
        return list(ser.index).index(t) + 1, round(float(ser[t]), 4)
    return None, None


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    uni = json.loads((ROOT / "evaluations/alpha_rnd_v1/universe_raw.json").read_text())
    tickers = [u["ticker"] for u in uni["constituents"]]
    extra = [c[0] for c in CASES if c[0] not in tickers]
    print("universe", len(tickers), "case tickers outside current universe:", extra)

    # one bulk pull covering all case dates
    if CACHE.exists():
        md = pickle.loads(CACHE.read_bytes())
    else:
        md, fails = {}, []
        all_t = ["SPY"] + sorted(set(tickers + extra))
        for i in range(0, len(all_t), 250):
            d, f = e17.fetch_batch_ohlcv(all_t[i:i + 250], "2024-09-01", "2026-10-03")
            md.update(d); fails += f
            print(f"fetch {i+250}/{len(all_t)} ok={len(md)}", flush=True)
            time.sleep(15)
        CACHE.write_bytes(pickle.dumps(md))
    spy_full = md["SPY"]["Close"]

    results = []
    dates = sorted(set(d for _, d, _ in CASES))
    cat_cache = {}
    for date in dates:
        print("=== eval date", date, flush=True)
        feats, lanes, fdf, rs60_pct = eval_date(md, tickers + extra, spy_full, date)
        # catalyst set at this date (EDGAR daily index + market signature)
        events = disc.sec_catalyst_events(date, set(feats))
        cat = {t: e for t, e in events.items()
               if t in feats and (abs(feats[t]["ret_5"]) >= 0.03 or feats[t]["volume_ratio_5_20"] >= 1.3)}
        cat_cache[date] = list(cat)
        # candidate pool assembly identical to discovery quotas
        chosen = []
        for seq in (list(lanes["A"].index[:8]), list(lanes["RS"].index[:6]),
                    list(lanes["B"].index[:5]), list(lanes["C"].index[:3])):
            for t in seq:
                if t not in chosen:
                    chosen.append(t)
        cat_rank = sorted(cat, key=lambda t: -abs(feats[t]["ret_5"]) * feats[t]["volume_ratio_5_20"])
        for t in cat_rank[:8]:
            if t not in chosen:
                chosen.append(t)
        triggered = set(lanes["A"].index) | set(lanes["B"].index) | set(lanes["C"].index) | set(lanes["RS"].index) | set(cat)
        context = {"date": date, "eligible": len(feats), "triggered_any": len(triggered),
                   "pool_size_noFA": len(chosen), "laneA": len(lanes["A"]), "laneB": len(lanes["B"]),
                   "laneC": len(lanes["C"]), "rs": len(lanes["RS"]), "catalyst": len(cat)}
        # labels + deep score for every pool member (FA excluded — flagged)
        pool_scores = []
        for t in chosen:
            fams = set()
            if t in lanes["A"].index or t in lanes["C"].index: fams.add("MOMENTUM")
            if t in lanes["RS"].index: fams.add("RELATIVE_STRENGTH")
            if t in lanes["B"].index: fams.add("QUALITY_PULLBACK")
            if t in cat: fams.add("CATALYST")
            sc = len(fams) * 10 + 2 * min(max(feats[t]["rs_60"], 0), 2) + (1 if "CATALYST" in fams else 0)
            pool_scores.append((t, round(sc, 3), sorted(fams)))
        pool_scores.sort(key=lambda x: (-x[1], x[0]))
        deep10 = {t for t, _, _ in pool_scores[:10]}
        for t, _, reg in [c for c in CASES if c[1] == date]:
            f = feats.get(t)
            r = {"ticker": t, "date": date, "regime": reg, "context": context,
                 "in_current_universe": t in tickers,
                 "eligible": f is not None, "families": [], "ranks": {}, "scores": {},
                 "pool": False, "deep": False, "final_ta": "NOT_TESTED"}
            if f is not None:
                r["close"] = round(f["close"], 2)
                if t in lanes["A"].index: r["families"].append("MOMENTUM")
                if t in lanes["C"].index: r["families"].append("MOMENTUM(BREAKOUT)")
                if t in lanes["RS"].index: r["families"].append("RELATIVE_STRENGTH")
                if t in lanes["B"].index: r["families"].append("QUALITY_PULLBACK")
                if t in cat: r["families"].append("CATALYST")
                for ln in ("A", "B", "C", "RS"):
                    rk, sc = rank_of(lanes[ln], t)
                    if rk: r["ranks"][ln] = rk; r["scores"][ln] = sc
                r["pool"] = t in chosen
                if r["pool"]:
                    r["deep_score_no_fa_rank"] = [x[0] for x in pool_scores].index(t) + 1
                    r["deep_no_fa"] = t in deep10
                    r["deep_note"] = "FA label deferred; +10 if acceleration confirmed via filed<=date companyfacts"
            results.append(r)
        (OUT / f"date_eval_{date}.json").write_text(json.dumps(
            {"context": context, "pool": pool_scores}, indent=1, default=str))

    (OUT / "coverage_results.json").write_text(json.dumps(results, indent=1, default=str))

    # FA check for case tickers only (filing-date-bounded companyfacts)
    subs = json.loads(disc.fetch_sec("https://www.sec.gov/files/company_tickers.json"))
    t2cik = {v["ticker"].upper(): int(v["cik_str"]) for v in subs.values()}
    for r in results:
        if not r["eligible"]:
            continue
        cik = t2cik.get(r["ticker"])
        if not cik:
            r["fa"] = "CIK_NOT_FOUND"
            continue
        a = disc.acceleration(r["date"], cik)
        r["fa"] = a["acceleration_flags"] if a else []
        if r["fa"]:
            r["families"].append("FUNDAMENTAL_ACCELERATION")
        time.sleep(0.2)

    (OUT / "coverage_results.json").write_text(json.dumps(results, indent=1, default=str))
    for r in results:
        print(r["ticker"], r["date"], r["regime"], "| elig:", r["eligible"],
              "| fam:", r["families"], "| pool:", r["pool"], "| deep_no_fa:", r.get("deep_no_fa"),
              "| fa:", r.get("fa"))


if __name__ == "__main__":
    main()
