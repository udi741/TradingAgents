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


class NumberNormalizationTest(unittest.TestCase):
    """Evidence binding must match the text's OWN units: '5%' must satisfy a
    0.05 intent field, '$83k' must satisfy 83000, '1.7-3.0M' must satisfy
    1700000. Prior gap produced false 'unsupported number' violations."""

    def test_percent_and_scaled_literals(self):
        n = sz._nums_in_text("starter ~5-8% of portfolio; cap 2.5%; "
                             "1.0%-1.25% band; 6%-daily-ATR")
        for x in (0.05, 0.08, 0.025, 0.01, 0.0125, 0.06):
            self.assertIn(round(x, 6), n, x)
        n = sz._nums_in_text("BTC reclaims $83k; 1.7-3.0 million-share baseline")
        self.assertIn(83000.0, n)
        self.assertIn(1700000.0, n)
        self.assertIn(3000000.0, n)

    def test_percent_size_passes_validation(self):
        a = art(signal="Sell",
                text="buy the dip at 60-62 only on a volume-backed reclaim; "
                     "size ~5-8% of portfolio; stop 55.90")
        i = intent(size_frac=None, params={"zone": [60.0, 62.0],
                                           "size_pct": [0.05, 0.08]})
        self.assertEqual(sz.validate(i, a), [])

    def test_truly_absent_number_still_rejected(self):
        a = art(signal="Sell", text="watch 60-62; stop 55.90")
        i = intent(params={"zone": [60.0, 62.0], "mystery": 0.37})
        self.assertIn("unsupported number 0.37", sz.validate(i, a))


class DispositionTest(unittest.TestCase):
    """Normal ambiguity -> deterministic non-executable class, never ACTION."""
    def _i(self, **kw):
        return intent(**kw)

    def test_contradictory_is_ambiguous_rejected(self):
        d = sz.disposition(self._i(), ["ambiguous: sizing 2% vs 3%"], set())
        self.assertEqual(d, "AMBIGUOUS_REJECTED")

    def test_news_gated_is_reanalyze(self):
        d = sz.disposition(self._i(),
                           ["event/news-gated trigger must be REANALYZE_ON_TRIGGER"],
                           set())
        self.assertEqual(d, "REANALYZE_ON_TRIGGER")

    def test_no_risk_plan_is_blocked(self):
        i = self._i(stop_level=None, invalidation="no stop stated",
                    watch_mode="AUTO_ENTRY")
        d = sz.disposition(i, ["some structural issue"], set())
        self.assertEqual(d, "RISK_PLAN_REQUIRED")

    def test_held_position_is_management(self):
        d = sz.disposition(self._i(ticker="SDGR"),
                           ["ambiguous: x"], {"SDGR"})
        self.assertEqual(d, "OPEN_POSITION_MANAGEMENT")

    def test_clean_is_executable(self):
        self.assertEqual(sz.disposition(self._i(), [], set()), "EXECUTABLE_WATCH")

    def test_reject_is_no_action(self):
        i = self._i(classification="REJECT")
        self.assertEqual(sz.disposition(i, ["bad watch_mode"], set()), "NO_ACTION")

    def test_validated_but_inert_is_not_executable(self):
        # complete prose plan but params carry no monitor-evaluable trigger key
        i = self._i(params={"primary_limit": 197.5}, trigger_type=None)
        self.assertEqual(sz.disposition(i, [], set()), "PUBLISHED_NON_EXECUTABLE")

    def test_reanalyze_intent_maps_to_reanalyze(self):
        i = self._i(classification="REANALYZE_ON_TRIGGER",
                    watch_mode="REANALYZE_ON_TRIGGER")
        self.assertEqual(sz.disposition(i, [], set()), "REANALYZE_ON_TRIGGER")

    def test_machine_trigger_and_plan_is_executable(self):
        # params contain a real monitor key (zone) + typed stop
        self.assertEqual(sz.disposition(self._i(), [], set()), "EXECUTABLE_WATCH")
