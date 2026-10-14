#!/usr/bin/env python3
"""Retry starvation guard: a stale RETRY_PENDING session never blocks the current session,
retries are bounded and fair, lifetimes expire to FAILED_TERMINAL, and nothing reaches a model.
A fake provider drives all outcomes; no inference is performed."""
import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import alpha_rnd.daily_scheduler as ds

OLD = "2026-10-05"
NEW = "2026-10-14"
DEEP = list("ABCDEFGHIJ")
FUTURE = "2099-01-01T00:00:00+00:00"


def _up(status, reset=None):
    return {"checked_at": "x", "bridge_process": "HEALTHY",
            "bridge_probe": {"unit_active": True, "models_endpoint_ok": True},
            "upstream": {"status": status, "reason_code": None, "reset_at": reset,
                         "latest_success_at": None, "latest_failure_at": None, "evidence_count": 1},
            "analysis_capability": "DEGRADED"}


class Env(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        for attr in ("SCHED_LOCK", "CYCLE_LOCK", "SCHED_STATE", "EVENTS", "LOG", "SCHED_STATE_LOCK"):
            setattr(ds, attr, self.tmp / getattr(ds, attr).name)
        ds.EV_DIR = self.tmp / "ev"
        (ds.EV_DIR / "case_artifacts").mkdir(parents=True)
        for sess in (OLD, NEW):
            (ds.EV_DIR / f"candidate_pool_frozen_{sess}.json").write_text(json.dumps(
                {"candidates": [{"ticker": t, "labels": ["MOMENTUM"], "rs_60": 1} for t in DEEP]}))
        self.ca = ds.EV_DIR / "case_artifacts"
        self.latest = NEW
        self.up = _up("UNKNOWN")
        self.outcome = {}  # (session, ticker) -> ok | rate | runtime ; default ok
        self.ta_calls = []  # (session, ticker) actually sent to the (fake) provider
        self.patches = [
            mock.patch.object(ds, "ensure_bridge", return_value=True),
            mock.patch.object(ds, "deep_allocation", return_value=DEEP),
            mock.patch.object(ds, "last_completed_session", side_effect=lambda: self.latest),
            mock.patch.object(ds, "_upstream_snapshot", side_effect=lambda: self.up),
            mock.patch.object(ds.subprocess, "run", side_effect=self._fake_run),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def _fake_run(self, cmd, **kw):
        c = " ".join(map(str, cmd))
        if "run_ta.py" in c:
            sess, tickers = cmd[2], cmd[3:]
            for t in tickers:
                if (self.ca / f"{t}_{sess}.json").exists():
                    continue  # run_ta resumes: never re-call a successful ticker
                self.ta_calls.append((sess, t))
                o = self.outcome.get((sess, t), "ok")
                if o == "ok":
                    (self.ca / f"{t}_{sess}.json").write_text(json.dumps({"ticker": t, "signal": "Buy"}))
                else:
                    retry = o == "rate"
                    (self.ca / f"{t}_{sess}.error.json").write_text(json.dumps({
                        "ticker": t, "status": "ANALYSIS_INFRASTRUCTURE_FAILED",
                        "reason_code": "MODEL_RATE_LIMITED" if retry else "TA_RUNTIME_FAILURE",
                        "retryable": retry, "raw_error": "fake provider", "error": "fake provider"}))
        elif "alpha_rnd.synthesize" in c:
            (ds.EV_DIR / f"publication_intents_{cmd[-1]}.json").write_text(json.dumps(
                {"validated": [], "intents": {}, "dispositions": {}, "review_required": []}))
        elif "alpha_rnd.publish" in c:
            st = ds._j(ds.SCHED_STATE, {}) or {}
            st["published_sessions"] = {**(st.get("published_sessions") or {}), cmd[-1]: {"watch_count": 0, "sha256": "x"}}
            ds.SCHED_STATE.write_text(json.dumps(st))
        return mock.Mock(returncode=0, stdout="", stderr="")

    def cycle(self, sess):
        self.ta_calls.clear()
        ds.run_cycle(sess)
        return [t for s, t in self.ta_calls if s == sess]

    def analysis(self, sess):
        return json.loads((ds.EV_DIR / f"analysis_status_{sess}.json").read_text())

    def ledger(self, sess):
        return json.loads((ds.EV_DIR / f"analysis_ledger_{sess}.json").read_text())

    def events(self):
        return [json.loads(l) for l in ds.EVENTS.read_text().splitlines()] if ds.EVENTS.exists() else []

    def launched_by_check(self):
        with mock.patch.object(ds.subprocess, "Popen") as pop:
            ds.check()
        if not pop.called:
            return None
        cmd = [str(x) for x in pop.call_args[0][0]]
        return cmd[cmd.index("--run-session") + 1]

    def make_old_pending(self):
        """OLD session: 7 successes + 3 retryable rate-limit failures (H, I, J)."""
        self.outcome = {(OLD, t): "rate" for t in "HIJ"}
        self.up = _up("UNKNOWN")
        self.cycle(OLD)
        self.assertEqual(self.analysis(OLD)["retry_pending"], ["H", "I", "J"])


class PriorityTests(Env):
    def test_1_new_due_session_beats_old_retry(self):
        self.make_old_pending()
        self.latest = NEW  # new market session is due, not yet processed
        self.assertEqual(self.launched_by_check(), NEW)

    def test_2_old_retry_is_not_lost_while_new_session_runs(self):
        self.make_old_pending()
        self.latest = NEW
        self.launched_by_check()
        self.assertEqual(self.analysis(OLD)["retry_pending"], ["H", "I", "J"])

    def test_3_later_opportunity_retries_old_pending_ticker(self):
        self.make_old_pending()
        self.latest = NEW
        self.cycle(NEW)  # new session completes its normal cycle
        self.assertTrue(ds.cycle_done(NEW))
        self.up = _up("UNKNOWN")
        self.outcome = {}
        self.assertEqual(self.launched_by_check(), OLD)
        retried = self.cycle(OLD)
        self.assertEqual(sorted(retried), ["H", "I"])  # bounded budget, not the successes

    def test_background_retry_never_takes_new_session_budget(self):
        self.make_old_pending()
        self.latest = NEW
        self.outcome = {}
        new_calls = self.cycle(NEW)
        self.assertEqual(sorted(new_calls), list("ABCDEFGHIJ"))  # current session: full cycle


class BackendWindowTests(Env):
    def test_4_active_rate_window_zero_inference(self):
        self.make_old_pending()
        self.up = _up("RATE_LIMITED", FUTURE)
        self.assertEqual(self.cycle(OLD), [])
        self.assertEqual(self.analysis(OLD)["retry_pending"], ["H", "I", "J"])

    def test_5_expired_window_permits_retry(self):
        self.make_old_pending()
        self.up = _up("UNKNOWN")
        self.outcome = {}
        self.assertEqual(len(self.cycle(OLD)), 2)  # budget-bounded attempt is permitted


class LifetimeTests(Env):
    def test_6_within_lifetime_remains_pending(self):
        self.make_old_pending()
        self.up = _up("RATE_LIMITED", FUTURE)
        self.cycle(OLD)
        self.assertEqual(self.analysis(OLD)["ticker_states"]["H"], "RETRY_PENDING")

    def test_7_expired_lifetime_becomes_terminal_with_preserved_evidence(self):
        self.make_old_pending()
        old_first = (datetime.now(timezone.utc) - ds.RETRY_LIFETIME - timedelta(days=3)).isoformat()
        led = self.ledger(OLD)
        for t in "HIJ":
            led[t]["first_failure_at"] = old_first
            led[t]["attempts"] = 4
        (ds.EV_DIR / f"analysis_ledger_{OLD}.json").write_text(json.dumps(led))
        self.up = _up("UNKNOWN")
        self.outcome = {}
        retried = self.cycle(OLD)
        a = self.analysis(OLD)
        self.assertEqual(retried, [])  # expired tickers are never sent again
        for t in "HIJ":
            self.assertEqual(a["ticker_states"][t], "FAILED_TERMINAL")
            f = a["failures"][t]
            self.assertEqual(f["reason_code"], "RETRY_WINDOW_EXPIRED")
            self.assertEqual(f["original_reason_code"], "MODEL_RATE_LIMITED")
            self.assertEqual(f["attempts"], 4)
            self.assertEqual(f["first_failure_at"], old_first)
            self.assertIn("last_attempt_at", f)
            self.assertNotIn("disposition", f)  # no investment disposition
        self.assertTrue(a["session_terminal"])
        self.assertFalse(a["analysis_complete"])
        self.assertTrue(ds.cycle_done(OLD))  # operationally finished
        self.assertTrue(any(e["kind"] == "ALPHA_DISCOVERY_COMPLETE" for e in self.events()))


class TerminalSemanticsTests(Env):
    def test_8_terminal_infrastructure_failure_creates_no_investment_disposition(self):
        self.outcome = {(OLD, "J"): "runtime"}
        self.cycle(OLD)
        pub = json.loads((ds.EV_DIR / f"publication_intents_{OLD}.json").read_text())
        self.assertNotIn("J", pub["dispositions"])
        self.assertNotIn("J", json.loads((ds.EV_DIR / f"analysis_status_{OLD}.json").read_text())
                         .get("ta_signals", {}) or {})

    def test_9_success_plus_terminal_is_session_terminal_not_complete(self):
        self.outcome = {(OLD, "J"): "runtime"}
        self.cycle(OLD)
        a = self.analysis(OLD)
        self.assertEqual(a["ticker_states"]["J"], "FAILED_TERMINAL")
        self.assertEqual(a["ticker_states"]["A"], "SUCCESS")
        self.assertTrue(a["session_terminal"])
        self.assertFalse(a["analysis_complete"])

    def test_10_successful_artifacts_never_rerun_or_rewrite(self):
        self.make_old_pending()
        before = {t: hashlib.sha256((self.ca / f"{t}_{OLD}.json").read_bytes()).hexdigest() for t in "ABCDEFG"}
        self.outcome = {}
        for _ in range(3):
            self.up = _up("UNKNOWN")
            calls = self.cycle(OLD)
            self.assertTrue(set(calls).isdisjoint(set("ABCDEFG")))
        self.assertTrue(all(hashlib.sha256((self.ca / f"{t}_{OLD}.json").read_bytes()).hexdigest() == h
                            for t, h in before.items()))


class FairnessAndFloodTests(Env):
    def test_11_repeated_degraded_cycles_do_not_flood(self):
        self.make_old_pending()
        self.up = _up("RATE_LIMITED", FUTURE)
        for _ in range(6):
            self.cycle(OLD)
            self.launched_by_check()
        kinds = [e["kind"] for e in self.events()]
        self.assertEqual(kinds.count("ALPHA_ANALYSIS_DEGRADED"), 1)

    def test_12_background_retry_rotates_through_all_pending_tickers(self):
        self.outcome = {(OLD, t): "rate" for t in DEEP[4:]}  # 6 pending
        self.up = _up("UNKNOWN")
        self.cycle(OLD)
        seen = []
        for _ in range(3):
            calls = self.cycle(OLD)
            self.assertEqual(len(calls), 2)  # budget per run
            seen += calls
        self.assertEqual(sorted(set(seen)), sorted(DEEP[4:]))  # fair: every pending ticker reached

    def test_13_pending_sessions_retried_least_recently_first(self):
        other = "2026-10-06"
        for sess in (OLD, other):
            (ds.EV_DIR / f"analysis_status_{sess}.json").write_text(json.dumps(
                {"session": sess, "retry_pending": ["X"], "analysis_complete": False}))
        st = ds._j(ds.SCHED_STATE, {}) or {}
        st["completed_sessions"] = [NEW]
        st["retry_launched"] = {OLD: "2026-10-14T10:00:00+00:00", other: "2026-10-14T09:00:00+00:00"}
        ds.SCHED_STATE.write_text(json.dumps(st))
        self.latest = NEW
        self.assertEqual(ds._pending_sessions(), [other, OLD])
        self.assertEqual(self.launched_by_check(), other)


if __name__ == "__main__":
    unittest.main()
