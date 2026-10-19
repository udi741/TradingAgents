import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from alpha_rnd import reuse_shadow
from alpha_rnd.case_integrity import seal_case
from alpha_rnd.savings_report import compare_metrics, render_report
from evaluations.alpha_rnd_v1 import run_ta

SESSION_14 = "2026-10-14"
SESSION_15 = "2026-10-15"
SESSION_16 = "2026-10-16"
GENERATED_AT = "2026-10-19T10:00:00+00:00"


def _metadata(**updates):
    value = {
        "coverage": {
            "filings": True,
            "earnings_or_guidance": True,
            "news": True,
            "social": True,
            "market_sector": True,
            "price_technical": True,
            "corporate_events": True,
        },
        "filings": [],
        "earnings_or_guidance": [],
        "news": [],
        "corporate_events": [],
        "social_sentiment": {"score": 50},
        "market_sector": {"market_change_pct": 0, "sector_change_pct": 0},
        "price_technical": {"close": 100.0},
    }
    value.update(updates)
    return value


def _case(session, provider_metadata=None, schema_version=None):
    artifact = {
        "ticker": "TEST",
        "decision_session": session,
        "signal": "Hold",
        "pm_rating": "Hold",
        "rm_rating": "Market Weight",
        "risk_judge_decision": "Risk acceptable",
        "final_trade_decision": (
            "**Rating**: Hold\n\n**Executive Summary**: Maintain the position."
        ),
        "market_report": (
            f"Verified close ({session}): $100.00\nRSI: 50"
        ),
        "sentiment_report": "Overall sentiment: Neutral",
        "news_report": "No company-specific news is confirmed.",
        "fundamentals_report": "Revenue and cash flow are stable.",
    }
    if provider_metadata is not None:
        artifact["provider_metadata"] = provider_metadata
    if schema_version is not None:
        artifact["schema_version"] = schema_version
    return seal_case(artifact)


def _write_case(case_dir, session, artifact=None, name=None, contents=None):
    case_dir.mkdir(parents=True, exist_ok=True)
    path = case_dir / (name or f"TEST_{session}.json")
    if contents is not None:
        path.write_text(contents)
    else:
        path.write_text(json.dumps(artifact or _case(session)))
    return path


class ReuseShadowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.case_dir = self.root / "case_artifacts"
        self.facts_dir = self.root / "facts"
        self.shadow_dir = self.root / "reuse_shadow"

    def tearDown(self):
        self.tmp.cleanup()

    def _record(self, **kwargs):
        return reuse_shadow.build_shadow_record(
            "TEST", SESSION_16, self.case_dir, self.facts_dir,
            generated_at=GENERATED_AT, **kwargs)

    def _write_facts(self, session):
        self.facts_dir.mkdir(parents=True, exist_ok=True)
        (self.facts_dir / f"fundamental_facts_{session}.json").write_text(
            json.dumps({"TEST": {"facts": {"revenue": {"last_filed": "2026-08-01"}}}})
        )

    def test_no_prior_case_is_first_analysis(self):
        _write_case(self.case_dir, SESSION_16)

        self.assertIsNone(self._record())
        self.assertIsNone(
            reuse_shadow.resolve_prior_case("TEST", SESSION_16, self.case_dir)["prior_case"])

    def test_valid_prior_case_is_structured_with_date_only_cutoff(self):
        prior = _case(SESSION_15)
        _write_case(self.case_dir, SESSION_15, prior)
        _write_case(self.case_dir, SESSION_16)
        self._write_facts(SESSION_15)

        resolved = reuse_shadow.resolve_prior_case(
            "TEST", SESSION_16, self.case_dir, self.facts_dir)
        case = resolved["prior_case"]
        self.assertEqual(case["session"], SESSION_15)
        self.assertEqual(case["decision"], "Hold")
        self.assertEqual(case["portfolio_manager_decision"]["rating"], "Hold")
        self.assertEqual(case["risk_management_decision"]["rating"], "Market Weight")
        self.assertIn("Maintain the position", case["thesis_summary"])
        self.assertEqual(case["info_cutoff"]["value"], SESSION_15)
        self.assertEqual(case["info_cutoff"]["precision"], "session_date")
        self.assertEqual(case["artifact_path"], str(self.case_dir / f"TEST_{SESSION_15}.json"))
        self.assertIsNotNone(case["previously_known_stable_facts"])

    def test_real_as_of_timestamp_is_preferred(self):
        prior = _case(SESSION_15)
        prior["information_cutoff"] = "2026-10-15T20:30:00+00:00"
        _write_case(self.case_dir, SESSION_15, prior)

        case = reuse_shadow.resolve_prior_case(
            "TEST", SESSION_16, self.case_dir)["prior_case"]
        self.assertEqual(case["info_cutoff"]["value"], prior["information_cutoff"])
        self.assertEqual(case["info_cutoff"]["precision"], "timestamp")

    def test_close_extraction_uses_the_requested_session(self):
        examples = (
            ("**Verified close (2026-10-14):** $14.21", "2026-10-14", 14.21),
            ("Verified close on 2026-10-15: **$14.72**", "2026-10-15", 14.72),
            ("Price closed at $226.30 on 2026-10-14", "2026-10-14", 226.30),
            ("MRNA closed 2026-10-16 at **$218.01**", "2026-10-16", 218.01),
            ("Verified snapshot (2026-10-16): O 14.65 / H 14.71 / C 13.62",
             "2026-10-16", 13.62),
        )
        for report, session, expected in examples:
            with self.subTest(session=session, report=report):
                self.assertEqual(
                    reuse_shadow._close(
                        {"market_report": report}, {}, session),
                    expected,
                )

    def test_exact_cutoff_detects_later_same_day_filing(self):
        prior = _case(SESSION_15, _metadata())
        prior["information_cutoff"] = "2026-10-15T20:30:00+00:00"
        current_metadata = _metadata(filings=[{
            "form": "8-K", "filed_at": "2026-10-15T21:00:00+00:00",
        }])
        _write_case(self.case_dir, SESSION_15, prior)
        _write_case(self.case_dir, SESSION_16, _case(SESSION_16, current_metadata))

        record = self._record()
        self.assertIn("NEW_FILINGS", record["delta"]["classifications"])
        self.assertIn("NEW_FILING_REQUIRES_REFRESH", record["shadow_mode"]["reasons"])

    def test_date_only_cutoff_treats_same_day_event_as_unknown(self):
        _write_case(self.case_dir, SESSION_15, _case(SESSION_15, _metadata()))
        _write_case(
            self.case_dir, SESSION_16,
            _case(SESSION_16, _metadata(filings=[{
                "form": "10-Q", "filed_at": "2026-10-15T21:00:00+00:00",
            }])),
        )

        record = self._record()
        self.assertEqual(record["shadow_mode"]["classification"], "FULL_REFRESH_REQUIRED")
        self.assertIn("INSUFFICIENT_PROVIDER_EVIDENCE", record["shadow_mode"]["reasons"])

    def test_latest_successful_prior_excludes_same_day_and_failure_artifacts(self):
        _write_case(self.case_dir, SESSION_14)
        _write_case(self.case_dir, SESSION_15, name=f"TEST_{SESSION_15}.error.json")
        _write_case(self.case_dir, SESSION_16)
        _write_case(self.case_dir, "2026-10-17")

        result = reuse_shadow.resolve_prior_case("TEST", SESSION_16, self.case_dir)
        self.assertEqual(result["prior_case"]["session"], SESSION_14)

    def test_corrupt_prior_forces_full_refresh(self):
        _write_case(self.case_dir, SESSION_15, contents="{broken")
        _write_case(self.case_dir, SESSION_16)

        record = self._record()
        self.assertEqual(record["shadow_mode"]["classification"], "FULL_REFRESH_REQUIRED")
        self.assertIn("PRIOR_CASE_CORRUPT", record["shadow_mode"]["reasons"])

    def test_legacy_case_without_integrity_is_readable_but_not_reusable(self):
        legacy = _case(SESSION_15, _metadata())
        legacy.pop("case_integrity")
        _write_case(self.case_dir, SESSION_15, legacy)
        current = _case(SESSION_16, _metadata())
        _write_case(self.case_dir, SESSION_16, current)

        self.assertIsNotNone(reuse_shadow.resolve_prior_case(
            "TEST", SESSION_16, self.case_dir)["prior_case"])
        record = self._record()
        self.assertEqual(record["shadow_mode"]["classification"], "FULL_REFRESH_REQUIRED")
        self.assertIn("PRIOR_CASE_INTEGRITY_MISSING", record["shadow_mode"]["reasons"])

    def test_current_case_integrity_mutation_forces_full_refresh(self):
        _write_case(self.case_dir, SESSION_15, _case(SESSION_15, _metadata()))
        current = _case(SESSION_16, _metadata())
        current["provider_metadata"]["news"].append({"id": "tampered"})
        _write_case(self.case_dir, SESSION_16, current)

        record = self._record()
        self.assertEqual(record["shadow_mode"]["classification"], "FULL_REFRESH_REQUIRED")
        self.assertIn("CASE_INTEGRITY_INVALID", record["shadow_mode"]["reasons"])

    def test_savings_math_is_measured_and_zero_denominators_are_safe(self):
        result = compare_metrics(
            {
                "wall_clock": {"elapsed_ms": 1000},
                "model_calls": {"total": 8},
                "provider_calls": {
                    "logical_data_calls": 4, "external_network_calls": 3,
                    "external_network_quality": "PARTIAL",
                },
                "tokens": {
                    "availability": "EXACT", "input_tokens": 100,
                    "output_tokens": 50, "total_tokens": 150,
                },
            },
            {
                "wall_clock": {"elapsed_ms": 400},
                "model_calls": {"total": 3},
                "provider_calls": {
                    "logical_data_calls": 2, "external_network_calls": 1,
                    "external_network_quality": "PARTIAL",
                },
                "tokens": {
                    "availability": "EXACT", "input_tokens": 40,
                    "output_tokens": 20, "total_tokens": 60,
                },
            },
        )
        self.assertEqual(result["time_saved_ms"], 600)
        self.assertEqual(result["time_saved_pct"], 60)
        self.assertEqual(result["model_calls_avoided"], 5)
        self.assertEqual(result["external_network_calls_avoided"], 2)
        self.assertEqual(result["quality"]["external_network_calls_avoided"], "PARTIAL")
        self.assertEqual(result["tokens"]["total_tokens"], 90)
        self.assertIsNone(compare_metrics(
            {"wall_clock": {"elapsed_ms": 0}}, {"wall_clock": {"elapsed_ms": 0}}
        )["time_saved_pct"])

    def test_no_optimized_metrics_means_no_realized_savings(self):
        result = compare_metrics({}, None)
        self.assertEqual(result["realized_savings"], "NOT_MEASURED")
        self.assertEqual(result["quality"], "UNAVAILABLE")

    def test_shadow_report_does_not_claim_realized_savings(self):
        self.case_dir.mkdir()
        self.shadow_dir.mkdir()
        artifact = _case(SESSION_16)
        artifact["analysis_metrics"] = {"wall_clock": {"elapsed_ms": 25}}
        seal_case(artifact)
        artifact["analysis_metrics"]["wall_clock"]["elapsed_ms"] = 999
        (self.case_dir / "TEST.json").write_text(json.dumps(artifact))
        (self.shadow_dir / "TEST.json").write_text(json.dumps({
            "shadow_mode": {"classification": "FULL_REFRESH_REQUIRED",
                            "reasons": ["INSUFFICIENT_PROVIDER_EVIDENCE"]},
            "estimated_reuse": {"estimated_model_calls_avoidable": 4},
        }))
        report = render_report(self.case_dir, self.shadow_dir)
        self.assertIn("REALIZED SAVINGS: NOT MEASURED", report)
        self.assertIn("ESTIMATED / PROJECTED lower bound 4", report)
        self.assertIn("UNAVAILABLE (0 measured runs)", report)

    def test_failed_prior_is_not_loaded_and_forces_full_refresh(self):
        _write_case(
            self.case_dir, SESSION_15, name=f"TEST_{SESSION_15}.error.json")
        _write_case(self.case_dir, SESSION_16)

        record = self._record()
        self.assertIsNone(record["prior_case"])
        self.assertEqual(record["shadow_mode"]["classification"], "FULL_REFRESH_REQUIRED")
        self.assertIn("PRIOR_ANALYSIS_FAILED", record["shadow_mode"]["reasons"])

    def test_new_filing_and_earnings_force_full_refresh(self):
        _write_case(self.case_dir, SESSION_15, _case(SESSION_15, _metadata()))
        for event_field, event in (
            ("filings", {"form": "10-Q", "filed_at": SESSION_16}),
            ("earnings_or_guidance", {"type": "earnings_release", "date": SESSION_16}),
        ):
            metadata = _metadata(**{event_field: [event]})
            _write_case(
                self.case_dir, SESSION_16,
                _case(SESSION_16, metadata),
                name=f"TEST_{SESSION_16}.json")
            record = self._record()
            self.assertEqual(
                record["shadow_mode"]["classification"], "FULL_REFRESH_REQUIRED")
            if event_field == "filings":
                self.assertIn("NEW_FILINGS", record["delta"]["classifications"])
                self.assertIn(
                    "NEW_FILING_REQUIRES_REFRESH", record["shadow_mode"]["reasons"])
            else:
                self.assertIn(
                    "NEW_EARNINGS_OR_GUIDANCE",
                    record["delta"]["classifications"])
                self.assertIn(
                    "NEW_EARNINGS_OR_GUIDANCE_REQUIRES_REFRESH",
                    record["shadow_mode"]["reasons"])
            _write_case(
                self.case_dir, SESSION_16,
                _case(SESSION_16, _metadata()),
                name=f"TEST_{SESSION_16}.json")

    def test_new_sec_facts_filing_forces_full_refresh(self):
        _write_case(self.case_dir, SESSION_15, _case(SESSION_15, _metadata()))
        _write_case(self.case_dir, SESSION_16, _case(SESSION_16, _metadata()))
        self._write_facts(SESSION_15)
        self.facts_dir.mkdir(parents=True, exist_ok=True)
        (self.facts_dir / f"fundamental_facts_{SESSION_16}.json").write_text(
            json.dumps({"TEST": {"facts": {
                "revenue": {"last_filed": SESSION_16},
            }}})
        )

        record = self._record()
        self.assertIn("NEW_FILINGS", record["delta"]["classifications"])
        self.assertEqual(
            record["delta"]["new_filings"][0]["source"], "fundamental_facts_snapshot")
        self.assertIn("NEW_FILING_REQUIRES_REFRESH", record["shadow_mode"]["reasons"])

    def test_small_delta_with_complete_evidence_is_reuse_eligible(self):
        previous_metadata = _metadata()
        current_metadata = _metadata(price_technical={"close": 100.5})
        _write_case(self.case_dir, SESSION_15, _case(SESSION_15, previous_metadata))
        _write_case(self.case_dir, SESSION_16, _case(SESSION_16, current_metadata))
        self._write_facts(SESSION_15)
        self._write_facts(SESSION_16)

        record = self._record()
        self.assertEqual(record["delta"]["price_change_pct"], 0.5)
        self.assertEqual(record["shadow_mode"]["classification"], "REUSE_ELIGIBLE")
        self.assertIn("NO_MATERIAL_CHANGE", record["delta"]["classifications"])
        self.assertTrue(record["estimated_reuse"]["sec_facts_identical"])
        self.assertEqual(
            record["estimated_reuse"]["model_calls_safe_to_avoid_in_shadow_mode"],
            record["estimated_reuse"]["estimated_model_calls_avoidable"],
        )

    def test_news_social_and_market_deltas_recommend_update_mode(self):
        previous_metadata = _metadata()
        current_metadata = _metadata(
            news=[{"published_at": SESSION_16, "id": "n1"}],
            social_sentiment={"score": 60},
            market_sector={"market_change_pct": 1, "sector_change_pct": 2},
        )
        _write_case(self.case_dir, SESSION_15, _case(SESSION_15, previous_metadata))
        _write_case(self.case_dir, SESSION_16, _case(SESSION_16, current_metadata))
        self._write_facts(SESSION_15)
        self._write_facts(SESSION_16)

        record = self._record()
        self.assertEqual(record["delta"]["new_news_count"], 1)
        self.assertEqual(
            record["shadow_mode"]["classification"], "UPDATE_MODE_RECOMMENDED")
        self.assertIn("NEW_NEWS", record["delta"]["classifications"])
        self.assertIn(
            "SOCIAL_SENTIMENT_CHANGE", record["delta"]["classifications"])
        self.assertIn(
            "MARKET_OR_SECTOR_CHANGE", record["delta"]["classifications"])

    def test_configured_age_limit_forces_full_refresh(self):
        _write_case(self.case_dir, "2026-09-01", _case("2026-09-01", _metadata()))
        _write_case(self.case_dir, SESSION_16, _case(SESSION_16, _metadata()))
        self._write_facts("2026-09-01")
        self._write_facts(SESSION_16)

        with mock.patch.dict(os.environ, {"ALPHA_REUSE_SHADOW_MAX_AGE_DAYS": "5"}):
            record = self._record()
        self.assertEqual(record["shadow_mode"]["classification"], "FULL_REFRESH_REQUIRED")
        self.assertIn("PRIOR_ANALYSIS_TOO_OLD", record["shadow_mode"]["reasons"])

    def test_incompatible_case_schema_forces_full_refresh(self):
        _write_case(self.case_dir, SESSION_15, _case(SESSION_15, _metadata(), 999))
        _write_case(self.case_dir, SESSION_16, _case(SESSION_16, _metadata()))

        record = self._record()
        self.assertEqual(record["shadow_mode"]["classification"], "FULL_REFRESH_REQUIRED")
        self.assertIn("SCHEMA_INCOMPATIBLE", record["shadow_mode"]["reasons"])

    def test_unknown_provider_evidence_does_not_qualify_for_reuse(self):
        _write_case(self.case_dir, SESSION_15)
        _write_case(self.case_dir, SESSION_16)

        record = self._record()
        self.assertEqual(record["shadow_mode"]["classification"], "FULL_REFRESH_REQUIRED")
        self.assertIn("INSUFFICIENT_PROVIDER_EVIDENCE", record["shadow_mode"]["reasons"])
        self.assertIn("UNKNOWN_INSUFFICIENT_DATA", record["delta"]["classifications"])
        self.assertEqual(
            record["estimated_reuse"]["model_calls_safe_to_avoid_in_shadow_mode"], 0)

    def test_shadow_artifact_is_schema_valid_and_persisted_deterministically(self):
        _write_case(self.case_dir, SESSION_15, _case(SESSION_15, _metadata()))
        _write_case(self.case_dir, SESSION_16, _case(SESSION_16, _metadata()))
        record = self._record()

        output = reuse_shadow.persist_shadow_record(record, self.shadow_dir)
        first = output.read_bytes()
        self.assertEqual(json.loads(first), record)
        self.assertEqual(record["schema_version"], reuse_shadow.SCHEMA_VERSION)
        self.assertEqual(output.name, f"TEST_{SESSION_16}.json")
        reuse_shadow.persist_shadow_record(record, self.shadow_dir)
        self.assertEqual(output.read_bytes(), first)

    def test_run_ta_still_invokes_the_existing_graph_once(self):
        class FakePosition:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        class FakePortfolio:
            def __init__(self, **kwargs):
                pass

            def render(self, ticker):
                return f"Portfolio for {ticker}"

        graph_calls = []

        class FakeGraph:
            def __init__(self, **kwargs):
                pass

            def propagate(self, *args, **kwargs):
                graph_calls.append((args, kwargs))
                return ({
                    "investment_debate_state": {
                        "bull_history": "bull",
                        "bear_history": "bear",
                        "judge_decision": "",
                    },
                    "risk_debate_state": {"judge_decision": ""},
                    "investment_plan": "**Recommendation**: Hold",
                    "trader_investment_plan": "**Action**: HOLD",
                    "final_trade_decision": "**Rating**: Hold",
                }, "Hold")

        graph_module = types.ModuleType("tradingagents.graph.trading_graph")
        graph_module.TradingAgentsGraph = FakeGraph
        portfolio_module = types.ModuleType("tradingagents.portfolio")
        portfolio_module.PortfolioContext = FakePortfolio
        portfolio_module.Position = FakePosition
        output_dir = self.root / "live_output"
        with mock.patch.dict(sys.modules, {
            "tradingagents.graph.trading_graph": graph_module,
            "tradingagents.portfolio": portfolio_module,
        }), mock.patch.object(run_ta, "D", output_dir), \
             mock.patch.object(run_ta, "cfg", return_value={}):
            result = run_ta.run_one("TEST", SESSION_16)

        self.assertEqual(result["signal"], "Hold")
        self.assertEqual(len(graph_calls), 1)

    def test_shadow_collection_runs_after_live_analysis_and_is_non_fatal(self):
        order = []
        with mock.patch.object(run_ta.sys, "argv", ["run_ta.py", SESSION_16, "TEST"]), \
             mock.patch.object(run_ta, "run_one",
                               side_effect=lambda *a: order.append("analysis") or {
                                   "signal": "Hold", "rm_rating": "Hold",
                                   "trader_action": "HOLD", "pm_rating": "Hold",
                                   "duration_s": 1,
                               }), \
             mock.patch.object(run_ta, "_record_shadow_case",
                               side_effect=lambda *a: order.append("shadow")):
            run_ta.main()
        self.assertEqual(order, ["analysis", "shadow"])


if __name__ == "__main__":
    unittest.main()
