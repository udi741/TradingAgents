#!/usr/bin/env python3
"""Part 1: portfolio-constrained re-run of the mechanics experiment.

Enforces: $100k start, <=$5k/position, <=10 simultaneous positions, no
borrowing/leverage, chronological admission (same-day ties by ticker),
no entry when cash insufficient. NAV marked daily at closes.
"""
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).parent))
import mechanics_multiyear as mm

COST = 0.001
NOTIONAL = 5000.0
MAX_POS = 10
START = 100000.0
OUT = Path(__file__).parent / "results"


_DATES_CACHE = [None, []]
_CLOSE_CACHE = {}


def portfolio_run(candidates, bars, period_start, period_end,
                  order_seed=None, return_detail=False, priority_fn=None):
    """candidates: trade dicts with fill_date, legs (with dates).
    Returns portfolio stats + admitted trade set."""
    # events: date -> {"exits": [(ticker, shares, px)], "entries": [cand]}
    exits = defaultdict(list)
    entries = defaultdict(list)
    for cd in candidates:
        entries[cd["fill_date"]].append(cd)
    if _DATES_CACHE[0] is None or len(_DATES_CACHE[1]) != len(bars):
        _DATES_CACHE[0] = {str(x.date()) for df in bars.values()
                           for x in df.index}
        _DATES_CACHE[1] = [None] * len(bars)
        _CLOSE_CACHE.clear()
        for t, df in bars.items():
            _CLOSE_CACHE[t] = dict(zip(
                (str(x.date()) for x in df.index),
                (float(v) for v in df["Close"])))
    dates = sorted(d for d in _DATES_CACHE[0] | set(entries)
                   if d <= period_end)
    cash = START
    pos = {}      # ticker -> {"shares":..., "fill":..., "legs": [...], "cd":...}
    admitted, rejected = [], []
    nav_series = {}
    employed = 0.0
    for s in dates:
        # process exits (legs due today)
        for t, p in list(pos.items()):
            while p["legs"] and p["legs"][0][3] <= s:
                sh, xp, why, xd = p["legs"].pop(0)
                if xd <= s:
                    # LONG: cash back = shares*cover*(1-C);
                    # SHORT: margin held = shares*fill*(1+C) at entry, so exit
                    # credits margin + pnl = shares*(2*fill - xp) net of costs.
                    if p["cd"]["direction"] == "LONG":
                        cash += sh * xp * (1 - COST)
                    else:
                        cash += sh * (2 * p["fill"] - xp) \
                            - sh * COST * (p["fill"] + xp)
                    p["shares"] -= sh
            if p["shares"] <= 0:
                pos.pop(t)
        # process entries for today (tie-break: ticker, or seed-shuffled)
        day_entries = entries.get(s, [])
        if order_seed is not None:
            # stable hash (md5): builtin hash() is salted per process,
            # so seeded orderings were not reproducible before this fix
            day_entries = sorted(day_entries, key=lambda c: int(
                hashlib.md5(f'{order_seed}:{c["ticker"]}'.encode())
                .hexdigest(), 16))
        elif priority_fn is not None:
            day_entries = sorted(day_entries,
                                 key=lambda c: (priority_fn(c), c["ticker"]))
        else:
            day_entries = sorted(day_entries, key=lambda c: c["ticker"])
        for cd in day_entries:
            t = cd["ticker"]
            if t in pos:
                rejected.append((cd, "dup_ticker"))
                continue
            if len(pos) >= MAX_POS:
                rejected.append((cd, "no_slot"))
                continue
            need = cd["shares"] * cd["fill"] * (1 + COST)
            if need > cash:
                rejected.append((cd, "insufficient_cash"))
                continue
            cash -= need
            pos[t] = {"shares": cd["shares"], "fill": cd["fill"],
                      "legs": list(cd["legs"]), "cd": cd}
            admitted.append(cd)
        # mark
        mv = 0.0
        for t, p in pos.items():
            cc = _CLOSE_CACHE.get(t)
            c = None
            if cc is not None:
                dmark = max(d2 for d2 in cc if d2 <= s)
                c = cc[dmark]
            mv += (c or p["fill"]) * p["shares"]
        nav_series[s] = cash + mv
        employed = max(employed, sum(p["shares"] * p["fill"]
                                     for p in pos.values()))
    navs = list(nav_series.values())
    peak = START
    mdd = 0.0
    for v in navs:
        peak = max(peak, v)
        mdd = max(mdd, peak - v)
    max_employed = employed
    pnl = sum(c["pnl"] for c in admitted)
    w = [c for c in admitted if c["pnl"] > 0]
    gp = sum(c["pnl"] for c in w)
    gl = -sum(c["pnl"] for c in admitted if c["pnl"] <= 0)
    return {"start": START, "end_nav": round(navs[-1], 2) if navs else START,
            "net_pnl": round(pnl, 2), "net_pct": round(100 * (navs[-1] / START - 1), 2) if navs else 0,
            "max_dd": round(mdd, 2),
            "signals": len(candidates), "admitted": len(admitted),
            "rejected": len(rejected),
            "reject_reasons": {r: sum(1 for _, rr in rejected if rr == r)
                               for r in {rr for _, rr in rejected}},
            "winners": len(w), "losers": len(admitted) - len(w),
            "pf": round(gp / gl, 2) if gl > 0 else None,
            "expectancy": round(pnl / len(admitted), 1) if admitted else 0,
            "max_capital": round(max_employed, 2),
            "admitted_trades": [{"ticker": c["ticker"], "in": c["fill_date"],
                                 "px": c["fill"], "pnl": c["pnl"],
                                 "dir": c["direction"]} for c in admitted]}


