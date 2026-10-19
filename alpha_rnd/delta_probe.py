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


def _fetch_news(ticker: str, prior_date: str, current_session: str):
    from tradingagents.dataflows import router

    return router.route_to_vendor("get_news", ticker, prior_date, current_session)


def _fetch_market(current_session: str, look_back_days: int):
    from tradingagents.dataflows import router

    # Normal analysis grounds macro/market context in global news AND FRED
    # macro series — a headline gap alone cannot prove market stability.
    router.route_to_vendor("get_global_news", current_session, look_back_days)
    router.route_to_vendor(
        "get_macro_indicators", "fed_funds_rate", current_session, look_back_days)


def _fetch_social(ticker: str, prior_date: str, current_session: str):
    from tradingagents.dataflows.vendors.reddit import fetch_reddit_posts
    from tradingagents.dataflows.vendors.stocktwits import fetch_stocktwits_messages

    # Both fetchers degrade to placeholder text and self-observe provenance;
    # only the gap window is requested so a historical probe sees no newer chatter.
    fetch_stocktwits_messages(
        ticker, limit=30, start_date=prior_date, end_date=current_session)
    fetch_reddit_posts(ticker, start_date=prior_date, end_date=current_session)
    return ["stocktwits", "reddit"]  # two real provider attempts


def _fetch_price(ticker: str, current_session: str, look_back_days: int):
    from tradingagents.dataflows.vendors.yahoo.snapshot import (
        build_verified_market_snapshot,
    )

    # One verified snapshot anchored at the session date: proves coverage back
    # to the first row and exposes the latest close — no multi-year OHLCV fetch.
    build_verified_market_snapshot(
        ticker, current_session, look_back_days=look_back_days)
    return ["yfinance_snapshot"]


def _safe(fn, family: str, errors: list, direct_calls: list):
    """Run a fetcher; returns its provider-attempt names into direct_calls.

    Router-routed fetchers return None — their attempts are already counted
    at the router layer, so a logical request is never double-counted.
    """
    try:
        providers = fn()
        if providers:
            direct_calls.extend(providers)
        return None
    except Exception as exc:
        errors.append(f"{family}: {type(exc).__name__}: {exc}")
        return None


