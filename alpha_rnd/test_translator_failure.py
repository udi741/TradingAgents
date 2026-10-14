import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

import alpha_rnd.synthesize as syn

S = "2026-10-05"


class TranslatorFailureClasses(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.old_ev = syn.EV
        syn.EV = self.tmp / "ev"
        (syn.EV / "case_artifacts").mkdir(parents=True)
        for t in ("AAA", "BBB"):
            (syn.EV / "case_artifacts" / f"{t}_{S}.json").write_text(json.dumps(
                {"ticker": t, "final_trade_decision": "Buy below 10. Stop $9.", "signal": "Buy"}))
        self.pub = syn.EV / f"publication_intents_{S}.json"

    def tearDown(self):
        syn.EV = self.old_ev

    def _run_with(self, fake):
        with mock.patch.object(syn, "call_bridge", side_effect=fake):
            return syn.run(S)

    def test_transport_502_is_infrastructure_not_ambiguous(self):
        def boom(payload):
            raise syn.TranslatorInfra("MODEL_UNAVAILABLE", "HTTP 502: devin_cli_error")
        doc = self._run_with(boom)
        self.assertEqual(doc["status"], "ANALYSIS_INFRASTRUCTURE_FAILED")
        self.assertEqual(doc["reason_code"], "MODEL_UNAVAILABLE")
        self.assertEqual(doc["dispositions"], {})
        self.assertFalse(self.pub.exists(), "publication_intents must not be written on transport failure")
        st = json.loads((syn.EV / f"publication_status_{S}.json").read_text())
        self.assertEqual(st["tickers"], ["AAA", "BBB"])
        self.assertTrue(st["retryable"])

    def test_rate_limit_text_as_content_is_rate_limited(self):
        doc = self._run_with(lambda p: "Reached free model rate limit. Your limit will reset in 2 hours.")
        self.assertEqual(doc["reason_code"], "MODEL_RATE_LIMITED")
        self.assertNotIn("AMBIGUOUS_REJECTED", json.dumps(doc))

    def test_malformed_output_is_its_own_class(self):
        doc = self._run_with(lambda p: "I could not process these reports.")
        self.assertEqual(doc["reason_code"], "MALFORMED_MODEL_OUTPUT")
        self.assertEqual(doc["status"], "ANALYSIS_INFRASTRUCTURE_FAILED")

    def test_timeout_transport_error(self):
        def slow(payload):
            raise syn.TranslatorInfra("MODEL_TIMEOUT", "TimeoutError('timed out')")
        self.assertEqual(self._run_with(slow)["reason_code"], "MODEL_TIMEOUT")

    def test_real_http_error_path_classifies_body(self):
        err = urllib.error.HTTPError("u", 502, "Bad Gateway", {}, None)
        err.read = lambda: b'{"error":{"message":"Reached free model rate limit"}}'
        with mock.patch.object(syn.urllib.request, "urlopen", side_effect=err):
            with self.assertRaises(syn.TranslatorInfra) as c:
                syn.call_bridge({"messages": []})
        self.assertEqual(c.exception.reason, "MODEL_RATE_LIMITED")

    def test_valid_reject_intent_keeps_legitimate_disposition(self):
        out = json.dumps([
            {"ticker": "AAA", "classification": "REJECT", "watch_mode": "NONE"},
            {"ticker": "BBB", "classification": "REJECT", "watch_mode": "NONE"}])
        doc = self._run_with(lambda p: out)
        self.assertEqual(doc["dispositions"]["AAA"]["disposition"], "NO_ACTION")
        self.assertTrue(self.pub.exists())

    def test_valid_array_omitting_a_ticker_is_infra_not_ambiguous(self):
        out = json.dumps([{"ticker": "AAA", "classification": "REJECT", "watch_mode": "NONE"}])
        doc = self._run_with(lambda p: out)
        self.assertEqual(doc["dispositions"]["BBB"]["disposition"], "ANALYSIS_INFRASTRUCTURE_FAILED")
        self.assertEqual(doc["dispositions"]["BBB"]["reason_code"], "MALFORMED_MODEL_OUTPUT")
        self.assertNotEqual(doc["dispositions"]["BBB"]["disposition"], "AMBIGUOUS_REJECTED")


if __name__ == "__main__":
    unittest.main()
