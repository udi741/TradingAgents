import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from alpha_rnd import reuse_shadow
from evaluations.alpha_rnd_v1 import run_ta
from tradingagents.dataflows import provenance
from tradingagents.dataflows import router

S15 = "2026-10-15"
S16 = "2026-10-16"
GENERATED_AT = "2026-10-19T10:00:00+00:00"


def _cov(status="COMPLETE", frm=S15, thru=S16, source="test", intervals=None):
    cov = {"status": status, "from": frm, "through": thru,
           "observed_at": f"{S16}T20:00:00+00:00", "sources": [source],
           "queries": 1, "items": 0}
    if intervals is not None:
        cov["intervals"] = intervals
    return cov


def _metadata_v1(session=S16, **updates):
    """Provider metadata in the real persisted schema (provenance.finish shape)."""
    value = {
        "schema_version": 1,
        "captured_at": f"{session}T20:00:00+00:00",
        "coverage": {
            f: _cov(frm=None, thru=session) for f in reuse_shadow.REQUIRED_EVIDENCE},
        "filings": [],
        "earnings_or_guidance": [],
        "news": [],
        "corporate_events": [],
        "insider": [],
        "social_sentiment": {"items_digest": "s1", "item_count": 3},
        "market_sector": {"items_digest": "m1", "item_count": 5},
        "price_technical": {"close": 100.0, "latest_bar_date": session,
                            "provider": "yfinance"},
        "information_cutoff": {"value": session, "precision": "date",
                               "complete": True},
        "calls": [],
    }
    value.update(updates)
    return value


def _case(session, provider_metadata=None):
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
        "market_report": f"Verified close ({session}): $100.00\nRSI: 50",
        "sentiment_report": "Overall sentiment: Neutral",
        "news_report": "No company-specific news is confirmed.",
        "fundamentals_report": "Revenue and cash flow are stable.",
    }
    if provider_metadata is not None:
        artifact["provider_metadata"] = provider_metadata
    return artifact


