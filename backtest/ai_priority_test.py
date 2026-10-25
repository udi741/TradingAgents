#!/usr/bin/env python3
"""AI-vs-mechanical admission priority — historical smoke test (Oct 2026).

Universe: per-session frozen candidate pools (the ~10 AI-researched names
per session — ratings apply only to what was actually researched).
Entry logic: identical mechanical retest (60d-high close, zone top fill,
2*ATR stop, close_below -> next open, 60-session cap), $5k/10-slot/$100k.
Admission variants: (a) alphabetical [mechanical], (b) AI rating rank
(Buy > Overweight > Neutral > Underweight > Sell; unrated last),
(c) fixed-seed shuffle.

AI ratings: latest published rating per ticker as of each fill date —
uses only decisions published on/before that date (no look-ahead).
Ratings source: case_artifacts (timestamped TA signals) + intents' rating
fields, keyed by publication session.
"""
import json
import sys
from pathlib import Path

import yfinance as yf

sys.path.insert(0, str(Path(__file__).parent))
import mechanics_multiyear as mm
from portfolio_sim import portfolio_run
from universe_pt import elig_mask

EV = Path("/home/udi/udi_provate/TradingAgents/evaluations/alpha_rnd_v1")
OUT = Path(__file__).parent / "results"
RATING_RANK = {"Buy": 5, "Overweight": 4, "Neutral": 3,
               "Underweight": 2, "Sell": 1}
PERIOD = ("2026-10-01", "2026-10-23")


def load_pools():
    pools = {}
    for f in sorted(EV.glob("candidate_pool_frozen_*.json")):
        d = json.loads(f.read_text())
        pools[d["session"]] = [c["ticker"] for c in d.get("candidates", [])]
    return pools


def load_ratings():
    """ticker -> [(pub_date, label)] from timestamped AI artifacts."""
    r = {}
    for f in EV.glob("case_artifacts/*.json"):
        d = json.loads(f.read_text())
        ds = d.get("decision_session")
        if ds and d.get("signal") in RATING_RANK:
            r.setdefault(d["ticker"], []).append((ds, d["signal"]))
    for f in EV.glob("publication_intents_*.json"):
        d = json.loads(f.read_text())
        sess = d.get("session") or f.stem.rsplit("_", 1)[-1]
        for t, i in (d.get("intents") or {}).items():
            lab = i.get("pm_rating") or i.get("rating") or i.get("pm")
            if t and lab in RATING_RANK:
                r.setdefault(t, []).append((sess, lab))
    for t in r:
        r[t].sort()
    return r


def rating_at(ratings, ticker, date):
    # conservative: a rating is eligible from the NEXT trading session
    # after its publication date (pub timestamps are dates, not times)
    lab = None
    for d, l in ratings.get(ticker, []):
        if d < date:
            lab = l
    return lab


def main():
    pools = load_pools()
    ratings = load_ratings()
    covered = sorted({t for ts in pools.values() for t in ts})
    print("covered tickers:", len(covered), "| sessions:", len(pools))
    d = yf.download(covered + ["SPY"], start="2025-10-01", end="2026-10-24",
                    group_by="ticker", progress=False, auto_adjust=True,
                    threads=True)
    spy = d["SPY"].dropna()
    sc = {str(x.date()): float(r) for x, r in spy["Close"].items()}
    sm = {str(x.date()): float(r) for x, r in
          spy["Close"].rolling(20).mean().items()}
    cand = []
    for t in covered:
        df = d[t].dropna()
        if len(df) < 40:
            continue
        for tr in mm.sim_period(df, sc, sm, PERIOD, "LONG", "ORIG",
                                elig=elig_mask(df)):
            tr["ticker"] = t
            tr["direction"] = "LONG"
            tr["rating"] = rating_at(ratings, t, tr["fill_date"])
            cand.append(tr)
    contested = {}
    for c in cand:
        contested.setdefault(c["fill_date"], []).append(c["ticker"])
    multi = {k: v for k, v in contested.items() if len(v) > 1}
    print("candidate fills:", len(cand), "| fill days:", len(contested),
          "| contested days:", len(multi))
    bars = {t: d[t].dropna() for t in covered}
    out = {}
    # variant a: existing alphabetical
    out["mechanical_alpha"] = portfolio_run(cand, bars, *PERIOD)
    # variant b: AI rating priority (best rating first, per fill date)
    out["ai_rating"] = portfolio_run(
        cand, bars, *PERIOD,
        priority_fn=lambda c: -RATING_RANK.get(c["rating"], 0))
    # variant c: two fixed seeds
    out["shuffle_s1"] = portfolio_run(cand, bars, *PERIOD, order_seed=1)
    out["shuffle_s7"] = portfolio_run(cand, bars, *PERIOD, order_seed=7)
    for k, r in out.items():
        print(f"{k:18s} admit={r['admitted']} rej={r['rejected']} "
              f"nav%={r['net_pct']} pnl={r['net_pnl']} pf={r['pf']} "
              f"trades={[t['ticker'] for t in r['admitted_trades']]}")
    out["_meta"] = {"contested_days": {k: v for k, v in multi.items()},
                    "candidate_fills": len(cand)}
    (OUT / "ai_priority.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
