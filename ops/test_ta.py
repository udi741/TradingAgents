#!/usr/bin/env python3
"""ops/ta tests — uses a fully isolated prefix/config; touches nothing live."""
import io, json, os, shutil, sys, tempfile, unittest
from contextlib import redirect_stdout
from unittest import mock
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
        # sim dirs are plain dirs, not git worktrees — stub the workspace
        # check; workspace behavior itself is covered in class Workspace
        self._wsmock = mock.patch.object(
            ta, "_ws_state",
            lambda p: {r: {"status": "OK"} for r in ta._ws_spec()})
        self._wsmock.start()
        self.addCleanup(self._wsmock.stop)

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
        with mock.patch.object(ta, "_ws_state", lambda x: {
                r: {"status": "MISSING"} for r in ta._ws_spec()}):
            out = io.StringIO()
            with redirect_stdout(out):
                rc = ta.cmd_setup(ns())
        self.assertEqual(rc, 2)
        self.assertIn("workspace setup", out.getvalue())

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
        # C12 is optional: absent ta_eval no longer degrades. rc 0..2 all
        # legitimate depending on ambient services; must not crash.
        self.assertIn(rc, (0, 1, 2))

    def test_adaptive_disabled_ok(self):
        _, o = self._health()
        self.assertIn("adaptive execution disabled (conservative)", o)

    def test_adaptive_enabled_with_provenance_not_unhealthy(self):
        # E1 acceptance: enabled paper execution is legitimate when it
        # carries activation provenance — must not flag fail/degraded.
        import json as _json
        (self.p / "TradingAgents-alpha-rnd/alpha_rnd/management_policy.json"
         ).write_text(_json.dumps({"execution": {
             "enabled": True, "activated_at": "2026-10-16",
             "activated_for": "fresh PBF decision accepted"}}))
        _, o = self._health()
        self.assertIn("[     OK] adaptive execution ENABLED with provenance", o)

    def test_adaptive_enabled_without_provenance_flagged(self):
        import json as _json
        (self.p / "TradingAgents-alpha-rnd/alpha_rnd/management_policy.json"
         ).write_text(_json.dumps({"execution": {"enabled": True}}))
        _, o = self._health()
        self.assertIn("[DEGRADED] adaptive execution ENABLED with provenance", o)

    def test_adaptive_policy_malformed_flagged(self):
        import json as _json
        (self.p / "TradingAgents-alpha-rnd/alpha_rnd/management_policy.json"
         ).write_text(_json.dumps({"execution": {"enabled": "yes"}}))
        _, o = self._health()
        self.assertIn("[ FAILED] adaptive execution policy well-formed", o)

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