class ShadowCoverageSchemaTest(unittest.TestCase):
    """reuse_shadow against the real persisted provider_metadata schema."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.case_dir = self.root / "case_artifacts"
        self.facts_dir = self.root / "facts"
        self.case_dir.mkdir(parents=True)
        self.facts_dir.mkdir(parents=True)
        self._write_facts(S15)
        self._write_facts(S16)

    def tearDown(self):
        self.tmp.cleanup()

    def _write_facts(self, session, last_filed="2026-08-01"):
        (self.facts_dir / f"fundamental_facts_{session}.json").write_text(
            json.dumps({"TEST": {"facts": {"revenue": {"last_filed": last_filed}}}}))

    def _write(self, session, metadata):
        (self.case_dir / f"TEST_{session}.json").write_text(
            json.dumps(_case(session, metadata)))

    def _record(self):
        return reuse_shadow.build_shadow_record(
            "TEST", S16, self.case_dir, self.facts_dir, generated_at=GENERATED_AT)

    def test_complete_coverage_no_delta_is_reuse_eligible(self):
        self._write(S15, _metadata_v1(session=S15))
        self._write(S16, _metadata_v1())
        rec = self._record()
        self.assertEqual(rec["shadow_mode"]["classification"], "REUSE_ELIGIBLE")
        self.assertEqual(
            set(rec["delta"]["evidence_coverage"].values()), {"COMPLETE"})

    def test_new_news_is_update_mode_not_refresh(self):
        meta = _metadata_v1(news=[{"published_at": f"{S16}T09:00:00+00:00",
                                  "id": "a1"}])
        self._write(S15, _metadata_v1(session=S15))
        self._write(S16, meta)
        rec = self._record()
        self.assertEqual(rec["shadow_mode"]["classification"],
                         "UPDATE_MODE_RECOMMENDED")
        self.assertIn("NEW_NEWS", rec["delta"]["classifications"])

    def test_new_filing_fails_closed(self):
        meta = _metadata_v1(
            filings=[{"filed_at": S16, "form": "10-Q",
                      "accession": "0001-26-000001", "id": "0001-26-000001"}])
        self._write(S15, _metadata_v1(session=S15))
        self._write(S16, meta)
        rec = self._record()
        self.assertEqual(rec["shadow_mode"]["classification"],
                         "FULL_REFRESH_REQUIRED")
        self.assertIn("NEW_FILING_REQUIRES_REFRESH", rec["shadow_mode"]["reasons"])

    def test_new_earnings_fails_closed(self):
        meta = _metadata_v1(earnings_or_guidance=[
            {"published_at": S16, "type": "earnings", "id": "e1"}])
        self._write(S15, _metadata_v1(session=S15))
        self._write(S16, meta)
        rec = self._record()
        self.assertEqual(rec["shadow_mode"]["classification"],
                         "FULL_REFRESH_REQUIRED")
        self.assertIn("NEW_EARNINGS_OR_GUIDANCE_REQUIRES_REFRESH",
                      rec["shadow_mode"]["reasons"])

    def test_corporate_event_fails_closed(self):
        meta = _metadata_v1(corporate_events=[
            {"date": S16, "type": "merger", "id": "c1"}])
        self._write(S15, _metadata_v1(session=S15))
        self._write(S16, meta)
        rec = self._record()
        self.assertEqual(rec["shadow_mode"]["classification"],
                         "FULL_REFRESH_REQUIRED")
        self.assertIn("MAJOR_CORPORATE_EVENT_REQUIRES_REFRESH",
                      rec["shadow_mode"]["reasons"])

    def test_disjoint_intervals_fail_closed(self):
        meta = _metadata_v1()
        meta["coverage"]["news"] = _cov(
            frm=None, thru=None,
            intervals=[{"from": "2026-10-10", "through": "2026-10-12"},
                       {"from": S16, "through": S16}])
        self._write(S15, _metadata_v1(session=S15))
        self._write(S16, meta)
        rec = self._record()
        self.assertEqual(rec["delta"]["evidence_coverage"]["news"], "PARTIAL")
        self.assertEqual(rec["shadow_mode"]["classification"],
                         "FULL_REFRESH_REQUIRED")

    def test_contiguous_intervals_can_be_complete(self):
        meta = _metadata_v1()
        meta["coverage"]["news"] = _cov(
            frm="2026-10-10", thru=S16,
            intervals=[{"from": "2026-10-10", "through": S15},
                       {"from": S15, "through": S16}])
        self._write(S15, _metadata_v1(session=S15))
        self._write(S16, meta)
        rec = self._record()
        self.assertEqual(rec["delta"]["evidence_coverage"]["news"], "COMPLETE")

    def test_source_aware_partial_beats_requested_window(self):
        # router requested 10-14..10-16 but the feed only proved 10-16:
        # the recorded interval, not the request, decides coverage.
        meta = _metadata_v1()
        meta["coverage"]["news"] = _cov(
            frm=S16, thru=S16, intervals=[{"from": S16, "through": S16}])
        meta["calls"] = [{"family": "news", "source": "yfinance",
                          "method": "get_news", "status": "ok",
                          "observed_at": f"{S16}T20:00:00+00:00",
                          "requested": {"from": "2026-10-14", "to": S16}}]
        self._write(S15, _metadata_v1(session=S15))
        self._write(S16, meta)
        rec = self._record()
        self.assertEqual(rec["delta"]["evidence_coverage"]["news"], "PARTIAL")
        self.assertEqual(rec["shadow_mode"]["classification"],
                         "FULL_REFRESH_REQUIRED")

    def test_window_not_reaching_prior_session_is_partial(self):
        meta = _metadata_v1()
        meta["coverage"]["news"] = _cov(frm=S16, thru=S16)  # only same-day
        self._write(S15, _metadata_v1(session=S15))
        self._write(S16, meta)
        rec = self._record()
        self.assertEqual(rec["delta"]["evidence_coverage"]["news"], "PARTIAL")
        self.assertEqual(rec["shadow_mode"]["classification"],
                         "FULL_REFRESH_REQUIRED")
        self.assertIn("INSUFFICIENT_PROVIDER_EVIDENCE",
                      rec["shadow_mode"]["reasons"])

    def test_provider_failure_fails_closed(self):
        meta = _metadata_v1()
        meta["coverage"]["news"] = _cov(status="FAILED", frm=None, thru=None)
        self._write(S15, _metadata_v1(session=S15))
        self._write(S16, meta)
        rec = self._record()
        self.assertEqual(rec["delta"]["evidence_coverage"]["news"], "FAILED")
        self.assertEqual(rec["shadow_mode"]["classification"],
                         "FULL_REFRESH_REQUIRED")

    def test_not_queried_family_fails_closed(self):
        meta = _metadata_v1()
        meta["coverage"]["corporate_events"] = {"status": "NOT_QUERIED"}
        self._write(S15, _metadata_v1(session=S15))
        self._write(S16, meta)
        rec = self._record()
        self.assertEqual(rec["delta"]["evidence_coverage"]["corporate_events"],
                         "NOT_QUERIED")
        self.assertEqual(rec["shadow_mode"]["classification"],
                         "FULL_REFRESH_REQUIRED")

    def test_empty_successful_covered_query_is_zero_events(self):
        # A covered window with no items proves absence, not ignorance.
        meta = _metadata_v1()
        self.assertEqual(meta["news"], [])
        self._write(S15, _metadata_v1(session=S15))
        self._write(S16, meta)
        rec = self._record()
        self.assertEqual(rec["delta"]["new_news_count"], 0)
        self.assertEqual(rec["delta"]["evidence_coverage"]["news"], "COMPLETE")

    def test_old_artifact_without_metadata_still_fails_closed(self):
        self._write(S15, _metadata_v1(session=S15))
        self._write(S16, None)
        rec = self._record()
        self.assertEqual(rec["shadow_mode"]["classification"],
                         "FULL_REFRESH_REQUIRED")
        self.assertIn("INSUFFICIENT_PROVIDER_EVIDENCE",
                      rec["shadow_mode"]["reasons"])


class RecorderTest(unittest.TestCase):
    def tearDown(self):
        provenance.finish()  # never leak armed state between tests

    def test_observe_and_finish_shape(self):
        provenance.begin("TEST", S16)
        provenance.observe("news", "yfinance", "get_news", "ok",
                           requested_from="2026-10-09", requested_to=S16,
                           coverage={"from": "2026-10-09", "through": S16},
                           items=[{"published_at": f"{S16}T10:00:00+00:00",
                                   "id": "n1"}])
        doc = provenance.finish()
        self.assertEqual(doc["schema_version"], 1)
        self.assertEqual(doc["coverage"]["news"]["status"], "COMPLETE")
        self.assertEqual(doc["coverage"]["news"]["from"], "2026-10-09")
        self.assertEqual(doc["coverage"]["news"]["intervals"],
                         [{"from": "2026-10-09", "through": S16}])
        self.assertEqual(doc["coverage"]["filings"]["status"], "NOT_QUERIED")
        self.assertEqual(doc["news"], [{"published_at": f"{S16}T10:00:00+00:00",
                                        "id": "n1"}])
        json.dumps(doc)  # serializable

    def test_finish_without_begin_is_unknown_not_fatal(self):
        doc = provenance.finish()
        self.assertEqual(doc["coverage"]["news"]["status"], "UNKNOWN")
        self.assertTrue(doc["instrumentation_errors"])

    def test_failed_call_marks_family_failed(self):
        provenance.begin("TEST", S16)
        provenance.observe("news", "yfinance", "get_news", "failed",
                           requested_from="2026-10-09", requested_to=S16)
        doc = provenance.finish()
        self.assertEqual(doc["coverage"]["news"]["status"], "FAILED")
        self.assertFalse(doc["information_cutoff"]["complete"])

    def test_mixed_success_and_failure_is_partial(self):
        provenance.begin("TEST", S16)
        provenance.observe("news", "yfinance", "get_news", "ok",
                           coverage={"from": "2026-10-09", "through": S16})
        provenance.observe("news", "alpha_vantage", "get_news", "failed")
        self.assertEqual(provenance.finish()["coverage"]["news"]["status"],
                         "PARTIAL")

    def test_disjoint_intervals_never_bridge_gap(self):
        provenance.begin("TEST", S16)
        provenance.observe("news", "a", "get_news", "ok",
                           coverage={"from": "2026-10-10", "through": "2026-10-12"})
        provenance.observe("news", "b", "get_news", "ok",
                           coverage={"from": S15, "through": S16})
        cov = provenance.finish()["coverage"]["news"]
        self.assertEqual(cov["intervals"],
                         [{"from": "2026-10-10", "through": "2026-10-12"},
                          {"from": S15, "through": S16}])
        # the gap 10-13..10-14 is NOT bridged into 10-10..10-16
        self.assertFalse(
            provenance.intervals_cover(cov["intervals"], "2026-10-10", S16))
        self.assertTrue(
            provenance.intervals_cover(cov["intervals"], "2026-10-10", "2026-10-12"))

    def test_touching_intervals_merge(self):
        provenance.begin("TEST", S16)
        provenance.observe("news", "a", "get_news", "ok",
                           coverage={"from": "2026-10-10", "through": "2026-10-14"})
        provenance.observe("news", "b", "get_news", "ok",
                           coverage={"from": "2026-10-14", "through": S16})
        cov = provenance.finish()["coverage"]["news"]
        self.assertEqual(cov["intervals"],
                         [{"from": "2026-10-10", "through": S16}])
        self.assertTrue(
            provenance.intervals_cover(cov["intervals"], "2026-10-10", S16))

    def test_request_only_observation_grants_no_coverage(self):
        provenance.begin("TEST", S16)
        provenance.observe("news", "yfinance", "get_news", "ok",
                           requested_from="2026-10-14", requested_to=S16)
        cov = provenance.finish()["coverage"]["news"]
        self.assertNotEqual(cov["status"], "COMPLETE")
        self.assertEqual(cov["intervals"], [])
        self.assertFalse(
            provenance.intervals_cover(cov["intervals"], "2026-10-14", S16))

    def test_sec_filings_horizon_is_bounded_not_unbounded(self):
        from tradingagents.dataflows.vendors import sec_edgar
        provenance.begin("TEST", S16)
        us_gaap = {"Revenue": {"units": {"USD": [
            {"filed": "2026-10-10", "accn": "0001-26-000001", "form": "8-K",
             "end": "2026-09-30", "val": 1},
            {"filed": "2020-01-01", "accn": "old-1", "form": "10-K",
             "end": "2019-12-31", "val": 1},  # outside the 400d item horizon
        ]}}}
        sec_edgar._record_filings(us_gaap, S16, "TEST", "balance_sheet")
        doc = provenance.finish()
        obs = doc["calls"][0]
        # the item list is bounded by _FILINGS_HORIZON, so coverage must record
        # the real lower bound — never an unbounded from=None.
        self.assertIsNotNone(obs["coverage"]["from"])
        self.assertEqual(obs["coverage"]["from"],
                         "2025-09-11")  # 2026-10-16 - 400d
        self.assertEqual(obs["coverage"]["through"], S16)
        self.assertEqual(len(doc["filings"]), 1)
        self.assertEqual(doc["filings"][0]["form"], "8-K")

    def test_recorder_failure_does_not_raise(self):
        provenance.begin("TEST", S16)
        provenance._run = []  # corrupt the state mid-run
        provenance.observe("news", "x", "y", "ok")  # must not raise
        doc = provenance.finish()
        self.assertIn("coverage", doc)


class RouterInstrumentationTest(unittest.TestCase):
    def tearDown(self):
        provenance.finish()

    def test_provider_called_once_and_result_unchanged(self):
        calls = []

        def fake_news(ticker, start, end):
            calls.append((ticker, start, end))
            return "## News body"

        original = router.VENDOR_METHODS["get_news"]
        router.VENDOR_METHODS["get_news"] = {"fake_vendor": fake_news}
        try:
            with mock.patch.object(router, "get_vendor", return_value="fake_vendor"):
                provenance.begin("TEST", S16)
                result = router.route_to_vendor("get_news", "TEST", "2026-10-09", S16)
                doc = provenance.finish()
        finally:
            router.VENDOR_METHODS["get_news"] = original
        self.assertEqual(result, "## News body")
        self.assertEqual(calls, [("TEST", "2026-10-09", "2026-10-16")])
        rec = [c for c in doc["calls"] if c["method"] == "get_news"]
        self.assertEqual(len(rec), 1)
        self.assertEqual(rec[0]["status"], "ok")
        # a generic routed call records the REQUESTED window only — achieved
        # coverage is unknown at this layer and must not be claimed.
        self.assertEqual(rec[0]["requested"],
                         {"from": "2026-10-09", "to": S16})
        self.assertNotIn("coverage", rec[0])
        self.assertNotEqual(doc["coverage"]["news"]["status"], "COMPLETE")

    def test_failed_vendor_not_marked_complete(self):
        def boom(*a):
            raise RuntimeError("net down")
        original = router.VENDOR_METHODS["get_news"]
        router.VENDOR_METHODS["get_news"] = {"fake_vendor": boom}
        try:
            with mock.patch.object(router, "get_vendor", return_value="fake_vendor"):
                provenance.begin("TEST", S16)
                with self.assertRaises(RuntimeError):
                    router.route_to_vendor("get_news", "TEST", "2026-10-09", S16)
                doc = provenance.finish()
        finally:
            router.VENDOR_METHODS["get_news"] = original
        self.assertEqual(doc["coverage"]["news"]["status"], "FAILED")

    def test_no_data_sentinel_is_empty_not_failed(self):
        original = router.VENDOR_METHODS["get_news"]
        router.VENDOR_METHODS["get_news"] = {"fake_vendor": lambda *a: "NO_DATA_AVAILABLE: none"}
        try:
            with mock.patch.object(router, "get_vendor", return_value="fake_vendor"):
                provenance.begin("TEST", S16)
                router.route_to_vendor("get_news", "TEST", "2026-10-09", S16)
                doc = provenance.finish()
        finally:
            router.VENDOR_METHODS["get_news"] = original
        rec = doc["calls"][0]
        self.assertEqual(rec["status"], "empty")
        # empty at the router layer proves the call ran, not the window —
        # without a source-aware coverage record the family is not COMPLETE.
        self.assertNotIn("coverage", rec)
        self.assertNotEqual(doc["coverage"]["news"]["status"], "COMPLETE")


class RunOneArtifactTest(unittest.TestCase):
    """provider_metadata lands in the case artifact; nothing else changes."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()
        provenance.finish()

    def _run_one(self, propagate):
        class FakePortfolio:
            def __init__(self, **kw):
                pass

            def render(self, ticker):
                return "Portfolio for TEST"

        class FakePosition:
            def __init__(self, **kw):
                pass

        class FakeGraph:
            def __init__(self, **kw):
                pass

            def propagate(self, *a, **kw):
                return propagate()

        graph_module = types.ModuleType("tradingagents.graph.trading_graph")
        graph_module.TradingAgentsGraph = FakeGraph
        portfolio_module = types.ModuleType("tradingagents.portfolio")
        portfolio_module.PortfolioContext = FakePortfolio
        portfolio_module.Position = FakePosition
        out_dir = self.root / "out"
        state = {
            "investment_debate_state": {"bull_history": "b", "bear_history": "e",
                                        "judge_decision": ""},
            "risk_debate_state": {"judge_decision": ""},
            "investment_plan": "**Recommendation**: Hold",
            "trader_investment_plan": "**Action**: HOLD",
            "final_trade_decision": "**Rating**: Hold",
        }
        with mock.patch.dict(sys.modules, {
                "tradingagents.graph.trading_graph": graph_module,
                "tradingagents.portfolio": portfolio_module}), \
                mock.patch.object(run_ta, "D", out_dir), \
                mock.patch.object(run_ta, "cfg", return_value={}):
            return run_ta.run_one("TEST", S16), out_dir

    def test_artifact_embeds_provider_metadata(self):
        provider_calls = []

        def propagate():
            def fake_news(ticker, start, end):
                provider_calls.append(1)
                return "## body"
            original = router.VENDOR_METHODS["get_news"]
            router.VENDOR_METHODS["get_news"] = {"fake_vendor": fake_news}
            try:
                with mock.patch.object(router, "get_vendor", return_value="fake_vendor"):
                    router.route_to_vendor("get_news", "TEST", "2026-10-09", S16)
            finally:
                router.VENDOR_METHODS["get_news"] = original
            # a source-aware vendor observation proves the achieved window
            provenance.observe("news", "fake_vendor", "get_news", "ok",
                               requested_from="2026-10-09", requested_to=S16,
                               coverage={"from": "2026-10-09", "through": S16})
            return (self._state(), "Hold")

        result, out_dir = self._run_one(propagate)
        self.assertEqual(len(provider_calls), 1)  # exactly one provider call
        meta = result["provider_metadata"]
        self.assertEqual(meta["schema_version"], 1)
        self.assertEqual(meta["ticker"], "TEST")
        self.assertEqual(meta["coverage"]["news"]["status"], "COMPLETE")
        self.assertEqual(meta["coverage"]["news"]["intervals"],
                         [{"from": "2026-10-09", "through": S16}])
        # persisted to the artifact on disk
        on_disk = json.loads(
            (out_dir / "case_artifacts" / f"TEST_{S16}.json").read_text())
        self.assertEqual(on_disk["provider_metadata"]["schema_version"], 1)
        # existing fields intact
        for key in ("ticker", "decision_session", "signal", "final_state_hash"):
            self.assertIn(key, on_disk)
        self.assertEqual(on_disk["signal"], "Hold")

    def _state(self):
        return {
            "investment_debate_state": {"bull_history": "b", "bear_history": "e",
                                        "judge_decision": ""},
            "risk_debate_state": {"judge_decision": ""},
            "investment_plan": "**Recommendation**: Hold",
            "trader_investment_plan": "**Action**: HOLD",
            "final_trade_decision": "**Rating**: Hold",
        }

    def test_zero_provider_calls_still_produces_metadata(self):
        result, _ = self._run_one(lambda: (self._state(), "Hold"))
        meta = result["provider_metadata"]
        self.assertEqual(meta["coverage"]["news"]["status"], "NOT_QUERIED")
        self.assertFalse(meta["information_cutoff"]["complete"])

    def test_instrumentation_failure_is_non_fatal(self):
        def propagate():
            provenance._run = {"observations": 42}  # corrupt mid-run state
            return (self._state(), "Hold")
        result, _ = self._run_one(propagate)
        self.assertEqual(result["signal"], "Hold")
        self.assertIn("provider_metadata", result)
        self.assertTrue(result["provider_metadata"]["instrumentation_errors"])


if __name__ == "__main__":
    unittest.main()
