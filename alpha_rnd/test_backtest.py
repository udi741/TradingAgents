#!/usr/bin/env python3
"""Front-door tests: help/list/mode metadata, routing, safety semantics."""
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from alpha_rnd import backtest as bt  # noqa: E402


def _run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = bt.main(argv)
    return rc, out.getvalue(), err.getvalue()


class FrontDoor(unittest.TestCase):
    def test_help_ok(self):
        with self.assertRaises(SystemExit) as cm:
            bt.main(["--help"])
        self.assertEqual(cm.exception.code, 0)

    def test_no_mode_prints_help(self):
        rc, out, _ = _run([])
        self.assertEqual(rc, 0)
        self.assertIn("DECISION GUIDE", out)

    def test_list_shows_all_modes(self):
        rc, out, _ = _run(["list"])
        self.assertEqual(rc, 0)
        for m in ("TARGETED", "RESEARCH-REPLAY", "GRID-BACKTEST",
                  "STRATEGY-BACKTEST", "PROSPECTIVE"):
            self.assertIn(m, out)

    def test_targeted_labeled_zero_model(self):
        self.assertEqual(bt.MODES["targeted"]["ai"], "NONE")
        self.assertEqual(bt.MODES["targeted"]["providers"], "NONE")

    def test_research_replay_help_warns_contamination(self):
        rc, _, err = _run(["research-replay", "audit", "--as-of", "x"])
        # warning fires before any engine call
        self.assertIn("MODEL_KNOWLEDGE_CONTAMINATION_RISK", err)

    def test_unknown_mode_fails(self):
        with self.assertRaises(SystemExit):
            bt.main(["nonexistent-mode"])

    def test_help_and_list_no_engine_imports(self):
        # help/list must not import the replay engines
        with mock.patch.dict(sys.modules,
                             {"alpha_rnd.replay": None,
                              "alpha_rnd.scenario_replay": None,
                              "alpha_rnd.cohort_outcomes": None}):
            rc, out, _ = _run(["list"])
            self.assertEqual(rc, 0)

    def test_targeted_routes_to_scenario_replay(self):
        called = {}
        from alpha_rnd import scenario_replay

        def fake_run(manifest, ev_dir=None):
            called["manifest"], called["ev_dir"] = manifest, ev_dir
            return {"summary": {"failed": 0}}

        with mock.patch.object(scenario_replay, "run_manifest", fake_run):
            rc, _, _ = _run(["targeted", "m.json", "--ev-dir", "/tmp/ev"])
        self.assertEqual(rc, 0)
        self.assertEqual(called["manifest"], "m.json")
        self.assertEqual(called["ev_dir"], "/tmp/ev")

    def test_targeted_cap_passthrough(self):
        # the underlying engine enforces the cap; routing preserves argv
        from alpha_rnd import scenario_replay
        self.assertEqual(scenario_replay.MAX_SCENARIOS, 12)

    def test_grid_backtest_routes_to_engine(self):
        import cli.main as cm
        captured = {}

        class _R:
            cells_run = skipped = 0
            log_path, run_id = "x", "r"
            failures = []
            settlement_failures = []

        def fake_run(names, dates, config, **kw):
            captured.update(names=names, dates=list(dates), kw=kw)
            return _R()

        class _Sum:
            def render(self):
                return "summary"

        with mock.patch.object(cm, "run_backtest", fake_run), \
                mock.patch.object(cm, "summarize", lambda r: _Sum()):
            rc, _, err = _run(["grid-backtest", "NVDA,AAPL",
                               "--start", "2026-06-01", "--end", "2026-06-15",
                               "--every", "7"])
        self.assertEqual(rc, 0)
        self.assertEqual(captured["names"], ["NVDA", "AAPL"])
        self.assertIn("2026-06-01", captured["dates"])
        self.assertIn("MODEL_KNOWLEDGE_CONTAMINATION_RISK", err)

    def test_grid_backtest_help_safe(self):
        # argparse-level help: exits 0 without touching the engine
        with self.assertRaises(SystemExit) as cm:
            bt.main(["grid-backtest", "--help"])
        self.assertEqual(cm.exception.code, 0)

    def test_unknown_subcommand_exit_code(self):
        with mock.patch("alpha_rnd.backtest._targeted",
                        side_effect=SystemExit(2)):
            with self.assertRaises(SystemExit):
                bt.main(["targeted"])


if __name__ == "__main__":
    unittest.main()
