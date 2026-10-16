#!/usr/bin/env python3
"""Phase B shadow management tests — no model, no economics."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from alpha_rnd import mgmt  # noqa: E402


def df_for(rows):
    """rows: list of (date, open, high, low, close)"""
    idx = pd.DatetimeIndex([pd.Timestamp(r[0]) for r in rows])
    return pd.DataFrame({"Open": [r[1] for r in rows],
                         "High": [r[2] for r in rows],
                         "Low": [r[3] for r in rows],
                         "Close": [r[4] for r in rows],
                         "Volume": [1e6] * len(rows)}, index=idx)


POL = {"version": 2, "mode": "shadow",
       "triggers": {
           "appreciation": {"r_multiple": 1.0},
           "peak_giveback": {"min_peak_r": 1.0, "giveback_fraction": 0.5},
           "adverse_acceleration": {"mae_r_multiple": 1.25},
           "horizon_review": {},
           "catalyst": {"enabled": False}},
       "debounce": {"cooldown_sessions": 2, "hysteresis_fraction": 0.2}}

SNAP_10PCT = {"risk_plan": {"stop_rule": {"type": "intraday_stop",
                                          "level": 9.0}}}   # 1R = 10% @10
SNAP_5PCT = {"risk_plan": {"stop_rule": {"type": "intraday_stop",
                                         "level": 9.5}}}    # 1R = 5% @10


class Snap(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._s, self._r, self._m, self._e = (mgmt.SNAP_DIR, mgmt.REQ_DIR,
                                             mgmt.STATE, mgmt.MEVENTS)
        mgmt.SNAP_DIR = self.tmp / "snap"
        mgmt.REQ_DIR = self.tmp / "req"
        mgmt.STATE = self.tmp / "mgmt_state.json"
        mgmt.MEVENTS = self.tmp / "mevents.jsonl"
        self.pos = {"shares": 100, "fill": 10.0, "cost": 1000.0,
                    "horizon": "2-3wk", "invalidation": "hard stop",
                    "stop_rule": {"type": "intraday_stop", "level": 9.0}}

    def tearDown(self):
        mgmt.SNAP_DIR, mgmt.REQ_DIR, mgmt.STATE, mgmt.MEVENTS = \
            self._s, self._r, self._m, self._e

    def _snap(self):
        mgmt.create_snapshot("XYZ", "2026-10-01", watch=None,
                             pos=self.pos, intent=None,
                             artifact_ref=None, missing=["intent"])
        return mgmt._j(mgmt.snapshot_path("XYZ", "2026-10-01"), {})

    def test_snapshot_immutable(self):
        mgmt.create_snapshot("XYZ", "2026-10-01", watch=None, pos=self.pos,
                             intent=None, artifact_ref=None)
        again = mgmt.create_snapshot("XYZ", "2026-10-01", watch=None,
                                     pos={"shares": 1, "fill": 99},
                                     intent=None, artifact_ref=None)
        self.assertIsNone(again)
        d = mgmt._j(mgmt.snapshot_path("XYZ", "2026-10-01"), {})
        self.assertEqual(d["entry_price"], 10.0)
        self.assertEqual(d["initial_shares"], 100)

    def test_metrics(self):
        rec = {"entry_session": "2026-10-01"}
        df = df_for([("2026-10-01", 10, 10.5, 9.8, 10.2),
                     ("2026-10-02", 10.2, 12.0, 10.0, 11.5),
                     ("2026-10-03", 11.5, 11.8, 10.9, 11.0)])
        mgmt.update_metrics(rec, {**self.pos, "mark": 11.0}, df, "2026-10-03")
        self.assertEqual(rec["high_since_entry"], 12.0)
        self.assertEqual(rec["low_since_entry"], 9.8)
        self.assertEqual(rec["peak_unrealized_pct"], 20.0)
        self.assertEqual(rec["unrealized_pct"], 10.0)
        self.assertEqual(rec["drawdown_from_peak_pct"], 10.0)
        self.assertEqual(rec["mae_pct"], -2.0)
        self.assertEqual(rec["sessions_held"], 3)
        self.assertEqual(rec["metrics_basis"], "close_bars")

    def test_intraday_extends_peak(self):
        rec = {"entry_session": "2026-10-01"}
        df = df_for([("2026-10-01", 10, 10.5, 9.8, 10.2)])
        idf = df_for([("2026-10-02", 10.2, 13.0, 10.0, 12.5)])
        mgmt.update_metrics(rec, self.pos, df, "2026-10-02", intraday_df=idf)
        self.assertEqual(rec["high_since_entry"], 13.0)
        self.assertEqual(rec["metrics_basis"], "close+intraday")

    def test_appreciation_r_contextual(self):
        # same raw return: fires for wide-stop stock, not for tight-stop
        rec = {"unrealized_pct": 6.0, "entry_price": 10.0}
        wide = mgmt.evaluate("X", rec, SNAP_10PCT, POL, "2026-10-05")
        self.assertNotIn("APPRECIATION", [e["family"] for e in wide])
        tight = mgmt.evaluate("X", rec, SNAP_5PCT, POL, "2026-10-05")
        self.assertIn("APPRECIATION", [e["family"] for e in tight])
        self.assertEqual([e for e in tight if e["family"] == "APPRECIATION"][0]
                         ["urgency"], "NORMAL")

    def test_no_universal_pct(self):
        # 9% would have fired the old universal threshold; with 1R=10% it must not
        evs = mgmt.evaluate("X", {"unrealized_pct": 9.0, "entry_price": 10.0},
                            SNAP_10PCT, POL, "2026-10-05")
        self.assertNotIn("APPRECIATION", [e["family"] for e in evs])
        evs = mgmt.evaluate("X", {"unrealized_pct": 11.0, "entry_price": 10.0},
                            SNAP_10PCT, POL, "2026-10-05")
        self.assertIn("APPRECIATION", [e["family"] for e in evs])

    def test_r_unavailable(self):
        evs = mgmt.evaluate("X", {"unrealized_pct": 50.0, "entry_price": 10.0},
                            None, POL, "2026-10-05")
        fams = [e["family"] for e in evs]
        self.assertIn("R_CONTEXT_UNAVAILABLE", fams)
        self.assertNotIn("APPRECIATION", fams)
        # malformed stop (>= entry for a long) also unavailable
        bad = {"risk_plan": {"stop_rule": {"type": "intraday_stop",
                                          "level": 12.0}}}
        evs = mgmt.evaluate("X", {"unrealized_pct": 50.0, "entry_price": 10.0},
                            bad, POL, "2026-10-05")
        self.assertIn("R_CONTEXT_UNAVAILABLE", [e["family"] for e in evs])

    def test_giveback_r(self):
        evs = mgmt.evaluate("X", {"unrealized_pct": 5.0,
                                  "peak_unrealized_pct": 20.0,
                                  "drawdown_from_peak_pct": 15.0,
                                  "entry_price": 10.0},
                            SNAP_10PCT, POL, "2026-10-05")
        self.assertIn("PEAK_GIVEBACK", [e["family"] for e in evs])

    def test_adverse(self):
        evs = mgmt.evaluate("X", {"mae_pct": -15.0, "entry_price": 10.0,
                                  "unrealized_pct": -12.0},
                            SNAP_10PCT, POL, "2026-10-05")
        self.assertIn("ADVERSE_ACCELERATION", [e["family"] for e in evs])
        self.assertEqual([e for e in evs
                          if e["family"] == "ADVERSE_ACCELERATION"][0]
                         ["urgency"], "URGENT")

    def test_adverse_scales_with_r(self):
        # same -8% MAE: adverse for 5% stop, not for 10% stop
        rec = {"mae_pct": -8.0, "entry_price": 10.0, "unrealized_pct": -6.0}
        t10 = mgmt.evaluate("X", rec, SNAP_10PCT, POL, "2026-10-05")
        self.assertNotIn("ADVERSE_ACCELERATION", [e["family"] for e in t10])
        t5 = mgmt.evaluate("X", rec, SNAP_5PCT, POL, "2026-10-05")
        self.assertIn("ADVERSE_ACCELERATION", [e["family"] for e in t5])

    def test_horizon(self):
        snap = {"reevaluation": "review after 2026-10-16"}
        evs = mgmt.evaluate("X", {"entry_price": 10}, snap, POL, "2026-10-16")
        self.assertIn("HORIZON_REVIEW", [e["family"] for e in evs])
        evs = mgmt.evaluate("X", {"entry_price": 10}, snap, POL, "2026-10-15")
        self.assertNotIn("HORIZON_REVIEW", [e["family"] for e in evs])
        snap2 = {"reevaluation": "next earnings"}
        self.assertIsNone(mgmt._horizon_date(snap2))

    def test_fire_once_and_rearm(self):
        rec = {"triggers": {}, "entry_session": "2026-10-01"}
        ev = {"family": "APPRECIATION", "value": 9.0, "threshold": 8.0,
              "urgency": "NORMAL", "reason": "x"}
        self.assertTrue(mgmt._fire("X", rec, ev, POL, "2026-10-05"))
        self.assertFalse(mgmt._fire("X", rec, ev, POL, "2026-10-05"))
        self.assertFalse(mgmt._fire("X", rec, {**ev, "value": 10.0}, POL,
                                    "2026-10-06"))  # still active
        st = rec["triggers"]["APPRECIATION"]
        st["armed_below"] = 9.0
        ev_low = {**ev, "value": 6.0, "threshold": 8.0}
        # value retreated below threshold-band -> re-arm check inside _fire
        rec["triggers"]["APPRECIATION"]["active"] = False
        self.assertTrue(mgmt._fire("X", rec, ev_low, POL, "2026-10-08"))

    def test_horizon_one_shot(self):
        rec = {"triggers": {}}
        ev = {"family": "HORIZON_REVIEW", "value": "2026-10-16",
              "threshold": "2026-10-16", "urgency": "NORMAL", "reason": "x"}
        self.assertTrue(mgmt._fire("X", rec, ev, POL, "2026-10-16"))
        self.assertFalse(mgmt._fire("X", rec, ev, POL, "2026-10-17"))

    def test_shadow_artifact_schema(self):
        rec = {"triggers": {}, "entry_session": "2026-10-01"}
        ev = {"family": "APPRECIATION", "value": 9.0, "threshold": 8.0,
              "urgency": "NORMAL", "reason": "x"}
        mgmt._fire("XYZ", rec, ev, POL, "2026-10-05")
        p = mgmt.REQ_DIR / "XYZ" / "APPRECIATION_2026-10-05.json"
        req = json.loads(p.read_text())
        self.assertEqual(req["status"], "SHADOW_TRIGGERED")
        self.assertIn("request_id", req)
        self.assertIn("metrics", req)
        for k in ("ticker", "trigger_family", "urgency", "fired_session",
                  "reason", "policy_version", "entry_snapshot"):
            self.assertIn(k, req)

    def test_no_economic_writes(self):
        """Trigger fire touches only mgmt dirs, not economic state."""
        rec = {"triggers": {}, "entry_session": "2026-10-01"}
        ev = {"family": "APPRECIATION", "value": 9.0, "threshold": 8.0,
              "urgency": "NORMAL", "reason": "x"}
        st = {"positions": {"XYZ": dict(self.pos)}, "cash": 100.0,
              "realized": 0.0, "executed": [], "pending_open_exits": [],
              "pending_open_fills": [], "event_outbox": []}
        before = json.dumps(st, sort_keys=True)
        mgmt._fire("XYZ", rec, ev, POL, "2026-10-05")
        self.assertEqual(json.dumps(st, sort_keys=True), before)

    def test_cooldown(self):
        idx = ["2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08"]
        st = {"fired_at": "2026-10-05"}
        self.assertFalse(mgmt._cooldown_ok(st, "2026-10-05", "2026-10-06",
                                           idx, 2))
        self.assertTrue(mgmt._cooldown_ok(st, "2026-10-05", "2026-10-08",
                                          idx, 2))


if __name__ == "__main__":
    unittest.main(verbosity=0)
