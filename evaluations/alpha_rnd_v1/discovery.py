#!/usr/bin/env python3
"""ALPHA_RND Gate-1: multi-source current-opportunity discovery.

Deterministic, point-in-time safe. No LLM calls. No future returns.

Sources:
  MOMENTUM               — frozen Lane-A eligibility/score (e17) + Lane-C breakout
  RELATIVE_STRENGTH      — rs_60 leadership vs SPY while trend intact
  QUALITY_PULLBACK       — Lane-B pullback in established uptrend
  CATALYST               — dated SEC 8-K/10-Q filing in last 10 business days
                           AND market signature (|ret_5|>=3% or vol_ratio>=1.3)
  FUNDAMENTAL_ACCELERATION — SEC companyfacts (filed-date <= session): last two
                           filed quarters vs year-ago; improving revenue growth,
                           margins, income, or operating cash flow.

Universe: Wikipedia S&P 500 + NASDAQ-100 + S&P MidCap 400, hygiene-filtered
(>=252 sessions history, close >= $5, median 20d dollar volume >= $20M).
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from ta_eval_alpha import e17_screener as e17  # noqa: E402

OUT = ROOT / "evaluations" / "alpha_rnd_v1"
SEC_UA = {"User-Agent": "ResearchAgent admin@openai.com", "Accept-Encoding": "identity"}
MIN_PRICE = 5.0
MIN_MEDIAN_DV20 = 20_000_000
MIN_HISTORY = 252

WIKI_SOURCES = [
    ("sp500", "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", "Symbol"),
    ("sp400", "https://en.wikipedia.org/wiki/List_of_S%26P_400_companies", "Symbol"),
]
NASDAQ_LISTED = "https://www.nasdaqtrader.com/dynamic/symdir/nasdaqlisted.txt"
OTHER_LISTED = "https://www.nasdaqtrader.com/dynamic/symdir/otherlisted.txt"
# Security-name substrings that mark non-common-stock / junk instruments
JUNK_SUBSTR = ("Warrant", "Right", "Unit", "Preferred", "Depositary", "Note", "Bond",
               "Baby Bond", " ETF", "ETF ", "Fund", "Trust", "Acquisition Corp")


def sha(t: str) -> str:
    return hashlib.sha256(t.encode()).hexdigest()


def fetch_url(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 research"})
    return urllib.request.urlopen(req, timeout=30).read()


def fetch_sec(url: str) -> bytes:
    req = urllib.request.Request(url, headers=SEC_UA)
    return urllib.request.urlopen(req, timeout=30).read()


def build_universe() -> list[dict]:
    rows = {}
    for name, url, col in WIKI_SOURCES:
        tables = pd.read_html(fetch_url(url))
        df = None
        for t in tables:
            if col in t.columns:
                df = t
                break
        if df is None:
            raise RuntimeError(f"{name}: no table with column {col}")
        for _, r in df.iterrows():
            tick = str(r[col]).strip().upper().replace(".", "-")
            if not tick or any(c in tick for c in (" ", "/")):
                continue
            rows.setdefault(tick, {"ticker": tick, "indices": []})
            rows[tick]["indices"].append(name)
        time.sleep(1)

    # Non-index expansion: nasdaqtrader symbol directories, common-stock only.
    nq = pd.read_csv(NASDAQ_LISTED, sep="|")
    nq = nq[(nq["Test Issue"] == "N") & (nq["ETF"] == "N") & (nq["Financial Status"] == "N")]
    for _, r in nq.iterrows():
        tick = str(r["Symbol"]).strip().upper()
        sname = str(r["Security Name"])
        if any(s in sname for s in JUNK_SUBSTR):
            continue
        if not tick.isalpha() or len(tick) > 5:
            continue
        rows.setdefault(tick, {"ticker": tick, "indices": []})
        rows[tick]["indices"].append("nasdaq_listed")

    ot = pd.read_csv(OTHER_LISTED, sep="|")
    ot = ot[(ot["Test Issue"] == "N") & (ot["ETF"] == "N") & ot["Exchange"].isin(["A", "N", "P"])]
    for _, r in ot.iterrows():
        tick = str(r["ACT Symbol"]).strip().upper().replace(".", "-")
        sname = str(r["Security Name"])
        if any(s in sname for s in JUNK_SUBSTR):
            continue
        if any(c in tick for c in (" ", "/", "$", "^")) or len(tick) > 6:
            continue
        rows.setdefault(tick, {"ticker": tick, "indices": []})
        rows[tick]["indices"].append("other_listed")

    return sorted(rows.values(), key=lambda x: x["ticker"])


def last_completed_session() -> str:
    spy, _ = e17.fetch_batch_ohlcv(["SPY"], "2026-08-01", None or (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d"), batch_size=1)
    idx = spy["SPY"].index
    today = pd.Timestamp.now(tz="US/Eastern").normalize().tz_localize(None)
    completed = idx[idx < today]
    return str(completed[-1].date())


def sec_catalyst_events(session: str, tickers: set[str]) -> dict[str, list[dict]]:
    """8-K / 10-Q / 10-K filings in the 10 business days ending at `session`,
    restricted to universe tickers via company_tickers.json CIK map."""
    subs = fetch_sec("https://www.sec.gov/files/company_tickers.json")
    cik2t = {int(v["cik_str"]): v["ticker"].upper() for v in json.loads(subs).values()}
    tset = tickers & set(cik2t.values())
    events: dict[str, list[dict]] = {}
    d = pd.Timestamp(session)
    days = []
    while len(days) < 10:
        if d.weekday() < 5:
            days.append(d)
        d -= timedelta(days=1)
    q = "QTR" + str((days[0].month - 1) // 3 + 1)
    year = days[0].year
    for day in sorted(days):
        idx_url = f"https://www.sec.gov/Archives/edgar/daily-index/{year}/{q}/master.{day.strftime('%Y%m%d')}.idx"
        try:
            raw = fetch_sec(idx_url).decode("latin-1", "replace")
        except Exception:
            continue
        for line in raw.splitlines():
            parts = line.split("|")
            if len(parts) < 5 or parts[2] not in ("8-K", "10-Q", "10-K", "8-K/A"):
                continue
            try:
                cik = int(parts[0])
            except ValueError:
                continue
            t = cik2t.get(cik)
            if t and t in tset:
                events.setdefault(t, []).append(
                    {"form": parts[2], "date": parts[3], "cik": cik}
                )
        time.sleep(0.3)
    return events


FACTS = {
    "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"],
    "op_income": ["OperatingIncomeLoss"],
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
    "ocf": ["NetCashProvidedByUsedInOperatingActivities"],
}


def quarterly_vals(facts_json: dict, tags: list[str], session: str) -> list[tuple]:
    """Return list of (end, start, val, filed) quarterly observations, filed<=session."""
    try:
        usgaap = facts_json["facts"]["us-gaap"]
    except KeyError:
        return []
    obs = []
    for tag in tags:
        if tag not in usgaap:
            continue
        for unit, arr in usgaap[tag]["units"].items():
            if unit != "USD":
                continue
            for it in arr:
                try:
                    filed = it.get("filed", "9999")
                    if filed > session:
                        continue
                    start, end = it.get("start"), it.get("end")
                    if not start or not end:
                        continue
                    dur = (pd.Timestamp(end) - pd.Timestamp(start)).days
                    if 75 <= dur <= 100:  # quarterly duration only
                        obs.append((end, start, float(it["val"]), filed))
                except Exception:
                    continue
        if obs:
            break  # first tag that yields quarterly data
    # dedupe by end keeping latest filed
    best = {}
    for end, start, val, filed in obs:
        if end not in best or filed > best[end][3]:
            best[end] = (end, start, val, filed)
    return sorted(best.values(), key=lambda x: x[0])


def acceleration(session: str, cik: int) -> dict | None:
    try:
        facts = json.loads(fetch_sec(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"))
    except Exception:
        return None
    out = {}
    for key, tags in FACTS.items():
        q = quarterly_vals(facts, tags, session)
        if len(q) < 6:
            out[key] = None
            continue
        # last two quarters vs same quarters a year ago (by end-date ordering)
        last2, prev2 = q[-1], q[-2]
        yr_ago = [x for x in q[:-2]]
        def yoy(cur):
            cand = [x for x in q if x[0] < cur[0] and 330 <= (pd.Timestamp(cur[0]) - pd.Timestamp(x[0])).days <= 400]
            if not cand:
                return None
            base = cand[-1][2]
            if base == 0:
                return None
            return (cur[2] - base) / abs(base)
        g1, g2 = yoy(prev2), yoy(last2)
        out[key] = {
            "last_q_end": last2[0], "last_filed": last2[3],
            "yoy_prev_q": None if g1 is None else round(g1, 4),
            "yoy_last_q": None if g2 is None else round(g2, 4),
        }
    if all(v is None for v in out.values()):
        return None
    acc = []
    r = out.get("revenue")
    if r and r["yoy_last_q"] is not None and r["yoy_prev_q"] is not None:
        if r["yoy_last_q"] > r["yoy_prev_q"] and r["yoy_last_q"] > 0:
            acc.append("revenue_growth_accelerating")
        elif r["yoy_last_q"] > 0.10:
            acc.append("revenue_growth_strong")
    for k in ("op_income", "net_income", "ocf"):
        m = out.get(k)
        if m and m["yoy_last_q"] is not None and m["yoy_last_q"] > 0 and (
            m["yoy_prev_q"] is None or m["yoy_last_q"] > m["yoy_prev_q"]
        ):
            acc.append(f"{k}_improving")
    return {"facts": out, "acceleration_flags": sorted(set(acc))}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    session = sys.argv[1] if len(sys.argv) > 1 else last_completed_session()
    print("latest completed session:", session)

    universe = build_universe()
    tickers = [u["ticker"] for u in universe]
    print("universe raw:", len(tickers))
    (OUT / "universe_raw.json").write_text(json.dumps({"session": session, "sources": [s[0] for s in WIKI_SOURCES], "constituents": universe}, indent=1))

    start = (pd.Timestamp(session) - pd.Timedelta(days=560)).strftime("%Y-%m-%d")
    end = (pd.Timestamp(session) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    import pickle
    mcache = OUT / f"market_cache_{session}.pkl"
    if mcache.exists():
        md, failures = pickle.loads(mcache.read_bytes())
    else:
        md, failures = {}, []
        CH = 250
        all_t = ["SPY"] + tickers
        for i in range(0, len(all_t), CH):
            d, f = e17.fetch_batch_ohlcv(all_t[i:i + CH], start, end)
            md.update(d)
            failures += f
            print(f"fetch {i + CH}/{len(all_t)} ok={len(md)}", flush=True)
            time.sleep(15)
        mcache.write_bytes(pickle.dumps((md, failures)))
    spy_close = md["SPY"]["Close"]
    spy_close = spy_close[spy_close.index <= pd.Timestamp(session)]

    feats, reasons = {}, {"fetch_failed": failures}
    for t in tickers:
        df = md.get(t)
        if df is None:
            continue
        df = df[df.index <= pd.Timestamp(session)]
        f = e17.compute_features(df["Close"], df["High"], df["Volume"], spy_close)
        if f is None:
            reasons.setdefault("insufficient_history", []).append(t)
            continue
        if f["close"] < MIN_PRICE:
            reasons.setdefault("price_below_5", []).append(t)
            continue
        if f["median_dollar_volume_20"] < MIN_MEDIAN_DV20:
            reasons.setdefault("illiquid", []).append(t)
            continue
        f["ret_1"] = df["Close"].pct_change().iloc[-1]
        feats[t] = f
    print("eligible:", len(feats))

    fdf = pd.DataFrame(feats).T
    laneA = e17.score_lane_a(fdf).sort_values(ascending=False)
    laneB = e17.score_lane_b(fdf).sort_values(ascending=False)
    laneC = e17.score_lane_c(fdf).sort_values(ascending=False)

    rs60_pct = fdf["rs_60"].rank(pct=True)
    rs_leaders = fdf[(rs60_pct >= 0.97) & (fdf["rs_20"] > 0) & (fdf["close"] > fdf["sma_50"])]
    rs_leaders = rs_leaders["rs_60"].sort_values(ascending=False)

    # Catalysts: dated SEC filings within last 10 business days
    events = sec_catalyst_events(session, set(feats))
    catalyst = {}
    for t, evs in events.items():
        if t not in feats:
            continue
        f = feats[t]
        if abs(f["ret_5"]) >= 0.03 or f["volume_ratio_5_20"] >= 1.3:
            catalyst[t] = evs
    print("catalyst names:", len(catalyst))

    # Fundamental acceleration on pre-pool (union of lane tops + catalysts)
    pre = set(laneA.index[:60]) | set(laneB.index[:40]) | set(laneC.index[:40]) | set(rs_leaders.index[:40]) | set(catalyst)
    fcache = OUT / f"fundamental_facts_{session}.json"
    if fcache.exists():
        fund = json.loads(fcache.read_text())
    else:
        subs = json.loads(fetch_sec("https://www.sec.gov/files/company_tickers.json"))
        t2cik = {v["ticker"].upper(): int(v["cik_str"]) for v in subs.values()}
        fund = {}
        for i, t in enumerate(sorted(pre)):
            cik = t2cik.get(t)
            if not cik:
                continue
            a = acceleration(session, cik)
            if a:
                fund[t] = a
            if i % 25 == 0:
                print(f"fund {i}/{len(pre)}", flush=True)
            time.sleep(0.15)
        fcache.write_text(json.dumps(fund, indent=1, default=str))

    # Assemble pool with labels
    def label(t):
        labs = []
        if t in laneA.index:
            labs.append("MOMENTUM")
        if t in laneC.index:
            labs.append("MOMENTUM")
        if t in rs_leaders.index:
            labs.append("RELATIVE_STRENGTH")
        if t in laneB.index:
            labs.append("QUALITY_PULLBACK")
        if t in catalyst:
            labs.append("CATALYST")
        if fund.get(t, {}).get("acceleration_flags"):
            labs.append("FUNDAMENTAL_ACCELERATION")
        return sorted(set(labs))

    # Balanced deterministic selection across independent discovery sources.
    chosen: list[str] = []
    quotas = [
        ("A", list(laneA.index[:8])),
        ("RS", list(rs_leaders.index[:6])),
        ("B", list(laneB.index[:5])),
        ("C", list(laneC.index[:3])),
    ]
    for _, seq in quotas:
        for t in seq:
            if t not in chosen:
                chosen.append(t)
    # catalysts: prefer multi-signal, then strongest market signature, cap 8
    cat_rank = sorted(catalyst, key=lambda t: (0 if len(set(label(t))) > 1 else 1, -abs(feats[t]["ret_5"]) * feats[t]["volume_ratio_5_20"], t))
    for t in cat_rank[:8]:
        if t not in chosen:
            chosen.append(t)
    # pure fundamental acceleration: strongest revenue acceleration, cap 4
    fa_only = [t for t in fund if fund[t]["acceleration_flags"] and t not in chosen and t in feats]
    fa_rank = sorted(fa_only, key=lambda t: -(((fund[t]["facts"].get("revenue") or {}).get("yoy_last_q")) or -9))
    for t in fa_rank[:4]:
        chosen.append(t)
    pool = []
    for t in chosen:
        labs = label(t)
        if len(labs) >= 3:
            labs = ["MULTI_SIGNAL"] + labs
        pool.append({
            "ticker": t,
            "labels": labs,
            "close": round(feats[t]["close"], 2),
            "ret_5": round(feats[t]["ret_5"], 4),
            "ret_20": round(feats[t]["ret_20"], 4),
            "rs_60": round(feats[t]["rs_60"], 4),
            "rsi_14": round(feats[t]["rsi_14"], 1),
            "pullback_20": round(feats[t]["pullback_20"], 3),
            "vol_ratio_5_20": round(feats[t]["volume_ratio_5_20"], 2),
            "catalyst_events": catalyst.get(t, [])[:3],
            "acceleration_flags": fund.get(t, {}).get("acceleration_flags", []),
        })
        if len(pool) >= 28:
            break

    result = {
        "session": session,
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "universe_size_raw": len(tickers),
        "universe_size_eligible": len(feats),
        "filters": {"min_history": MIN_HISTORY, "min_price": MIN_PRICE, "min_median_dv20": MIN_MEDIAN_DV20},
        "exclusion_counts": {k: len(v) for k, v in reasons.items()},
        "lane_counts": {"A_momentum": len(laneA), "B_pullback": len(laneB), "C_breakout": len(laneC), "RS_leaders": len(rs_leaders), "catalyst": len(catalyst), "fund_acc": sum(1 for v in fund.values() if v["acceleration_flags"])},
        "candidates": pool,
        "artifact_sha256": None,
    }
    result["artifact_sha256"] = sha(json.dumps(result["candidates"], sort_keys=True))
    (OUT / f"candidate_pool_frozen_{session}.json").write_text(json.dumps(result, indent=1, default=str))
    print(json.dumps(result["lane_counts"]))
    for c in pool:
        print(f"{c['ticker']:6} {','.join(c['labels'])}")


if __name__ == "__main__":
    main()
