#!/usr/bin/env python3
"""ops/ta tests — uses a fully isolated prefix/config; touches nothing live."""
import io, json, os, sys, tempfile, unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ops import ta  # noqa: E402


class Sim(unittest.TestCase):
    def setUp(self):
        t = Path(tempfile.mkdtemp())
        self.p = t / "root"; self.cfg = t / "cfg"
        for d in ("TradingAgents-alpha-rnd/alpha_rnd",
                  "TradingAgents-c12/evaluations/gate_c12_prospective",
                  "TradingAgents"):
            (self.p / d).mkdir(parents=True)
        self.cfg.mkdir()
        # canned monitor state + healthy monitor log
        ar = self.p / "TradingAgents-alpha-rnd/alpha_rnd"
        (ar / "monitor_state.json").write_text(json.dumps(
            {"cash": 100.0, "realized": 0, "positions": {"X": {"shares": 1}},
             "pending_open_fills": [], "pending_open_exits": [],
             "executed": ["e1"]}))
        (ar / "monitor_cron.log").write_text(
            "checked 2026-10-16T00:00:00+00:00 data=ok\n")
        (ar / "scheduler.log").write_text("")
        (ar / "management_policy.json").write_text(
            '{"execution": {"enabled": false}}')

    def _setup(self, **kw):
        ns = type("A", (), {"prefix": str(self.p), "config_dir": str(self.cfg),
                            "dry_run": kw.get("dry", True),
                            "no_systemctl": True, "sim": True})
        out = io.StringIO()
        with redirect_stdout(out):
            rc = ta.cmd_setup(ns())
        return rc, out.getvalue()

    def _health(self):
        ns = type("A", (), {"prefix": str(self.p)})
        out = io.StringIO()
        with redirect_stdout(out):
            rc = ta.cmd_health(ns())
        return rc, out.getvalue()

    # --- setup ---
    def test_dry_run_changes_nothing(self):
        rc, o = self._setup(dry=True)
        self.assertIn("DRY-RUN complete", o)
        self.assertFalse((self.cfg / "tradingagents").exists())

    def test_fresh_install_writes_units_and_env(self):
        self._setup(dry=False)
        u = self.cfg / "systemd/tradingagents-telegram.service"
        self.assertTrue(u.exists())
        self.assertIn(str(self.p), u.read_text())
        env = self.cfg / "tradingagents/telegram.env"
        self.assertTrue(env.exists())
        self.assertIn("<bot-token", env.read_text())
        self.assertEqual(oct(env.stat().st_mode)[-3:], "600")

    def test_rerun_idempotent_and_never_overwrites_secret(self):
        self._setup(dry=False)
        env = self.cfg / "tradingagents/telegram.env"
        env.write_text("TELEGRAM_BOT_TOKEN=REAL\n")
        rc, o = self._setup(dry=False)
        self.assertEqual(env.read_text(), "TELEGRAM_BOT_TOKEN=REAL\n")
        self.assertIn("never overwriting secrets", o)

    def test_partial_cron_is_flagged_not_duplicated(self):
        # 1 of 4 job patterns present -> problem, not silent append
        ta._cron_read = lambda: "* * * * * python3 -m alpha_rnd.monitor --once\n"
        _, o = self._setup(dry=True)
        self.assertIn("partial cron coverage", o)

    def test_missing_alpha_worktree_aborts(self):
        p = Path(tempfile.mkdtemp()) / "empty"; p.mkdir()
        ns = type("A", (), {"prefix": str(p), "config_dir": str(self.cfg),
                            "dry_run": True, "no_systemctl": True,
                            "sim": True})
        self.assertEqual(ta.cmd_setup(ns()), 2)

    # --- health ---
    def test_health_stale_monitor_is_failed(self):
        rc, o = self._health()
        self.assertEqual(rc, 2)   # tick from 2026 is ancient
        self.assertIn("FAILED", o)

    def test_health_fresh_monitor_and_readable_state(self):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        (self.p / "TradingAgents-alpha-rnd/alpha_rnd/monitor_cron.log"
         ).write_text(f"checked {now}+00:00 data=ok\n")
        rc, o = self._health()
        self.assertIn("[     OK] ALPHA monitor", o)
        self.assertIn("cash $100", o)
        # bridge/c12/services missing in sim -> degraded not crash
        self.assertIn(rc, (1, 2))

    def test_adaptive_disabled_reported(self):
        _, o = self._health()
        self.assertIn("adaptive execution DISABLED", o)

    def test_health_exit_codes_documented(self):
        self.assertIn("0=HEALTHY", ta.cmd_health.__doc__)

    # --- helpers ---
    def test_missing_py_deps_detects_absent_module(self):
        req = self.cfg / "req.txt"
        req.write_text("definitely_not_a_real_pkg==9.9\n")
        self.assertEqual(ta._missing_py_deps(req),
                         ["definitely_not_a_real_pkg"])
        req.write_text("pandas\n")
        self.assertEqual(ta._missing_py_deps(req), [])

    def test_path_independence(self):
        lay = ta._layout(Path("/somewhere/else"))
        u = ta._fill((ta.TPL / "tradingagents-telegram.service").read_text(), lay)
        self.assertIn("/somewhere/else/TradingAgents-tracks", u)
        self.assertNotIn("/home/udi", u)


if __name__ == "__main__":
    unittest.main()
