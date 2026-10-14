import unittest
from datetime import datetime, timezone

import alpha_rnd.infra_status as inf

NOW = datetime(2026, 10, 14, 14, 40, tzinfo=timezone.utc)

RATE_LINE = ('2026-10-14T17:13:03+0300 udi-ThinkPad python3[8012]: [bridge] ERROR devin_bridge.server: '
             'request=ba95cf9b executor error: Devin CLI exited non-zero (code=1). stderr: Error: Agent error: '
             'Reached free model rate limit. Please switch to a different model. Your limit will reset in '
             '2 hours 46 minutes (at 17:01 UTC). (trace ID: x)')
RATE_EXIT = '2026-10-14T17:13:03+0300 udi-ThinkPad python3[8012]: [bridge] INFO devin_bridge.executor: request=ba95cf9b exit=1 duration=2.3s'
OK_LINE = '2026-10-14T16:45:52+0300 udi-ThinkPad python3[8012]: [bridge] INFO devin_bridge.executor: request=1ada5f59 exit=0 duration=33.6s'
CONN_LINE = ('2026-10-14T15:00:00+0300 udi-ThinkPad python3[8012]: [bridge] ERROR devin_bridge.server: '
             'request=aa11bb22 executor error: [Errno 111] Connection refused')
TIMEOUT_LINE = ('2026-10-14T15:10:00+0300 udi-ThinkPad python3[8012]: [bridge] ERROR devin_bridge.server: '
                'request=cc33dd44 executor error: upstream timed out after 1200s')


class ClassifyTest(unittest.TestCase):
    def test_rate_limit_text(self):
        self.assertEqual(inf.classify(RATE_LINE), "MODEL_RATE_LIMITED")

    def test_quota_text_not_confused_with_rate_limit(self):
        self.assertEqual(inf.classify("insufficient credits remaining"), "MODEL_QUOTA_EXHAUSTED")
        self.assertEqual(inf.classify("HTTP 402 payment required"), "MODEL_QUOTA_EXHAUSTED")

    def test_timeout(self):
        self.assertEqual(inf.classify(TIMEOUT_LINE), "MODEL_TIMEOUT")

    def test_bridge_process_failure(self):
        self.assertEqual(inf.classify(CONN_LINE), "BRIDGE_FAILURE")

    def test_unavailable_502(self):
        self.assertEqual(inf.classify("HTTP 502 devin_cli_error"), "MODEL_UNAVAILABLE")

    def test_code_exception_is_runtime_failure(self):
        self.assertEqual(inf.classify("KeyError('x')", exc_name="KeyError"), "TA_RUNTIME_FAILURE")

    def test_unknown_falls_back_explicitly(self):
        self.assertEqual(inf.classify("something odd"), "UNKNOWN_MODEL_FAILURE")


class UpstreamEvidenceTest(unittest.TestCase):
    def test_rate_limit_evidence_gives_rate_limited_until_reset(self):
        ev = inf.parse_journal("\n".join([OK_LINE, RATE_LINE, RATE_EXIT]))
        self.assertEqual(len(ev), 2)  # one per request id, not per log line
        up = inf.upstream_status(ev, NOW)
        self.assertEqual(up["status"], "RATE_LIMITED")
        self.assertEqual(up["reason_code"], "MODEL_RATE_LIMITED")
        self.assertEqual(up["reset_at"], "2026-10-14T17:01:00+00:00")  # "(at 17:01 UTC)"
        self.assertEqual(datetime.fromisoformat(up["latest_success_at"]).astimezone(timezone.utc),
                         datetime(2026, 10, 14, 13, 45, 52, tzinfo=timezone.utc))

    def test_after_reset_without_new_evidence_is_unknown_not_available(self):
        ev = inf.parse_journal(RATE_LINE)
        later = datetime(2026, 10, 14, 18, 0, tzinfo=timezone.utc)
        self.assertEqual(inf.upstream_status(ev, later)["status"], "UNKNOWN")

    def test_no_evidence_is_unknown(self):
        self.assertEqual(inf.upstream_status([], NOW)["status"], "UNKNOWN")

    def test_latest_success_is_available_within_window(self):
        later_ok = OK_LINE.replace("16:45:52", "17:20:00").replace("1ada5f59", "ffee0011")
        ev = inf.parse_journal("\n".join([RATE_LINE, later_ok]))
        self.assertEqual(inf.upstream_status(ev, NOW)["status"], "AVAILABLE")

    def test_bridge_connection_failure_does_not_claim_upstream_status(self):
        ev = inf.parse_journal(CONN_LINE)
        self.assertEqual(inf.upstream_status(ev, NOW)["status"], "UNKNOWN")


