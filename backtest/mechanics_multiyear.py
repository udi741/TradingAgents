#!/usr/bin/env python3
"""Multi-year MECHANICS experiment — NOT historical AI performance.

Tests whether the framework's deterministic entry/stop/exit machinery is
economically sound over multiple regimes, using a fixed mechanical proxy
for the AI-authored fields (zone/stop come from the model historically;
here they are computed mechanically and labeled as such).

Proxy (fixed a priori, matches production fill/stop semantics and the
recorded "post-breakout pullback" entry pattern):
  LONG:  after any session closes at a NEW 60-day high, watch up to 20
         sessions for a pullback touch of high*0.97; fill at that level;
         stop = fill - 2*ATR14; close_below -> next open; max hold 60
         sessions; else mark at period end. One position per ticker.
  SHORT: mirror — new 60-day LOW close, then short a retest bounce to
         low*1.03; stop = fill + 2*ATR14; close_above -> next open.
  One position per ticker at a time; 10 bps/side; $5k notional; whole shares;
  shorts borrow 2%/yr.

Variants (frozen rules):
  ORIG       = as above.
  GAPFILT    = skip LONG fill if any |ret|>=8% in the fill day's prior 5
               sessions (inclusive) or SPY close < its 20-SMA that day.
  PROFIT     = ORIG + trim 50% at first close >= +8%; trail rest at
               max(stop, peak_close-8pp), close_below -> next open.
  SHORT_ORIG = mirrored short mechanics only.

Periods (untouched by rule design): 2024 (rising), 2025 (mixed),
2026-01-01..2026-09-24 (pre-recording, ends before the Oct sample).

Survivorship caveat: universe = union of tickers the system actually
analyzed in Oct 2026 (~60 names) -> selection is hindsight-biased toward
names that existed/survived; results are a mechanics test, not strategy
alpha.
"""
import json
import sys
from pathlib import Path

import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).parent))
import historical_backtest as hb

OUT = Path(__file__).parent / "results"
COST = 0.001
NOTIONAL = 5000.0
MAX_HOLD = 60
PERIODS = {"2024": ("2024-01-01", "2024-12-31"),
           "2025": ("2025-01-01", "2025-12-31"),
           "2026YTD": ("2026-01-01", "2026-09-24")}
DATA_END = "2026-09-24"


def universe(ev):
    ts = set()
    for f in sorted(ev.glob("publication_intents_*.json")) + \
             sorted(ev.glob("replays/*/*/publication.json")):
        d = json.loads(f.read_text())
        its = d.get("intents")
        if isinstance(its, dict):
            its = its.values()
        elif its is None:
            its = [v.get("intent") for v in
                   (d.get("dispositions") or {}).values()]
        for i in its or []:
            if i and i.get("ticker"):
                ts.add(i["ticker"])
    return sorted(ts)


def sim_period(df, spy_close, spy_sma, dates, direction, variant,
               elig=None, stop_mult=2.0):
    """Walk a ticker's bars within [dates]; return trade dicts."""
    hi60 = df["Close"].rolling(60).max()
    lo60 = df["Close"].rolling(60).min()
    atr = (df["High"] - df["Low"]).rolling(14).mean()
    ret = df["Close"].pct_change().abs()
    trades = []
    watch_until = -1
    ref = None
    arm_day = -1
    i = 61
    while i < len(df):
        s = str(df.index[i].date())
        if s < dates[0]:
            i += 1
            continue
        if s > dates[1]:
            break
        o, h, l, c = (float(df.iloc[i][k]) for k in
                      ("Open", "High", "Low", "Close"))
        a = float(atr.iloc[i])
        if pd.isna(a) or a <= 0:
            i += 1
            continue
        if elig is not None and not bool(elig.iloc[i]):
            i += 1
            continue
        # signal day arms a 20-session watch (retest of the 60d extreme)
        # arming needs the signal-day CLOSE; fills only on later bars
        if direction == "LONG" and c >= float(hi60.iloc[i - 1]):
            watch_until, ref, arm_day = i + 20, float(hi60.iloc[i - 1]), i
        if direction == "SHORT" and c <= float(lo60.iloc[i - 1]):
            watch_until, ref, arm_day = i + 20, float(lo60.iloc[i - 1]), i
        if i <= arm_day or i > watch_until or ref is None:
            i += 1
            continue
        if direction == "LONG":
            zt = ref * 0.97
            if l > zt:
                i += 1
                continue
            # GAPFILT check (on the would-be fill day)
            if variant in ("GAPFILT", "SPYGATE"):
                if variant == "GAPFILT" and \
                        (ret.iloc[max(0, i - 4):i + 1] >= 0.08).any():
                    i += 1
                    continue
                sp = spy_close.get(s)
                if sp is not None and sp < spy_sma.get(s, 0):
                    i += 1
                    continue
            fill = zt
            stop = fill - stop_mult * a
        else:
            zb = ref * 1.03
            if h < zb:
                i += 1
                continue
            fill = zb
            stop = fill + stop_mult * a
        # manage
        sh = int(NOTIONAL / fill)
        if sh < 1:
            i += 1
            continue
        watch_until, arm_day = -1, -1  # consume the armed signal
        legs, peak, state = [], fill, "OPEN"
        j = i
        while j < len(df) and j - i <= MAX_HOLD:
            b = df.iloc[j]
            sj = str(b.name.date())
            if sj > dates[1]:
                break
            bo, bh, bl, bc = (float(b[k]) for k in
                              ("Open", "High", "Low", "Close"))
            if direction == "LONG":
                if state == "OPEN":
                    if bc < stop:
                        nxp = float(df.iloc[j + 1]["Open"]) \
                            if j + 1 < len(df) else bc
                        legs.append((sh, nxp, "close_below_stop", str(df.iloc[j + 1].name.date()) if j + 1 < len(df) else sj)); state = "DONE"; break
                    if variant == "PROFIT" and bc >= fill * 1.08:
                        half = sh // 2 or 1
                        nxp = float(df.iloc[j + 1]["Open"]) \
                            if j + 1 < len(df) else bc
                        legs.append((half, nxp, "trim_8pct", str(df.iloc[j + 1].name.date()) if j + 1 < len(df) else sj))
                        sh -= half
                        state = "TRAIL"
                else:
                    peak = max(peak, bc)
                    trail = max(stop, peak * 0.92)
                    if bc <= trail:
                        nxp = float(df.iloc[j + 1]["Open"]) \
                            if j + 1 < len(df) else bc
                        legs.append((sh, nxp, "trail_exit", str(df.iloc[j + 1].name.date()) if j + 1 < len(df) else sj)); state = "DONE"; break
            else:  # SHORT
                if bc > stop:
                    nxp = float(df.iloc[j + 1]["Open"]) \
                        if j + 1 < len(df) else bc
                    legs.append((sh, nxp, "close_above_stop", str(df.iloc[j + 1].name.date()) if j + 1 < len(df) else sj)); state = "DONE"; break
            j += 1
        if state != "DONE":
            xp = float(df.iloc[min(j, len(df) - 1)]["Close"])
            legs.append((sh, xp, "period_or_horizon_exit", str(df.index[min(j, len(df) - 1)].date())))
        if direction == "LONG":
            pnl = sum(s_ * xp * (1 - COST) - s_ * fill * (1 + COST)
                      for s_, xp, *_ in legs)
        else:
            held_days = j - i
            pnl = sum(s_ * (fill * (1 - COST) - xp * (1 + COST))
                      for s_, xp, *_ in legs) \
                - sh * fill * 0.02 / 365 * held_days
        trades.append({"fill_date": s, "fill": round(fill, 2),
                       "stop": round(stop, 2), "shares": sh,
                       "legs": [(a_, round(p_, 2), w, xd) for a_, p_, w, xd in legs],
                       "pnl": round(pnl, 2),
                       "ret_pct": round(sum(s_ * (xp - fill) for s_, xp, *_
                                            in legs) / (trades and 1 or 1) /
                                        (sh * fill) * 100, 2)
                       if direction == "LONG" else
                       round(sum(s_ * (fill - xp) for s_, xp, *_ in legs)
                             / (sh * fill) * 100, 2)})
        i = j + 1  # next signal only after exit (one position per ticker)
    return trades


