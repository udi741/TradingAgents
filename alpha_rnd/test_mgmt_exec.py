#!/usr/bin/env python3
"""Phase E machinery tests — isolated/canary state only; kill switch on
only inside tests."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from alpha_rnd import mgmt, mgmt_reassess as mr, mgmt_validate as mv, \
    mgmt_exec as mx, monitor  # noqa: E402


def pbf_state():
    return {"cash": 92899.01, "realized": -2140.99, "executed": [],
            "pending_open_exits": [], "pending_open_fills": [],
            "event_outbox": [],
            "positions": {"PBF": {"shares": 62, "fill": 80.0,
                                  "cost": 4964.96, "mark": 86.99,
                                  "entry_session": "2026-10-02",
                                  "stop_rule": {"type": "intraday_stop",
                                                "level": 74.5}}}}

PBF_INTENT = {"ticker": "PBF", "status": "VALIDATED_SHADOW_INTENT",
              "management_decision_id": "d1", "position_id": "PBF:2026-10-02",
              "validated_action": "PARTIAL_EXIT",
              "proposed_exit_fraction": 0.5,
              "normalized_exit_quantity": 31, "remaining_quantity": 31,
              "proposed_risk_rule": {"type": "close_below", "level": 83.5,
                                     "label": "tighten"},
              "action_id": "mgmact_test1"}


class E(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._saves = (mv.INTENT_DIR, mgmt.MEVENTS, mgmt.STATE,
                       mgmt.POLICY_P, mr.ANA_DIR, mx.ACTIONS_P,
                       monitor.NOTIFY, monitor.desktop_notify)
        # shadow/test runs must never write executed-sounding wording to the
        # live operator log or desktop — notify writes real state msgs
        monitor.NOTIFY = self.tmp / "notify.log"
        monitor.desktop_notify = lambda *a, **k: None
        mv.INTENT_DIR = self.tmp / "i"
        mgmt.MEVENTS = self.tmp / "e.jsonl"
        mgmt.STATE = self.tmp / "ms.json"
        mr.ANA_DIR = self.tmp / "ana"
        mx.ACTIONS_P = self.tmp / "actions.json"
        self.pol_on = self.tmp / "pol_on.json"
        pol = json.loads((ROOT / "alpha_rnd/management_policy.json")
                         .read_text())
        pol["execution"] = {"enabled": True}
        self.pol_on.write_text(json.dumps(pol))
        (mv.INTENT_DIR / "PBF").mkdir(parents=True)
        (mv.INTENT_DIR / "PBF" / "d1.json").write_text(json.dumps(PBF_INTENT))
        # seed mgmt state so _live_mark returns 86.99
        mgmt.save_mgmt({"positions": {"PBF": {"latest_price": 86.99}}})
        self.st = pbf_state()
        self.wl = {"open_positions": [{"ticker": "PBF", "invalidation":
                                       {"type": "intraday_stop",
                                        "level": 74.5}}]}

    def tearDown(self):
        (mv.INTENT_DIR, mgmt.MEVENTS, mgmt.STATE,
         mgmt.POLICY_P, mr.ANA_DIR, mx.ACTIONS_P,
         monitor.NOTIFY, monitor.desktop_notify) = self._saves

    def _enable(self):
        mgmt.POLICY_P = self.pol_on

    def test_disabled_noop(self):
        r = mx.execute("PBF", self.st, self.wl)
        self.assertEqual(r["result"], "SKIP_EXECUTION_DISABLED")
        self.assertEqual(self.st["pending_open_exits"], [])
        self.assertEqual(self.st["positions"]["PBF"]["shares"], 62)

    def test_partial_composite(self):
        self._enable()
        r = mx.execute("PBF", self.st, self.wl)
        self.assertEqual(r["result"], "ENQUEUED_ADAPTIVE")
        pe = self.st["pending_open_exits"][0]
        self.assertEqual(pe["shares"], 31)
        # queued is NOT executed: canonical fill registry untouched
        self.assertNotIn("mgmact_test1", self.st["executed"])
        # remainder stop pending — original protection still on all 62
        self.assertEqual(self.st["positions"]["PBF"]["stop_rule"]["level"],
                         74.5)
        a = mx._actions()["mgmact_test1"]
        self.assertEqual(a["status"], "ENQUEUED")
        self.assertEqual(a["remainder_status"], "PENDING_FILL")

    def test_composite_after_fill(self):
        self._enable()
        mx.execute("PBF", self.st, self.wl)
        od = self.st["pending_open_exits"][0]
        monitor.do_exit(self.st, "PBF", 90.0, "fill", shares=od["shares"])
        self.st["executed"].append(od["order_id"])
        self.st["pending_open_exits"] = []
        mx._tick_actions(self.st, self.wl)
        a = mx._actions()["mgmact_test1"]
        self.assertEqual(a["status"], "EXECUTED")
        self.assertEqual(self.st["positions"]["PBF"]["shares"], 31)
        self.assertEqual(self.st["positions"]["PBF"]["stop_rule"]["level"],
                         83.5)
        # idempotent tick: second pass changes nothing
        mx._tick_actions(self.st, self.wl)
        self.assertEqual(self.st["positions"]["PBF"]["stop_rule"]["level"],
                         83.5)

    # --- shadow notification semantics: nothing shadow may say EXECUTED ---
    def test_shadow_paths_never_say_executed(self):
        # 1. disabled execution writes NOTHING to the operator log
        r = mx.execute("PBF", self.st, self.wl)
        self.assertEqual(r["result"], "SKIP_EXECUTION_DISABLED")
        self.assertFalse((self.tmp / "notify.log").exists())
        # 2. enabled-but-queued shadow intent still writes no fill wording
        self._enable()
        mx.execute("PBF", self.st, self.wl)
        txt = (self.tmp / "notify.log").read_text()             if (self.tmp / "notify.log").exists() else ""
        for bad in ("EXECUTED", "FILLED", "SOLD", "STOP CHANGED"):
            self.assertNotIn(bad, txt)
        # 3. validated intent record itself carries shadow status, never a
        #    fill claim
        self.assertEqual(mx._actions()["mgmact_test1"]["status"], "ENQUEUED")
        self.assertNotIn("mgmact_test1", self.st["executed"])
        # 4. SHADOW artifacts/sections are explicitly labeled non-economic
        self.assertIn("SHADOW RECOMMENDATION ONLY",
                      open(ROOT / "alpha_rnd/mgmt_reassess.py").read())
        self.assertIn("NOT AN ECONOMIC ACTION",
                      open(ROOT / "alpha_rnd/mgmt.py").read())

    def test_real_fill_still_says_executed(self):
        # canonical fill wording preserved — do_exit on real authority
        monitor.do_exit(self.st, "PBF", 90.0, "test fill", shares=31)
        txt = (self.tmp / "notify.log").read_text()
        self.assertIn("PAPER EXIT EXECUTED", txt)
        self.assertIn("PBF", txt)
        # dedup/idempotency unchanged: same exec_id exits once economically
        self.assertEqual(self.st["positions"]["PBF"]["shares"], 31)

    def test_partial_fill_pro_rata(self):
        self._enable()
        mx.execute("PBF", self.st, self.wl)
        o = self.st["pending_open_exits"].pop()
        cash0, rl0 = self.st["cash"], self.st["realized"]
        monitor.do_exit(self.st, "PBF", 90.0, "fill", shares=o["shares"])
        self.assertEqual(self.st["positions"]["PBF"]["shares"], 31)
        self.assertGreater(self.st["cash"], cash0)
        self.assertAlmostEqual(self.st["realized"],
                               rl0 + 31 * 90 * (1 - monitor.COST_BPS)
                               - 4964.96 / 2, places=1)
        self.assertAlmostEqual(self.st["positions"]["PBF"]["cost"],
                               4964.96 / 2, places=1)

    def test_full_exit(self):
        self._enable()
        it = dict(PBF_INTENT, validated_action="FULL_EXIT",
                  proposed_risk_rule=None, normalized_exit_quantity=None,
                  action_id="mgmact_full")
        r = mx.execute("PBF", self.st, self.wl, intent=it)
        self.assertEqual(r["result"], "ENQUEUED_ADAPTIVE")
        self.assertEqual(self.st["pending_open_exits"][0]["type"], "full")
        self.assertNotIn("mgmact_full", self.st["executed"])

    def test_dup_no_double(self):
        self._enable()
        mx.execute("PBF", self.st, self.wl)
        r = mx.execute("PBF", self.st, self.wl)  # same intent again
        self.assertEqual(r["result"], "ALREADY_ENQUEUED")
        self.assertEqual(len(self.st["pending_open_exits"]), 1)

    def test_closed_noop(self):
        self._enable()
        st = pbf_state(); st["positions"] = {}
        r = mx.execute("PBF", st, self.wl)
        self.assertEqual(r["result"], "REVALIDATION_FAILED")

    def test_qty_changed(self):
        self._enable()
        st = pbf_state(); st["positions"]["PBF"]["shares"] = 31
        r = mx.execute("PBF", st, self.wl)
        self.assertEqual(r["result"], "REVALIDATION_FAILED")
        self.assertFalse(st["pending_open_exits"])

    def _fill_partial(self, st):
        od = st["pending_open_exits"][0]
        monitor.do_exit(st, "PBF", 90.0, "fill", shares=od["shares"])
        st["executed"].append(od["order_id"])
        st["pending_open_exits"] = []

    def test_obsolete_stop(self):
        # mark drops below proposed 83.5 before fill -> remainder rejected
        # at activation; the partial exit itself still proceeds
        self._enable()
        st = pbf_state()
        r = mx.execute("PBF", st, self.wl)
        self.assertEqual(r["result"], "ENQUEUED_ADAPTIVE")
        mgmt.save_mgmt({"positions": {"PBF": {"latest_price": 82.0}}})
        self._fill_partial(st)
        mx._tick_actions(st, self.wl)
        a = mx._actions()["mgmact_test1"]
        self.assertEqual(a["status"], "EXECUTED_REMAINDER_REJECTED")
        self.assertIn("obsolete", a["remainder_errors"][-1])
        self.assertEqual(st["positions"]["PBF"]["stop_rule"]["level"], 74.5)

    def test_never_widen_exec(self):
        # a stronger stop (85) exists before activation -> 83.5 never widens
        self._enable()
        st = pbf_state()
        mx.execute("PBF", st, self.wl)
        st["positions"]["PBF"]["stop_rule"]["level"] = 85.0
        self._fill_partial(st)
        mx._tick_actions(st, self.wl)
        a = mx._actions()["mgmact_test1"]
        self.assertEqual(a["status"], "EXECUTED_REMAINDER_REJECTED")
        self.assertTrue(any("NEVER_WIDEN" in e for e in a["remainder_errors"]))
        self.assertEqual(st["positions"]["PBF"]["stop_rule"]["level"], 85.0)

    def test_superseded(self):
        self._enable()
        (mv.INTENT_DIR / "PBF" / "d2.json").write_text(json.dumps(
            dict(PBF_INTENT, management_decision_id="d2")))
        r = mx.execute("PBF", self.st, self.wl, intent=PBF_INTENT)
        self.assertEqual(r["result"], "REVALIDATION_FAILED")

    def test_hard_stop_independent(self):
        # deterministic path doesn't consult mgmt_exec — simulate directly
        monitor.do_exit(self.st, "PBF", 74.5, "intraday_stop",
                        exec_id="intraday_stop:PBF:s")
        self.assertNotIn("PBF", self.st["positions"])
        # pending mgmt order for the closed position gets cleared
        self.assertFalse([o for o in self.st["pending_open_exits"]
                          if o["ticker"] == "PBF"])


if __name__ == "__main__":
    unittest.main(verbosity=0)
