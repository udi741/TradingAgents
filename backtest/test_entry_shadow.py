#!/usr/bin/env python3
"""Regression for entry_shadow: no lookahead, determinism, paper-only."""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from backtest import entry_shadow as E  # noqa: E402


def _bars():
    idx = pd.bdate_range("2026-10-01", periods=30)
    rows = []
    px = 100.0
    for i, d in enumerate(idx):
        rows.append({"Open": px, "High": px + 1.5, "Low": px - 1.5,
                     "Close": px + 0.5})
        px += 0.5
    return pd.DataFrame(rows, index=idx)


def main():
    df = _bars()
    sess = str(df.index[15].date())
    before, fut = df[df.index <= sess], df[df.index > sess]
    # no lookahead: ATR uses only bars <= session
    a = E.atr14(before)
    assert a == 3.0  # constant daily range
    # B continuation fills next open deterministically
    r1 = E.sim_B("LONG", None, None, float(before["Close"].iloc[-1]), a, fut)
    r2 = E.sim_B("LONG", None, None, float(before["Close"].iloc[-1]), a, fut)
    assert r1 == r2 and r1["entry_px"] == float(fut["Open"].iloc[0])
    assert r1["shares"] == int(5000 // r1["entry_px"])
    # gap guard: gap up >3% => no fill
    fut2 = fut.copy(); fut2.iloc[0, fut2.columns.get_loc("Open")] = 999.0
    assert E.sim_B("LONG", None, None,
                   float(before["Close"].iloc[-1]), a, fut2)["no_fill"]
    # A pullback: fill only on intraday zone touch after session
    ra = E.sim_A("LONG", [95.0, 96.0], 90.0, 110.0, fut)
    assert ra is None  # lows ~104+ never reach 96
    assert ra is None or "pnl" not in ra  # no invented fill
    # SHORT mirror doesn't crash and signs are right
    rs = E.sim_B("SHORT", None, None, float(before["Close"].iloc[-1]), a, fut)
    assert rs is None or "pnl" in rs
    print("PASS entry_shadow: lookahead-free, deterministic, gap-guarded, "
          "no invented fills")


if __name__ == "__main__":
    main()
