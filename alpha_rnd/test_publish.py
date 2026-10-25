#!/usr/bin/env python3
"""Watch-lifecycle / carry-forward tests for alpha_rnd.publish — isolated."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import alpha_rnd.publish as pb
import alpha_rnd.gen_watchlist as gw
import alpha_rnd.daily_scheduler as ds


def intent_doc(session, tickers):
    return {"session": session,
            "intents": {t: {"ticker": t, "classification": "WATCH_FOR_ENTRY",
                            "watch_mode": "DETERMINISTIC_CONFIRMATION",
                            "trigger": "x", "params": {"zone": [1, 2]},
                            "invalidation": "s", "size_frac": 0.5}
                        for t in tickers},
            "validated": list(tickers), "review_required": []}


def spec_watch(t, artifact=None, session=None, **kw):
    w = {"ticker": t, "cls": "DETERMINISTIC_CONFIRMATION", "v": 2,
         "trigger": "x", "trigger_type": "close_in_zone",
         "params": {"zone2": [1, 2]}, "invalidation": "s", "horizon": "h",
         "size_frac": 0.5}
    if artifact:
        w["artifact"] = artifact
    if session:
        w["session"] = session
    w.update(kw)
    return w


class PubTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._root = pb.ROOT
        pb.ROOT = self.tmp
        self.ev = self.tmp / "evaluations" / "alpha_rnd_v1"
        self.ev.mkdir(parents=True)
        (self.tmp / "alpha_rnd").mkdir()
        self._gw = mock.patch.object(gw, "build_doc")
        self.gw = self._gw.start()
        self._gwout = mock.patch.object(gw, "OUT",
                                        self.tmp / "alpha_rnd" / "live_watchlist.json")
        self._gwout.start()
        self._txn = mock.patch.object(ds, "_state_txn", side_effect=lambda fn: fn({}))
        self._txn.start()
        self._mst = mock.patch.object(pb, "_monitor_state", return_value={})
        self.mst = self._mst.start()

    def tearDown(self):
        pb.ROOT = self._root
        mock.patch.stopall()

    def doc(self, session):
        return json.loads((self.tmp / "alpha_rnd" / "live_watchlist.json").read_text())

    def _intents(self, session, tickers):
        (self.ev / f"publication_intents_{session}.json").write_text(
            json.dumps(intent_doc(session, tickers)))

    def _pub(self, session="2026-10-09"):
        pb.publish(session)
        return {w["ticker"]: w for w in self.doc(session)["watches"]}

    def test_pgen_carry_forward_newer_intent_persists(self):
        self.gw.return_value = {"watches": [], "open_positions": []}
        self._intents("2026-10-07", ["PGEN"])
        self._intents("2026-10-09", [])
        ws = self._pub()
        self.assertEqual(ws["PGEN"]["artifact"], "PGEN_2026-10-07.json")
        self.assertEqual(ws["PGEN"]["session"], "2026-10-07")

    def test_older_intent_never_replaces_newer_spec_revision(self):
        # TXG-style regression: spec rev (artifact session 10-02) beats
        # a same-session auto intent, and risk_blocked revision survives
        self.gw.return_value = {"watches": [spec_watch("TXG", "TXG_2026-10-02.json")],
                                "open_positions": []}
        self._intents("2026-10-02", ["TXG"])
        ws = self._pub()
        self.assertEqual(ws["TXG"]["v"], 2)  # spec revision, not "auto"

    def test_terminal_lifecycle_blocks_resurrection(self):
        # RETIRED/EXPIRED/TRIGGERED/RISK_PLAN_REQUIRED at rev session S
        # reject intents with session <= S
        for status, sess in (("RETIRED", "2026-10-03"), ("EXPIRED", "2026-10-04"),
                             ("TRIGGERED", "2026-10-02"), ("RISK_PLAN_REQUIRED", "2026-10-02")):
            self.mst.return_value = {"watch_lifecycle":
                {"X": {"status": status, "rev": f"X_{sess}.json#1", "session": sess}}}
            self.gw.return_value = {"watches": [], "open_positions": []}
            self._intents("2026-10-02", ["X"])
            ws = self._pub()
            self.assertNotIn("X", ws, status)

    def test_newer_intent_supersedes_prior_terminal_state(self):
        self.mst.return_value = {"watch_lifecycle":
            {"X": {"status": "RISK_PLAN_REQUIRED", "rev": "X_2026-10-02.json#2",
                   "session": "2026-10-02"}}}
        self.gw.return_value = {"watches": [], "open_positions": []}
        self._intents("2026-10-09", ["X"])
        ws = self._pub()
        self.assertEqual(ws["X"]["artifact"], "X_2026-10-09.json")

    def test_republish_idempotent(self):
        self.gw.return_value = {"watches": [spec_watch("A", "A_2026-10-01.json")],
                                "open_positions": []}
        self._intents("2026-10-07", ["B"])
        w1 = self._pub()
        w2 = self._pub()
        self.assertEqual(w1, w2)

    def test_structured_session_beats_nonstandard_filename(self):
        # artifact filename without a session must not control ordering —
        # explicit "session" field does
        self.gw.return_value = {"watches": [spec_watch("Y", "Y_custom.json",
                                                       session="2026-10-03")],
                                "open_positions": []}
        self._intents("2026-10-02", ["Y"])
        ws = self._pub()
        self.assertEqual(ws["Y"]["artifact"], "Y_custom.json")

    def test_predisposition_doc_blocks_bearish_geometry(self):
        # legacy doc with no "dispositions": `validated` used to mint an
        # executable watch unchecked; SHORT-shaped geometry must not pass.
        self.gw.return_value = {"watches": [], "open_positions": []}
        doc = {"session": "2026-10-07", "intents": {
            "PCVX": {"ticker": "PCVX", "classification": "WATCH_FOR_ENTRY",
                     "watch_mode": "DETERMINISTIC_CONFIRMATION",
                     "trigger": "re-entry on 62-64 hold", "stop_level": 73.8,
                     "params": {"reentry_zone": [62, 64], "reclaim": 68.6},
                     "invalidation": "x", "size_frac": 0.5},
            "GOOD": {"ticker": "GOOD", "classification": "WATCH_FOR_ENTRY",
                     "watch_mode": "DETERMINISTIC_CONFIRMATION",
                     "trigger": "close in zone", "stop_level": 55.0,
                     "params": {"zone": [60, 62]},
                     "invalidation": "close<55", "size_frac": 0.5}},
            "validated": ["PCVX", "GOOD"], "review_required": []}
        (self.ev / "publication_intents_2026-10-07.json").write_text(
            json.dumps(doc))
        ws = self._pub()
        self.assertNotIn("PCVX", ws)
        self.assertIn("GOOD", ws)


if __name__ == "__main__":
    unittest.main()