class BackupRestore(unittest.TestCase):
    """Isolated backup->restore cycle. Never touches the live prefix."""
    def setUp(self):
        t = Path(tempfile.mkdtemp())
        self.src = t / "src"; self.dst = t / "dst"
        for base in (self.src, self.dst):
            for d in ("TradingAgents",
                      "TradingAgents-alpha-rnd/alpha_rnd",
                      "TradingAgents-alpha-rnd/evaluations/alpha_rnd_v1/"
                      "management_intents",
                      "TradingAgents-c12/evaluations/gate_c12_prospective/"
                      "weeks"):
                (base / d).mkdir(parents=True)
        # sim dirs are not git checkouts — stub a matching SHA so backup
        # manifest and restore checks agree (overridden per-test as needed)
        self._gitmock = mock.patch.object(
            ta, "_git", lambda d: {"sha": "f" * 40, "dirty": False})
        self._gitmock.start()
        self.addCleanup(self._gitmock.stop)
        ar = self.src / "TradingAgents-alpha-rnd/alpha_rnd"
        st = {"cash": 5000.0, "realized": -100.0,
              "positions": {"X": {"shares": 9, "fill": 10.0,
                                  "stop_rule": {"type": "close_below",
                                                "level": 9}}},
              "pending_open_fills": [{"ticker": "Y", "order_id": "o1"}],
              "pending_open_exits": [], "executed": ["e1", "e2"],
              "book": {"mark_session": "S1"}}
        (ar / "monitor_state.json").write_text(json.dumps(st))
        (ar / "live_watchlist.json").write_text("{}")
        (ar / "scheduler_state.json").write_text("{}")
        (ar / "trigger_events.jsonl").write_text('{}"+chr(10)')
        (ar / "scheduler_events.jsonl").write_text('{}"+chr(10)')
        (ar / "management_policy.json").write_text(
            '{"execution":{"enabled":false}}')
        ev = self.src / ("TradingAgents-alpha-rnd/evaluations"
                         "/alpha_rnd_v1")
        (ev / "alpha_paper_ledger.jsonl").write_text('{"type":"MARK"}'+chr(10))
        (ev / "management_state.json").write_text("{}")
        (ev / "management_actions.json").write_text("{}")
        cd = self.src / ("TradingAgents-c12/evaluations"
                         "/gate_c12_prospective")
        (cd / "c12_paper_portfolio.jsonl").write_text('{"a":1}'+chr(10))
        (cd / "c12_nav.jsonl").write_text('{"nav": 999.0}'+chr(10))
        (cd / "c12_signal_ledger.jsonl").write_text('{}"+chr(10)')
        (cd / "scheduler_state.json").write_text("{}")
        (cd / "journal.jsonl").write_text('{}"+chr(10)')
        self.arc = t / "b.tar.gz"

    def _backup(self, out=None):
        ns = type("A", (), {"prefix": str(self.src),
                            "output": str(out or self.arc),
                            "label": "t", "dry_run": False})
        out = io.StringIO()
        with redirect_stdout(out):
            return ta.cmd_backup(ns()), out.getvalue()

    def _man(self, arc=None):
        import tarfile
        with tarfile.open(arc or self.arc) as t:
            return json.loads(t.extractfile("manifest.json").read())

    def _restore_fail_at(self, n):
        """Run restore with shutil.move raising on call #n."""
        calls = [0]
        orig = shutil.move

        def boom(s, d):
            calls[0] += 1
            if calls[0] == n:
                raise OSError("simulated disk failure")
            return orig(s, d)
        with mock.patch.object(ta.shutil, "move", side_effect=boom):
            return self._restore()

    def _journal(self):
        return json.loads(
            (self.dst / ".restore_in_progress").read_text())

    def _assert_identical(self):
        for rel in ("alpha_rnd/monitor_state.json",
                    "alpha_rnd/trigger_events.jsonl",
                    "alpha_rnd/management_policy.json"):
            self.assertEqual(
                (self.src / "TradingAgents-alpha-rnd" / rel).read_bytes(),
                (self.dst / "TradingAgents-alpha-rnd" / rel).read_bytes())
        self.assertFalse((self.dst / ".restore_in_progress").exists())

    def _restore(self, dry=False, prefix=None, arc=None):
        ns = type("A", (), {"archive": str(arc or self.arc),
                            "prefix": str(prefix or self.dst),
                            "dry_run": dry})
        out = io.StringIO()
        with redirect_stdout(out):
            return ta.cmd_restore(ns()), out.getvalue()

    def test_full_cycle(self):
        rc, o = self._backup()
        self.assertEqual(rc, 0, o)
        self.assertTrue(self.arc.exists())
        rc, o = self._restore(dry=True)
        self.assertEqual(rc, 0)
        self.assertFalse((self.dst / "TradingAgents-alpha-rnd/alpha_rnd"
                          "/monitor_state.json").exists())
        rc, o = self._restore()
        self.assertEqual(rc, 0, o)
        # authority identical byte-for-byte
        for rel in ("alpha_rnd/monitor_state.json",
                    "alpha_rnd/trigger_events.jsonl"):
            self.assertEqual(
                (self.src / "TradingAgents-alpha-rnd" / rel).read_bytes(),
                (self.dst / "TradingAgents-alpha-rnd" / rel).read_bytes())
        # pending order + executed ids preserved -> no dup/replay possible
        st = json.loads((self.dst / "TradingAgents-alpha-rnd/alpha_rnd"
                         "/monitor_state.json").read_text())
        self.assertEqual(st["executed"], ["e1", "e2"])
        self.assertEqual(st["pending_open_fills"][0]["order_id"], "o1")

    def test_corrupt_archive_fails_closed(self):
        self._backup()
        data = bytearray(self.arc.read_bytes())
        data[100] ^= 0xFF
        bad = self.arc.with_name("bad.tar.gz")
        bad.write_bytes(bytes(data))
        rc, o = self._restore(arc=bad)
        self.assertEqual(rc, 2)

    def test_missing_manifest_fails(self):
        import tarfile, io as _io
        no = self.arc.with_name("no.tar.gz")
        with tarfile.open(no, "w:gz") as t:
            b = b"x"; ti = tarfile.TarInfo("payload/x"); ti.size = 1
            t.addfile(ti, _io.BytesIO(b))
        rc, o = self._restore(arc=no)
        self.assertEqual(rc, 2)

    def test_path_traversal_rejected(self):
        import tarfile, io as _io
        bad = self.arc.with_name("trav.tar.gz")
        man = {"format_version": ta.FMT_VER, "files": []}
        with tarfile.open(bad, "w:gz") as t:
            mb = json.dumps(man).encode()
            ti = tarfile.TarInfo("manifest.json"); ti.size = len(mb)
            t.addfile(ti, _io.BytesIO(mb))
            b = b"x"; ti = tarfile.TarInfo("../evil"); ti.size = 1
            t.addfile(ti, _io.BytesIO(b))
        rc, _ = self._restore(arc=bad)
        self.assertEqual(rc, 2)

    def test_nonempty_target_refused(self):
        self._backup()
        self._restore()
        rc, o = self._restore()   # second restore into non-empty target
        self.assertEqual(rc, 2)
        self.assertIn("REFUSE", o)

    def test_backup_has_no_secrets_and_manifest_shas(self):
        self._backup()
        import tarfile, json as _j
        with tarfile.open(self.arc) as t:
            man = _j.loads(t.extractfile("manifest.json").read())
        self.assertIn("telegram.env", str(man["secrets_required_not_included"]))
        self.assertTrue(all("sha256" in f for f in man["files"]))
        self.assertEqual(man["alpha"]["cash"], 5000.0)
        self.assertEqual(man["alpha"]["adaptive_execution_enabled"], False)


    def test_sha_mismatch_refuses_runtime(self):
        self._backup()
        import tarfile, json as _j, io as _io
        # rewrite manifest with a bogus ALPHA sha inside the archive
        tampered = self.arc.with_name("tamper.tar.gz")
        with tarfile.open(self.arc) as tin, \
                tarfile.open(tampered, "w:gz") as tout:
            for m in tin.getmembers():
                data = tin.extractfile(m).read()
                if m.name == "manifest.json":
                    man = _j.loads(data)
                    man["git"] = {"ALPHA_DIR": {"sha": "deadbeef" * 5,
                                                "dirty": False},
                                  "C12_DIR": {"sha": "cafebabe" * 5,
                                              "dirty": False},
                                  "BASE_DIR": {"sha": "cafebabe" * 5,
                                               "dirty": False}}
                    man["files"] = [{**f, "sha256":
                                     f["sha256"]} for f in man["files"]]
                    data = _j.dumps(man).encode()
                    m = tarfile.TarInfo("manifest.json"); m.size = len(data)
                tout.addfile(m, _io.BytesIO(data))
        orig = ta._git
        try:
            ta._git = lambda d: {"sha": "cafebabe" * 5, "dirty": False}
            rc, o = self._restore(arc=tampered)
        finally:
            ta._git = orig
        self.assertEqual(rc, 2)
        self.assertIn("code mismatch", o)
        self.assertIn("deadbeef", o)
        self.assertIn("checkout", o)
        # nothing promoted
        self.assertFalse((self.dst / "TradingAgents-alpha-rnd/alpha_rnd"
                          "/monitor_state.json").exists())

    def test_prepromotion_failure_leaves_target_untouched(self):
        self._backup()
        # corrupt one payload member -> checksum failure during staging
        import tarfile, io as _io
        bad = self.arc.with_name("prepro.tar.gz")
        with tarfile.open(self.arc) as tin, \
                tarfile.open(bad, "w:gz") as tout:
            for m in tin.getmembers():
                data = tin.extractfile(m).read()
                if m.name.endswith("monitor_state.json") and \
                        "payload/" in m.name:
                    data = b'{"corrupted": true}'
                    m = tarfile.TarInfo(m.name); m.size = len(data)
                tout.addfile(m, _io.BytesIO(data))
        rc, o = self._restore(arc=bad)
        self.assertEqual(rc, 2)
        # nothing promoted
        self.assertFalse((self.dst / "TradingAgents-alpha-rnd/alpha_rnd"
                          "/monitor_state.json").exists())
        self.assertFalse(any(self.dst.rglob("*restore_stage*")))
        self.assertFalse((self.dst / ".restore_in_progress").exists())

    def test_staged_continuity_failure_no_promotion(self):
        self._backup()
        # manifest summary lies vs payload -> staged continuity fails
        import tarfile, json as _j, io as _io
        bad = self.arc.with_name("cont.tar.gz")
        with tarfile.open(self.arc) as tin, \
                tarfile.open(bad, "w:gz") as tout:
            for m in tin.getmembers():
                data = tin.extractfile(m).read()
                if m.name == "manifest.json":
                    man = _j.loads(data); man["alpha"]["cash"] = 1.0
                    # keep file sha entries valid (payload unchanged)
                    data = _j.dumps(man).encode()
                    m = tarfile.TarInfo("manifest.json"); m.size = len(data)
                tout.addfile(m, _io.BytesIO(data))
        rc, o = self._restore(arc=bad)
        self.assertEqual(rc, 2)
        self.assertFalse((self.dst / "TradingAgents-alpha-rnd/alpha_rnd"
                          "/monitor_state.json").exists())

    # ---- Phase 2B: unverifiable runtime SHA + interrupted promotion ----

    def test_unverifiable_runtime_sha_refused(self):
        self._backup()
        # target is not a git checkout -> _git returns {} -> fail closed
        with mock.patch.object(ta, "_git", return_value={}):
            rc, o = self._restore()
        self.assertEqual(rc, 2)
        self.assertIn("CANNOT VERIFY RUNTIME CODE VERSION", o)
        self.assertIn("checkout", o)
        self.assertFalse((self.dst / "TradingAgents-alpha-rnd/alpha_rnd"
                          "/monitor_state.json").exists())

    def test_interrupted_after_first_file_then_resume(self):
        self._backup()
        rc, o = self._restore_fail_at(2)
        self.assertEqual(rc, 2)
        j = self._journal()
        self.assertEqual(sum(1 for f in j["files"] if f["promoted"]), 1)
        self.assertEqual(j["backup_id"], self._man()["backup_id"])
        # health must report FAILED, not healthy
        hout = io.StringIO()
        with redirect_stdout(hout):
            hrc = ta.cmd_health(type("A", (), {"prefix": str(self.dst)})())
        self.assertEqual(hrc, 2)
        self.assertIn("INCOMPLETE RESTORE TRANSACTION", hout.getvalue())
        # rerun same restore -> resumes and completes
        rc, o = self._restore()
        self.assertEqual(rc, 0, o)
        self.assertIn("resum", o)
        self._assert_identical()

    def test_interrupted_mid_file_then_resume(self):
        self._backup()
        n = len(self._man()["files"])
        rc, _ = self._restore_fail_at(n // 2 + 1)
        self.assertEqual(rc, 2)
        j = self._journal()
        self.assertEqual(sum(1 for f in j["files"] if f["promoted"]),
                         n // 2)
        rc, o = self._restore()
        self.assertEqual(rc, 0, o)
        self._assert_identical()

    def test_interrupted_on_final_file_then_resume(self):
        self._backup()
        n = len(self._man()["files"])
        rc, _ = self._restore_fail_at(n)
        self.assertEqual(rc, 2)
        self.assertEqual(sum(1 for f in self._journal()["files"]
                             if f["promoted"]), n - 1)
        rc, o = self._restore()
        self.assertEqual(rc, 0, o)
        self._assert_identical()

    def test_crash_after_all_moves_journal_left(self):
        """All files promoted but journal unlink crashed -> resume just
        verifies + cleans up."""
        self._backup()
        real_unlink = Path.unlink

        def u(self, *a, **k):
            if self.name == ".restore_in_progress":
                raise OSError("simulated crash on journal cleanup")
            return real_unlink(self, *a, **k)
        with mock.patch.object(Path, "unlink", u):
            rc, _ = self._restore()
        self.assertEqual(rc, 2)
        j = self._journal()
        self.assertTrue(all(f["promoted"] for f in j["files"]))
        rc, o = self._restore()
        self.assertEqual(rc, 0, o)
        self._assert_identical()

    def test_wrong_backup_cannot_resume(self):
        self._backup()
        rc, _ = self._restore_fail_at(2)
        self.assertEqual(rc, 2)
        other = self.arc.with_name("b2.tar.gz")
        self._backup(out=other)  # different backup_id
        rc, o = self._restore(arc=other)
        self.assertEqual(rc, 2)
        self.assertIn("belongs to backup", o)
        # original backup still resumes fine
        rc, o = self._restore()
        self.assertEqual(rc, 0, o)
        self._assert_identical()

    def test_corrupt_staged_file_resume_refused(self):
        self._backup()
        rc, _ = self._restore_fail_at(3)
        self.assertEqual(rc, 2)
        j = self._journal()
        todo = [f for f in j["files"] if not f["promoted"]]
        Path(todo[0]["staged"]).write_bytes(b"corrupted")
        rc, o = self._restore()
        self.assertEqual(rc, 2)
        self.assertIn("unverifiable", o)

    def test_missing_stage_rolls_back_and_restores(self):
        self._backup()
        rc, _ = self._restore_fail_at(2)
        self.assertEqual(rc, 2)
        j = self._journal()
        import shutil as _s
        _s.rmtree(j["stage_root"])
        rc, o = self._restore()
        self.assertEqual(rc, 0, o)
        self.assertIn("rolling back", o)
        self._assert_identical()

    def test_rollback_never_deletes_foreign_file(self):
        self._backup()
        rc, _ = self._restore_fail_at(2)
        self.assertEqual(rc, 2)
        j = self._journal()
        foreign = (self.dst / "TradingAgents-alpha-rnd/alpha_rnd"
                   "/operator_file.txt")
        foreign.write_text("not from the backup")
        import shutil as _s
        _s.rmtree(j["stage_root"])
        rc, o = self._restore()
        self.assertEqual(rc, 0, o)
        self.assertTrue(foreign.exists())  # untouched by rollback
        self.assertEqual(foreign.read_text(), "not from the backup")

    def test_non_authority_dirty_dir_collapse(self):
        # git collapses untracked dirs to `dir/` — authority paths inside
        # must not be treated as foreign (they are mid-restore promotions)
        rels = {"a/x.json", "weeks/w1/state.json"}
        self.assertEqual(
            ta._non_authority_dirty(["a/x.json", "weeks/w1/"], rels), [])
        self.assertEqual(
            ta._non_authority_dirty(["weeks/evil/", "a/x.json"], rels),
            ["weeks/evil/"])
        self.assertEqual(
            ta._non_authority_dirty(["code.py"], rels), ["code.py"])

    def test_rollback_refuses_unverifiable_promoted(self):
        self._backup()
        rc, _ = self._restore_fail_at(2)
        self.assertEqual(rc, 2)
        j = self._journal()
        promoted = [f for f in j["files"] if f["promoted"]][0]
        Path(promoted["target"]).write_bytes(b"tampered")
        rc, o = self._restore()
        self.assertEqual(rc, 2)
        self.assertIn("unverifiable", o)


class Workspace(unittest.TestCase):
    """Real-git workspace creation/status tests."""
    def setUp(self):
        import subprocess as sp
        self.sp = sp
        t = Path(tempfile.mkdtemp())
        self.pfx = t / "ws"; self.pfx.mkdir()
        base = self.pfx / "TradingAgents"
        def g(*a, d=base):
            sp.run(["git", "-C", str(d)] + list(a), check=1,
                   capture_output=1)
        sp.run(["git", "init", "-b", "infra/devin-bridge", str(base)],
               check=1, capture_output=1)
        (base / "x.py").write_text("x=1\n")
        g("add", "-A")
        g("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "i")
        for br in ("exp/alpha-rnd-v1", "exp/gate-c12-prospective",
                   "exp/expert-rnd-v2", "project/tracks"):
            g("branch", br)
        g("worktree", "add", str(self.pfx / "TradingAgents-tracks"),
          "project/tracks")
        self.g = g

    def _ws(self, action="status", dry=False, opt=False):
        ns = type("A", (), {"prefix": str(self.pfx), "action": action,
                            "dry_run": dry, "with_optional": opt})
        out = io.StringIO()
        with redirect_stdout(out):
            return ta.cmd_workspace(ns()), out.getvalue()

    def test_status_reports_missing_required(self):
        rc, o = self._ws()
        self.assertEqual(rc, 2)
        self.assertIn("ALPHA", o)
        self.assertIn("MISSING", o)
        self.assertIn("BASE", o)

    def test_setup_dry_run_creates_nothing(self):
        rc, o = self._ws("setup", dry=True)
        self.assertEqual(rc, 0)
        self.assertIn("DRY", o)
        self.assertFalse((self.pfx / "TradingAgents-alpha-rnd").exists())

    def test_setup_creates_required_and_is_idempotent(self):
        rc, o = self._ws("setup")
        self.assertEqual(rc, 0, o)
        self.assertTrue((self.pfx / "TradingAgents-alpha-rnd").exists())
        self.assertTrue((self.pfx / "TradingAgents-c12").exists())
        self.assertFalse((self.pfx / "TradingAgents-expert-rnd").exists())
        br, _ = ta._git_branch(self.pfx / "TradingAgents-alpha-rnd")
        self.assertEqual(br, "exp/alpha-rnd-v1")
        rc, o = self._ws("setup")   # idempotent
        self.assertEqual(rc, 0)
        self.assertIn("SKIP ALPHA", o)

    def test_optional_created_with_flag(self):
        self._ws("setup", opt=True)
        self.assertTrue((self.pfx / "TradingAgents-expert-rnd").exists())

    def test_conflict_path_refused(self):
        (self.pfx / "TradingAgents-c12").mkdir()
        (self.pfx / "TradingAgents-c12" / "junk").write_text("x")
        rc, o = self._ws("setup")
        self.assertEqual(rc, 2)
        self.assertIn("CONFLICT", o)

    def test_wrong_branch_refused(self):
        self._ws("setup")
        self.g("checkout", "-b", "wrong",
               d=self.pfx / "TradingAgents-alpha-rnd")
        rc, o = self._ws("status")
        self.assertEqual(rc, 2)
        self.assertIn("WRONG_BRANCH", o)
        rc, o = self._ws("setup")
        self.assertEqual(rc, 2)

    def test_branch_checked_out_elsewhere_refused(self):
        self.g("worktree", "add", str(self.pfx / "elsewhere"),
               "exp/alpha-rnd-v1")
        rc, o = self._ws("setup")
        self.assertEqual(rc, 2)
        self.assertIn("checked out elsewhere", o)

    def test_setup_refuses_incomplete_workspace(self):
        cfg = Path(tempfile.mkdtemp())
        ns = type("A", (), {"prefix": str(self.pfx),
                            "config_dir": str(cfg), "dry_run": True,
                            "no_systemctl": True, "sim": True})
        out = io.StringIO()
        with redirect_stdout(out):
            rc = ta.cmd_setup(ns())
        self.assertEqual(rc, 2)
        self.assertIn("workspace setup", out.getvalue())


class Boot(unittest.TestCase):
    """Boot recovery self-test."""
    def setUp(self):
        t = Path(tempfile.mkdtemp())
        self.p = t / "root"
        for d in ("TradingAgents-alpha-rnd/alpha_rnd",
                  "TradingAgents-c12/evaluations/gate_c12_prospective",
                  "TradingAgents"):
            (self.p / d).mkdir(parents=True)
        ar = self.p / "TradingAgents-alpha-rnd/alpha_rnd"
        (ar / "monitor_state.json").write_text(json.dumps(
            {"cash": 100.0, "pending_open_fills": [],
             "pending_open_exits": [], "executed": []}))
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        (ar / "monitor_cron.log").write_text(
            f"checked {now}+00:00 data=ok\n")
        (ar / "scheduler.log").write_text("")
        (ar / "management_policy.json").write_text(
            '{"execution":{"enabled":false}}')
        (self.p / "TradingAgents-c12/evaluations/gate_c12_prospective"
         "/scheduler.log").write_text("")
        self.sf = t / "boot_health.json"
        for name, val in (("_svc", lambda u: "active"),
                          ("_get", lambda *a, **k: {"runtime_ready": True}),
                          ("_cron_read", lambda: "alpha_rnd.monitor\n"
                           "alpha_rnd.daily_scheduler\n"
                           "ta_eval.c12_scheduler\n"),
                          ("_boot_id", lambda: "test-boot-1")):
            m = mock.patch.object(ta, name, val)
            m.start(); self.addCleanup(m.stop)

    def _boot(self):
        ns = type("A", (), {"prefix": str(self.p),
                            "state_file": str(self.sf)})
        out = io.StringIO()
        with redirect_stdout(out):
            return ta.cmd_bootcheck(ns()), out.getvalue()

    def test_healthy_boot_writes_artifact(self):
        rc, o = self._boot()
        self.assertEqual(rc, 0)
        self.assertIn("BOOT RECOVERY: HEALTHY", o)
        rec = json.loads(self.sf.read_text())
        self.assertEqual(rec["overall"], "HEALTHY")
        self.assertEqual(rec["boot_id"], "test-boot-1")

    def test_degraded_then_recovered_records_recovery(self):
        orig = ta._svc
        with mock.patch.object(ta, "_svc",
                               lambda u: "inactive"
                               if "telegram" in u else "active"):
            rc, o = self._boot()
        self.assertEqual(rc, 1)
        self.assertIn("DEGRADED", o)
        rc, o = self._boot()   # relay came back
        self.assertEqual(rc, 0)
        rec = json.loads(self.sf.read_text())
        self.assertTrue(rec.get("recovered_utc"))

    def test_stale_monitor_fails(self):
        (self.p / "TradingAgents-alpha-rnd/alpha_rnd/monitor_cron.log"
         ).write_text("checked 2020-01-01T00:00:00+00:00 x\n")
        rc, o = self._boot()
        self.assertEqual(rc, 2)
        self.assertIn("BOOT RECOVERY: FAILED", o)

    def test_incomplete_restore_marker_fails(self):
        (self.p / ".restore_in_progress").write_text("{}")
        rc, o = self._boot()
        self.assertEqual(rc, 2)

    def test_missing_worktree_fails(self):
        import shutil as _s
        _s.rmtree(self.p / "TradingAgents-c12")
        rc, o = self._boot()
        self.assertEqual(rc, 2)

    def test_health_shows_boot_state(self):
        self._boot()
        home = self.sf.parent
        (home / ".config/tradingagents").mkdir(parents=True)
        (home / ".config/tradingagents/boot_health.json"
         ).write_text(self.sf.read_text())
        ns = type("A", (), {"prefix": str(self.p)})
        out = io.StringIO()
        with mock.patch.object(Path, "home", classmethod(lambda c: home)):
            with redirect_stdout(out):
                ta.cmd_health(ns())
        self.assertIn("boot recovery: HEALTHY", out.getvalue())


if __name__ == "__main__":
    unittest.main()
