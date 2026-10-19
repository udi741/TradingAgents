"""Reuse engine tests — mocks/fixtures only; no model or provider calls."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from alpha_rnd import reuse_engine, savings_report
from alpha_rnd.case_integrity import seal_case, verify_case

PRIOR = "2026-10-15"
SESSION = "2026-10-16"


def _complete_coverage():
    return {f: {"status": "COMPLETE"} for f in (
        "filings", "earnings_or_guidance", "news", "social",
        "market_sector", "price_technical", "corporate_events")}


def _probe(**updates):
    probe = {
        "ticker": "TEST", "prior_cutoff": PRIOR, "current_session": SESSION,
        "filings": [], "earnings_or_guidance": [], "news": [],
        "unclassified_news": [], "corporate_events": [],
        "price_technical": {"close": 100.0, "prior_close": 100.0,
                            "price_change_pct": 0.0},
        "social": {"item_count": 0}, "market_sector": {"item_count": 0},
        "coverage": _complete_coverage(), "classification": "REUSE",
        "reasons": [], "provider_call_count": 6, "direct_provider_calls": 3,
        "cache_hits": 0, "known_external_network_calls": 3,
        "external_network_quality": "MEASURED", "elapsed_ms": 40.0,
        "swe_calls": 0, "fetch_errors": [],
    }
    probe.update(updates)
    return probe


def _prior_artifact(signal="Hold", pm="Hold", sealed=True):
    artifact = {
        "ticker": "TEST", "decision_session": PRIOR,
        "signal": signal, "pm_rating": pm, "rm_rating": "Market Weight",
        "trader_action": signal,
        "information_cutoff": PRIOR,
        "market_report": "OLD MARKET REPORT PAYLOAD",
        "news_report": "old news",
        "fundamentals_report": "old fundamentals",
        "final_trade_decision": "Thesis: steady compounder, hold.",
        "risk_judge_decision": "Risk: moderate.",
        "provider_metadata": {"price_technical": {"close": 100.0}},
        "analysis_metrics": {"wall_clock": {"elapsed_ms": 300000},
                             "model_calls": {"total": 10},
                             "provider_calls": {"logical_data_calls": 14},
                             "tokens": {"availability": "UNAVAILABLE"}},
    }
    return seal_case(artifact) if sealed else artifact


class EngineFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.case_dir = root / "case_artifacts"
        self.case_dir.mkdir()
        self.facts_dir = root / "facts"
        self.facts_dir.mkdir()
        self.validation_dir = root / "validation"
        for session in (PRIOR, SESSION):
            (self.facts_dir / f"fundamental_facts_{session}.json").write_text(
                json.dumps({"TEST": {"facts": {"revenue": {"last_filed": "2026-08-01",
                                                           "value": 1}}}}))

    def _write_prior(self, signal="Hold", pm="Hold", sealed=True):
        (self.case_dir / f"TEST_{PRIOR}.json").write_text(
            json.dumps(_prior_artifact(signal, pm, sealed)))

    def _decide(self, probe=None):
        self._write_prior()
        return reuse_engine.decide(
            "TEST", SESSION, case_dir=self.case_dir, facts_dir=self.facts_dir,
            probe_fn=lambda *a, **k: probe or _probe())

    def _full_run(self, calls=None, signal="Hold", metrics=None):
        def run(ticker, date, out_name=None, **kwargs):
            if calls is not None:
                calls.append(out_name)
            artifact = _prior_artifact(signal=signal, sealed=False)
            artifact["decision_session"] = date
            artifact["analysis_metrics"] = metrics or {
                "wall_clock": {"elapsed_ms": 300000},
                "model_calls": {"total": 10},
                "provider_calls": {"logical_data_calls": 14},
                "tokens": {"availability": "UNAVAILABLE",
                           "input_tokens": None, "output_tokens": None,
                           "total_tokens": None}}
            path = self.case_dir / (out_name or f"{ticker}_{date}.json")
            artifact = seal_case(artifact)
            path.write_text(json.dumps(artifact, indent=1))
            return artifact
        return run

    def _optimized(self, probe=None, llm_fn=None, signal="Hold", pm="Hold"):
        self._write_prior(signal=signal, pm=pm)
        calls = []
        artifact = reuse_engine.run_optimized(
            "TEST", SESSION, full_run=self._full_run(calls),
            case_dir=self.case_dir, facts_dir=self.facts_dir,
            probe_fn=lambda *a, **k: probe or _probe(), llm_fn=llm_fn,
            artifact_path=self.case_dir / f"TEST_{SESSION}.optimized.json")
        return artifact, calls


# ----------------------------------------------------------------- selection

class ModeSelection(EngineFixture):
    def test_first_time_is_full_refresh(self):
        decision = reuse_engine.decide(
            "TEST", SESSION, case_dir=self.case_dir, facts_dir=self.facts_dir,
            probe_fn=lambda *a, **k: _probe())
        self.assertEqual(decision["mode"], "FULL_REFRESH")
        self.assertIn("PRIOR_CASE_MISSING", decision["reasons"])

    def test_invalid_prior_integrity_full_refresh(self):
        artifact = _prior_artifact()
        artifact["signal"] = "Sell"  # tamper after sealing
        (self.case_dir / f"TEST_{PRIOR}.json").write_text(json.dumps(artifact))
        decision = reuse_engine.decide(
            "TEST", SESSION, case_dir=self.case_dir, facts_dir=self.facts_dir,
            probe_fn=lambda *a, **k: _probe())
        self.assertEqual(decision["mode"], "FULL_REFRESH")
        self.assertIn("PRIOR_CASE_INTEGRITY_INVALID", decision["reasons"])

    def test_legacy_unsealed_prior_full_refresh(self):
        self._write_prior(sealed=False)
        decision = reuse_engine.decide(
            "TEST", SESSION, case_dir=self.case_dir, facts_dir=self.facts_dir,
            probe_fn=lambda *a, **k: _probe())
        self.assertEqual(decision["mode"], "FULL_REFRESH")
        self.assertIn("PRIOR_CASE_INTEGRITY_MISSING", decision["reasons"])

    def test_incomplete_coverage_full_refresh(self):
        probe = _probe()
        probe["coverage"]["news"] = {"status": "PARTIAL"}
        self.assertEqual(self._decide(probe)["mode"], "FULL_REFRESH")

    def test_new_filings_full_refresh(self):
        for form in ("10-Q", "10-K", "8-K", "6-K", "20-F", "40-F"):
            with self.subTest(form=form):
                probe = _probe(filings=[{"form": form, "filed_at": SESSION}])
                decision = self._decide(probe)
                self.assertEqual(decision["mode"], "FULL_REFRESH")
                self.assertIn("NEW_FILING", decision["reasons"])

    def test_earnings_full_refresh(self):
        decision = self._decide(_probe(
            earnings_or_guidance=[{"title": "Company raises guidance"}]))
        self.assertEqual(decision["mode"], "FULL_REFRESH")
        self.assertIn("EARNINGS_OR_GUIDANCE", decision["reasons"])

    def test_corporate_event_full_refresh(self):
        decision = self._decide(_probe(
            corporate_events=[{"title": "Company announces merger"}]))
        self.assertEqual(decision["mode"], "FULL_REFRESH")
        self.assertIn("CORPORATE_EVENT", decision["reasons"])

    def test_material_price_move_full_refresh(self):
        probe = _probe()
        probe["price_technical"]["price_change_pct"] = 5.2
        decision = self._decide(probe)
        self.assertEqual(decision["mode"], "FULL_REFRESH")
        self.assertIn("MATERIAL_PRICE_MOVE", decision["reasons"])

    def test_probe_exception_full_refresh(self):
        self._write_prior()
        def boom(*a, **k):
            raise RuntimeError("probe exploded")
        decision = reuse_engine.decide(
            "TEST", SESSION, case_dir=self.case_dir, facts_dir=self.facts_dir,
            probe_fn=boom)
        self.assertEqual(decision["mode"], "FULL_REFRESH")
        self.assertIn("DELTA_PROBE_FAILED", decision["reasons"])

    def test_ordinary_news_update(self):
        decision = self._decide(_probe(
            news=[{"title": "Routine product note"}],
            unclassified_news=[{"title": "Routine product note"}]))
        self.assertEqual(decision["mode"], "UPDATE")
        self.assertIn("NEWS_DELTA", decision["delta_reasons"])

    def test_moderate_price_delta_update(self):
        probe = _probe()
        probe["price_technical"]["price_change_pct"] = 2.4
        decision = self._decide(probe)
        self.assertEqual(decision["mode"], "UPDATE")
        self.assertIn("PRICE_TECHNICAL_DELTA", decision["delta_reasons"])

    def test_social_and_market_delta_update(self):
        for key, reason in (("social", "SOCIAL_DELTA"),
                            ("market_sector", "MARKET_SECTOR_DELTA")):
            with self.subTest(key=key):
                probe = _probe(**{key: {"item_count": 3}})
                decision = self._decide(probe)
                self.assertEqual(decision["mode"], "UPDATE")
                self.assertIn(reason, decision["delta_reasons"])

    def test_no_material_delta_reuse(self):
        decision = self._decide()
        self.assertEqual(decision["mode"], "REUSE")
        self.assertEqual(decision["reasons"], [])

    def test_missing_stable_facts_full_refresh(self):
        (self.facts_dir / f"fundamental_facts_{SESSION}.json").unlink()
        decision = self._decide()
        self.assertEqual(decision["mode"], "FULL_REFRESH")
        self.assertIn("STABLE_FACTS_UNKNOWN", decision["reasons"])

    def test_prior_too_old_full_refresh(self):
        self._write_prior()
        decision = reuse_engine.decide(
            "TEST", SESSION, case_dir=self.case_dir, facts_dir=self.facts_dir,
            probe_fn=lambda *a, **k: _probe(), age_limit_days=0)
        self.assertEqual(decision["mode"], "FULL_REFRESH")
        self.assertIn("PRIOR_CASE_TOO_OLD", decision["reasons"])


# ------------------------------------------------------------ execution safety

class ExecutionSafety(EngineFixture):
    def test_prior_sell_reuse_allowed(self):
        decision = self._decide()
        self.assertEqual(decision["mode"], "REUSE")
        artifact, calls = self._optimized(signal="Sell")
        self.assertEqual(artifact["signal"], "Sell")
        self.assertEqual(calls, [])

    def test_prior_hold_reuse_allowed(self):
        artifact, calls = self._optimized(signal="Hold")
        self.assertEqual(artifact["signal"], "Hold")
        self.assertEqual(calls, [])

    def test_prior_buy_upgrades_reuse_to_update(self):
        llm_calls = []
        artifact, calls = self._optimized(
            signal="Buy", pm="Buy",
            llm_fn=lambda p: llm_calls.append(p) or _update_text("HOLD"))
        self.assertEqual(artifact["reuse_execution"]["mode"], "UPDATE")
        self.assertIn("REUSE_UPGRADED_EXECUTABLE_BUY",
                      artifact["reuse_execution"]["delta_reasons"])
        self.assertEqual(len(llm_calls), 1)
        self.assertEqual(calls, [])

    def test_update_buy_without_plan_falls_back(self):
        artifact, calls = self._optimized(
            probe=_probe(news=[{"title": "n"}],
                         unclassified_news=[{"title": "n"}]),
            llm_fn=lambda p: _update_text("BUY", plan=False))
        self.assertTrue(artifact["reuse_execution"]["fallback_to_full_refresh"])
        self.assertEqual(len(calls), 1)
        self.assertEqual(artifact["reuse_execution"]["mode"], "FULL_REFRESH")

    def test_update_buy_with_valid_plan(self):
        artifact, calls = self._optimized(
            probe=_probe(news=[{"title": "n"}],
                         unclassified_news=[{"title": "n"}]),
            llm_fn=lambda p: _update_text("BUY", plan=True))
        self.assertFalse(artifact["reuse_execution"]["fallback_to_full_refresh"])
        self.assertEqual(calls, [])
        plan = artifact["success_plan"]
        self.assertTrue(plan["base_case_top"] > artifact["entry_basis"])
        self.assertGreater(plan["expected_reward_to_risk"], 0)


def _update_text(signal, plan=False, refresh="NO", thesis_status="UNCHANGED"):
    lines = [
        f"THESIS_STATUS: {thesis_status}",
        f"FULL_REFRESH_REQUIRED: {refresh}",
        f"SIGNAL: {signal}",
        "RATING: Hold",
        "UPDATED_THESIS: delta reviewed; thesis unchanged.",
        "HORIZON: UNCHANGED",
        "PRICE_TARGET: UNCHANGED",
    ]
    if plan:
        lines += [
            "ENTRY_BASIS: 100.0", "FAILURE_LEVEL: 90.0",
            "BASE_OBJECTIVE: 120.0", "EXPECTED_UPSIDE_PCT: 20",
            "EXPECTED_RR: 2.0", "SUCCESS_CRITERIA: breakout holds",
            "PROFIT_PLAN: scale out at objective",
        ]
    return "\n".join(lines)


# ----------------------------------------------------------------- UPDATE path

class UpdatePath(EngineFixture):
    def _news_probe(self):
        return _probe(news=[{"title": "Routine product note",
                             "published_at": "2026-10-16T10:00:00Z"}],
                      unclassified_news=[{"title": "Routine product note"}])

    def test_prior_thesis_in_prompt(self):
        prompts = []
        self._optimized(probe=self._news_probe(),
                        llm_fn=lambda p: prompts.append(p) or _update_text("HOLD"))
        self.assertIn("steady compounder", prompts[0])
        self.assertIn("PREVIOUS", prompts[0].upper())

    def test_old_provider_payloads_excluded(self):
        prompts = []
        self._optimized(probe=self._news_probe(),
                        llm_fn=lambda p: prompts.append(p) or _update_text("HOLD"))
        self.assertNotIn("OLD MARKET REPORT PAYLOAD", prompts[0])

    def test_only_delta_evidence_included(self):
        prompts = []
        self._optimized(probe=self._news_probe(),
                        llm_fn=lambda p: prompts.append(p) or _update_text("HOLD"))
        self.assertIn("Routine product note", prompts[0])

    def test_update_requests_full_refresh(self):
        artifact, calls = self._optimized(
            probe=self._news_probe(),
            llm_fn=lambda p: _update_text("HOLD", refresh="YES"))
        self.assertTrue(artifact["reuse_execution"]["fallback_to_full_refresh"])
        self.assertEqual(len(calls), 1)

    def test_update_exception_full_refresh(self):
        def boom(prompt):
            raise RuntimeError("bridge down")
        artifact, calls = self._optimized(probe=self._news_probe(), llm_fn=boom)
        self.assertTrue(artifact["reuse_execution"]["fallback_to_full_refresh"])
        self.assertEqual(len(calls), 1)

    def test_invalidated_thesis_full_refresh(self):
        artifact, calls = self._optimized(
            probe=self._news_probe(),
            llm_fn=lambda p: _update_text("SELL", thesis_status="INVALIDATED"))
        self.assertTrue(artifact["reuse_execution"]["fallback_to_full_refresh"])
        self.assertEqual(len(calls), 1)

    def test_successful_update_no_full_graph(self):
        artifact, calls = self._optimized(
            probe=self._news_probe(), llm_fn=lambda p: _update_text("HOLD"))
        self.assertEqual(calls, [])
        self.assertEqual(artifact["analysis_metrics"]["model_calls"]["total"], 1)
        self.assertEqual(artifact["signal"], "Hold")
        self.assertEqual(artifact["update_reasoning"]["thesis_status"], "UNCHANGED")


# ------------------------------------------------------------------ REUSE path

class ReusePath(EngineFixture):
    def test_reuse_zero_model_calls(self):
        artifact, calls = self._optimized()
        self.assertEqual(calls, [])
        self.assertEqual(artifact["analysis_metrics"]["model_calls"]["total"], 0)

    def test_reuse_no_full_graph(self):
        artifact, calls = self._optimized()
        self.assertEqual(artifact["reuse_execution"]["mode"], "REUSE")
        self.assertIn("full_graph", artifact["reuse_execution"]["work_skipped"])

    def test_reused_fields_identify_source(self):
        artifact, _ = self._optimized()
        self.assertEqual(artifact["source_session"], PRIOR)
        self.assertEqual(artifact["data_as_of"], SESSION)
        self.assertTrue(artifact["reused_fields"]["signal"]["reused"])
        self.assertEqual(
            artifact["reused_fields"]["signal"]["source_session"], PRIOR)
        self.assertEqual(
            artifact["provider_metadata"]["reused_from_session"], PRIOR)


# ------------------------------------------------------------------ FULL path

class FullPath(EngineFixture):
    def test_full_refresh_invokes_graph_once(self):
        artifact, calls = self._optimized(probe=_probe(
            filings=[{"form": "8-K", "filed_at": SESSION}]))
        self.assertEqual(calls, [f"TEST_{SESSION}.optimized.json"])
        self.assertEqual(artifact["reuse_execution"]["mode"], "FULL_REFRESH")

    def test_full_refresh_reasons_recorded(self):
        artifact, _ = self._optimized(probe=_probe(
            earnings_or_guidance=[{"title": "guidance raised"}]))
        self.assertIn("EARNINGS_OR_GUIDANCE",
                      artifact["reuse_execution"]["decision_reasons"])


# ----------------------------------------------------------------- integrity

class Integrity(EngineFixture):
    def test_optimized_artifact_verifies(self):
        artifact, _ = self._optimized(
            probe=_probe(news=[{"title": "n"}], unclassified_news=[{"title": "n"}]),
            llm_fn=lambda p: _update_text("HOLD"))
        self.assertTrue(verify_case(artifact))
        artifact, _ = self._optimized()
        self.assertTrue(verify_case(artifact))

    def test_modifying_reuse_execution_invalidates(self):
        artifact, _ = self._optimized()
        artifact["reuse_execution"]["mode"] = "UPDATE"
        self.assertFalse(verify_case(artifact))

    def test_modifying_updated_thesis_invalidates(self):
        artifact, _ = self._optimized(
            probe=_probe(news=[{"title": "n"}], unclassified_news=[{"title": "n"}]),
            llm_fn=lambda p: _update_text("HOLD"))
        artifact["update_reasoning"]["updated_thesis"] = "tampered"
        self.assertFalse(verify_case(artifact))


# ---------------------------------------------------------- paired validation

class PairedValidation(EngineFixture):
    def _pair(self, probe=None, llm_fn=None, baseline_signal="Hold",
              baseline_metrics=None):
        self._write_prior()
        return reuse_engine.run_validated_pair(
            "TEST", SESSION, full_run=self._full_run(
                signal=baseline_signal, metrics=baseline_metrics),
            case_dir=self.case_dir, facts_dir=self.facts_dir,
            probe_fn=lambda *a, **k: probe or _probe(), llm_fn=llm_fn,
            validation_dir=self.validation_dir)

    def test_isolation_and_baseline_authority(self):
        baseline = self._pair()
        canonical = json.loads(
            (self.case_dir / f"TEST_{SESSION}.json").read_text())
        optimized = json.loads(
            (self.case_dir / f"TEST_{SESSION}.optimized.json").read_text())
        self.assertEqual(canonical["decision_session"], SESSION)
        self.assertNotEqual(canonical, optimized)
        self.assertEqual(optimized["reuse_execution"]["mode"], "REUSE")
        record = json.loads(
            (self.validation_dir / f"TEST_{SESSION}.json").read_text())
        self.assertEqual(record["authority"], "FULL_REFRESH_BASELINE")
        self.assertIs(baseline, baseline)

    def test_full_refresh_pair_no_duplicate_spend(self):
        calls = []
        self._write_prior()
        reuse_engine.run_validated_pair(
            "TEST", SESSION, full_run=self._full_run(calls),
            case_dir=self.case_dir, facts_dir=self.facts_dir,
            probe_fn=lambda *a, **k: _probe(
                filings=[{"form": "10-Q", "filed_at": SESSION}]),
            validation_dir=self.validation_dir)
        self.assertEqual(calls, [f"TEST_{SESSION}.json"])
        self.assertFalse(
            (self.case_dir / f"TEST_{SESSION}.optimized.json").exists())

    def test_agreement_classified(self):
        self._pair()
        record = json.loads(
            (self.validation_dir / f"TEST_{SESSION}.json").read_text())
        self.assertTrue(record["signal_agreement"])
        self.assertFalse(record["executable_disagreement"])

    def test_signal_disagreement_detected(self):
        self._pair(baseline_signal="Sell")
        record = json.loads(
            (self.validation_dir / f"TEST_{SESSION}.json").read_text())
        self.assertFalse(record["signal_agreement"])
        self.assertFalse(record["executable_disagreement"])  # both no-entry

    def test_executable_disagreement_detected(self):
        self._pair(baseline_signal="Buy")
        record = json.loads(
            (self.validation_dir / f"TEST_{SESSION}.json").read_text())
        self.assertTrue(record["executable_disagreement"])

    def test_savings_math(self):
        self._pair()
        record = json.loads(
            (self.validation_dir / f"TEST_{SESSION}.json").read_text())
        s = record["savings"]
        self.assertEqual(s["model_calls_avoided"], 10)
        self.assertEqual(s["provider_calls_avoided"], 14 - 6)
        self.assertEqual(s["quality"]["model_calls_avoided"], "MEASURED")
        self.assertEqual(s["tokens"]["availability"], "UNAVAILABLE")

    def test_update_pair_measured(self):
        self._pair(
            probe=_probe(news=[{"title": "n"}],
                         unclassified_news=[{"title": "n"}]),
            llm_fn=lambda p: _update_text("HOLD"))
        record = json.loads(
            (self.validation_dir / f"TEST_{SESSION}.json").read_text())
        self.assertEqual(record["optimized_mode"], "UPDATE")
        self.assertEqual(record["savings"]["model_calls_avoided"], 9)


# ---------------------------------------------------------------- rollout gate

class RolloutGate(EngineFixture):
    def _record(self, ticker, session, mode="UPDATE", disagreement=False,
                missed=False, model_avoided=8, time_saved=1000):
        (self.validation_dir).mkdir(exist_ok=True)
        clean_evidence = {"filings": [], "earnings_or_guidance": [],
                          "corporate_events": [], "price_change_pct": 0.5,
                          "coverage": {f: {"status": "COMPLETE"} for f in (
                              "filings", "earnings_or_guidance", "news",
                              "social", "market_sector", "price_technical",
                              "corporate_events")},
                          "prior_integrity_valid": True}
        if missed:
            clean_evidence["filings"] = [{"form": "8-K"}]
        rec = {"ticker": ticker, "session": session, "optimized_mode": mode,
               "executable_disagreement": disagreement,
               "probe_evidence": clean_evidence,
               "decision_reasons": [],
               "fallback_to_full_refresh": False,
               "savings": {"model_calls_avoided": model_avoided,
                           "time_saved_ms": time_saved,
                           "quality": {"model_calls_avoided": "MEASURED",
                                       "time_saved_ms": "MEASURED"}}}
        (self.validation_dir / f"{ticker}_{session}.json").write_text(
            json.dumps(rec))

    def test_insufficient_sample_no(self):
        self._record("AAA", SESSION)
        gate = reuse_engine.evaluate_readiness(self.validation_dir)
        self.assertEqual(gate["ready_for_optimized_authority"], "NO")

    def test_unsafe_disagreement_no(self):
        for i, t in enumerate(("AAA", "BBB", "CCC", "DDD", "EEE")):
            self._record(t, SESSION, disagreement=(i == 0))
        gate = reuse_engine.evaluate_readiness(self.validation_dir)
        self.assertEqual(gate["ready_for_optimized_authority"], "NO")

    def test_missed_refresh_trigger_no(self):
        for i, t in enumerate(("AAA", "BBB", "CCC", "DDD", "EEE")):
            self._record(t, SESSION, missed=(i == 0))
        gate = reuse_engine.evaluate_readiness(self.validation_dir)
        self.assertEqual(gate["ready_for_optimized_authority"], "NO")

    def test_valid_sample_yes(self):
        for t in ("AAA", "BBB", "CCC", "DDD", "EEE"):
            self._record(t, SESSION)
        gate = reuse_engine.evaluate_readiness(self.validation_dir)
        self.assertEqual(gate["ready_for_optimized_authority"], "YES")
        self.assertFalse(gate["auto_enable"])

    def test_gate_never_enables(self):
        gate = reuse_engine.evaluate_readiness(self.validation_dir)
        self.assertFalse(gate["auto_enable"])
        self.assertEqual(os.getenv("ALPHA_REUSE_ENGINE") or "OFF", "OFF")


# --------------------------------------------------------------- misc config

class Config(EngineFixture):
    def test_default_off(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ALPHA_REUSE_ENGINE", None)
            self.assertEqual(reuse_engine.engine_mode(), "OFF")

    def test_bad_value_off(self):
        with mock.patch.dict(os.environ, {"ALPHA_REUSE_ENGINE": "bogus"}):
            self.assertEqual(reuse_engine.engine_mode(), "OFF")

    def test_validate_max_pairs(self):
        with mock.patch.dict(os.environ, {"ALPHA_REUSE_MAX_PAIRS": "3"}):
            self.assertEqual(reuse_engine.max_validation_pairs(), 3)


if __name__ == "__main__":
    unittest.main()


# ------------------------------------------------ artifact consistency (fix 1)

class ArtifactConsistency(EngineFixture):
    def _update_artifact(self, signal="Sell", prior_signal="Hold", prior_pm="Hold",
                         **probe_kw):
        return self._optimized(
            signal=prior_signal, pm=prior_pm,
            probe=_probe(news=[{"title": "n"}],
                         unclassified_news=[{"title": "n"}], **probe_kw),
            llm_fn=lambda p: _update_text(signal))

    def test_signal_change_cannot_leave_stale_trader_action(self):
        artifact, _ = self._update_artifact("Sell")
        self.assertEqual(artifact["signal"], "Sell")
        self.assertEqual(artifact["trader_action"], "Sell")

    def test_current_decision_text_is_fresh_not_prior(self):
        artifact, _ = self._update_artifact("Sell")
        self.assertIn("INCREMENTAL UPDATE", artifact["final_trade_decision"])
        self.assertNotIn("steady compounder, hold.",
                         artifact["final_trade_decision"])
        # prior decision preserved only in the labelled archive
        self.assertIn("steady compounder",
                      artifact["prior_case_decision"]["final_trade_decision"])
        self.assertTrue(artifact["prior_case_decision"]["reused"])

    def test_prior_buy_to_sell_has_no_stale_executable_semantics(self):
        artifact, _ = self._update_artifact(
            "Sell", prior_signal="Buy", prior_pm="Buy")
        self.assertEqual(artifact["signal"], "Sell")
        for field in ("success_plan", "entry_basis", "stop_level"):
            self.assertNotIn(field, artifact)

    def test_optimized_duration_is_current(self):
        prior = _prior_artifact()
        prior["duration_s"] = 300.0
        prior["final_state_hash"] = "stale-hash"
        (self.case_dir / f"TEST_{PRIOR}.json").write_text(
            json.dumps(seal_case(prior)))
        artifact, _ = self._optimized()
        self.assertLess(artifact["duration_s"], 10)
        self.assertNotEqual(artifact["final_state_hash"], "stale-hash")
        self.assertTrue(verify_case(artifact))


# ------------------------------------------------------------------ cutoff chain

DAY3 = "2026-10-19"


class CutoffChain(EngineFixture):
    def _day2_optimized_canonical(self, probe=None, llm_fn=None):
        """ENABLED-style write: optimized artifact under the canonical name."""
        self._write_prior()
        return reuse_engine.run_optimized(
            "TEST", SESSION, full_run=self._full_run([]),
            case_dir=self.case_dir, facts_dir=self.facts_dir,
            probe_fn=lambda *a, **k: probe or _probe(), llm_fn=llm_fn,
            artifact_path=self.case_dir / f"TEST_{SESSION}.json")

    def test_day3_resolves_day2_cutoff(self):
        self._day2_optimized_canonical()
        (self.facts_dir / f"fundamental_facts_{DAY3}.json").write_text(
            json.dumps({"TEST": {"facts": {"revenue": {"last_filed": "2026-08-01",
                                                     "value": 1}}}}))
        captured = {}
        def spy(t, cutoff, s, **k):
            captured["cutoff"] = cutoff
            p = _probe(prior_cutoff=cutoff, current_session=s)
            return p
        decision = reuse_engine.decide(
            "TEST", DAY3, case_dir=self.case_dir, facts_dir=self.facts_dir,
            probe_fn=spy)
        self.assertEqual(decision["prior_case"]["session"], SESSION)
        self.assertEqual(captured["cutoff"], SESSION)  # not Day-1 PRIOR
        self.assertEqual(decision["mode"], "REUSE")

    def test_merged_coverage_cannot_overclaim(self):
        artifact = self._day2_optimized_canonical()
        self.assertEqual(
            artifact["provider_metadata"]["coverage"],
            _probe()["coverage"])
        self.assertEqual(
            artifact["provider_metadata"]["information_cutoff"]["value"], SESSION)

    def test_metadata_distinguishes_reused_vs_gap_evidence(self):
        artifact = self._day2_optimized_canonical()
        meta = artifact["provider_metadata"]
        self.assertEqual(meta["reused_from_session"], PRIOR)
        self.assertIn("NOT refetched", meta["note"])
        self.assertTrue(
            artifact["reused_fields"]["market_report"]["reused"])


# ------------------------------------------------------------------ validation

class ValidationIsolation(EngineFixture):
    def test_fallback_invokes_full_graph_exactly_once(self):
        calls = []
        self._write_prior()
        baseline = reuse_engine.run_validated_pair(
            "TEST", SESSION, full_run=self._full_run(calls),
            case_dir=self.case_dir, facts_dir=self.facts_dir,
            probe_fn=lambda *a, **k: _probe(
                news=[{"title": "n"}], unclassified_news=[{"title": "n"}]),
            llm_fn=lambda p: _update_text("HOLD", refresh="YES"),
            validation_dir=self.validation_dir)
        # One canonical baseline run; no research full graph.
        self.assertEqual(calls, [f"TEST_{SESSION}.json"])
        record = json.loads(
            (self.validation_dir / f"TEST_{SESSION}.json").read_text())
        self.assertTrue(record["fallback_to_full_refresh"])
        stub = json.loads(
            (self.case_dir / f"TEST_{SESSION}.optimized.json").read_text())
        self.assertTrue(stub["optimized_aborted"])

    def test_optimized_never_writes_canonical(self):
        self._write_prior()
        reuse_engine.run_validated_pair(
            "TEST", SESSION, full_run=self._full_run([]),
            case_dir=self.case_dir, facts_dir=self.facts_dir,
            probe_fn=lambda *a, **k: _probe(),
            validation_dir=self.validation_dir)
        canonical = json.loads(
            (self.case_dir / f"TEST_{SESSION}.json").read_text())
        self.assertNotIn("reuse_execution", canonical)
        self.assertNotIn("reused_fields", canonical)

    def test_cache_isolation_or_downgrade(self):
        # Real cache dir -> isolated legs -> timing stays MEASURED.
        cache = Path(self.tmp.name) / "cache"
        cache.mkdir()
        (cache / "seed.json").write_text("{}")
        self._write_prior()
        reuse_engine.run_validated_pair(
            "TEST", SESSION, full_run=self._full_run([]),
            case_dir=self.case_dir, facts_dir=self.facts_dir,
            probe_fn=lambda *a, **k: _probe(),
            validation_dir=self.validation_dir, cache_dir=cache)
        record = json.loads(
            (self.validation_dir / f"TEST_{SESSION}.json").read_text())
        self.assertTrue(record["cache_isolation"])
        # No cache dir -> cannot isolate -> time savings must not be MEASURED.
        (self.validation_dir / f"TEST_{SESSION}.json").unlink()
        reuse_engine.run_validated_pair(
            "TEST", SESSION, full_run=self._full_run([]),
            case_dir=self.case_dir, facts_dir=self.facts_dir,
            probe_fn=lambda *a, **k: _probe(),
            validation_dir=self.validation_dir,
            cache_dir=Path(self.tmp.name) / "missing_cache")
        record = json.loads(
            (self.validation_dir / f"TEST_{SESSION}.json").read_text())
        self.assertFalse(record["cache_isolation"])
        self.assertNotEqual(
            record["savings"]["quality"]["time_saved_ms"], "MEASURED")
        self.assertEqual(
            record["savings"]["quality"]["model_calls_avoided"], "MEASURED")


# ------------------------------------------------------------------ comparison

class Comparison(unittest.TestCase):
    def _art(self, signal="Hold", pm="Market Weight", rm="Market Weight",
             trader="HOLD", plan=None):
        artifact = {"signal": signal, "pm_rating": pm, "rm_rating": rm,
                    "trader_action": trader}
        if plan:
            artifact.update(plan)
        return artifact

    def test_hold_vs_sell_research_disagreement_executable_agreement(self):
        cmp = reuse_engine.compare_decisions(
            self._art(), self._art(signal="Sell", trader="SELL"))
        self.assertTrue(cmp["research_disagreement"])
        self.assertTrue(cmp["executable_action_agreement"])
        self.assertFalse(cmp["executable_disagreement"])

    def test_buy_vs_hold_executable_disagreement(self):
        cmp = reuse_engine.compare_decisions(
            self._art(signal="Buy", trader="BUY"), self._art())
        self.assertTrue(cmp["executable_disagreement"])

    def test_buy_vs_buy_different_plan_executable_disagreement(self):
        buy_a = self._art(signal="Buy", trader="BUY",
                          plan={"entry_basis": 100.0, "stop_level": 90.0,
                                "success_plan": {"base_case_top": 120.0}})
        buy_b = self._art(signal="Buy", trader="BUY",
                          plan={"entry_basis": 100.0, "stop_level": 80.0,
                                "success_plan": {"base_case_top": 120.0}})
        cmp = reuse_engine.compare_decisions(buy_a, buy_b)
        self.assertTrue(cmp["executable_disagreement"])
        same = reuse_engine.compare_decisions(buy_a, dict(buy_a))
        self.assertFalse(same["executable_disagreement"])

    def test_overweight_vs_underweight_rating_disagreement(self):
        cmp = reuse_engine.compare_decisions(
            self._art(pm="Overweight"), self._art(pm="Underweight"))
        self.assertFalse(cmp["rating_agreement"])

    def test_unknown_ratings_cannot_silently_agree(self):
        cmp = reuse_engine.compare_decisions(
            self._art(pm="gibberish"), self._art(pm=None))
        self.assertIsNone(cmp["rating_agreement"])

    def test_market_weight_normalizes(self):
        cmp = reuse_engine.compare_decisions(
            self._art(pm="Market Weight"), self._art(pm="Market-Weight"))
        self.assertTrue(cmp["rating_agreement"])


# ------------------------------------------------------------------ gate independence

class GateIndependence(EngineFixture):
    def _record(self, ticker, evidence):
        self.validation_dir.mkdir(exist_ok=True)
        rec = {"ticker": ticker, "session": SESSION, "optimized_mode": "UPDATE",
               "executable_disagreement": False, "probe_evidence": evidence,
               "fallback_to_full_refresh": False,
               "savings": {"model_calls_avoided": 8, "time_saved_ms": 100}}
        (self.validation_dir / f"{ticker}_{SESSION}.json").write_text(
            json.dumps(rec))

    def test_filing_evidence_blocks_gate(self):
        for i, t in enumerate(("AAA", "BBB", "CCC", "DDD", "EEE")):
            ev = {"filings": [{"form": "8-K"}] if i == 0 else [],
                  "earnings_or_guidance": [], "corporate_events": [],
                  "price_change_pct": 0.1,
                  "coverage": {f: {"status": "COMPLETE"} for f in (
                      "filings", "earnings_or_guidance", "news", "social",
                      "market_sector", "price_technical", "corporate_events")},
                  "prior_integrity_valid": True}
            self._record(t, ev)
        gate = reuse_engine.evaluate_readiness(self.validation_dir)
        self.assertEqual(gate["ready_for_optimized_authority"], "NO")
        self.assertTrue(gate["missed_full_refresh_triggers"])

    def test_incomplete_coverage_evidence_blocks_gate(self):
        for t in ("AAA", "BBB", "CCC", "DDD", "EEE"):
            cov = {f: {"status": "COMPLETE"} for f in (
                "filings", "earnings_or_guidance", "news", "social",
                "market_sector", "price_technical", "corporate_events")}
            if t == "AAA":
                cov["social"] = {"status": "PARTIAL"}
            self._record(t, {"filings": [], "earnings_or_guidance": [],
                             "corporate_events": [], "price_change_pct": 0.1,
                             "coverage": cov, "prior_integrity_valid": True})
        gate = reuse_engine.evaluate_readiness(self.validation_dir)
        self.assertEqual(gate["ready_for_optimized_authority"], "NO")


# ----------------------------------------------------------- call counting (fix 8)

class ProbeCounting(unittest.TestCase):
    def tearDown(self):
        from tradingagents.dataflows import provenance
        provenance.finish()

    def _probe(self, fetchers):
        from alpha_rnd import delta_probe
        from tradingagents.dataflows.vendors import sec_edgar
        from unittest import mock
        # Unset families use no-network no-ops; only the family under test is real.
        all_fetchers = {"news": lambda: None, "social": lambda: None,
                        "market": lambda: None, "price": lambda: None}
        all_fetchers.update(fetchers)
        with mock.patch.object(sec_edgar, "submissions_filings",
                               return_value={"status": "COMPLETE", "events": []}):
            return delta_probe.probe_gap(
                "TEST", PRIOR, SESSION, prior_close=100.0, fetchers=all_fetchers)

    def _observe(self, family, start, end, call_id=None, **kw):
        from tradingagents.dataflows import provenance
        provenance.observe(
            family, "yfinance", f"mock_{family}", "empty",
            requested_from=start, requested_to=end,
            coverage={"from": start, "through": end},
            layer="router", call_id=call_id, **kw)

    def test_stocktwits_plus_reddit_two_provider_attempts(self):
        result = self._probe({
            "social": lambda: ["stocktwits", "reddit"],
            "price": lambda: ["yfinance_snapshot"],
        })
        # SEC(1) + social(2) + snapshot(1) direct providers
        self.assertEqual(result["direct_provider_calls"], 3)
        self.assertEqual(result["provider_attempts"], 4)

    def test_router_dedupes_by_call_id(self):
        def news():
            # one logical get_news call, observed twice (router + vendor layer
            # record) under the SAME call_id -> counted once logically.
            self._observe("news", PRIOR, SESSION, call_id="c1")
            self._observe("news", PRIOR, SESSION, call_id="c1")
        result = self._probe({"news": news})
        self.assertEqual(result["logical_router_calls"], 1)
        self.assertEqual(result["provider_call_count"], 2)  # SEC + news only

    def test_cache_hit_is_not_external_call(self):
        def news():
            self._observe("news", PRIOR, SESSION, call_id="c1",
                          cache={"hit": True})
        def price():
            self._observe("price_technical", PRIOR, SESSION,
                          cache={"hit": False}, close=100.0)
            return ["yfinance_snapshot"]
        result = self._probe({"news": news, "price": price})
        self.assertEqual(result["cache_hits"], 1)
        # SEC submissions(1) + the cache-miss observation(1); the cache HIT
        # contributes nothing external.
        self.assertEqual(result["known_external_network_calls"], 2)


# --------------------------------------------------------------- prompt delta

class PromptDelta(EngineFixture):
    def test_prompt_carries_directional_delta_not_counts_only(self):
        prompts = []
        probe = _probe(
            news=[{"title": "Routine product note",
                   "published_at": "2026-10-16T10:00:00Z"}],
            unclassified_news=[{"title": "Routine product note"}])
        probe["social"] = {"item_count": 2, "items": [
            {"published_at": "2026-10-16T09:00:00Z", "sentiment": "Bearish",
             "title": "traders are selling TEST"}]}
        probe["market_sector"] = {"item_count": 1, "items": [
            {"published_at": "2026-10-16T08:00:00Z",
             "title": "Fed signals higher for longer"}]}
        calls = []
        self._optimized(probe=probe,
                        llm_fn=lambda p: prompts.append(p) or _update_text("HOLD"))
        prompt = prompts[0]
        self.assertIn("traders are selling TEST", prompt)
        self.assertIn("Bearish", prompt)
        self.assertIn("Fed signals higher for longer", prompt)
        self.assertNotIn("OLD MARKET REPORT PAYLOAD", prompt)
        self.assertEqual(len(prompts), 1)  # still exactly one update call


if __name__ == "__main__":
    unittest.main()


# -------------------------------------------- pre-probe cache isolation (fix)

class PreProbeCacheIsolation(EngineFixture):
    def test_clone_happens_before_probe_and_no_cross_contamination(self):
        """Fails on c3c0e7fe semantics (post-probe snapshot).

        Optimized probe writes marker B into its cache; the baseline leg must
        see pre-probe marker A but NEVER B. The baseline's own write C must
        likewise never appear in the optimized clone.
        """
        from tradingagents.dataflows.config import get_config

        cache = Path(self.tmp.name) / "cache"
        cache.mkdir()
        (cache / "marker_A").write_text("A")
        state = {}
        def probe(t, cutoff, s, **k):
            opt_dir = Path(get_config()["data_cache_dir"])
            opt_dir.mkdir(parents=True, exist_ok=True)
            (opt_dir / "marker_B").write_text("B")
            state["opt_dir"] = opt_dir
            return _probe()
        def baseline(ticker, date, out_name=None, config_overrides=None):
            base_dir = Path(config_overrides["data_cache_dir"])
            state["baseline_seen"] = sorted(p.name for p in base_dir.iterdir())
            (base_dir / "marker_C").write_text("C")
            # Reverse direction: the optimized clone must not contain C.
            state["opt_dir_final"] = sorted(
                p.name for p in state["opt_dir"].iterdir())
            return self._full_run()(ticker, date, out_name)
        self._write_prior()
        reuse_engine.run_validated_pair(
            "TEST", SESSION, full_run=baseline, case_dir=self.case_dir,
            facts_dir=self.facts_dir, probe_fn=probe,
            validation_dir=self.validation_dir, cache_dir=cache)
        self.assertEqual(state["baseline_seen"], ["marker_A"])
        self.assertNotIn("marker_C", state["opt_dir_final"])
        self.assertIn("marker_B", state["opt_dir_final"])
        self.assertNotEqual(state["opt_dir"], cache)
        record = json.loads(
            (self.validation_dir / f"TEST_{SESSION}.json").read_text())
        self.assertTrue(record["cache_isolation"])
        self.assertEqual(
            record["savings"]["quality"]["time_saved_ms"], "MEASURED")

    def test_probe_inside_optimized_sandbox(self):
        from tradingagents.dataflows.config import get_config
        cache = Path(self.tmp.name) / "cache"
        cache.mkdir()
        seen = {}
        def probe(t, cutoff, s, **k):
            seen["dir"] = Path(get_config()["data_cache_dir"])
            return _probe()
        self._write_prior()
        reuse_engine.run_validated_pair(
            "TEST", SESSION, full_run=self._full_run([]),
            case_dir=self.case_dir, facts_dir=self.facts_dir, probe_fn=probe,
            validation_dir=self.validation_dir, cache_dir=cache)
        self.assertNotEqual(seen["dir"], cache)
        self.assertIn("optimized", str(seen["dir"].parent))


# --------------------------------------------------- FRED point-in-time (fix 3)

class FredPointInTime(unittest.TestCase):
    def _fred_call(self, as_of):
        from tradingagents.dataflows.vendors import fred
        calls = []
        def fake(path, params):
            calls.append((path, params))
            if path == "series":
                return {"seriess": [{"title": "x", "frequency_short": "M",
                                     "units_short": "%"}]}
            return {"observations": [{"date": as_of, "value": "5.0"}]}
        with mock.patch.object(fred, "get_api_key", return_value="k"), \
                mock.patch.object(fred, "_request", side_effect=fake):
            fred.get_macro_data("fed_funds_rate", as_of, look_back_days=10)
        return dict(calls[-1][1])

    def test_vintage_pinned_to_as_of(self):
        params = self._fred_call("2026-10-16")
        # realtime bounds pin the data VINTAGE: historical runs see values
        # known as of the session, not today's revised series (#1275).
        self.assertEqual(params["realtime_start"], "2026-10-16")
        self.assertEqual(params["realtime_end"], "2026-10-16")
        self.assertEqual(params["observation_end"], "2026-10-16")

    def test_future_as_of_clamped_to_fred_today(self):
        from tradingagents.dataflows.vendors import fred
        params = self._fred_call("2999-01-01")
        self.assertEqual(params["realtime_start"], fred._fred_today())

    def test_historical_partial_coverage_fails_closed(self):
        """A non-PIT-safe family (can't prove the gap) can never COMPLETE."""
        from alpha_rnd import delta_probe
        from tradingagents.dataflows.vendors import sec_edgar
        from tradingagents.dataflows import provenance
        try:
            def market():
                # provider only reached back to session day, not the gap start
                provenance.observe(
                    "market_sector", "yfinance", "mock", "ok",
                    requested_from=PRIOR, requested_to=SESSION,
                    coverage={"from": SESSION, "through": SESSION},
                    layer="router", call_id="m1")
            fetchers = {"news": lambda: None, "social": lambda: None,
                        "market": market, "price": lambda: None}
            with mock.patch.object(sec_edgar, "submissions_filings",
                                   return_value={"status": "COMPLETE",
                                                 "events": []}):
                result = delta_probe.probe_gap(
                    "TEST", PRIOR, SESSION, prior_close=100.0,
                    fetchers=fetchers)
            self.assertEqual(result["coverage"]["market_sector"]["status"],
                             "PARTIAL")
            self.assertEqual(result["classification"], "FULL_REFRESH_REQUIRED")
        finally:
            provenance.finish()


if __name__ == "__main__":
    unittest.main()


# ------------------------------------------------- FULL_REFRESH overhead accounting

class FullRefreshOverhead(EngineFixture):
    def _refresh_pair(self):
        self._write_prior()
        calls = []
        reuse_engine.run_validated_pair(
            "TEST", SESSION, full_run=self._full_run(calls),
            case_dir=self.case_dir, facts_dir=self.facts_dir,
            probe_fn=lambda *a, **k: _probe(
                filings=[{"form": "10-Q", "filed_at": SESSION}]),
            validation_dir=self.validation_dir)
        return json.loads(
            (self.validation_dir / f"TEST_{SESSION}.json").read_text()), calls

    def test_probe_overhead_recorded(self):
        record, calls = self._refresh_pair()
        self.assertEqual(calls, [f"TEST_{SESSION}.json"])  # one graph only
        overhead = record["probe_overhead"]
        self.assertEqual(overhead["provider_call_count"], 6)
        self.assertEqual(overhead["model_calls"], 0)
        self.assertIsNotNone(overhead["elapsed_ms"])

    def test_model_call_savings_is_exactly_zero(self):
        record, _ = self._refresh_pair()
        self.assertEqual(record["savings"]["model_calls_avoided"], 0)
        self.assertEqual(
            record["savings"]["quality"]["model_calls_avoided"], "MEASURED")

    def test_extra_provider_work_visible_and_negative(self):
        record, _ = self._refresh_pair()
        # baseline 14 logical calls vs optimized-path probe 6 -> -6 overhead,
        # not hidden behind a NOT_MEASURED label.
        # enabled path = probe(6) + full graph(14) vs baseline 14 -> -6
        self.assertEqual(record["savings"]["provider_calls_avoided"], -6)
        self.assertLess(record["savings"]["provider_calls_avoided"], 0)
        self.assertEqual(
            record["savings"]["quality"]["provider_calls_avoided"], "MEASURED")

    def test_refresh_time_not_falsely_exact(self):
        record, _ = self._refresh_pair()
        self.assertIsNone(record["savings"]["time_saved_ms"])
        self.assertEqual(
            record["savings"]["quality"]["optimized_full_refresh_time"],
            "PARTIAL")
        self.assertIsNotNone(
            record["savings"]["full_refresh_probe_overhead_ms"])

    def test_report_shows_probe_overhead(self):
        self._refresh_pair()
        report = savings_report.render_report(
            self.case_dir, validation_dir=self.validation_dir)
        self.assertIn("FULL_REFRESH probe overhead", report)
        self.assertIn("cases: 1", report)


class GateQualityFiltering(EngineFixture):
    def _record(self, ticker, model_avoided, model_q, time_saved, time_q):
        self.validation_dir.mkdir(exist_ok=True)
        (self.validation_dir / f"{ticker}_{SESSION}.json").write_text(json.dumps({
            "ticker": ticker, "session": SESSION, "optimized_mode": "UPDATE",
            "executable_disagreement": False,
            "probe_evidence": {
                "filings": [], "earnings_or_guidance": [],
                "corporate_events": [], "price_change_pct": 0.5,
                "coverage": {f: {"status": "COMPLETE"} for f in (
                    "filings", "earnings_or_guidance", "news", "social",
                    "market_sector", "price_technical", "corporate_events")},
                "prior_integrity_valid": True},
            "savings": {
                "model_calls_avoided": model_avoided,
                "time_saved_ms": time_saved,
                "quality": {"model_calls_avoided": model_q,
                            "time_saved_ms": time_q}},
        }))

    def test_partial_time_cannot_satisfy_gate(self):
        for t in ("AAA", "BBB", "CCC", "DDD", "EEE"):
            self._record(t, 0, "MEASURED", 50000, "PARTIAL")
        gate = reuse_engine.evaluate_readiness(self.validation_dir)
        self.assertFalse(gate["meaningful_measured_benefit"])
        self.assertEqual(gate["ready_for_optimized_authority"], "NO")
        self.assertEqual(gate["measured_time_saved_ms"], 0)

    def test_measured_model_benefit_satisfies_independently(self):
        for t in ("AAA", "BBB", "CCC", "DDD", "EEE"):
            self._record(t, 8, "MEASURED", 50000, "PARTIAL")
        gate = reuse_engine.evaluate_readiness(self.validation_dir)
        self.assertTrue(gate["meaningful_measured_benefit"])
        self.assertEqual(gate["measured_model_calls_avoided"], 40)
        self.assertEqual(gate["ready_for_optimized_authority"], "YES")

    def test_unavailable_model_metric_not_benefit(self):
        for t in ("AAA", "BBB", "CCC", "DDD", "EEE"):
            self._record(t, 8, "UNAVAILABLE", 100, "MEASURED")
        gate = reuse_engine.evaluate_readiness(self.validation_dir)
        self.assertEqual(gate["measured_model_calls_avoided"], 0)
        self.assertTrue(gate["meaningful_measured_benefit"])  # via MEASURED time


class ConservativeExecutableDetection(EngineFixture):
    def test_hold_signal_overweight_pm_cannot_reuse(self):
        artifact, calls = self._optimized(
            signal="Hold", pm="Overweight",
            llm_fn=lambda p: _update_text("HOLD"))
        self.assertEqual(artifact["reuse_execution"]["mode"], "UPDATE")
        self.assertIn("REUSE_UPGRADED_EXECUTABLE_BUY",
                      artifact["reuse_execution"]["delta_reasons"])
        self.assertEqual(calls, [])  # never ran the graph


if __name__ == "__main__":
    unittest.main()
