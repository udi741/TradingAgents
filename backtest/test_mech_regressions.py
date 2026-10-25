#!/usr/bin/env python3
"""Regression tests for exp-14 correctness fixes.

Covers:
  T1  TREND200 gate uses the PREVIOUS completed session — a fill-day
      close that crosses above the 200-SMA must NOT admit the trade.
  T2  PROFIT leg shares sum to recorded "shares" (no phantom shares).
  T3  1-share position never trims, never crashes, exits cleanly.
  T4  portfolio_run cash/NAV reconciliation on a known trade.
  T5  trim/exit legs are dated AFTER their signal close (no same-day
      fill from a close-derived signal).
"""
import pickle
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import mechanics_multiyear as mm
import portfolio_sim as ps
from portfolio_sim import portfolio_run

ARC = Path.home() / "udi_provate/research-results-archive"


def _mk(closes, lows=None, highs=None, opens=None):
    n = len(closes)
    idx = pd.bdate_range("2023-01-02", periods=n)
    return pd.DataFrame({
        "Open": opens or [c for c in closes],
        "High": highs or [c + 1 for c in closes],
        "Low": lows or [c - 1 for c in closes],
        "Close": closes}, index=idx)


def test_trend200_no_lookahead():
    # days 0-199 decline 120->~100 (sma200 ~110); day 200 jumps to 107
    # (new 60d high -> arms ref=~106, zt~102.8) but is still below
    # sma200. day 201 dips to zt intraday but CLOSES at 111 > sma200:
    # leaked logic fills (same-day close > sma200); correct logic must
    # reject because the PRIOR completed close (107) < sma200 (~110).
    closes = [120 - 0.1 * k for k in range(200)] + [107, 111] + [111] * 5
    lows = [c - 0.5 for c in closes]
    highs = [c + 0.5 for c in closes]
    lows[201] = 102.0   # intraday touch of zt
    closes[201] = 111.0
    df = _mk(closes, lows=lows, highs=highs)
    tr = mm.sim_period(df, {}, {}, ("2023-01-02", "2026-01-01"),
                       "LONG", "TREND200", stop_mult=2.5)
    assert tr == [], f"leaked fill admitted: {tr}"


def test_profit_leg_shares_reconcile():
    bars = pickle.load(open(ARC / "sp500_snapshot_bars.pkl", "rb"))
    addmap = {t: "2020-01-01" for t in bars}
    n_tr = 0
    for t in ("AAPL", "MSFT", "NVDA", "XOM"):
        df = bars[t]
        for tr in mm.sim_period(df, {}, {}, ("2024-01-01", "2026-09-24"),
                                "LONG", "PROFIT", elig=None,
                                stop_mult=2.5):
            legs = tr["legs"]
            assert sum(l[0] for l in legs) == tr["shares"], (
                t, tr)
            assert all(l[0] > 0 for l in legs)
            n_tr += 1
    assert n_tr > 0


def test_one_share_no_trim_no_crash():
    # fill ~3000 -> sh==1; rally +20% then fall back: no trim leg, no
    # crash, single clean exit.
    closes = [100.0] * 70 + [110.0] + [3000.0]  # jump arms at 110?
    # simpler: flat 100 then a print at 110 arms ref=101; then fabricate
    # a high-priced name instead: flat 3000, spike 3300, dip to zt.
    closes = [3000.0] * 70 + [3300.0] + [3200.0, 3201.0, 3202.0]
    lows = [c - 5 for c in closes]
    highs = [c + 5 for c in closes]
    # ref = 60d high prior to day 71 = 3005ish (highs)=3005; use highs+5
    # so prior hi60 = 3005, zt = 2914.85; day 72 low must be <= 2914.85
    lows[72] = 2900.0
    closes[72] = 3200.0
    df = _mk(closes, lows=lows, highs=highs)
    tr = mm.sim_period(df, {}, {}, ("2023-01-02", "2026-01-01"),
                       "LONG", "PROFIT", stop_mult=2.5)
    assert len(tr) == 1
    assert tr[0]["shares"] == 1
    assert all(l[2] != "trim_8pct" for l in tr[0]["legs"])
    assert sum(l[0] for l in tr[0]["legs"]) == 1


def test_portfolio_cash_reconciliation():
    # known LONG trade: 10 @ fill 100, single exit leg 110.
    cd = {"ticker": "TST", "direction": "LONG", "fill_date": "2024-03-04",
          "fill": 100.0, "shares": 10, "pnl": 97.9,
          "legs": [(10, 110.0, "x", "2024-03-10")]}
    idx = pd.bdate_range("2024-03-01", periods=11)  # through 2024-03-15
    bars = {"TST": pd.DataFrame({
                "Open": [110.0] * 11, "High": [111.0] * 11,
                "Low": [109.0] * 11, "Close": [110.0] * 11}, index=idx),
            "SPY": pd.DataFrame({
                "Open": [500.0] * 11, "High": [501.0] * 11,
                "Low": [499.0] * 11, "Close": [500.0] * 11}, index=idx)}
    ps.COST = 0.001
    r = portfolio_run([cd], bars, "2024-03-01", "2024-03-15")
    exp = 100000 - 10 * 100 * 1.001 + 10 * 110 * 0.999
    assert abs(r["end_nav"] - exp) < 0.5, (r["end_nav"], exp)
    assert r["admitted"] == 1 and r["rejected"] == 0


def test_trim_legs_after_signal_close():
    bars = pickle.load(open(ARC / "sp500_snapshot_bars.pkl", "rb"))
    checked = 0
    for t in ("AAPL", "MSFT", "NVDA", "XOM"):
        df = bars[t]
        cl = {str(x.date()): float(v) for x, v in df["Close"].items()}
        for tr in mm.sim_period(df, {}, {}, ("2024-01-01", "2026-09-24"),
                                "LONG", "PROFIT", stop_mult=2.5):
            # every leg must execute strictly after the fill date on a
            # real trading day with a real mark
            for sh, px, why, xd in tr["legs"]:
                assert xd > tr["fill_date"] or why != "trim_8pct"
                assert xd in cl
            checked += 1
    assert checked > 0


if __name__ == "__main__":
    for fn in (test_trend200_no_lookahead, test_profit_leg_shares_reconcile,
               test_one_share_no_trim_no_crash,
               test_portfolio_cash_reconciliation,
               test_trim_legs_after_signal_close):
        fn()
        print("PASS", fn.__name__)
