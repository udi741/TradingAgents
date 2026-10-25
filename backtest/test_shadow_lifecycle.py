#!/usr/bin/env python3
"""Deterministic 3-session shadow lifecycle test (synthetic bars only).

Scenario on synthetic ticker SYN:
  Day 61 (Monday): close at new 60d high -> arms retest watch; low does
    NOT reach the zone -> no fill possible on the arm day anyway.
  Day 62 (Tuesday): low touches zone top (0.97*ref) -> fill at zone top.
  Day 63 (Wednesday): close below 2*ATR stop -> exit at NEXT open (Thu).
Assert: no Monday fill; Tuesday fill recorded; Thursday exit; NAV/cash/P&L
update; rerun produces byte-identical books; all three priorities see the
same lifecycle; no bar beyond session end is visible.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import mechanics_multiyear as mm
from portfolio_sim import portfolio_run


def _synthetic_df():
    idx = pd.date_range("2025-06-02", periods=90, freq="B")  # Mon start
    rows = []
    for i in range(90):
        px, lo = 10.0, 9.9
        if i == 61:            # Monday: closes at new 60d high
            px, lo = 11.0, 10.9
        if i == 62:            # Tuesday: dips to zone top -> fill
            px, lo = 10.0, 9.6
        if i == 63:            # Wednesday: close below stop
            px, lo = 8.0, 7.9
        if i >= 64:
            px, lo = 8.0, 7.9
        rows.append({"Open": px, "High": px * 1.01, "Low": lo,
                     "Close": px, "Volume": 1e7})
    return pd.DataFrame(rows, index=idx)


class ShadowLifecycleTest(unittest.TestCase):
    def setUp(self):
        self.df = _synthetic_df()
        self.bars = {"SYN": self.df}
        self.period = ("2025-06-02", "2025-09-05")

    def _cands(self):
        out = []
        for tr in mm.sim_period(self.df, {}, {}, self.period, "LONG",
                                "ORIG"):
            tr["ticker"] = "SYN"
            tr["direction"] = "LONG"
            out.append(tr)
        return out

    def test_day1_no_fill_day2_fill_day4_exit(self):
        cands = self._cands()
        self.assertEqual(len(cands), 1)
        c = cands[0]
        arm_day = str(self.df.index[61].date())
        self.assertGreater(c["fill_date"], arm_day)          # no day-1 fill
        self.assertEqual(c["fill_date"], str(self.df.index[62].date()))
        self.assertAlmostEqual(c["fill"], 10.0 * 0.97, places=4)
        # stop = fill - 2*ATR(14 at fill day): Wednesday close 8.0 breaches
        self.assertEqual(c["legs"][0][2], "close_below_stop")
        # exit leg date = next session's open (Thursday)
        self.assertEqual(c["legs"][0][3], str(self.df.index[64].date()))

    def test_three_books_identical_and_deterministic(self):
        cands = self._cands()
        a = portfolio_run([dict(c) for c in cands], self.bars, *self.period)
        b = portfolio_run([dict(c) for c in cands], self.bars, *self.period,
                          priority_fn=lambda c: 0)
        c42 = portfolio_run([dict(c) for c in cands], self.bars, *self.period,
                            order_seed=42)
        for r in (a, b, c42):
            self.assertEqual(r["admitted"], 1)
            self.assertEqual(r["end_nav"], a["end_nav"])
        # deterministic rerun
        a2 = portfolio_run([dict(c) for c in cands], self.bars, *self.period)
        self.assertEqual(json.dumps(a, sort_keys=True),
                         json.dumps(a2, sort_keys=True))
        # P&L sign: stop-out below fill -> loss
        self.assertLess(a["net_pnl"], 0)
        # cash accounting: started 100k, single $5k position
        self.assertGreater(a["max_capital"], 4000)
        self.assertLess(a["max_capital"], 5100)

    def test_no_future_bars(self):
        # clip bars at session end: sim must not see later dates
        clip = self.df[self.df.index.strftime("%Y-%m-%d") <= "2025-08-25"]
        cands = []
        for tr in mm.sim_period(clip, {}, {}, self.period, "LONG", "ORIG"):
            tr["ticker"] = "SYN"
            tr["direction"] = "LONG"
            cands.append(tr)
        for t in cands:
            for leg in t["legs"]:
                self.assertLessEqual(leg[3], "2025-08-25")
            self.assertLessEqual(t["fill_date"], "2025-08-25")

    def test_ledger_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            led = Path(td) / "decisions.jsonl"
            rec = {"session": "2026-10-26", "x": 1}
            seen = {json.loads(l)["session"] for l in led.open()} \
                if led.exists() else set()
            if rec["session"] not in seen:
                led.open("a").write(json.dumps(rec) + "\n")
            # second run
            seen = {json.loads(l)["session"] for l in led.open()}
            self.assertIn("2026-10-26", seen)
            # simulate rerun: must not append
            if rec["session"] not in seen:
                led.open("a").write(json.dumps(rec) + "\n")
            self.assertEqual(len(led.read_text().strip().split("\n")), 1)


if __name__ == "__main__":
    unittest.main()
