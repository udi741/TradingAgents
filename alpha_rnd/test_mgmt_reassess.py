#!/usr/bin/env python3
"""Phase C shadow reassessment tests — model_fn injected; no real calls."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from alpha_rnd import mgmt, mgmt_reassess as mr  # noqa: E402
from alpha_rnd.synthesize import TranslatorInfra  # noqa: E402

GOOD = json.dumps({"ticker": "XYZ", "thesis_status": "INTACT",
                   "catalyst_status": "PENDING",
                   "reward_risk_status": "unchanged",
                   "price_vs_thesis": "confirming",
                   "recommended_action": "HOLD_UNCHANGED",
                   "proposed_stop": {"type": None, "level": None,
                                    "rationale": None},
                   "partial_exit": {"fraction": None, "rationale": None},
                   "next_reassessment": "on next trigger",
                   "confidence": "medium", "reasoning_summary": "ok",
                   "data_limitations": "none"})


class T(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._ = (mgmt.SNAP_DIR, mgmt.REQ_DIR, mgmt.STATE, mgmt.MEVENTS,
                  mr.CTX_DIR, mr.ANA_DIR)
        mgmt.SNAP_DIR = self.tmp / "snap"; mgmt.REQ_DIR = self.tmp / "req"
        mgmt.STATE = self.tmp / "ms.json"; mgmt.MEVENTS = self.tmp / "ev.jsonl"
        mr.CTX_DIR = self.tmp / "ctx"; mr.ANA_DIR = self.tmp / "ana"
        mgmt.SNAP_DIR.mkdir(parents=True)
        (mgmt.SNAP_DIR / "XYZ_2026-10-01.json").write_text(json.dumps(
            {"ticker": "XYZ", "entry_session": "2026-10-01",
             "entry_price": 10.0,
             "risk_plan": {"stop_rule": {"type": "intraday_stop",
                                         "level": 9.0}},
             "horizon": "2wk", "thesis": "t"}))
        rd = mgmt.REQ_DIR / "XYZ"; rd.mkdir(parents=True)
        (rd / "APPRECIATION_2026-10-05.json").write_text(json.dumps(
            {"request_id": "r1", "ticker": "XYZ",
             "trigger_family": "APPRECIATION", "urgency": "NORMAL",
             "fired_session": "2026-10-05", "value": 1.2, "threshold": 1.0,
             "reason": "test", "status": "SHADOW_TRIGGERED"}))
        self.st = {"positions": {"XYZ": {"shares": 10, "fill": 10.0,
                                         "stop_rule": {"type": "intraday_stop",
                                                       "level": 9.0}}}}
        self.orig_build = mr.build_context
        def _bc(t, pos, rec, reqs, snap, asof, session):
            return {"context_hash": "h",
                    "position_state_hash": mr._fingerprint(pos, reqs),
                    "ticker": "XYZ"}
        mr.build_context = _bc

    def tearDown(self):
        mgmt.SNAP_DIR, mgmt.REQ_DIR, mgmt.STATE, mgmt.MEVENTS = self._[:4]
        mr.CTX_DIR, mr.ANA_DIR = self._[4:]
        mr.build_context = self.orig_build

    def _mk_req(self):
        rd = mgmt.REQ_DIR / "XYZ"; rd.mkdir(parents=True, exist_ok=True)
        (rd / "APPRECIATION_2026-10-05.json").write_text(json.dumps(
            {"request_id": "r1", "ticker": "XYZ",
             "trigger_family": "APPRECIATION", "urgency": "NORMAL",
             "fired_session": "2026-10-05", "value": 1.2, "threshold": 1.0,
             "reason": "test", "status": "SHADOW_TRIGGERED"}))

    def _run(self, fn=None, states=None):
        self._mk_req()
        states = states or [self.st]
        it = iter(list(states) + [states[-1]] * 5)
        return mr.assess("XYZ", "2026-10-05", model_fn=fn or (lambda c: GOOD),
                         state_fn=lambda: next(it))

    def test_success(self):
        d = self._run()
        self.assertEqual(d["status"], "SUCCESS")
        self.assertEqual(d["analysis"]["recommended_action"], "HOLD_UNCHANGED")
        self.assertTrue(d["shadow"])
        self.assertTrue(Path(d["context_ref"]).exists())

    def test_actions_accepted(self):
        for a in ("HOLD_AND_TIGHTEN_RISK", "PARTIAL_EXIT", "FULL_EXIT",
                  "REASSESS_LATER"):
            g = json.loads(GOOD); g["recommended_action"] = a
            self.assertEqual(self._run(lambda c, g=g: json.dumps(g))["status"],
                             "SUCCESS")

    def test_malformed(self):
        self.assertEqual(self._run(lambda c: "not json")["status"],
                         "RETRY_PENDING")
        bad = json.loads(GOOD); bad["recommended_action"] = "MAYBE"
        self.assertEqual(self._run(lambda c: json.dumps(bad))["status"],
                         "FAILED_TERMINAL")

    def test_infra(self):
        self.assertEqual(self._run(
            lambda c: (_ for _ in ()).throw(
                TranslatorInfra("MODEL_RATE_LIMITED", "429")))["status"],
            "RETRY_PENDING")
        self.assertEqual(self._run(
            lambda c: (_ for _ in ()).throw(
                TranslatorInfra("MODEL_QUOTA_EXHAUSTED", "x")))["status"],
            "FAILED_TERMINAL")

    def test_stale_closed(self):
        # position open at call start, closed before result returns
        self.assertEqual(self._run(
            states=[self.st, {"positions": {}}])["status"],
            "STALE_POSITION_CLOSED")

    def test_stale_changed(self):
        s2 = {"positions": {"XYZ": {"shares": 5, "fill": 10.0,
                                    "stop_rule": {"type": "intraday_stop",
                                                  "level": 9.0}}}}
        self.assertEqual(self._run(states=[self.st, s2])["status"],
                         "STALE_POSITION_CHANGED")

    def test_no_trigger_no_call(self):
        d = mr.assess("NONE", "2026-10-05", model_fn=lambda c: GOOD,
                      state_fn=lambda: self.st)
        self.assertEqual(d["status"], "NO_PENDING_TRIGGER")

    def test_requests_consumed(self):
        self._run()
        r = json.loads((mgmt.REQ_DIR / "XYZ" /
                        "APPRECIATION_2026-10-05.json").read_text())
        self.assertEqual(r["status"], "CONSUMED_BY_SHADOW_ANALYSIS")

    def test_zero_economics(self):
        before = json.dumps(self.st, sort_keys=True)
        self._run()
        self.assertEqual(json.dumps(self.st, sort_keys=True), before)


if __name__ == "__main__":
    unittest.main(verbosity=0)
