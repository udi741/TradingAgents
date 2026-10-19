"""Read-only prior-case comparison for ALPHA analysis reuse experiments."""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import UTC, date, datetime
from pathlib import Path

from alpha_rnd.case_integrity import verify_case

ROOT = Path(__file__).resolve().parents[1]
EV_DIR = ROOT / "evaluations" / "alpha_rnd_v1"
CASE_DIR = EV_DIR / "case_artifacts"
FACTS_DIR = EV_DIR
SHADOW_DIR = EV_DIR / "reuse_shadow"
SCHEMA_VERSION = 1
REQUIRED_EVIDENCE = (
    "filings", "earnings_or_guidance", "news", "social",
    "market_sector", "price_technical", "corporate_events",
)
REPORT_FIELDS = (
    "market_report", "sentiment_report", "news_report", "fundamentals_report",
)
MODEL_OUTPUT_FIELDS = REPORT_FIELDS + (
    "bull_history", "bear_history", "judge_decision", "investment_plan",
    "trader_investment_plan", "risk_judge_decision", "final_trade_decision",
)
_CASE_NAME = re.compile(r"^([A-Z0-9.-]+)_(\d{4}-\d{2}-\d{2})\.json$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_PRICE_VALUE = r"\**\s*\$?\s*\**\s*([\d,]+(?:\.\d+)?)\**"


def _json(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None


def _valid_date(value: str) -> bool:
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        return False


def _validate_identity(ticker: str, session: str) -> None:
    if (not re.fullmatch(r"[A-Z0-9.-]+", ticker) or not _DATE.fullmatch(session)
            or not _valid_date(session)):
        raise ValueError("ticker and session must be normalized")


def _valid_artifact(artifact, ticker: str, session: str) -> bool:
    return (
        isinstance(artifact, dict)
        and artifact.get("ticker") == ticker
        and artifact.get("decision_session") == session
        and (
            (isinstance(artifact.get("signal"), str) and bool(artifact["signal"]))
            or (isinstance(artifact.get("final_trade_decision"), str)
                and bool(artifact["final_trade_decision"]))
        )
    )


def _cutoff(artifact: dict, session: str) -> dict:
    for key in ("information_cutoff", "info_cutoff", "as_of_timestamp", "as_of"):
        value = artifact.get(key)
        if isinstance(value, dict):
            value = value.get("value") or value.get("timestamp")
        if isinstance(value, str) and value:
            if "T" in value:
                try:
                    datetime.fromisoformat(value.replace("Z", "+00:00"))
                    precision = "timestamp"
                except ValueError:
                    precision = "unknown"
            else:
                precision = "date" if _valid_date(value[:10]) else "unknown"
            return {"value": value, "precision": precision, "source": key}
    meta_cutoff = (artifact.get("provider_metadata") or {}).get("information_cutoff")
    if (isinstance(meta_cutoff, dict)
            and isinstance(meta_cutoff.get("value"), str) and meta_cutoff["value"]
            and meta_cutoff.get("precision") in ("timestamp", "date")):
        return {"value": meta_cutoff["value"], "precision": meta_cutoff["precision"],
                "source": "provider_metadata.information_cutoff"}
    return {
        "value": session,
        "precision": "session_date",
        "source": "decision_session",
        "note": "Date-only information cutoff; no reliable intraday timestamp is stored.",
    }


def _summary(artifact: dict) -> str:
    for field in ("thesis_summary", "previous_thesis", "thesis"):
        value = artifact.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()[:1600]
    decision = artifact.get("final_trade_decision") or artifact.get("investment_plan") or ""
    if not isinstance(decision, str):
        decision = ""
    match = re.search(
        r"(?:Executive Summary|Thesis|Summary)\**\s*[:—-]\s*(.+?)(?:\n\n|$)",
        decision,
        re.I | re.S,
    )
    return (match.group(1).strip() if match else decision.strip())[:1600]


def _target(artifact: dict):
    if artifact.get("price_target") is not None:
        return artifact["price_target"]
    text = "\n".join(
        str(artifact.get(key) or "")
        for key in ("final_trade_decision", "investment_plan", "fundamentals_report")
    )
    match = re.search(r"price target(?:\s+of|\s+at|[:\s])+\$?([\d,]+(?:\.\d+)?)", text, re.I)
    return float(match.group(1).replace(",", "")) if match else None


def _horizon(artifact: dict):
    if artifact.get("time_horizon") is not None:
        return artifact["time_horizon"]
    text = "\n".join(
        str(artifact.get(key) or "")
        for key in ("final_trade_decision", "investment_plan")
    )
    match = re.search(r"time horizon\s*[:=]\s*([^\n]+)", text, re.I)
    return match.group(1).strip() if match else None


def _stable_facts(ticker: str, session: str, facts_dir: Path):
    path = facts_dir / f"fundamental_facts_{session}.json"
    payload = _json(path)
    if not isinstance(payload, dict) or ticker not in payload:
        return None, None
    return payload[ticker], str(path)


def _prior_record(
    ticker: str, session: str, path: Path, artifact: dict, facts_dir: Path,
):
    stable_facts, facts_path = _stable_facts(ticker, session, facts_dir)
    schema_version = artifact.get("schema_version")
    return {
        "ticker": ticker,
        "session": session,
        "artifact_path": str(path),
        "info_cutoff": _cutoff(artifact, session),
        "decision": artifact.get("signal"),
        "portfolio_manager_decision": {
            "rating": artifact.get("pm_rating"),
            "decision": artifact.get("final_trade_decision"),
        },
        "risk_management_decision": {
            "rating": artifact.get("rm_rating"),
            "decision": artifact.get("risk_judge_decision"),
        },
        "thesis_summary": _summary(artifact),
        "previous_price_target": _target(artifact),
        "previous_time_horizon": _horizon(artifact),
        "schema_version": schema_version,
        "schema_info": "legacy-unversioned" if schema_version is None else schema_version,
        "previously_known_stable_facts": stable_facts,
        "stable_facts_artifact_path": facts_path,
        "integrity_verified": verify_case(artifact),
    }


def resolve_prior_case(
    ticker: str,
    session: str,
    case_dir: Path | None = None,
    facts_dir: Path | None = None,
) -> dict:
    _validate_identity(ticker, session)
    case_dir = Path(case_dir or CASE_DIR)
    facts_dir = Path(facts_dir or FACTS_DIR)
    candidates = []
    corrupt = []
    failed = []
    for path in case_dir.glob(f"{ticker}_*.json"):
        match = _CASE_NAME.fullmatch(path.name)
        error = re.fullmatch(
            rf"{re.escape(ticker)}_(\d{{4}}-\d{{2}}-\d{{2}})\.error\.json", path.name)
        if error:
            if error.group(1) < session:
                failed.append(path)
            continue
        if not match or match.group(1) != ticker or match.group(2) >= session:
            continue
        if not _valid_date(match.group(2)):
            corrupt.append((match.group(2), path))
            continue
        artifact = _json(path)
        if _valid_artifact(artifact, ticker, match.group(2)):
            candidates.append((match.group(2), path, artifact))
        else:
            corrupt.append((match.group(2), path))
    if candidates:
        prior_session, path, artifact = max(candidates, key=lambda row: row[0])
        issues = []
        if any(day > prior_session for day, _ in corrupt):
            issues.append("PRIOR_CASE_CORRUPT")
        schema = artifact.get("schema_version")
        if schema not in (None, SCHEMA_VERSION):
            issues.append("SCHEMA_INCOMPATIBLE")
        return {
            "prior_case": _prior_record(ticker, prior_session, path, artifact, facts_dir),
            "artifact": artifact,
            "issues": issues,
        }
    issues = []
    if corrupt:
        issues.append("PRIOR_CASE_CORRUPT")
    if failed:
        issues.append("PRIOR_ANALYSIS_FAILED")
    return {"prior_case": None, "artifact": None, "issues": issues}


def _facts_file(ticker: str, session: str, facts_dir: Path):
    payload = _json(facts_dir / f"fundamental_facts_{session}.json")
    if not isinstance(payload, dict):
        return None
    return payload.get(ticker)


def _last_filed(facts):
    dates = {}
    if not isinstance(facts, dict):
        return dates
    sections = facts.get("facts")
    if not isinstance(sections, dict):
        return dates
    for name, values in sections.items():
        if (isinstance(values, dict) and isinstance(values.get("last_filed"), str)
                and _valid_date(values["last_filed"])):
            dates[name] = values["last_filed"]
    return dates


def _has_invalid_filing_dates(facts) -> bool:
    sections = facts.get("facts") if isinstance(facts, dict) else None
    if not isinstance(sections, dict):
        return True
    return any(
        not isinstance(values, dict)
        or "last_filed" not in values
        or not isinstance(values["last_filed"], str)
        or not _valid_date(values["last_filed"])
        for values in sections.values()
    )


def _new_facts_filings(previous, current, cutoff_date: str):
    old = _last_filed(previous)
    new = _last_filed(current)
    filed = {}
    for name, filed_at in new.items():
        if filed_at > cutoff_date and filed_at > old.get(name, ""):
            filed.setdefault(filed_at, []).append(name)
    return [
        {"filed_at": filed_at, "form": None, "fact_categories": sorted(names),
         "source": "fundamental_facts_snapshot"}
        for filed_at, names in sorted(filed.items())
    ]


def _event_after_cutoff(event, cutoff: dict):
    if cutoff.get("precision") == "unknown":
        return None
    value = None
    if isinstance(event, dict):
        value = next(
            (event.get(key) for key in ("filed_at", "published_at", "date", "timestamp")
             if isinstance(event.get(key), str) and event[key]),
            None,
        )
    if value is None:
        return None
    event_date = value[:10]
    if not _valid_date(event_date):
        return None
    cutoff_value = cutoff.get("value", "")
    cutoff_date = cutoff_value[:10]
    if event_date == cutoff_date:
        if cutoff.get("precision") != "timestamp" or "T" not in value:
            return None
        try:
            event_time = datetime.fromisoformat(value.replace("Z", "+00:00"))
            cutoff_time = datetime.fromisoformat(cutoff_value.replace("Z", "+00:00"))
            if event_time.tzinfo is None:
                event_time = event_time.replace(tzinfo=UTC)
            if cutoff_time.tzinfo is None:
                cutoff_time = cutoff_time.replace(tzinfo=UTC)
            return event_time > cutoff_time
        except ValueError:
            return None
    return event_date > cutoff_date


def _new_events(metadata: dict, field: str, cutoff: dict):
    events = metadata.get(field)
    if not isinstance(events, list):
        return None
    statuses = [_event_after_cutoff(event, cutoff) for event in events]
    if any(status is None for status in statuses):
        return None
    return [event for event, is_new in zip(events, statuses, strict=True) if is_new]


def _close(artifact: dict, metadata: dict, session: str):
    data = metadata.get("price_technical")
    if isinstance(data, dict) and isinstance(data.get("close"), (int, float)):
        return float(data["close"])
    report = str(artifact.get("market_report") or "")
    day = re.escape(session)
    patterns = (
        rf"\b(?:verified\s+)?close(?:\s+on)?\s*\(?{day}\)?\s*[:=]\s*{_PRICE_VALUE}",
        rf"\bclosed?\s+{day}\s+at\s+{_PRICE_VALUE}",
        rf"\b(?:closed|close\s+of)\s+(?:at\s+)?{_PRICE_VALUE}.*?\bon\s+{day}\b",
        rf"\bverified\s+snapshot\s*\(?{day}\)?[^\n]*?\bC\s*[:=]?\s*{_PRICE_VALUE}",
    )
    for pattern in patterns:
        match = re.search(pattern, report, re.I)
        if match:
            return float(match.group(1).replace(",", ""))
    return None


def _close_source(artifact: dict, metadata: dict, session: str):
    price = metadata.get("price_technical")
    if isinstance(price, dict) and isinstance(price.get("close"), (int, float)):
        return "provider_metadata"
    return "existing_market_report" if _close(artifact, metadata, session) is not None else None


def _same(left, right) -> bool:
    return json.dumps(left, sort_keys=True, separators=(",", ":"), default=str) == \
        json.dumps(right, sort_keys=True, separators=(",", ":"), default=str)


def _entry_covers(entry, need_from: str, need_through: str) -> str:
    """Whether one recorded coverage entry proves the gap [need_from, need_through].

    ``True`` (legacy/synthetic fixtures) counts as COMPLETE. A schema-1 dict is
    COMPLETE only when the provider's ACHIEVED coverage spans the required
    interval — proven from the recorded ``intervals`` (never bridged across a
    gap), or the single ``from``/``through`` span of older records. Anything
    else surfaces the recorded status so the reason stays honest.
    """
    if entry is True:
        return "COMPLETE"
    if not isinstance(entry, dict):
        return "UNKNOWN"
    status = entry.get("status")
    if status != "COMPLETE":
        return status or "UNKNOWN"
    intervals = entry.get("intervals")
    if not isinstance(intervals, list):
        intervals = ([{"from": entry.get("from"), "through": entry.get("through")}]
                     if entry.get("through") is not None else [])
    if not need_from or not need_through:
        return "PARTIAL"
    from tradingagents.dataflows.provenance import intervals_cover
    if not intervals or not intervals_cover(intervals, need_from, need_through):
        return "PARTIAL"
    return "COMPLETE"


def _prev_entry_ok(entry) -> bool:
    """The prior case's own evidence existed (for change comparison)."""
    return entry is True or (
        isinstance(entry, dict) and entry.get("status") in ("COMPLETE", "PARTIAL"))


def _coverage(metadata: dict, previous_metadata: dict, prior: dict | None,
              session: str) -> dict:
    current_coverage = metadata.get("coverage") or {}
    previous_coverage = previous_metadata.get("coverage") or {}
    if not isinstance(current_coverage, dict):
        current_coverage = {}
    if not isinstance(previous_coverage, dict):
        previous_coverage = {}
    need_from = (prior or {}).get("session", "")
    coverage = {}
    for name in REQUIRED_EVIDENCE:
        status = _entry_covers(current_coverage.get(name), need_from, session)
        if name in ("social", "market_sector", "price_technical"):
            if status == "COMPLETE" and (
                    not _prev_entry_ok(previous_coverage.get(name)) or prior is None):
                status = "UNKNOWN"
        coverage[name] = status
    if not (
        isinstance(metadata.get("price_technical"), dict)
        and isinstance(previous_metadata.get("price_technical"), dict)
        and isinstance(metadata["price_technical"].get("close"), (int, float))
        and isinstance(previous_metadata["price_technical"].get("close"), (int, float))
    ):
        coverage["price_technical"] = "UNKNOWN"
    if metadata.get("social_sentiment") is None or previous_metadata.get("social_sentiment") is None:
        coverage["social"] = "UNKNOWN"
    if metadata.get("market_sector") is None or previous_metadata.get("market_sector") is None:
        coverage["market_sector"] = "UNKNOWN"
    return coverage


def _delta(
    ticker: str,
    session: str,
    previous: dict,
    current: dict,
    prior: dict | None,
    facts_dir: Path,
) -> dict:
    cutoff = (prior or {}).get("info_cutoff") or {
        "value": (prior or {}).get("session", ""),
        "precision": "session_date",
    }
    if not cutoff.get("value"):
        cutoff["value"] = session
    cutoff_date = cutoff["value"][:10]
    old_metadata = (previous or {}).get("provider_metadata")
    current_metadata = current.get("provider_metadata")
    previous_metadata = old_metadata if isinstance(old_metadata, dict) else {}
    metadata = current_metadata if isinstance(current_metadata, dict) else {}
    prior_facts = _facts_file(ticker, (prior or {}).get("session", ""), facts_dir)
    current_facts = _facts_file(ticker, session, facts_dir)

    filing_events = _new_events(metadata, "filings", cutoff)
    earnings_events = _new_events(metadata, "earnings_or_guidance", cutoff)
    news_events = _new_events(metadata, "news", cutoff)
    corporate_events = _new_events(metadata, "corporate_events", cutoff)
    snapshot_filings = _new_facts_filings(prior_facts, current_facts, cutoff_date)
    if filing_events is None:
        if snapshot_filings:
            filing_events = snapshot_filings
    else:
        filing_events.extend(snapshot_filings)
    coverage = _coverage(metadata, previous_metadata, prior, session)
    fact_dates = _last_filed(current_facts)
    old_fact_dates = _last_filed(prior_facts)
    same_day_fact_ambiguity = [
        name for name, filed_at in fact_dates.items()
        if filed_at == cutoff_date and filed_at > old_fact_dates.get(name, "")
    ]
    if (prior_facts is None or current_facts is None or same_day_fact_ambiguity
            or _has_invalid_filing_dates(prior_facts)
            or _has_invalid_filing_dates(current_facts)
            or cutoff.get("precision") == "unknown"):
        coverage["filings"] = "UNKNOWN"
    if filing_events is None:
        coverage["filings"] = "UNKNOWN"
    if earnings_events is None:
        coverage["earnings_or_guidance"] = "UNKNOWN"
    if news_events is None:
        coverage["news"] = "UNKNOWN"
    if corporate_events is None:
        coverage["corporate_events"] = "UNKNOWN"

    old_close = _close(previous or {}, previous_metadata, (prior or {}).get("session", ""))
    new_close = _close(current, metadata, session)
    price_sources = {
        "prior": _close_source(
            previous or {}, previous_metadata, (prior or {}).get("session", "")),
        "current": _close_source(current, metadata, session),
    }
    price_change_pct = (
        round((new_close - old_close) / old_close * 100, 4)
        if old_close and new_close is not None else None
    )
    old_technical = previous_metadata.get("price_technical")
    new_technical = metadata.get("price_technical")
    technical_changed = (
        not _same(old_technical, new_technical)
        if isinstance(old_technical, dict) and isinstance(new_technical, dict)
        else (old_close != new_close if old_close is not None and new_close is not None else None)
    )
    changed_technical_metrics = (
        sorted(
            key for key in old_technical.keys() | new_technical.keys()
            if key != "close" and old_technical.get(key) != new_technical.get(key)
        )
        if isinstance(old_technical, dict) and isinstance(new_technical, dict)
        else []
    )
    old_social = previous_metadata.get("social_sentiment")
    new_social = metadata.get("social_sentiment")
    social_changed = (
        not _same(old_social, new_social)
        if old_social is not None and new_social is not None else None
    )
    old_market = previous_metadata.get("market_sector")
    new_market = metadata.get("market_sector")
    market_changed = (
        not _same(old_market, new_market)
        if old_market is not None and new_market is not None else None
    )
    if social_changed is None:
        coverage["social"] = "UNKNOWN"
    if market_changed is None:
        coverage["market_sector"] = "UNKNOWN"
    if technical_changed is None:
        coverage["price_technical"] = "UNKNOWN"
    facts_identical = (
        _same(prior_facts, current_facts)
        if prior_facts is not None and current_facts is not None else None
    )
    stable_facts_changed = facts_identical is False
    categories = []
    if filing_events:
        categories.append("NEW_FILINGS")
    if earnings_events:
        categories.append("NEW_EARNINGS_OR_GUIDANCE")
    if news_events:
        categories.append("NEW_NEWS")
    if ((price_change_pct is not None and price_change_pct != 0)
            or changed_technical_metrics):
        categories.append("PRICE_TECHNICAL_CHANGE")
    if social_changed:
        categories.append("SOCIAL_SENTIMENT_CHANGE")
    if market_changed:
        categories.append("MARKET_OR_SECTOR_CHANGE")
    if stable_facts_changed:
        categories.append("STABLE_FACTS_CHANGED")
    no_material_change = (
        not filing_events and not earnings_events and not news_events
        and not corporate_events and not stable_facts_changed
        and social_changed is False and market_changed is False
        and not changed_technical_metrics
        and (price_change_pct is None or abs(price_change_pct) <= 1)
        and all(value == "COMPLETE" for value in coverage.values())
    )
    if no_material_change:
        categories.append("NO_MATERIAL_CHANGE")
    if any(value != "COMPLETE" for value in coverage.values()):
        categories.append("UNKNOWN_INSUFFICIENT_DATA")
    if corporate_events:
        categories.append("MAJOR_CORPORATE_EVENT")

    close_summary = (
        f"close {old_close:.4f} -> {new_close:.4f} ({price_change_pct:+.4f}%)"
        if price_change_pct is not None else None
    )
    if changed_technical_metrics:
        suffix = f"technical metrics changed: {', '.join(changed_technical_metrics)}"
        close_summary = f"{close_summary}; {suffix}" if close_summary else suffix
    return {
        "new_filings": filing_events,
        "new_earnings_or_guidance": earnings_events,
        "new_news_count": len(news_events) if news_events is not None else None,
        "new_news": news_events,
        "price_change_pct": price_change_pct,
        "price_change_sources": price_sources,
        "technical_change_summary": close_summary,
        "technical_metrics_changed": changed_technical_metrics,
        "social_sentiment_change": social_changed,
        "market_or_sector_change": market_changed,
        "other_material_changes": corporate_events or [],
        "classifications": categories,
        "evidence_coverage": coverage,
        "sec_facts_identical": facts_identical,
        "stable_facts_changed": stable_facts_changed,
        "same_day_cutoff_ambiguity": sorted(same_day_fact_ambiguity),
    }


def _classification(
    prior: dict | None, issues: list[str], delta: dict, session: str, max_age_days: int,
) -> dict:
    reasons = list(issues)
    if prior:
        age = (date.fromisoformat(session) - date.fromisoformat(prior["session"])).days
        if age > max_age_days:
            reasons.append("PRIOR_ANALYSIS_TOO_OLD")
    elif not reasons:
        reasons.append("PRIOR_CASE_MISSING")
    if delta["new_filings"]:
        reasons.append("NEW_FILING_REQUIRES_REFRESH")
    if delta["new_earnings_or_guidance"]:
        reasons.append("NEW_EARNINGS_OR_GUIDANCE_REQUIRES_REFRESH")
    if delta["other_material_changes"]:
        reasons.append("MAJOR_CORPORATE_EVENT_REQUIRES_REFRESH")
    if delta["price_change_pct"] is not None and abs(delta["price_change_pct"]) >= 5:
        reasons.append("MATERIAL_PRICE_MOVE")
    if any(value != "COMPLETE" for value in delta["evidence_coverage"].values()):
        reasons.append("INSUFFICIENT_PROVIDER_EVIDENCE")
    no_material_change = (
        not delta["new_filings"]
        and not delta["new_earnings_or_guidance"]
        and delta["new_news_count"] == 0
        and not delta["other_material_changes"]
        and not delta["stable_facts_changed"]
        and delta["social_sentiment_change"] is False
        and delta["market_or_sector_change"] is False
        and (delta["price_change_pct"] is None or abs(delta["price_change_pct"]) <= 1)
    )
    if reasons:
        classification = "FULL_REFRESH_REQUIRED"
    elif no_material_change:
        classification = "REUSE_ELIGIBLE"
    else:
        classification = "UPDATE_MODE_RECOMMENDED"
    return {"classification": classification, "reasons": sorted(set(reasons))}


def _reuse_estimate(previous: dict | None, current: dict, prior_path: Path | None) -> dict:
    previous = previous or {}
    reusable = [field for field in REPORT_FIELDS if previous.get(field)]
    regenerated = [field for field in REPORT_FIELDS if current.get(field)]
    reusable_outputs = [field for field in MODEL_OUTPUT_FIELDS if previous.get(field)]
    output_fields = [field for field in MODEL_OUTPUT_FIELDS if current.get(field)]
    duplicate = [
        field for field in reusable
        if isinstance(previous.get(field), str) and previous.get(field) == current.get(field)
    ]
    duplicate_bytes = sum(len(previous[field].encode("utf-8")) for field in duplicate)
    prior_bytes = prior_path.stat().st_size if prior_path and prior_path.exists() else None
    return {
        "prior_artifact_bytes": prior_bytes,
        "reusable_report_sections": reusable,
        "historical_reports_regenerated": len(regenerated),
        "graph_invocations_rerun": 1 if current else 0,
        "model_stages_with_persisted_outputs": output_fields,
        "model_stage_count_observed": len(output_fields),
        "provider_calls_appearing_repeated": None,
        "sec_facts_identical": None,
        "prior_thesis_loaded": False,
        "measured_identical_report_bytes": duplicate_bytes,
        "likely_duplicate_context_bytes": None,
        "estimated_model_calls_avoidable": len(reusable_outputs),
        "model_call_estimate_basis": (
            "Theoretical lower bound: one completion per persisted model-output field, "
            "if safe to reuse. Not provider usage; debate fields can represent multiple calls."
        ),
        "context_bytes_basis": "Prompt/input snapshots are not persisted.",
        "measurement_basis": {
            "prior_artifact_bytes": "MEASURED_FILE_SIZE",
            "historical_reports_regenerated": "COUNT_OF_NONEMPTY_SAVED_REPORT_FIELDS",
            "graph_invocations_rerun": "INFERRED_FROM_ONE_RUNNER_PROPAGATE_CALL",
            "model_stage_count_observed": "COUNT_OF_NONEMPTY_SAVED_MODEL_OUTPUT_FIELDS",
            "provider_calls_appearing_repeated": "NOT_EXPOSED_BY_RUNTIME",
            "sec_facts_identical": "EXACT_FACTS_SNAPSHOT_COMPARISON",
            "measured_identical_report_bytes": "EXACT_IDENTICAL_REPORT_FIELDS",
            "likely_duplicate_context_bytes": "PROMPT_SNAPSHOTS_NOT_PERSISTED",
            "estimated_model_calls_avoidable": "LOWER_BOUND_ESTIMATE",
            "model_calls_safe_to_avoid_in_shadow_mode": "ZERO_UNLESS_REUSE_ELIGIBLE",
        },
    }


def build_shadow_record(
    ticker: str,
    session: str,
    case_dir: Path | None = None,
    facts_dir: Path | None = None,
    generated_at: str | None = None,
    max_age_days: int | None = None,
) -> dict | None:
    if max_age_days is None:
        try:
            max_age_days = max(1, int(os.getenv("ALPHA_REUSE_SHADOW_MAX_AGE_DAYS", "30")))
        except ValueError:
            max_age_days = 30
    else:
        max_age_days = max(1, max_age_days)
    _validate_identity(ticker, session)
    case_dir = Path(case_dir or CASE_DIR)
    facts_dir = Path(facts_dir or FACTS_DIR)
    current_path = case_dir / f"{ticker}_{session}.json"
    current = _json(current_path)
    if not _valid_artifact(current, ticker, session):
        return None
    resolved = resolve_prior_case(ticker, session, case_dir, facts_dir)
    prior = resolved["prior_case"]
    if prior is None and not resolved["issues"]:
        return None
    previous = resolved["artifact"]
    prior_path = Path(prior["artifact_path"]) if prior else None
    delta = _delta(ticker, session, previous, current, prior, facts_dir)
    issues = list(resolved["issues"])
    if not verify_case(current):
        issues.append(
            "CASE_INTEGRITY_INVALID" if "case_integrity" in current
            else "CASE_INTEGRITY_MISSING"
        )
    if prior and not prior.get("integrity_verified"):
        issues.append(
            "PRIOR_CASE_INTEGRITY_INVALID" if "case_integrity" in previous
            else "PRIOR_CASE_INTEGRITY_MISSING"
        )
    shadow_mode = _classification(
        prior, issues, delta, session, max_age_days)
    estimates = _reuse_estimate(previous, current, prior_path)
    estimates["sec_facts_identical"] = delta["sec_facts_identical"]
    estimates["model_calls_safe_to_avoid_in_shadow_mode"] = (
        estimates["estimated_model_calls_avoidable"]
        if shadow_mode["classification"] == "REUSE_ELIGIBLE" else 0
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "ticker": ticker,
        "session": session,
        "generated_at": generated_at or datetime.now(UTC).isoformat(),
        "prior_case": prior,
        "delta": delta,
        "shadow_mode": shadow_mode,
        "estimated_reuse": estimates,
    }


def persist_shadow_record(record: dict, shadow_dir: Path | None = None) -> Path:
    if record.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported shadow artifact schema")
    _validate_identity(record["ticker"], record["session"])
    path_dir = Path(shadow_dir or SHADOW_DIR)
    path_dir.mkdir(parents=True, exist_ok=True)
    path = path_dir / f"{record['ticker']}_{record['session']}.json"
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)
    return path


def record_for_session(ticker: str, session: str):
    record = build_shadow_record(ticker, session)
    if record is not None:
        persist_shadow_record(record)
    return record


def backfill(
    sessions: list[str],
    case_dir: Path | None = None,
    facts_dir: Path | None = None,
    shadow_dir: Path | None = None,
    generated_at: str | None = None,
) -> list[dict]:
    case_dir = Path(case_dir or CASE_DIR)
    facts_dir = Path(facts_dir or FACTS_DIR)
    sessions = set(sessions)
    for session in sessions:
        if not _DATE.fullmatch(session) or not _valid_date(session):
            raise ValueError("backfill sessions must be ISO dates")
    records = []
    for path in sorted(case_dir.glob("*.json")):
        match = _CASE_NAME.fullmatch(path.name)
        if not match or match.group(2) not in sessions:
            continue
        record = build_shadow_record(
            match.group(1), match.group(2), case_dir, facts_dir, generated_at)
        if record is not None:
            persist_shadow_record(record, shadow_dir)
            records.append(record)
    return records


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backfill", nargs="+", required=True, metavar="SESSION")
    args = parser.parse_args()
    records = backfill(args.backfill)
    for record in records:
        print(
            f"{record['ticker']} {record['session']}: "
            f"{record['shadow_mode']['classification']}"
        )
    print(f"persisted {len(records)} repeated-case shadow records")


if __name__ == "__main__":
    main()