def main():
    # reload per-ticker candidate trades via sim_period (with direction tag)
    ev = Path("/home/udi/udi_provate/TradingAgents/evaluations/alpha_rnd_v1")
    tickers = mm.universe(ev)
    d = yf.download(tickers + ["SPY"], start="2023-11-01", end="2026-09-25",
                    group_by="ticker", progress=False, auto_adjust=True,
                    threads=True)
    spy = d["SPY"].dropna()
    spy_close = {str(x.date()): float(r) for x, r in spy["Close"].items()}
    spy_sma = {str(x.date()): float(r) for x, r in
               spy["Close"].rolling(20).mean().items()}
    bars = {t: (d[t].dropna() if len(tickers) > 1 else d.dropna())
            for t in tickers}
    results = {}
    for period, dates in mm.PERIODS.items():
        results[period] = {}
        for variant, direction in (("ORIG", "LONG"), ("GAPFILT", "LONG"),
                                   ("PROFIT", "LONG"), ("SHORT_ORIG", "SHORT")):
            cand = []
            for t in tickers:
                df = bars[t]
                if len(df) < 40:
                    continue
                for tr in mm.sim_period(df, spy_close, spy_sma, dates,
                                        direction, variant):
                    tr["ticker"] = t
                    tr["direction"] = direction
                    cand.append(tr)
            r = portfolio_run(cand, bars, *dates)
            results[period][variant] = r
            print(f"{period} {variant:10s} sig={r['signals']:4d} "
                  f"admit={r['admitted']:4d} rej={r['rejected']:3d} "
                  f"nav={r['end_nav']:>9.0f} ({r['net_pct']:+.1f}%) "
                  f"dd={r['max_dd']:>7.0f} pf={r['pf']} exp={r['expectancy']}")
        def _px(m, d):
            ks = sorted(k for k in m if k <= d)
            return m[ks[-1]] if ks else None
        e, x = _px(spy_close, dates[0]), _px(spy_close, dates[1])
        if e and x:
            results[period]["SPY"] = round(100 * (x / e - 1), 2)
            print(f"  SPY {period}: {results[period]['SPY']:+.2f}%")
        # survivorship gauge: equal-weight universe return IN period vs SPY
        u = []
        for t in tickers:
            df = bars[t]
            c0 = df[df.index.strftime("%Y-%m-%d") <= dates[0]]["Close"]
            c1 = df[df.index.strftime("%Y-%m-%d") <= dates[1]]["Close"]
            if len(c0) and len(c1):
                u.append(float(c1.iloc[-1] / c0.iloc[-1] - 1))
        results[period]["universe_eq_ret_pct"] = round(
            100 * sum(u) / len(u), 2)
        print(f"  universe eq-weight {period}: "
              f"{results[period]['universe_eq_ret_pct']:+.1f}%")
    (OUT / "portfolio_sim.json").write_text(json.dumps(results, indent=1))


if __name__ == "__main__":
    main()
