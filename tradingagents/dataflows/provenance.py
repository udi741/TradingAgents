"""Passive, run-scoped provider-call provenance recorder (observability only).

``begin()`` arms a recorder for one analysis run; instrumented router/vendor
code calls ``observe()``; ``finish()`` aggregates the observations into a
JSON-serializable ``provider_metadata`` doc for the case artifact. Every entry
point is best-effort: a recorder failure is noted under
``instrumentation_errors`` and never raised into the analysis path.

Coverage semantics: an observation's ``coverage`` dict is the interval the
provider actually observed (``from`` may be None for an unbounded history), NOT
merely the requested window — a feed that only serves recent items records the
bound of what it saw. Absence of events inside a covered window is evidence;
absence of a covered window is not.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

SCHEMA_VERSION = 1
MAX_ITEMS_PER_CALL = 60
# Evidence families the reuse-shadow comparison requires. Families with no
# dedicated provider (earnings/guidance, corporate events) stay NOT_QUERIED —
# never fabricated as covered.
REQUIRED_FAMILIES = (
    "filings", "earnings_or_guidance", "news", "social",
    "market_sector", "price_technical", "corporate_events",
)

_run: dict | None = None


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _err(exc: Exception) -> None:
    try:
        _run["errors"].append(f"{type(exc).__name__}: {exc}"[:300])
    except Exception:
        pass


# Positional-arg layout of each routed method: (from_index, through_index);
# _LOOKBACK gives the arg index of a trailing look-back window in days.
_WINDOWS = {
    "get_stock_data": (1, 2),
    "get_indicators": (None, 2),
    "get_fundamentals": (None, 1),
    "get_balance_sheet": (None, 2),
    "get_cashflow": (None, 2),
    "get_income_statement": (None, 2),
    "get_news": (1, 2),
    "get_global_news": (None, 0),
    "get_insider_transactions": (None, 1),
    "get_macro_indicators": (None, 1),
    "get_prediction_markets": (None, 2),
}
_LOOKBACK = {"get_global_news": 1, "get_macro_indicators": 2, "get_indicators": 3}


def call_window(method: str, args: tuple, kwargs: dict) -> tuple[str | None, str | None]:
    """(requested_from, requested_to) for a routed call, best-effort."""
    try:
        spec = _WINDOWS.get(method)
        if spec is None:
            return None, None
        pos = list(args) + [None] * 4
        start_i, end_i = spec
        through = pos[end_i] if end_i is not None else None
        if through is None or not isinstance(through, str):
            through = None
        start = pos[start_i] if start_i is not None else None
        if not isinstance(start, str):
            start = None
        lb_i = _LOOKBACK.get(method)
        if start is None and lb_i is not None:
            lb = pos[lb_i]
            if isinstance(lb, int) and through:
                from datetime import timedelta
                start = (_parse_dt(through) - timedelta(days=lb)).date().isoformat()
        return start, through
    except Exception:
        return None, None


def begin(ticker: str | None = None, session: str | None = None) -> None:
    """Arm the recorder for a run; resets any leftover state from a crashed run."""
    global _run
    _run = {"ticker": ticker, "session": session, "observations": [], "errors": []}


def active() -> bool:
    return _run is not None


def observe(
    family: str,
    source: str,
    method: str,
    status: str,
    *,
    requested_from: str | None = None,
    requested_to: str | None = None,
    coverage: dict | None = None,
    items: list | None = None,
    **extra,
) -> None:
    """Record one provider observation. ``status``: ok | empty | failed.

    ``requested_*`` is the window the caller asked for; ``coverage`` is the
    interval the source PROVABLY observed — ``{"from": ..., "through": ...}``
    where ``from`` may be None only for a genuinely unbounded history. They are
    not interchangeable: omit ``coverage`` entirely when achieved coverage is
    not proven.
    """
    if _run is None:
        return
    try:
        rec = {
            "family": family,
            "source": source,
            "method": method,
            "status": status,
            "observed_at": _now(),
        }
        if requested_from is not None or requested_to is not None:
            rec["requested"] = {"from": requested_from, "to": requested_to}
        if isinstance(coverage, dict) and coverage.get("through") is not None:
            rec["coverage"] = {"from": coverage.get("from"),
                               "through": coverage["through"]}
        if items:
            rec["items"] = items[:MAX_ITEMS_PER_CALL]
        rec.update(extra)
        _run["observations"].append(rec)
    except Exception as exc:
        _err(exc)


def item_id(*parts) -> str:
    """Stable short id for an evidence item (never its full body)."""
    return hashlib.sha256("\x1f".join(str(p) for p in parts).encode()).hexdigest()[:16]


def feed_coverage(dates, start_date: str | None, end_date: str | None) -> dict | None:
    """Achieved coverage of a latest-items-only feed over [start_date, end_date].

    Mirrors date_window.coverage_gap: coverage reaches the oldest returned item
    and ends at today. Returns the covered interval, or None when nothing the
    feed served can prove coverage of the window.
    """
    try:
        now = datetime.now(UTC)
        oldest = min(
            (d for d in (
                d if isinstance(d, datetime) else _parse_dt(d) for d in dates)
             if d is not None),
            default=now,
        )
        if end_date:
            through = min(end_date, now.date().isoformat())
        else:
            through = now.date().isoformat()
        if start_date and oldest.date().isoformat() > start_date:
            covered_from = oldest.date().isoformat()
            if covered_from > through:
                return None
            return {"from": covered_from, "through": through}
        return {"from": start_date or covered_from_or_now(oldest), "through": through}
    except Exception:
        return None


def covered_from_or_now(oldest: datetime) -> str:
    return oldest.date().isoformat() if isinstance(oldest, datetime) else datetime.now(UTC).date().isoformat()


def _parse_dt(value) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _day(value) -> "date | None":
    from datetime import date
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _touches(prev_through, nxt_from) -> bool:
    """Two spans form one continuous coverage block when the next starts no
    later than the day after the previous ends (dates are inclusive)."""
    if prev_through is None or nxt_from is None:
        return True  # an unbounded end absorbs everything after it
    a, b = _day(prev_through), _day(nxt_from)
    if a is not None and b is not None:
        from datetime import timedelta
        return b <= a + timedelta(days=1)
    return str(nxt_from) <= str(prev_through)


def merge_intervals(intervals: list[dict]) -> list[dict]:
    """Merge overlapping/touching achieved-coverage spans. NEVER bridges a
    proven gap: disjoint spans remain disjoint in the output."""
    spans = sorted(
        ((iv.get("from"), iv.get("through")) for iv in intervals
         if isinstance(iv, dict)),
        key=lambda s: (s[0] is not None, str(s[0])),
    )
    merged: list[list] = []
    for frm, through in spans:
        if merged and _touches(merged[-1][1], frm):
            if merged[-1][1] is not None and (
                    through is None or str(through) > str(merged[-1][1])):
                merged[-1][1] = through
        else:
            merged.append([frm, through])
    return [{"from": f, "through": t} for f, t in merged]


def intervals_cover(intervals: list[dict], need_from: str, need_through: str) -> bool:
    """Whether the merged achieved spans provably cover [need_from, need_through]."""
    merged = merge_intervals(intervals)
    for span in merged:
        frm, through = span["from"], span["through"]
        if frm is not None and str(frm)[:10] > str(need_from)[:10]:
            continue  # this span starts too late; earlier spans are sorted before
        if through is None or str(through)[:10] >= str(need_through)[:10]:
            return True
    return False


def _family_status(obs: list[dict]) -> str:
    contributing = [
        o for o in obs
        if o["status"] in ("ok", "empty") and o.get("coverage")
        and not o.get("cik_facts")
    ]
    failed = [o for o in obs if o["status"] == "failed"]
    if not contributing:
        return "FAILED" if failed else "UNKNOWN"
    return "PARTIAL" if failed else "COMPLETE"


def _family_coverage(obs: list[dict]) -> dict:
    contributing = [
        o for o in obs
        if o["status"] in ("ok", "empty") and o.get("coverage")
        and not o.get("cik_facts")
    ]
    merged = merge_intervals([o["coverage"] for o in contributing])
    cov = {
        "status": _family_status(obs),
        "intervals": merged,
        "observed_at": max(o["observed_at"] for o in obs),
        "sources": sorted({o["source"] for o in obs}),
        "queries": len(obs),
        "items": sum(len(o.get("items") or []) for o in obs),
    }
    if len(merged) == 1:
        cov["from"], cov["through"] = merged[0]["from"], merged[0]["through"]
    else:
        cov["from"] = cov["through"] = None
        cov["contiguous"] = False
    return cov


def _merge_extras(obs: list[dict], keys: tuple[str, ...]) -> dict:
    out: dict = {}
    for o in obs:
        for key in keys:
            if key in o:
                out[key] = o[key]
    return out


def finish() -> dict:
    """Aggregate observations into the persisted provider_metadata doc."""
    global _run
    state = _run
    _run = None
    if not isinstance(state, dict) or not isinstance(state.get("observations"), list):
        return {"schema_version": SCHEMA_VERSION,
                "captured_at": _now(),
                "coverage": {f: {"status": "UNKNOWN"} for f in REQUIRED_FAMILIES},
                "instrumentation_errors": ["finish() without a valid begin()"]}
    try:
        obs = state["observations"]
        by_family: dict[str, list[dict]] = {}
        for o in obs:
            by_family.setdefault(o.get("family", "unknown"), []).append(o)
        coverage = {}
        for fam in REQUIRED_FAMILIES:
            fam_obs = by_family.get(fam, [])
            coverage[fam] = _family_coverage(fam_obs) if fam_obs else {"status": "NOT_QUERIED"}
        for fam in sorted(set(by_family) - set(REQUIRED_FAMILIES)):
            coverage[fam] = _family_coverage(by_family[fam])

        filings, news, insider = [], [], []
        for o in obs:
            for it in o.get("items") or []:
                target = {"filings": filings, "news": news, "insider": insider}.get(o["family"])
                if target is not None:
                    target.append(it)
        seen = set()
        for lst in (filings, news, insider):
            lst.sort(key=lambda i: str(i.get("filed_at") or i.get("published_at") or i.get("date") or ""))
            deduped = []
            for it in lst:
                key = it.get("id") or json_key(it)
                if key in seen:
                    continue
                seen.add(key)
                deduped.append(it)
            lst[:] = deduped

        complete_throughs = [
            coverage[f]["through"] for f in REQUIRED_FAMILIES
            if coverage[f]["status"] == "COMPLETE" and coverage[f].get("through")
        ]
        incomplete = [f for f in REQUIRED_FAMILIES if coverage[f]["status"] != "COMPLETE"]
        cutoff = {
            "value": min(complete_throughs) if complete_throughs else None,
            "precision": "date" if not incomplete else "incomplete",
            "complete": not incomplete,
            "incomplete_families": incomplete,
            "per_family_through": {f: coverage[f].get("through") for f in coverage},
        }

        def _family_items(fam: str) -> list:
            return [it for o in by_family.get(fam, []) for it in (o.get("items") or [])]

        social = _merge_extras(
            by_family.get("social", []), ("stocktwits", "reddit", "item_count"))
        social["item_count"] = len(_family_items("social"))
        social["items_digest"] = item_id(*sorted(str(i.get("id")) for i in _family_items("social"))) \
            if _family_items("social") else None
        market = _merge_extras(
            by_family.get("market_sector", []),
            ("global_news", "macro", "prediction_markets"))
        market["item_count"] = len(_family_items("market_sector"))
        market["items_digest"] = item_id(*sorted(str(i.get("id")) for i in _family_items("market_sector"))) \
            if _family_items("market_sector") else None

        doc = {
            "schema_version": SCHEMA_VERSION,
            "ticker": state.get("ticker"),
            "session": state.get("session"),
            "captured_at": _now(),
            "coverage": coverage,
            "filings": filings,
            "earnings_or_guidance": [],
            "news": news,
            "corporate_events": [],
            "insider": insider,
            "price_technical": _merge_extras(
                by_family.get("price_technical", []),
                ("close", "latest_bar_date", "provider", "cache")),
            "social_sentiment": social,
            "market_sector": market,
            "information_cutoff": cutoff,
            "calls": obs,
            "instrumentation_errors": state["errors"],
        }
        return doc
    except Exception as exc:
        return {
            "schema_version": SCHEMA_VERSION,
            "ticker": state.get("ticker"),
            "session": state.get("session"),
            "captured_at": _now(),
            "coverage": {f: {"status": "UNKNOWN"} for f in REQUIRED_FAMILIES},
            "instrumentation_errors": [f"finish failed: {type(exc).__name__}: {exc}"],
        }


def json_key(item: dict) -> str:
    import json
    return json.dumps(item, sort_keys=True, default=str)
