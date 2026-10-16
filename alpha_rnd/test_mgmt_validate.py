#!/usr/bin/env python3
"""Phase D validator tests — shadow only."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from alpha_rnd import mgmt, mgmt_reassess as mr  # noqa: E402
from alpha_rnd import mgmt_validate as mv  # noqa: E402

POS = {"shares": 100, "fill": 10.0,
       "stop_rule": {"type": "intraday_stop", "level": 9.0}}
ST = {"positions": {"XYZ": dict(POS)}, "pending_open_exits": []}
WL = {"open_positions": []}


def dec(action, **kw):
    d = {"ticker": "XYZ", "status": "SUCCESS", "context_hash": "c",
         "request_refs": [], "analyzed_at": "2026-10-05T00",
         "position_state_hash": "x",
         "analysis": {"recommended_action": action,
                      "thesis_status": "INTACT",
                      "catalyst_status": "PENDING", "confidence": "medium"}}
    d["analysis"].update(kw)
    return d


class V(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._d, self._s, self._m = mv.INTENT_DIR, mgmt.STATE, mgmt.MEVENTS
        self._a = mr.ANA_DIR
        mv.INTENT_DIR = self.tmp / "i"
        mr.ANA_DIR = self.tmp / "ana"
        mgmt.STATE = self.tmp / "ms.json"; mgmt.MEVENTS = self.tmp / "e.jsonl"

    def tearDown(self):
        mv.INTENT_DIR, mgmt.STATE, mgmt.MEVENTS = self._d, self._s, self._m
        mr.ANA_DIR = self._a

    def _v(self, action, st=None, wl=None, **kw):
        return mv.validate("XYZ", dec=dec(action, **kw),
                           state_fn=lambda: st or ST, wl=wl or WL)

    def test_hold(self):
        v = self._v("HOLD_UNCHANGED")
        self.assertEqual(v["status"], "VALIDATED_SHADOW_INTENT")
        self.assertEqual(v["validated_action"], "HOLD_UNCHANGED")

    def test_hold_hidden(self):
        v = self._v("HOLD_UNCHANGED", proposed_stop={"level": 9.5})
        self.assertEqual(v["status"], "NON_EXECUTABLE_MANAGEMENT_PLAN")

    def test_tighten_ok(self):
        v = self._v("HOLD_AND_TIGHTEN_RISK",
                    proposed_stop={"level": 9.5, "type": "closing_stop"})
        self.assertEqual(v["status"], "VALIDATED_SHADOW_INTENT")
        self.assertEqual(v["proposed_risk_rule"]["type"], "close_below")

    def test_equal_stop_noop(self):
        v = self._v("HOLD_AND_TIGHTEN_RISK",
                    proposed_stop={"level": 9.0, "type": "intraday_stop"})
        self.assertEqual(v["status"], "NON_EXECUTABLE_MANAGEMENT_PLAN")

    def test_wider_stop_rejected(self):
        v = self._v("HOLD_AND_TIGHTEN_RISK",
                    proposed_stop={"level": 8.0, "type": "intraday_stop"})
        self.assertEqual(v["status"], "NON_EXECUTABLE_MANAGEMENT_PLAN")
        self.assertIn("NEVER_WIDEN", v["rejection_reasons"][0])

    def test_stop_above_market(self):
        st = {"positions": {"XYZ": {**POS, "mark": 9.2}},
              "pending_open_exits": []}
        m = {"positions": {"XYZ": {"latest_price": 9.2}}}
        mgmt.save_mgmt(m)
        v = self._v("HOLD_AND_TIGHTEN_RISK",
                    proposed_stop={"level": 9.5, "type": "intraday_stop"},
                    st=st)
        self.assertEqual(v["status"], "NON_EXECUTABLE_MANAGEMENT_PLAN")

    def test_malformed_stop(self):
        for bad in ({"level": None}, {}, {"level": -1}):
            v = self._v("HOLD_AND_TIGHTEN_RISK", proposed_stop=bad)
            self.assertEqual(v["status"], "NON_EXECUTABLE_MANAGEMENT_PLAN")

    def test_partial_fraction(self):
        v = self._v("PARTIAL_EXIT", partial_exit={"fraction": 0.5})
        self.assertEqual(v["status"], "VALIDATED_SHADOW_INTENT")
        self.assertEqual(v["normalized_exit_quantity"], 50)
        self.assertEqual(v["remaining_quantity"], 50)

    def test_partial_exact_qty(self):
        v = self._v("PARTIAL_EXIT", partial_exit={"quantity": 25})
        self.assertEqual(v["normalized_exit_quantity"], 25)

    def test_partial_bad(self):
        for f in (0, -0.5, 1.0):
            v = self._v("PARTIAL_EXIT", partial_exit={"fraction": f})
            self.assertIn(v["status"], ("NON_EXECUTABLE_MANAGEMENT_PLAN",
                                        "FORBIDDEN_MANAGEMENT_ACTION"))

    def test_partial_forbidden_over_holdings(self):
        v = self._v("PARTIAL_EXIT", partial_exit={"quantity": 150})
        self.assertEqual(v["status"], "FORBIDDEN_MANAGEMENT_ACTION")

    def test_partial_no_silent_full(self):
        # fraction that rounds to all shares is rejected, not converted
        v = self._v("PARTIAL_EXIT", partial_exit={"fraction": 0.999})
        self.assertEqual(v["status"], "NON_EXECUTABLE_MANAGEMENT_PLAN")

    def test_partial_composite(self):
        v = self._v("PARTIAL_EXIT", partial_exit={"fraction": 0.5},
                    proposed_stop={"level": 9.5, "type": "closing_stop"})
        self.assertEqual(v["risk_validation"]["status"],
                         "PARTIAL_VALID_REMAINDER_VALID")
        v2 = self._v("PARTIAL_EXIT", partial_exit={"fraction": 0.5},
                     proposed_stop={"level": 8.0, "type": "closing_stop"})
        self.assertEqual(v2["risk_validation"]["remainder_ok"], False)

    def test_full_exit(self):
        v = self._v("FULL_EXIT")
        self.assertEqual(v["status"], "VALIDATED_SHADOW_INTENT")

    def test_pending_exit_conflict(self):
        st = {"positions": {"XYZ": dict(POS)},
              "pending_open_exits": [{"ticker": "XYZ"}]}
        v = self._v("FULL_EXIT", st=st)
        self.assertEqual(v["status"], "NON_EXECUTABLE_MANAGEMENT_PLAN")
        self.assertIn("CONFLICTING_PENDING_ACTION", v["rejection_reasons"][0])

    def test_reassess_later(self):
        v = self._v("REASSESS_LATER",
                    next_reassessment="after 2026-10-20 earnings")
        self.assertEqual(v["status"], "VALIDATED_SHADOW_INTENT")
        v2 = self._v("REASSESS_LATER", next_reassessment="check later")
        self.assertEqual(v2["status"], "NON_EXECUTABLE_MANAGEMENT_PLAN")

    def test_stale_closed(self):
        v = self._v("HOLD_UNCHANGED", st={"positions": {},
                                          "pending_open_exits": []})
        self.assertEqual(v["status"], "STALE_MANAGEMENT_DECISION")

    def test_superseded(self):
        td = mr.ANA_DIR / "XYZ"; td.mkdir(parents=True)
        (td / "reassess_2026-10-06.json").write_text(json.dumps(
            {"analyzed_at": "2026-10-06T00"}))
        v = self._v("HOLD_UNCHANGED")
        self.assertEqual(v["status"], "SUPERSEDED_MANAGEMENT_DECISION")

    def test_action_id_deterministic(self):
        d = dec("PARTIAL_EXIT", partial_exit={"fraction": 0.5})
        v1 = mv.validate("XYZ", dec=d, state_fn=lambda: ST, wl=WL)
        v2 = mv.validate("XYZ", dec=d, state_fn=lambda: ST, wl=WL)
        self.assertEqual(v1["action_id"], v2["action_id"])
        v3 = mv.validate("XYZ", dec=dec("PARTIAL_EXIT",
                                      partial_exit={"fraction": 0.25}),
                         state_fn=lambda: ST, wl=WL)
        self.assertNotEqual(v1["action_id"], v3["action_id"])

    def test_no_economics(self):
        before = json.dumps(ST, sort_keys=True)
        self._v("PARTIAL_EXIT", partial_exit={"fraction": 0.5})
        self.assertEqual(json.dumps(ST, sort_keys=True), before)


if __name__ == "__main__":
    unittest.main(verbosity=0)
