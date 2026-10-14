#!/usr/bin/env python3
"""Retry completion: temporary inference failures recover automatically, successes are never
repeated, dedup holds, and nothing reaches a model. A fake provider drives per-ticker outcomes."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import alpha_rnd.daily_scheduler as ds

SESS = "2026-10-05"
DEEP = list("ABCDEFGHIJ")
FUTURE = "2099-01-01T00:00:00+00:00"


def _up(status, reset=None):
    return {"checked_at": "x", "bridge_process": "HEALTHY",
            "bridge_probe": {"unit_active": True, "models_endpoint_ok": True},
            "upstream": {"status": status, "reason_code": None, "reset_at": reset,
                         "latest_success_at": None, "latest_failure_at": None, "evidence_count": 1},
            "analysis_capability": "DEGRADED"}


class Provider:
    """Per-ticker outcome script. 'ok' -> valid artifact, 'rate' -> retryable rate-limit,
    'runtime' -> non-retryable TA_RUNTIME_FAILURE. Mirrors run_ta's resume (skips existing json)."""

    def __init__(self, outcomes, ca):
        self.outcomes, self.ca = dict(outcomes), ca
        self.calls = []  # tickers actually sent to the model

    def run_ta(self, cmd, **kw):
        tickers = [t for t in cmd[3:]] if "run_ta.py" in str(cmd) else []
        for t in tickers:
            if (self.ca / f"{t}_{SESS}.json").exists():
                continue
            self.calls.append(t)
            o = self.outcomes[t]
            if o == "ok":
                (self.ca / f"{t}_{SESS}.json").write_text(json.dumps({"ticker": t, "signal": "Buy"}))
                (self.ca / f"{t}_{SESS}.error.json").unlink(missing_ok=True)
            else:
                rec = {"ticker": t, "status": "ANALYSIS_INFRASTRUCTURE_FAILED",
                       "reason_code": "MODEL_RATE_LIMITED" if o == "rate" else "TA_RUNTIME_FAILURE",
                       "retryable": o == "rate", "raw_error": "fake provider",
                       "error": "fake provider"}
                (self.ca / f"{t}_{SESS}.error.json").write_text(json.dumps(rec))
        return mock.Mock(returncode=0, stdout="", stderr="")

    def fake_run(self, cmd, **kw):
        c = " ".join(map(str, cmd))
        if "run_ta.py" in c:
            return self.run_ta(cmd, **kw)
        if "alpha_rnd.synthesize" in c:
            (ds.EV_DIR / f"publication_intents_{SESS}.json").write_text(json.dumps(
                {"validated": [], "intents": {}, "dispositions": {}, "review_required": []}))
        if "--once" in c and "alpha_rnd.publish" not in c and "monitor" in c:
            pass
        if "alpha_rnd.publish" in c:
            st = ds._j(ds.SCHED_STATE, {}) or {}
            st["published_sessions"] = {**(st.get("published_sessions") or {}),
                                        SESS: {"watch_count": 0, "sha256": "x"}}
            ds.SCHED_STATE.write_text(json.dumps(st))
        return mock.Mock(returncode=0, stdout="", stderr="")