def agg(trades):
    n = len(trades)
    w = [t for t in trades if t["pnl"] > 0]
    gp = sum(t["pnl"] for t in w)
    gl = -sum(t["pnl"] for t in trades if t["pnl"] <= 0)
    eq = sorted((t["fill_date"], t["pnl"]) for t in trades)
    cum = peak = mdd = 0.0
    for _, p in eq:
        cum += p
        peak = max(peak, cum)
        mdd = max(mdd, peak - cum)
    return {"n": n, "win_rate": round(len(w) / n, 3) if n else 0,
            "net": round(sum(t["pnl"] for t in trades), 2),
            "avg_win": round(gp / len(w), 1) if w else 0,
            "avg_loss": round(-gl / (n - len(w)), 1) if n - len(w) else 0,
            "expectancy": round(sum(t["pnl"] for t in trades) / n, 1) if n else 0,
            "pf": round(gp / gl, 2) if gl > 0 else None,
            "max_dd": round(mdd, 2)}


def main():
    ev = Path("/home/udi/udi_provate/TradingAgents/evaluations/alpha_rnd_v1")
    tickers = universe(ev)
    print("universe:", len(tickers), "tickers")
    d = yf.download(tickers + ["SPY"], start="2023-11-01", end="2026-09-25",
                    group_by="ticker", progress=False, auto_adjust=True,
                    threads=True)
    spy = d["SPY"].dropna()
    spy_close = {str(x.date()): float(r) for x, r in spy["Close"].items()}
    spy_sma = {str(x.date()): float(r) for x, r in
               spy["Close"].rolling(20).mean().items()}
    results = {}
    for period, dates in PERIODS.items():
        results[period] = {}
        for variant, direction in (("ORIG", "LONG"), ("GAPFILT", "LONG"),
                                   ("PROFIT", "LONG"), ("SHORT_ORIG", "SHORT")):
            all_trades = []
            for t in tickers:
                try:
                    df = d[t].dropna()
                except Exception:
                    continue
                if len(df) < 40:
                    continue
                all_trades += sim_period(df, spy_close, spy_sma, dates,
                                         direction, variant)
            results[period][variant] = {"stats": agg(all_trades),
                                        "trades": all_trades}
            s = results[period][variant]["stats"]
            print(f"{period} {variant:10s} n={s['n']:3d} win={s['win_rate']} "
                  f"net={s['net']:>9.0f} exp={s['expectancy']:>7.1f} "
                  f"pf={s['pf']} dd={s['max_dd']:.0f}")
        # benchmark
        e, x = spy_close.get(dates[0]), spy_close.get(dates[1])
        if e and x:
            print(f"  SPY {period}: {100*(x/e-1):+.1f}%")
    (OUT / "mechanics_multiyear.json").write_text(json.dumps(results, indent=1))


if __name__ == "__main__":
    main()
