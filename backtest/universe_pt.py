#!/usr/bin/env python3
"""Task 1+2: mechanical LONG on a lower-bias point-in-time universe.

Universe = the 1,823 tickers in candidate_pool_frozen_2026-10-23 eligible
set (passed 252d history / $5 price / $20M median dv20 at Oct-2026).
Residual bias: names must have survived/listed through Oct-2026; delisted
stocks are absent (requires paid delisting data — reported dependency).
Per-entry-date eligibility is ALSO enforced: >=252 prior bars, close>=$5,
20d median dollar volume >=$20M — approximating the screener gates PIT.
"""
import json
import pickle
import sys
from pathlib import Path

import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).parent))
import mechanics_multiyear as mm
from portfolio_sim import portfolio_run, COST, START

OUT = Path(__file__).parent / "results"
CACHE = OUT / "eligible_bars.pkl"
POOL = Path("/home/udi/udi_provate/TradingAgents/evaluations/alpha_rnd_v1/"
            "candidate_pool_frozen_2026-10-23.json")


def elig_mask(df):
    dv = (df["Close"] * df["Volume"]).rolling(20).median()
    hist = pd.Series(range(len(df)), index=df.index) + 1
    return (hist >= 252) & (df["Close"] >= 5.0) & (dv >= 20_000_000)


def main():
    tickers = sorted(json.loads(POOL.read_text())["eligible_features"])
    print("PIT universe:", len(tickers))
    if CACHE.exists():
        bars_all = pickle.load(open(CACHE, "rb"))
    else:
        bars_all = {}
    missing = [t for t in tickers + ["SPY"] if t not in bars_all]
    for k in range(0, len(missing), 150):
        chunk = missing[k:k + 150]
        try:
            d = yf.download(chunk, start="2023-01-01", end="2026-09-25",
                            group_by="ticker", progress=False,
                            auto_adjust=True, threads=True)
            for t in chunk:
                try:
                    df = d[t].dropna() if len(chunk) > 1 else d.dropna()
                    if len(df):
                        bars_all[t] = df
                except Exception:
                    pass
        except Exception as e:
            print("chunk fail", k, e)
        print("fetched", min(k + 150, len(missing)), "of", len(missing))
    pickle.dump(bars_all, open(CACHE, "wb"))
    print("bars for", len(bars_all), "tickers")
    spy = bars_all["SPY"].dropna()
    spy_close = {str(x.date()): float(r) for x, r in spy["Close"].items()}
    spy_sma = {str(x.date()): float(r) for x, r in
               spy["Close"].rolling(20).mean().items()}
    results = {}
    for period, dates in mm.PERIODS.items():
        for variant in ("ORIG", "GAPFILT"):
            cand = []
            for t in tickers:
                df = bars_all.get(t)
                if df is None or len(df) < 270:
                    continue
                for tr in mm.sim_period(df, spy_close, spy_sma, dates,
                                        "LONG", variant,
                                        elig=elig_mask(df)):
                    tr["ticker"] = t
                    tr["direction"] = "LONG"
                    cand.append(tr)
            r = portfolio_run(cand, bars_all, *dates)
            results.setdefault(period, {})[variant] = r
            print(f"{period} {variant:8s} sig={r['signals']:4d} "
                  f"admit={r['admitted']:4d} nav={r['end_nav']:>9.0f} "
                  f"({r['net_pct']:+.1f}%) dd={r['max_dd']:>7.0f} "
                  f"pf={r['pf']} exp={r['expectancy']}")
        ks = sorted(k for k in spy_close if dates[0] <= k <= dates[1])
        if ks:
            results[period]["SPY"] = round(
                100 * (spy_close[ks[-1]] / spy_close[ks[0]] - 1), 2)
            print("  SPY", period, f"{results[period]['SPY']:+.2f}%")
    (OUT / "universe_pt.json").write_text(json.dumps(results, indent=1))


if __name__ == "__main__":
    main()
