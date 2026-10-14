#!/usr/bin/env python3
"""Cycle-level tests: infrastructure failures are explicit, never investment results.
No model calls: subprocess and upstream probes are faked."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import alpha_rnd.daily_scheduler as ds

SESS = "2026-10-05"
DEEP = list("ABCDEFGHIJ")


def _up(status, reset=None):
    return {"checked_at": "2026-10-14T14:00:00+00:00", "bridge_process": "HEALTHY",
            "bridge_probe": {"unit_active": True, "models_endpoint_ok": True},
            "upstream": {"status": status, "reason_code": "MODEL_RATE_LIMITED" if status == "RATE_LIMITED" else None,
                         "reset_at": reset, "latest_success_at": None, "latest_failure_at": None,
                         "evidence_count": 1},
            "analysis_capability": "DEGRADED"}


class AnalysisFailureCycle(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        for attr in ("SCHED_LOCK", "CYCLE_LOCK", "SCHED_STATE", "EVENTS", "LOG", "SCHED_STATE_LOCK"):
            setattr(ds, attr, self.tmp / getattr(ds, attr).name)
        ds.EV_DIR = self.tmp / "ev"
        (ds.EV_DIR / "case_artifacts").mkdir(parents=True)
        (ds.EV_DIR / f"candidate_pool_frozen_{SESS}.json").write_text(json.dumps(
            {"candidates": [{"ticker": t, "labels": ["MOMENTUM"], "rs_60": 1} for t in DEEP + ["K"]]}))
        self.patches = [mock.patch.object(ds, "ensure_bridge", return_value=True),
                        mock.patch.object(ds, "deep_allocation", return_value=DEEP)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def _events(self):
        if not ds.EVENTS.exists():
            return []
        return [json.loads(l) for l in ds.EVENTS.read_text().splitlines()]

    def _calls_fake(self, ok_tickers, reason="MODEL_RATE_LIMITED", calls=None):
        def fake_run(cmd, **kw):
            if calls is not None:
                calls.append(cmd)
            if "run_ta.py" in str(cmd):
                for t in DEEP:
                    f = ds.EV_DIR / "case_artifacts" / f"{t}_{SESS}"
                    if t in ok_tickers:
                        (f.with_suffix(".json")).write_text(json.dumps({"ticker": t, "signal": "Buy"}))
                    else:
                        (Path(str(f) + ".error.json")).write_text(json.dumps(
                            {"ticker": t, "status": "ANALYSIS_INFRASTRUCTURE_FAILED",
                             "reason_code": reason, "retryable": True,
                             "raw_error": "Reached free model rate limit"}))
            return mock.Mock(returncode=0, stdout="", stderr="")
        return fake_run

    def test_partial_cycle_is_not_complete_and_visible(self):
        ok = list("ABCDEFG")
        with mock.patch.object(ds, "_upstream_snapshot", return_value=_up("UNKNOWN")), \
             mock.patch.object(ds.subprocess, "run", side_effect=self._calls_fake(ok)):
            ds.run_cycle(SESS)
        a = json.loads((ds.EV_DIR / f"analysis_status_{SESS}.json").read_text())
        self.assertEqual((a["ta_requested"], a["ta_succeeded"], a["ta_failed"]), (10, 7, 3))
        self.assertFalse(a["analysis_complete"])
        self.assertEqual(a["ta_failure_reasons"], {"MODEL_RATE_LIMITED": 3})
        self.assertEqual(a["failed_tickers"], ["H", "I", "J"])
        self.assertNotIn("signal", json.loads((ds.EV_DIR / "case_artifacts" / f"H_{SESS}.error.json").read_text()))
        kinds = [e["kind"] for e in self._events()]
        self.assertEqual(kinds.count("ALPHA_ANALYSIS_DEGRADED"), 1)
        self.assertNotIn("ALPHA_ANALYSIS_INFRASTRUCTURE_FAILED", kinds)

    def test_known_rate_limit_makes_no_model_calls(self):
        calls = []
        with mock.patch.object(ds, "_upstream_snapshot",
                               return_value=_up("RATE_LIMITED", "2026-10-14T17:01:00+00:00")), \
             mock.patch.object(ds.subprocess, "run", side_effect=self._calls_fake([], calls=calls)):
            ds.run_cycle(SESS)
        self.assertFalse([c for c in calls if "run_ta.py" in str(c)], "run_ta must not run while rate-limited")
        for t in DEEP:
            rec = json.loads((ds.EV_DIR / "case_artifacts" / f"{t}_{SESS}.error.json").read_text())
            self.assertEqual(rec["reason_code"], "MODEL_RATE_LIMITED")
            self.assertIn("no SWE call made", rec["raw_error"])
        st = json.loads(ds.SCHED_STATE.read_text())
        self.assertEqual(st["session_status"][SESS], "ERROR")
        self.assertNotIn(SESS, st.get("completed_sessions") or [])
        kinds = [e["kind"] for e in self._events()]
        self.assertEqual(kinds.count("ALPHA_ANALYSIS_INFRASTRUCTURE_FAILED"), 1)
        self.assertNotIn("ALPHA_PUBLICATION_SUMMARY", kinds)  # no fake "no opportunities"

    def test_repeated_identical_outage_alerts_once(self):
        with mock.patch.object(ds, "_upstream_snapshot",
                               return_value=_up("RATE_LIMITED", "2026-10-14T17:01:00+00:00")), \
             mock.patch.object(ds.subprocess, "run", side_effect=self._calls_fake([])):
            for _ in range(4):
                ds.run_cycle(SESS)
        kinds = [e["kind"] for e in self._events()]
        self.assertEqual(kinds.count("ALPHA_ANALYSIS_INFRASTRUCTURE_FAILED"), 1)

    def test_translator_transport_failure_is_infra_and_does_not_touch_publication(self):
        from alpha_rnd import synthesize as syn
        pub = ds.EV_DIR / f"publication_intents_{SESS}.json"
        pub.write_text(json.dumps({"intents": {}, "dispositions": {}}))
        before = pub.read_text()
        def fake_run(cmd, **kw):
            if "run_ta.py" in str(cmd):
                return self._calls_fake(DEEP)(cmd, **kw)
            if "alpha_rnd.synthesize" in " ".join(map(str, cmd)):
                (ds.EV_DIR / f"publication_status_{SESS}.json").write_text(json.dumps(
                    {"status": "ANALYSIS_INFRASTRUCTURE_FAILED", "stage": "publication_synthesis",
                     "reason_code": "MODEL_UNAVAILABLE", "raw_error": "HTTP 502"}))
            return mock.Mock(returncode=0, stdout="", stderr="")
        with mock.patch.object(ds, "_upstream_snapshot", return_value=_up("UNKNOWN")), \
             mock.patch.object(ds.subprocess, "run", side_effect=fake_run):
            ds.run_cycle(SESS)
        self.assertEqual(pub.read_text(), before)
        kinds = [e["kind"] for e in self._events()]
        self.assertIn("ALPHA_ANALYSIS_INFRASTRUCTURE_FAILED", kinds)
        self.assertNotIn("ALPHA_PUBLICATION_SUMMARY", kinds)
        self.assertEqual(json.loads(ds.SCHED_STATE.read_text())["session_status"][SESS], "ERROR")

    def test_book_stage_runs_first_and_independent_of_ta_failure(self):
        calls = []
        with mock.patch.object(ds, "_upstream_snapshot", return_value=_up("UNKNOWN")), \
             mock.patch.object(ds.subprocess, "run", side_effect=self._calls_fake([], calls=calls)):
            ds.run_cycle(SESS)
        strs = [" ".join(map(str, c)) for c in calls]
        mon = next(i for i, c in enumerate(strs) if "alpha_rnd.monitor" in c and "--once" in c)
        ta = next(i for i, c in enumerate(strs) if "run_ta.py" in c)
        self.assertLess(mon, ta)


if __name__ == "__main__":
    unittest.main()