class BridgeVsUpstreamTest(unittest.TestCase):
    def test_models_endpoint_alone_is_not_upstream_available(self):
        rep = inf.status_report(journal_text="", probe={"unit_active": True, "models_endpoint_ok": True}, now=NOW)
        self.assertEqual(rep["bridge_process"], "HEALTHY")
        self.assertEqual(rep["upstream"]["status"], "UNKNOWN")
        self.assertEqual(rep["analysis_capability"], "UNKNOWN")

    def test_process_alive_with_rate_limit_evidence(self):
        rep = inf.status_report(journal_text=RATE_LINE,
                                probe={"unit_active": True, "models_endpoint_ok": True}, now=NOW)
        self.assertEqual(rep["bridge_process"], "HEALTHY")
        self.assertEqual(rep["upstream"]["status"], "RATE_LIMITED")
        self.assertEqual(rep["analysis_capability"], "DEGRADED")

    def test_bridge_down_is_blocked(self):
        rep = inf.status_report(journal_text=RATE_LINE,
                                probe={"unit_active": False, "models_endpoint_ok": False}, now=NOW)
        self.assertEqual(rep["bridge_process"], "DOWN")
        self.assertEqual(rep["analysis_capability"], "BLOCKED")


class FailureRecordTest(unittest.TestCase):
    def test_rate_limit_ta_failure_is_infrastructure_with_reason(self):
        rec = inf.failure_record("2026-10-13", "IOVA", "ta", "boom", upstream={"status": "RATE_LIMITED"})
        self.assertEqual(rec["status"], "ANALYSIS_INFRASTRUCTURE_FAILED")
        self.assertEqual(rec["reason_code"], "MODEL_RATE_LIMITED")
        self.assertTrue(rec["retryable"])
        self.assertEqual(rec["user_action"], "NONE")
        self.assertEqual(rec["raw_error"], "boom")
        self.assertNotIn("signal", rec)

    def test_timeout_reason(self):
        self.assertEqual(inf.failure_record("s", "T", "ta", TIMEOUT_LINE)["reason_code"], "MODEL_TIMEOUT")

    def test_quota_needs_user_action_and_is_not_retryable(self):
        rec = inf.failure_record("s", None, "publication_synthesis", "insufficient credits")
        self.assertEqual(rec["reason_code"], "MODEL_QUOTA_EXHAUSTED")
        self.assertFalse(rec["retryable"])
        self.assertEqual(rec["user_action"], "REQUIRED")


class AnalysisSummaryTest(unittest.TestCase):
    def test_partial_cycle_is_not_complete_and_lists_failures(self):
        req = [f"T{i}" for i in range(10)]
        ok = req[:7]
        fails = {t: {"reason_code": "MODEL_RATE_LIMITED", "retryable": True} for t in req[7:]}
        s = inf.analysis_summary("2026-10-12", req, ok, fails)
        self.assertEqual((s["ta_requested"], s["ta_succeeded"], s["ta_failed"]), (10, 7, 3))
        self.assertFalse(s["analysis_complete"])
        self.assertEqual(s["status"], "DEGRADED")
        self.assertEqual(s["ta_failure_reasons"], {"MODEL_RATE_LIMITED": 3})
        self.assertEqual(s["failed_tickers"], ["T7", "T8", "T9"])

    def test_total_failure_is_infrastructure_not_no_opportunities(self):
        req = ["A", "B"]
        fails = {t: {"reason_code": "MODEL_RATE_LIMITED"} for t in req}
        s = inf.analysis_summary("2026-10-13", req, [], fails)
        self.assertEqual(s["status"], "ANALYSIS_INFRASTRUCTURE_FAILED")
        self.assertEqual(s["dominant_reason"], "MODEL_RATE_LIMITED")
        self.assertFalse(s["analysis_complete"])

    def test_full_success_is_complete(self):
        s = inf.analysis_summary("2026-10-13", ["A", "B"], ["A", "B"], {})
        self.assertTrue(s["analysis_complete"])
        self.assertEqual(s["status"], "COMPLETE")


if __name__ == "__main__":
    unittest.main()
