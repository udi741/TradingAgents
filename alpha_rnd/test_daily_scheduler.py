#!/usr/bin/env python3
"""Orchestration tests for alpha_rnd.daily_scheduler — no model calls."""
import fcntl
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import alpha_rnd.daily_scheduler as ds


class SchedTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        for attr in ("SCHED_LOCK", "CYCLE_LOCK", "SCHED_STATE", "EVENTS", "LOG",
                     "SCHED_STATE_LOCK"):
            setattr(ds, attr, self.tmp / getattr(ds, attr).name)
        ds.EV_DIR = self.tmp / "ev"
        ds.EV_DIR.mkdir()
        (ds.EV_DIR / "case_artifacts").mkdir()

    def _events(self):
        if not ds.EVENTS.exists():
            return []
        return [json.loads(l) for l in ds.EVENTS.read_text().splitlines()]

    def test_up_to_date_no_action(self):
        ds.mark_done("2026-10-02", {})
        with mock.patch.object(ds, "last_completed_session", return_value="2026-10-02"), \
             mock.patch.object(ds.subprocess, "Popen") as pop:
            ds.check()
        pop.assert_not_called()

    def test_due_session_launches_once_and_repeated_tick_no_dup(self):
        with mock.patch.object(ds, "last_completed_session", return_value="2026-10-05"), \
             mock.patch.object(ds.subprocess, "Popen") as pop:
            ds.check()
            self.assertEqual(pop.call_count, 1)
            # hold the cycle lock -> second tick does not relaunch
            with ds.CYCLE_LOCK.open("w") as lf:
                fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB)
                ds.check()
        self.assertEqual(pop.call_count, 1)

    def test_completed_marker_prevents_rerun(self):
        ds.mark_done("2026-10-05", {})
        with mock.patch.object(ds, "last_completed_session", return_value="2026-10-05"), \
             mock.patch.object(ds.subprocess, "Popen") as pop:
            ds.check()
        pop.assert_not_called()

    def test_crash_before_done_is_retried(self):
        # ran once but crashed: no done marker -> due again
        (ds.EV_DIR / "candidate_pool_frozen_2026-10-05.json").write_text("{}")
        with mock.patch.object(ds, "last_completed_session", return_value="2026-10-05"), \
             mock.patch.object(ds.subprocess, "Popen") as pop:
            ds.check()
        pop.assert_called_once()

    def test_stale_lock_released(self):
        # flock is kernel-held; after holder releases, next tick proceeds
        with ds.CYCLE_LOCK.open("w") as lf:
            fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with mock.patch.object(ds, "last_completed_session", return_value="2026-10-05"), \
             mock.patch.object(ds.subprocess, "Popen") as pop:
            ds.check()
        pop.assert_called_once()

    def test_bridge_blocked_event_and_no_done(self):
        (ds.EV_DIR / "candidate_pool_frozen_2026-10-05.json").write_text(
            json.dumps({"candidates": [{"ticker": "X", "labels": ["MOMENTUM"], "rs_60": 1}]}))
        with mock.patch.object(ds.subprocess, "run", return_value=mock.Mock(returncode=0, stdout="", stderr="")), \
             mock.patch.object(ds, "ensure_bridge", return_value=False):
            ds.run_cycle("2026-10-05")
        kinds = [e["kind"] for e in self._events()]
        self.assertIn("ALPHA_DISCOVERY_BLOCKED_BRIDGE", kinds)
        self.assertFalse(ds.cycle_done("2026-10-05"))

    def test_success_cycle_marks_done_and_emits(self):
        (ds.EV_DIR / "candidate_pool_frozen_2026-10-05.json").write_text(json.dumps(
            {"candidates": [{"ticker": t, "labels": ["MOMENTUM"], "rs_60": 1}
                            for t in "ABCDEFGHIJK"]}))
        for t in "ABCDEFGHIJ":  # complete analysis: every deep ticker has a valid artifact
            (ds.EV_DIR / "case_artifacts" / f"{t}_2026-10-05.json").write_text(
                json.dumps({"ticker": t, "signal": "BUY"}))
        def fake_run(cmd, **kw):
            cmd = [str(x) for x in cmd]
            if "synthesize" in " ".join(cmd):
                (ds.EV_DIR / "publication_intents_2026-10-05.json").write_text(json.dumps(
                    {"validated": ["A"], "intents": {}, "review_required": []}))
            if "publish" in " ".join(cmd):
                st = ds._j(ds.SCHED_STATE, {}) or {}
                st["published_sessions"] = {"2026-10-05": {"watch_count": 3, "sha256": "x"}}
                ds.SCHED_STATE.write_text(json.dumps(st))
            return mock.Mock(returncode=0, stdout="", stderr="")
        with mock.patch.object(ds.subprocess, "run", side_effect=fake_run), \
             mock.patch.object(ds, "ensure_bridge", return_value=True):
            ds.run_cycle("2026-10-05")
        kinds = [e["kind"] for e in self._events()]
        self.assertEqual(kinds[0], "ALPHA_DISCOVERY_STARTED")
        self.assertIn("ALPHA_DISCOVERY_COMPLETE", kinds)  # auto publish -> done
        self.assertTrue(ds.cycle_done("2026-10-05"))
        n = kinds.count("ALPHA_DISCOVERY_COMPLETE")
        with mock.patch.object(ds, "last_completed_session", return_value="2026-10-05"), \
             mock.patch.object(ds.subprocess, "Popen") as pop:
            ds.check()  # completed -> no republish, no second COMPLETE
        pop.assert_not_called()
        self.assertEqual(kinds.count("ALPHA_DISCOVERY_COMPLETE"), n)

    def test_crash_after_partial_ta_resumes_only_missing(self):
        (ds.EV_DIR / "candidate_pool_frozen_2026-10-05.json").write_text(json.dumps(
            {"candidates": [{"ticker": t, "labels": ["MOMENTUM"], "rs_60": 1}
                            for t in "ABCDEFGHIJK"]}))
        for t in "ABC":  # 3/10 already analyzed before crash
            (ds.EV_DIR / "case_artifacts" / f"{t}_2026-10-05.json").write_text(
                json.dumps({"ticker": t, "signal": "HOLD"}))
        calls = []
        def fake_run(cmd, **kw):
            calls.append(cmd)
            return mock.Mock(returncode=0, stdout="", stderr="")
        with mock.patch.object(ds.subprocess, "run", side_effect=fake_run), \
             mock.patch.object(ds, "ensure_bridge", return_value=True):
            ds.run_cycle("2026-10-05")
        ta_call = [c for c in calls if "run_ta.py" in str(c)]
        self.assertEqual(len(ta_call), 1)
        passed = [a for a in ta_call[0] if isinstance(a, str) and len(a) == 1]
        self.assertEqual(sorted(passed), list("DEFGHIJ"))  # K outside deep-10; no re-analysis

    def test_crash_before_done_marker_no_duplicate_side_effects(self):
        # simulate: artifacts published, marker never written -> retry is a
        # no-side-effect rerun (discovery file rewritten identically, all TA
        # artifacts cached, no orders/watches touched by scheduler at all)
        (ds.EV_DIR / "candidate_pool_frozen_2026-10-05.json").write_text(json.dumps(
            {"candidates": [{"ticker": t, "labels": ["MOMENTUM"], "rs_60": 1}
                            for t in "ABCDEFGHIJK"]}))
        for t in "ABCDEFGHIJ":
            (ds.EV_DIR / "case_artifacts" / f"{t}_2026-10-05.json").write_text(
                json.dumps({"ticker": t, "signal": "HOLD"}))
        calls = []
        def fake_run(cmd, **kw):
            calls.append(cmd)
            return mock.Mock(returncode=0, stdout="", stderr="")
        with mock.patch.object(ds.subprocess, "run", side_effect=fake_run), \
             mock.patch.object(ds, "ensure_bridge", return_value=True):
            ds.run_cycle("2026-10-05")
        ta_calls = [c for c in calls if "run_ta.py" in str(c)]
        self.assertEqual(len(ta_calls), 1)
        self.assertTrue(ta_calls[0][-1].endswith("run_ta.py")
                        or all(len(a) != 1 for a in ta_calls[0][2:]))  # 0 missing tickers
        kinds = [e["kind"] for e in self._events()]
        self.assertIn("ALPHA_DISCOVERY_ERROR", kinds)  # synthesize/publish not provisioned in this fake

    def test_dead_run_reaped_interrupted_and_relaunched(self):
        # run-session process vanished (power-off/kill): INTERRUPTED once,
        # record cleared, due logic resumes prospectively
        ds._state_txn(lambda st: st.__setitem__("current_run",
            {"session": "2026-10-05", "run_id": "x", "pid": 99999999,
             "started_at": "x", "stage": "ta", "last_progress_at": "x",
             "deep_total": 10}))
        with mock.patch.object(ds, "last_completed_session", return_value="2026-10-05"), \
             mock.patch.object(ds.subprocess, "run",
                               return_value=mock.Mock(returncode=0)), \
             mock.patch.object(ds.subprocess, "Popen") as pop:
            ds.check()
        st = ds._j(ds.SCHED_STATE)
        self.assertNotIn("current_run", st)
        self.assertEqual(st["session_status"]["2026-10-05"], "INTERRUPTED")
        kinds = [e["kind"] for e in self._events()]
        self.assertEqual(kinds.count("ALPHA_DISCOVERY_INTERRUPTED"), 1)
        pop.assert_called_once()

    def test_live_run_reported_not_interrupted(self):
        ds._state_txn(lambda st: st.__setitem__("current_run",
            {"session": "2026-10-05", "run_id": "x", "pid": os.getpid(),
             "started_at": "x", "stage": "discovery",
             "last_progress_at": ds._utcnow(), "deep_total": 0}))
        with mock.patch.object(ds, "last_completed_session", return_value="2026-10-05"), \
             mock.patch.object(ds.subprocess, "Popen") as pop:
            ds.check()
        pop.assert_not_called()
        self.assertNotIn("ALPHA_DISCOVERY_INTERRUPTED",
                         [e["kind"] for e in self._events()])

    def test_exception_leaves_terminal_error(self):
        # crash inside the pipeline -> ERROR terminal + event, not silent STARTED
        with mock.patch.object(ds, "_run_cycle", side_effect=RuntimeError("boom")):
            ds.run_cycle("2026-10-05")
        st = ds._j(ds.SCHED_STATE)
        self.assertEqual(st["session_status"]["2026-10-05"], "ERROR")
        self.assertNotIn("current_run", st)
        self.assertIn("ALPHA_DISCOVERY_ERROR", [e["kind"] for e in self._events()])

    def test_success_writes_complete_terminal(self):
        (ds.EV_DIR / "candidate_pool_frozen_2026-10-05.json").write_text(json.dumps(
            {"candidates": [{"ticker": "A", "labels": ["MOMENTUM"], "rs_60": 1}]}))
        (ds.EV_DIR / "case_artifacts" / "A_2026-10-05.json").write_text(
            json.dumps({"ticker": "A", "signal": "HOLD"}))
        (ds.EV_DIR / "publication_intents_2026-10-05.json").write_text(
            json.dumps({"validated": [], "review_required": []}))
        def fake_run(cmd, **kw):
            if "publish" in str(cmd):
                ds._state_txn(lambda st: st.setdefault("published_sessions", {})
                              .__setitem__("2026-10-05", {"published_at": "x"}))
            return mock.Mock(returncode=0, stdout="", stderr="")
        with mock.patch.object(ds.subprocess, "run", side_effect=fake_run), \
             mock.patch.object(ds, "ensure_bridge", return_value=True), \
             mock.patch.object(ds, "deep_allocation", return_value=["A"]):
            ds.run_cycle("2026-10-05")
        st = ds._j(ds.SCHED_STATE)
        self.assertEqual(st["session_status"]["2026-10-05"], "COMPLETE")
        self.assertNotIn("current_run", st)

    def test_deep_allocation_formula_and_tiebreak(self):
        cands = [
            {"ticker": "Z", "labels": ["MOMENTUM"], "rs_60": 0},
            {"ticker": "A", "labels": ["MOMENTUM", "CATALYST"], "rs_60": 0},
            {"ticker": "B", "labels": ["MOMENTUM", "CATALYST"], "rs_60": 2.0},
        ]
        (ds.EV_DIR / "candidate_pool_frozen_2026-10-05.json").write_text(
            json.dumps({"candidates": cands}))
        self.assertEqual(ds.deep_allocation("2026-10-05")[:2], ["B", "A"])


if __name__ == "__main__":
    unittest.main()
