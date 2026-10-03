#!/usr/bin/env python3
"""Validator/synthesis tests — synthetic artifacts only, no model calls."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import alpha_rnd.synthesize as sz


def art(t="X", signal="Buy", text=""):
    return {"ticker": t, "signal": signal, "final_trade_decision": text,
            "trader_investment_plan": "", "risk_judge_decision": "",
            "investment_plan": ""}


def intent(**kw):
    base = {"ticker": "X", "classification": "WATCH_FOR_ENTRY",
            "watch_mode": "DETERMINISTIC_CONFIRMATION",
            "trigger": "close in 60-62 on low volume",
            "params": {"zone": [60.0, 62.0]},
            "entry_convention": "next open", "invalidation": "close <55.9",
            "stop_level": 55.9, "target": None, "horizon": "weeks",
            "reevaluation": "earnings", "size_frac": 1.0,
            "auto_execution_authorized": False, "ambiguity": None}
    base.update(kw)
    return base


class ValidateTest(unittest.TestCase):
    TXT = "close inside $60-62 with low volume; stop 55.90; risk <213; " \
          "target 70; zone 8.00-8.20; offering $55-80; 1.5 million shares"

    def v(self, i, a):
        return sz.validate(i, a)

    def test_clear_deterministic_watch_passes(self):
        a = art(signal="Sell", text=self.TXT)
        self.assertEqual(self.v(intent(), a), [])

    def test_unsupported_level_rejected(self):
        a = art(signal="Sell", text=self.TXT)
        e = self.v(intent(params={"zone": [60.0, 99.9]}), a)
        self.assertTrue(any("unsupported number 99.9" in x for x in e))

    def test_missing_stop_not_invented(self):
        # artifact never states a stop; intent claims one -> reject
        a = art(signal="Buy", text="zone 8.00-8.20 only")
        e = self.v(intent(watch_mode="AUTO_ENTRY",
                          auto_execution_authorized=True, stop_level=7.7), a)
        self.assertTrue(e)

    def test_auto_entry_vs_sell_rejected(self):
        a = art(signal="Sell", text=self.TXT)
        e = self.v(intent(watch_mode="AUTO_ENTRY",
                          auto_execution_authorized=True), a)
        self.assertTrue(any("contradicts" in x for x in e))

    def test_auto_entry_clear_case_passes(self):
        a = art(signal="Buy", text=self.TXT)
        self.assertEqual(self.v(intent(
            watch_mode="AUTO_ENTRY", classification="ACTIONABLE_NOW",
            auto_execution_authorized=True), a), [])

    def test_malformed_rejected(self):
        a = art(signal="Buy", text=self.TXT)
        self.assertTrue(self.v({"ticker": "X"}, a))
        self.assertTrue(self.v(intent(classification="MAYBE"), a))

    def test_ambiguity_fails_closed(self):
        a = art(signal="Buy", text=self.TXT)
        self.assertTrue(self.v(intent(ambiguity="conflicting triggers"), a))

    def test_news_gated_trigger_needs_reanalysis_mode(self):
        a = art(signal="Sell", text=self.TXT)
        e = self.v(intent(trigger="enter after catalyst check above 70"), a)
        self.assertTrue(any("REANALYZE" in x for x in e))
        self.assertEqual(self.v(intent(
            watch_mode="REANALYZE_ON_TRIGGER",
            classification="REANALYZE_ON_TRIGGER",
            trigger="enter after catalyst check above 70"), a), [])

    def test_scaled_volume_and_word_fractions(self):
        a = art(signal="Sell", text="breakout needs 1.5 million shares; "
                                    "quarter size entry at 70")
        i = intent(params={"vol_min": 1500000}, size_frac=0.25,
                   stop_level=None, trigger="vol>1.5M close>70")
        self.assertEqual(self.v(i, a), [])
        self.assertTrue(self.v(intent(size_frac=0.9, stop_level=None), a))

    def test_reject_intent_needs_no_watch(self):
        a = art(signal="Sell", text="no setup")
        self.assertEqual(self.v(intent(
            classification="REJECT", watch_mode="NONE", trigger=None,
            params=None, stop_level=None, size_frac=None), a), [])


class RunTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        sz.EV = self.tmp
        (self.tmp / "case_artifacts").mkdir()

    def _seed(self, ticker, signal="Sell", text="zone 8.00-8.20; stop 7.75"):
        p = self.tmp / "case_artifacts" / f"{ticker}_2099-01-01.json"
        p.write_text(json.dumps(art(ticker, signal, text)))

    def test_run_persists_intents_and_resumes_without_recall(self):
        self._seed("AAA"); self._seed("BBB")
        fake = [intent(ticker="AAA", params={"zone": [8.0, 8.2]},
                       stop_level=7.75, trigger="zone 8.00-8.20"),
                intent(ticker="BBB", ambiguity="x")]
        with mock.patch.object(sz, "synthesize", return_value=fake) as syn:
            d = sz.run("2099-01-01")
        self.assertEqual(d["validated"], ["AAA"])
        self.assertEqual([r["ticker"] for r in d["review_required"]], ["BBB"])
        # crash/restart: intents cached -> no second bridge call
        with mock.patch.object(sz, "synthesize") as syn2:
            sz.run("2099-01-01")
        syn2.assert_not_called()


if __name__ == "__main__":
    unittest.main()
