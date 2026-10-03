#!/usr/bin/env python3
"""Orchestration tests for alpha_rnd.daily_scheduler — no model calls."""
import fcntl
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import alpha_rnd.daily_scheduler as ds


class SchedTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        for attr in ("SCHED_LOCK", "CYCLE_LOCK", "SCHED_STATE", "EVENTS", "LOG"):
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
        (ds.EV_DIR / "case_artifacts" / "A_2026-10-05.json").write_text(
            json.dumps({"ticker": "A", "signal": "BUY"}))
        with mock.patch.object(ds.subprocess, "run", return_value=mock.Mock(returncode=0, stdout="", stderr="")), \
             mock.patch.object(ds, "ensure_bridge", return_value=True):
            ds.run_cycle("2026-10-05")
        kinds = [e["kind"] for e in self._events()]
        self.assertEqual(kinds[0], "ALPHA_DISCOVERY_STARTED")
        self.assertIn("ALPHA_DISCOVERY_COMPLETE", kinds)
        self.assertTrue(ds.cycle_done("2026-10-05"))

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