class InferenceRetry(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        for attr in ("SCHED_LOCK", "CYCLE_LOCK", "SCHED_STATE", "EVENTS", "LOG", "SCHED_STATE_LOCK"):
            setattr(ds, attr, self.tmp / getattr(ds, attr).name)
        ds.EV_DIR = self.tmp / "ev"
        (ds.EV_DIR / "case_artifacts").mkdir(parents=True)
        (ds.EV_DIR / f"candidate_pool_frozen_{SESS}.json").write_text(json.dumps(
            {"candidates": [{"ticker": t, "labels": ["MOMENTUM"], "rs_60": 1} for t in DEEP]}))
        self.ca = ds.EV_DIR / "case_artifacts"
        self.patches = [mock.patch.object(ds, "ensure_bridge", return_value=True),
                        mock.patch.object(ds, "deep_allocation", return_value=DEEP),
                        mock.patch.object(ds, "last_completed_session", return_value=SESS)]
        for p in self.patches:
            p.start()
        self.up = _up("UNKNOWN")
        self.p_up = mock.patch.object(ds, "_upstream_snapshot", side_effect=lambda: self.up)
        self.p_up.start()

    def tearDown(self):
        for p in self.patches + [self.p_up]:
            p.stop()

    def _cycle(self, outcomes):
        prov = Provider(outcomes, self.ca)
        with mock.patch.object(ds.subprocess, "run", side_effect=prov.fake_run):
            ds.run_cycle(SESS)
        return prov

    def _analysis(self):
        return json.loads((ds.EV_DIR / f"analysis_status_{SESS}.json").read_text())

    def _events(self):
        return [json.loads(l) for l in ds.EVENTS.read_text().splitlines()] if ds.EVENTS.exists() else []

    def _kinds(self):
        return [e["kind"] for e in self._events()]

    def _hash(self, t):
        return hashlib.sha256((self.ca / f"{t}_{SESS}.json").read_bytes()).hexdigest()

    def test_1_seven_ok_three_rate_limited_pending_and_incomplete(self):
        out = {t: "ok" for t in DEEP[:7]} | {t: "rate" for t in DEEP[7:]}
        self._cycle(out)
        self.up = _up("RATE_LIMITED", FUTURE)
        a = self._analysis()
        self.assertEqual(sum(v == "SUCCESS" for v in a["ticker_states"].values()), 7)
        self.assertEqual(a["retry_pending"], ["H", "I", "J"])
        self.assertFalse(a["analysis_complete"])
        self.assertNotIn(SESS, (ds._j(ds.SCHED_STATE, {}) or {}).get("completed_sessions") or [])

    def test_2_rate_window_active_zero_inference_attempts(self):
        out = {t: "ok" for t in DEEP[:7]} | {t: "rate" for t in DEEP[7:]}
        self._cycle(out)
        self.up = _up("RATE_LIMITED", FUTURE)
        prov = self._cycle(out)
        self.assertEqual(prov.calls, [], "no model call while the reset window is active")
        self.assertEqual(self._analysis()["retry_pending"], ["H", "I", "J"])

    def test_3_reset_expired_retries_exactly_pending_not_successes(self):
        out = {t: "ok" for t in DEEP[:7]} | {t: "rate" for t in DEEP[7:]}
        self._cycle(out)
        self.up = _up("RATE_LIMITED", FUTURE)
        before = {t: self._hash(t) for t in DEEP[:7]}
        self.up = _up("UNKNOWN")  # reset passed, no newer evidence: retry allowed
        out2 = {t: "ok" for t in DEEP}
        prov = self._cycle(out2)
        self.assertEqual(sorted(prov.calls), ["H", "I", "J"])
        self.assertTrue(all(self._hash(t) == h for t, h in before.items()), "successes rewritten")

    def test_4_two_of_three_then_incomplete(self):
        self._cycle({t: "ok" for t in DEEP[:7]} | {t: "rate" for t in DEEP[7:]})
        self.up = _up("RATE_LIMITED", FUTURE)
        self.up = _up("UNKNOWN")
        self._cycle({t: "ok" for t in DEEP[:7]} | {"H": "ok", "I": "ok", "J": "rate"})
        a = self._analysis()
        self.assertEqual(sum(v == "SUCCESS" for v in a["ticker_states"].values()), 9)
        self.assertEqual(a["retry_pending"], ["J"])
        self.assertFalse(a["analysis_complete"])

    def test_5_final_retry_completes_session(self):
        self._cycle({t: "ok" for t in DEEP[:7]} | {t: "rate" for t in DEEP[7:]})
        self.up = _up("RATE_LIMITED", FUTURE)
        self.up = _up("UNKNOWN")
        self._cycle({t: "ok" for t in DEEP[:7]} | {"H": "ok", "I": "ok", "J": "rate"})
        self._cycle({t: "ok" for t in DEEP})
        a = self._analysis()
        self.assertTrue(a["analysis_complete"])
        self.assertEqual(a["ta_succeeded"], 10)
        self.assertTrue(ds.cycle_done(SESS))
        self.assertEqual(self._kinds().count("ALPHA_DISCOVERY_COMPLETE"), 1)

    def test_6_runtime_failure_is_terminal_not_retried(self):
        out = {t: "ok" for t in DEEP[:9]} | {"J": "runtime"}
        self._cycle(out)
        self.assertEqual(self._analysis()["ticker_states"]["J"], "FAILED_TERMINAL")
        prov = self._cycle(out)
        self.assertNotIn("J", prov.calls)
        self.assertTrue(self._analysis()["session_terminal"])
        self.assertFalse(self._analysis()["analysis_complete"])  # terminal failure: not fully analysed
        self.assertTrue(ds.cycle_done(SESS))

    def test_7_successful_tickers_never_resent_or_rewritten(self):
        self._cycle({t: "ok" for t in DEEP[:7]} | {t: "rate" for t in DEEP[7:]})
        self.up = _up("RATE_LIMITED", FUTURE)
        before = {t: self._hash(t) for t in DEEP[:7]}
        self.up = _up("UNKNOWN")
        for _ in range(2):
            prov = self._cycle({t: "ok" for t in DEEP})
            self.assertTrue(set(prov.calls).isdisjoint(DEEP[:7]))
        self.assertTrue(all(self._hash(t) == h for t, h in before.items()))

    def test_8_repeated_degraded_cycles_do_not_flood(self):
        out = {t: "ok" for t in DEEP[:7]} | {t: "rate" for t in DEEP[7:]}
        self._cycle(out)
        self.up = _up("RATE_LIMITED", FUTURE)
        for _ in range(5):
            self._cycle(out)
        k = self._kinds()
        self.assertEqual(k.count("ALPHA_DISCOVERY_STARTED"), 1)
        self.assertEqual(k.count("ALPHA_ANALYSIS_DEGRADED"), 1)
        self.assertLessEqual(k.count("ALPHA_PUBLICATION_SUMMARY"), 1)  # no per-cycle summaries

    def test_9_pending_tickers_have_no_investment_artifact_or_disposition(self):
        self._cycle({t: "ok" for t in DEEP[:7]} | {t: "rate" for t in DEEP[7:]})
        self.up = _up("RATE_LIMITED", FUTURE)
        for t in DEEP[7:]:
            self.assertFalse((self.ca / f"{t}_{SESS}.json").exists(),
                             "pending ticker must not have a TA result artifact")
            err = json.loads((self.ca / f"{t}_{SESS}.error.json").read_text())
            self.assertNotIn("signal", err)
            self.assertNotIn("disposition", err)
        pub = json.loads((ds.EV_DIR / f"publication_intents_{SESS}.json").read_text())
        self.assertFalse(set(pub["dispositions"]) & set(DEEP[7:]))

    def test_10_monitor_runs_before_ta_in_retry_cycles(self):
        calls = []
        out = {t: "rate" for t in DEEP}
        prov = Provider(out, self.ca)
        def rec(cmd, **kw):
            calls.append(" ".join(map(str, cmd)))
            return prov.fake_run(cmd, **kw)
        with mock.patch.object(ds.subprocess, "run", side_effect=rec):
            ds.run_cycle(SESS)
        mon = next(i for i, c in enumerate(calls) if "alpha_rnd.monitor" in c and "--once" in c)
        ta = next(i for i, c in enumerate(calls) if "run_ta.py" in c)
        self.assertLess(mon, ta)

    def test_12_scheduler_revisits_pending_session_without_newer_session(self):
        self._cycle({t: "ok" for t in DEEP[:7]} | {t: "rate" for t in DEEP[7:]})
        self.up = _up("RATE_LIMITED", FUTURE)
        newer = "2026-10-06"  # a newer session completed; SESS is older and still pending
        st = ds._j(ds.SCHED_STATE, {}) or {}
        st["completed_sessions"] = [newer]
        ds.SCHED_STATE.write_text(json.dumps(st))
        with mock.patch.object(ds, "last_completed_session", return_value=newer), \
             mock.patch.object(ds.subprocess, "Popen") as pop:
            ds.check()
        args = " ".join(map(str, pop.call_args[0][0]))
        self.assertIn("--run-session " + SESS, args)


if __name__ == "__main__":
    unittest.main()
