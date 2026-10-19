import re
import time
from datetime import date, datetime

from alpha_rnd.reuse_shadow import REQUIRED_EVIDENCE


_EARNINGS_TERMS = re.compile(
    r"\b(earnings|quarterly results|financial results|guidance|outlook)\b", re.I
)
_CORPORATE_TERMS = re.compile(
    r"\b(merger|acquisition|acquires|bankruptcy|restructuring|dilution|"
    r"chief executive|chief financial|ceo|cfo|lawsuit|regulatory|approval|"
    r"rejection|dividend|buyback|stock split|major contract)\b", re.I
)
def probe_gap(ticker: str, prior_cutoff: str, current_session: str) -> dict:
    from tradingagents.dataflows import provenance, router
    from tradingagents.dataflows.provenance import intervals_cover
    from tradingagents.dataflows.vendors import sec_edgar

    if not re.fullmatch(r"[A-Z0-9.-]+", ticker):
        raise ValueError("ticker must be normalized")
    date.fromisoformat(current_session)
    prior_date = prior_cutoff[:10]
    date.fromisoformat(prior_date)
    if prior_date > current_session:
        raise ValueError("prior cutoff must not follow the current session")
    if "T" in prior_cutoff:
        datetime.fromisoformat(prior_cutoff.replace("Z", "+00:00"))
    started = time.monotonic()
    provenance.begin(ticker, current_session)
    try:
        filings = sec_edgar.submissions_filings(ticker, prior_date, current_session)
        provenance.observe(
            "filings", "sec_edgar", "submissions", "ok" if filings["status"] == "COMPLETE" else "failed",
            requested_from=prior_date, requested_to=current_session,
            coverage=(
                {"from": prior_date, "through": current_session}
                if filings["status"] == "COMPLETE" else None
            ),
            items=filings.get("events", []),
            network_calls=1,
        )
        router.route_to_vendor("get_news", ticker, prior_date, current_session)
        metadata = provenance.finish()
    except Exception:
        metadata = provenance.finish()
        raise

    news = metadata.get("news", [])
    earnings, corporate = classify_news_titles(news)
    classified = {id(item) for item in earnings + corporate}
    unclassified_news = [
        item for item in news if id(item) not in classified
    ]
    coverage = {
        family: {"status": "NOT_QUERIED"} for family in REQUIRED_EVIDENCE
    }
    coverage["filings"] = {"status": filings["status"]}
    news_coverage = metadata.get("coverage", {}).get("news") or {}
    news_complete = (
        news_coverage.get("status") == "COMPLETE"
        and intervals_cover(news_coverage.get("intervals", []), prior_date, current_session)
    )
    coverage["news"] = {"status": "COMPLETE" if news_complete else "PARTIAL"}
    event_status = (
        "COMPLETE"
        if coverage["filings"]["status"] == "COMPLETE"
        and coverage["news"]["status"] == "COMPLETE"
        else "UNKNOWN"
    )
    coverage["earnings_or_guidance"] = {
        "status": "UNKNOWN" if unclassified_news else event_status
    }
    coverage["corporate_events"] = {
        "status": "UNKNOWN" if unclassified_news else event_status
    }
    calls = [call for call in metadata.get("calls", []) if call.get("layer") == "router"]
    cache_calls = [
        call for call in metadata.get("calls", []) if isinstance(call.get("cache"), dict)
    ]
    cik_mapping_calls = [
        call for call in cache_calls if call.get("method") == "cache:company_tickers.json"
    ]
    known_external = sum(
        call.get("network_calls", 0)
        + int(isinstance(call.get("cache"), dict) and call["cache"].get("hit") is False)
        for call in metadata.get("calls", [])
    )
    reasons = []
    if filings.get("events"):
        reasons.append("NEW_FILING")
    if earnings:
        reasons.append("EARNINGS_OR_GUIDANCE")
    if corporate:
        reasons.append("CORPORATE_EVENT")
    if unclassified_news:
        reasons.append("UNCLASSIFIED_COMPANY_NEWS")
    if any(value["status"] != "COMPLETE" for value in coverage.values()):
        classification = "FULL_REFRESH_REQUIRED"
        reasons.append("INCOMPLETE_COVERAGE")
    elif reasons:
        classification = "FULL_REFRESH_REQUIRED"
    elif news:
        classification = "UPDATE_MODE_RECOMMENDED"
    else:
        classification = "REUSE"
    return {
        "ticker": ticker,
        "prior_cutoff": prior_cutoff,
        "current_session": current_session,
        "filings": filings.get("events", []),
        "earnings_or_guidance": earnings,
        "news": news,
        "corporate_events": corporate,
        "price_technical": None,
        "social": None,
        "market_sector": None,
        "coverage": coverage,
        "classification": classification,
        "reasons": sorted(set(reasons)),
        "provider_call_count": 1 + len(calls) + len(cik_mapping_calls),
        "cache_hits": sum(call["cache"].get("hit") is True for call in cache_calls),
        "external_network_call_count": None,
        "known_external_network_calls": known_external,
        "external_network_quality": "PARTIAL" if calls else "MEASURED",
        "elapsed_ms": round((time.monotonic() - started) * 1000, 3),
        "swe_calls": 0,
        "instrumentation_errors": metadata.get("instrumentation_errors", []),
    }


def classify_news_titles(items: list[dict]) -> tuple[list[dict], list[dict]]:
    earnings = [
        item for item in items
        if isinstance(item.get("title"), str) and _EARNINGS_TERMS.search(item["title"])
    ]
    corporate = [
        item for item in items
        if isinstance(item.get("title"), str) and _CORPORATE_TERMS.search(item["title"])
    ]
    return earnings, corporate