def probe_gap(ticker: str, prior_cutoff: str, current_session: str,
              prior_close: float | None = None, fetchers: dict | None = None) -> dict:
    """Minimal deterministic gap probe across every evidence family.

    No model calls. Each family is queried only for the window
    (prior_cutoff, current_session]; whatever a provider cannot prove for that
    window stays non-COMPLETE and the caller fails closed. ``fetchers`` may
    override {"news", "social", "market", "price"} callables (testing).
    """
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
    gap_days = max(
        1, (date.fromisoformat(current_session) - date.fromisoformat(prior_date)).days)
    fetchers = fetchers or {}
    fetch_news = fetchers.get("news") or (lambda: _fetch_news(ticker, prior_date, current_session))
    fetch_social = fetchers.get("social") or (lambda: _fetch_social(ticker, prior_date, current_session))
    fetch_market = fetchers.get("market") or (lambda: _fetch_market(current_session, gap_days))
    fetch_price = fetchers.get("price") or (lambda: _fetch_price(ticker, current_session, gap_days))
    started = time.monotonic()
    provenance.begin(ticker, current_session)
    errors = []
    direct_calls = []
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
        _safe(fetch_news, "news", errors, direct_calls)
        _safe(fetch_social, "social", errors, direct_calls)
        _safe(fetch_market, "market_sector", errors, direct_calls)
        _safe(fetch_price, "price_technical", errors, direct_calls)
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
    meta_coverage = metadata.get("coverage", {})

    def _family(family: str) -> dict:
        entry = meta_coverage.get(family) or {}
        status = entry.get("status")
        if status in (None, "NOT_QUERIED", "FAILED"):
            return {"status": "UNKNOWN"}
        if status != "COMPLETE":
            return {"status": status}
        if not intervals_cover(entry.get("intervals", []), prior_date, current_session):
            return {"status": "PARTIAL"}
        return {"status": "COMPLETE"}

    coverage = {family: _family(family) for family in REQUIRED_EVIDENCE}
    coverage["filings"] = {"status": filings["status"]}
    # Earnings/corporate classification is deterministic over the full news
    # set: every item is checked against the term lists, so coverage is
    # COMPLETE whenever filings + news windows are proven. Unclassified
    # headlines are not a coverage failure — they flow to UPDATE, where the
    # update reasoner sees them in full and can escalate to FULL_REFRESH.
    event_status = (
        "COMPLETE"
        if coverage["filings"]["status"] == "COMPLETE"
        and coverage["news"]["status"] == "COMPLETE"
        else "UNKNOWN"
    )
    coverage["earnings_or_guidance"] = {"status": event_status}
    coverage["corporate_events"] = {"status": event_status}
    price_meta = metadata.get("price_technical") or {}
    new_close = price_meta.get("close")
    if not isinstance(new_close, (int, float)):
        coverage["price_technical"] = {"status": "UNKNOWN"}
        new_close = None
    price_change_pct = (
        round((new_close - prior_close) / prior_close * 100, 4)
        if prior_close and new_close is not None else None
    )
    if coverage["price_technical"]["status"] == "COMPLETE" and new_close is None:
        coverage["price_technical"] = {"status": "UNKNOWN"}
    def _items(family: str, limit: int = 20) -> list:
        items = []
        for call in metadata.get("calls", []):
            if call.get("family") == family:
                items.extend(call.get("items") or [])
        return items[:limit]

    social_items = _items("social")
    market_items = _items("market_sector")
    social_count = (metadata.get("social_sentiment") or {}).get("item_count")
    market_count = (metadata.get("market_sector") or {}).get("item_count")
    calls = [call for call in metadata.get("calls", []) if call.get("layer") == "router"]
    cache_calls = [
        call for call in metadata.get("calls", []) if isinstance(call.get("cache"), dict)
    ]
    cik_mapping_calls = [
        call for call in cache_calls if call.get("method") == "cache:company_tickers.json"
    ]
    # Logical provider requests: SEC submissions + one per routed logical call
    # (deduplicated by call_id, matching analysis_metrics.provider_call_metrics)
    # + one per direct vendor attempt (stocktwits/reddit/snapshot are not
    # routed, so each named provider is a real attempt).
    logical_router = len({call.get("call_id") for call in calls if call.get("call_id")}) \
        or len(calls)
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
        reasons.append("ORDINARY_NEWS_DELTA")
    if social_count:
        reasons.append("SOCIAL_DELTA")
    if market_count:
        reasons.append("MARKET_SECTOR_DELTA")
    if price_change_pct is not None and abs(price_change_pct) >= 5:
        reasons.append("MATERIAL_PRICE_MOVE")
    refresh_triggers = {
        "NEW_FILING", "EARNINGS_OR_GUIDANCE", "CORPORATE_EVENT",
        "MATERIAL_PRICE_MOVE",
    }
    if any(value["status"] != "COMPLETE" for value in coverage.values()):
        classification = "FULL_REFRESH_REQUIRED"
        reasons.append("INCOMPLETE_COVERAGE")
    elif reasons and set(reasons) & refresh_triggers:
        classification = "FULL_REFRESH_REQUIRED"
    elif news or social_count or market_count or (
            price_change_pct is not None and abs(price_change_pct) > 1):
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
        "unclassified_news": unclassified_news,
        "corporate_events": corporate,
        "price_technical": {
            "close": new_close,
            "latest_bar_date": price_meta.get("latest_bar_date"),
            "provider": price_meta.get("provider"),
            "prior_close": prior_close,
            "price_change_pct": price_change_pct,
        },
        "social": {"item_count": social_count, "items": social_items,
                   "items_digest": (metadata.get("social_sentiment") or {}).get("items_digest")},
        "market_sector": {"item_count": market_count, "items": market_items,
                          "items_digest": (metadata.get("market_sector") or {}).get("items_digest")},
        "coverage": coverage,
        "classification": classification,
        "reasons": sorted(set(reasons)),
        "provider_call_count": 1 + logical_router + len(cik_mapping_calls) + len(direct_calls),
        "provider_attempts": 1 + len(calls) + len(cik_mapping_calls) + len(direct_calls),
        "logical_router_calls": logical_router,
        "direct_provider_calls": len(direct_calls),
        "direct_providers": direct_calls,
        "cache_hits": sum(call["cache"].get("hit") is True for call in cache_calls),
        "external_network_call_count": None,
        "known_external_network_calls": known_external,
        "external_network_quality": "PARTIAL" if calls else "MEASURED",
        "elapsed_ms": round((time.monotonic() - started) * 1000, 3),
        "swe_calls": 0,
        "fetch_errors": errors,
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
