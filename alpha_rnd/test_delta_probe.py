import tempfile
import unittest
from pathlib import Path
from unittest import mock

from alpha_rnd import delta_probe

IDLE_FETCHERS = {"social": lambda: None, "market": lambda: None, "price": lambda: None}


def _observe(family, source, start, end, items=None, **extra):
    provenance.observe(
        family, source, f"mock_{family}", "ok" if items else "empty",
        requested_from=start, requested_to=end,
        coverage={"from": start, "through": end}, items=items or [], **extra)


def full_fetchers(start="2026-10-15", end="2026-10-16", close=100.0,
                  social_items=None, market_items=None):
    return {
        "social": lambda: [
            _observe("social", "stocktwits", start, end, social_items),
            _observe("social", "reddit", start, end)],
        "market": lambda: _observe(
            "market_sector", "yfinance", start, end, market_items),
        "price": lambda: _observe(
            "price_technical", "yfinance", start, end, close=close),
    }
from tradingagents.dataflows import provenance
from tradingagents.dataflows.vendors import sec_edgar


class DeltaProbeTest(unittest.TestCase):
    def tearDown(self):
        provenance.finish()

    def test_new_sec_filing_fails_closed_without_model_call(self):
        def news_call(method, ticker, start, end):
            provenance.observe(
                "news", "yfinance", method, "empty",
                requested_from=start, requested_to=end,
                coverage={"from": start, "through": end}, layer="router",
            )

        with mock.patch.object(sec_edgar, "submissions_filings", return_value={
            "status": "COMPLETE",
            "events": [{
                "form": form, "filed_at": "2026-10-16",
                "accession": form, "id": form,
            } for form in ("10-Q", "10-K", "8-K", "6-K")],
        }), mock.patch("tradingagents.dataflows.router.route_to_vendor", side_effect=news_call):
            result = delta_probe.probe_gap("TEST", "2026-10-15", "2026-10-16", fetchers=IDLE_FETCHERS)
        self.assertEqual(result["classification"], "FULL_REFRESH_REQUIRED")
        self.assertEqual(result["provider_call_count"], 2)
        self.assertEqual(result["swe_calls"], 0)
        self.assertEqual(result["coverage"]["earnings_or_guidance"]["status"], "COMPLETE")

    def test_earnings_and_corporate_headlines_are_deterministic(self):
        earnings, corporate = delta_probe.classify_news_titles([
            {"title": "Company raises full-year guidance"},
            {"title": "Company announces merger agreement"},
            {"title": "Routine product update"},
        ])
        self.assertEqual(len(earnings), 1)
        self.assertEqual(len(corporate), 1)

    def test_earnings_and_material_company_news_require_full_refresh(self):
        for title in (
            "Company raises full-year guidance",
            "Company announces merger agreement",
        ):
            with self.subTest(title=title):
                def news_call(method, ticker, start, end):
                    provenance.observe(
                        "news", "yfinance", method, "ok",
                        requested_from=start, requested_to=end,
                        coverage={"from": start, "through": end},
                        items=[{
                            "id": title, "title": title,
                            "published_at": "2026-10-16T12:00:00+00:00",
                        }],
                        layer="router",
                    )

                with mock.patch.object(sec_edgar, "submissions_filings", return_value={
                    "status": "COMPLETE", "events": [],
                }), mock.patch("tradingagents.dataflows.router.route_to_vendor",
                               side_effect=news_call):
                    result = delta_probe.probe_gap("TEST", "2026-10-15", "2026-10-16", fetchers=IDLE_FETCHERS)
                self.assertEqual(result["classification"], "FULL_REFRESH_REQUIRED")

    def test_no_event_with_proven_event_coverage_has_complete_event_families(self):
        def news_call(method, ticker, start, end):
            provenance.observe(
                "news", "yfinance", method, "empty",
                requested_from=start, requested_to=end,
                coverage={"from": start, "through": end}, layer="router",
            )

        with mock.patch.object(sec_edgar, "submissions_filings", return_value={
            "status": "COMPLETE", "events": [],
        }), mock.patch("tradingagents.dataflows.router.route_to_vendor", side_effect=news_call):
            result = delta_probe.probe_gap("TEST", "2026-10-15", "2026-10-16", fetchers=IDLE_FETCHERS)
        self.assertEqual(result["coverage"]["earnings_or_guidance"]["status"], "COMPLETE")
        self.assertEqual(result["coverage"]["corporate_events"]["status"], "COMPLETE")
        self.assertEqual(result["classification"], "FULL_REFRESH_REQUIRED")

    def test_incomplete_event_coverage_fails_closed(self):
        with mock.patch.object(sec_edgar, "submissions_filings", return_value={
            "status": "PARTIAL", "events": [],
        }), mock.patch("tradingagents.dataflows.router.route_to_vendor", return_value=""):
            result = delta_probe.probe_gap("TEST", "2026-10-15", "2026-10-16", fetchers=IDLE_FETCHERS)
        self.assertEqual(result["classification"], "FULL_REFRESH_REQUIRED")
        self.assertIn("INCOMPLETE_COVERAGE", result["reasons"])

    def test_unclassified_company_news_flows_to_update(self):
        def news_call(method, ticker, start, end):
            provenance.observe(
                "news", "yfinance", method, "ok",
                requested_from=start, requested_to=end,
                coverage={"from": start, "through": end},
                items=[{"id": "n1", "title": "Company updates a strategic agreement"}],
                layer="router",
            )

        with mock.patch.object(sec_edgar, "submissions_filings", return_value={
            "status": "COMPLETE", "events": [],
        }), mock.patch("tradingagents.dataflows.router.route_to_vendor",
                       side_effect=news_call):
            result = delta_probe.probe_gap("TEST", "2026-10-15", "2026-10-16",
                                           prior_close=100.0, fetchers=full_fetchers())
        # Deterministic classification examined every item; the headline is
        # ordinary news, which routes to UPDATE (the update reasoner sees it in
        # full and can escalate) rather than failing the coverage check.
        self.assertEqual(result["coverage"]["earnings_or_guidance"]["status"], "COMPLETE")
        self.assertEqual(result["coverage"]["corporate_events"]["status"], "COMPLETE")
        self.assertIn("ORDINARY_NEWS_DELTA", result["reasons"])
        self.assertEqual(result["classification"], "UPDATE_MODE_RECOMMENDED")

    def test_sec_submissions_extracts_accession_and_rejects_ambiguous_window(self):
        payload = {"filings": {"recent": {
            "filingDate": ["2026-10-16", "2026-10-15", "2026-10-01"],
            "form": ["8-K", "10-Q", "10-K"],
            "accessionNumber": ["a1", "a2", "a0"],
            "primaryDocument": ["a.htm", "b.htm", "c.htm"],
            "primaryDocDescription": ["Current report", "Quarterly report", "Annual report"],
        }}}
        with tempfile.TemporaryDirectory() as temp, \
                mock.patch.object(sec_edgar, "cik_for", return_value="0000000001"), \
                mock.patch.object(sec_edgar, "_fetch_json", return_value=payload), \
                mock.patch.object(sec_edgar, "get_config",
                                  return_value={"data_cache_dir": temp}):
            result = sec_edgar.submissions_filings("TEST", "2026-10-14", "2026-10-16")
            ambiguous = sec_edgar.submissions_filings(
                "TEST", "2026-10-15T12:00:00+00:00", "2026-10-16")
            cached = (Path(temp) / "sec_edgar" / "submissions_0000000001.json").exists()
        self.assertEqual(result["events"][0]["form"], "8-K")
        self.assertEqual(result["events"][0]["accession"], "a1")
        self.assertEqual(ambiguous["status"], "PARTIAL")
        self.assertTrue(cached)


if __name__ == "__main__":
    unittest.main()
