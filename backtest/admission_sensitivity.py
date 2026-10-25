#!/usr/bin/env python3
"""Task 3: fixed-seed admission-order sensitivity on cached PIT universe.

Same-day competing entries are currently admitted alphabetically — an
arbitrary choice with no future information. This re-runs admission with
deterministic shuffles (fixed seeds) on identical candidates, rules, caps,
and costs. No optimization; the seed set is fixed a priori.
"""
import json
import pickle
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import mechanics_multiyear as mm
from portfolio_sim import portfolio_run
from universe_pt import elig_mask

OUT = Path(__file__).parent / "results"
BARS = OUT / "eligible_bars.pkl"
SEEDS = [1, 7, 13, 42, 99]


def main():
    bars_all = pickle.load(open(BARS, "rb"))
    tickers = sorted(t for t in bars_all if t != "SPY")
    spy = bars_all["SPY"].dropna()
    sc = {str(x.date()): float(r) for x, r in spy["Close"].items()}
    sm = {str(x.date()): float(r) for x, r in
          spy["Close"].rolling(20).mean().items()}
    results = {}
    for period, dates in mm.PERIODS.items():
        cand = []
        for t in tickers:
            df = bars_all[t]
            if len(df) < 270:
                continue
            for tr in mm.sim_period(df, sc, sm, dates, "LONG", "ORIG",
                                    elig=elig_mask(df)):
                tr["ticker"] = t
                tr["direction"] = "LONG"
                cand.append(tr)
        base = portfolio_run(cand, bars_all, *dates)
        navs = {}
        for seed in SEEDS:
            r = portfolio_run(cand, bars_all, *dates, order_seed=seed)
            navs[seed] = {"end_nav": r["end_nav"], "net_pct": r["net_pct"],
                          "admitted": r["admitted"], "net_pnl": r["net_pnl"],
                          "max_dd": r["max_dd"], "pf": r["pf"]}
        results[period] = {"alpha_order": {
            "end_nav": base["end_nav"], "net_pct": base["net_pct"],
            "admitted": base["admitted"], "net_pnl": base["net_pnl"],
            "max_dd": base["max_dd"], "pf": base["pf"],
            "reject_reasons": base["reject_reasons"]},
            "seed_navs": navs,
            "nav_range": [min(v["net_pct"] for v in navs.values()),
                          max(v["net_pct"] for v in navs.values())],
            "signals": base["signals"]}
        rr = base["reject_reasons"]
        print(period, "alpha nav%", base["net_pct"],
              "seeds range", results[period]["nav_range"],
              "rejects", rr)
    (OUT / "admission_sensitivity.json").write_text(
        json.dumps(results, indent=1))


if __name__ == "__main__":
    main()
