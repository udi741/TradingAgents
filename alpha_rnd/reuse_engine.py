"""Incremental repeated-analysis reuse engine for ALPHA.

A repeated candidate is an update to an existing case, not a new case from
zero. For every repeated ticker/session this module resolves the latest
trusted prior case, runs the deterministic gap probe, classifies into exactly
one mode — FULL_REFRESH / UPDATE / REUSE — executes only that path, and seals
the resulting artifact. Every uncertain condition fails closed to
FULL_REFRESH, which is the existing full TradingAgents graph, unchanged.

Modes are controlled by ALPHA_REUSE_ENGINE:
  OFF      (default) — engine inert; run_ta behaves exactly as before.
  VALIDATE — run optimized path AND the existing full graph for the same
             repeated ticker; the FULL baseline remains the economic and
             publication authority, the optimized artifact is research-only.
             Provider caches are snapshotted per leg so neither run warms the
             other; if isolation is impossible, time/network savings are
             labelled PARTIAL/UNAVAILABLE rather than MEASURED.
  ENABLED  — optimized path writes the canonical artifact. Not auto-promoted:
             an operator flips this only after evaluate_readiness() reports
             READY_FOR_OPTIMIZED_AUTHORITY and approves.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import time
from datetime import UTC, date, datetime
from pathlib import Path

from alpha_rnd import delta_probe, reuse_shadow
from alpha_rnd.case_integrity import seal_case, verify_case
from alpha_rnd.success_plan import validate as validate_success_plan

ROOT = Path(__file__).resolve().parents[1]
EV_DIR = ROOT / "evaluations" / "alpha_rnd_v1"
CASE_DIR = EV_DIR / "case_artifacts"
CACHE_DIR = EV_DIR / "cache"
VALIDATION_DIR = EV_DIR / "reuse_validation"
SCHEMA_VERSION = 1

CLASSIFICATIONS = ("FULL_REFRESH", "UPDATE", "REUSE")
MATERIAL_PRICE_PCT = 5.0
SMALL_PRICE_PCT = 1.0
BRIDGE_URL = "http://127.0.0.1:8765/v1"
UPDATE_MODEL = "devin-deep"  # swe-2-high; single focused update call

_ENGINE_MODES = {"OFF", "VALIDATE", "ENABLED"}


def engine_mode() -> str:
    value = os.getenv("ALPHA_REUSE_ENGINE", "OFF").strip().upper()
    return value if value in _ENGINE_MODES else "OFF"


def max_validation_pairs() -> int:
    try:
        return max(0, int(os.getenv("ALPHA_REUSE_MAX_PAIRS", "2")))
    except ValueError:
        return 2


def max_age_days() -> int:
    try:
        return max(1, int(os.getenv("ALPHA_REUSE_MAX_AGE_DAYS", "30")))
    except ValueError:
        return 30


def _norm_signal(value) -> str | None:
    if not isinstance(value, str):
        return None
    match = re.search(r"\b(BUY|HOLD|SELL|OVERWEIGHT|UNDERWEIGHT)\b", value, re.I)
    return match.group(1).upper() if match else None


_RATINGS = {
    "BUY": "BUY", "OVERWEIGHT": "OVERWEIGHT", "HOLD": "HOLD",
    "MARKET_WEIGHT": "MARKET_WEIGHT", "MARKET WEIGHT": "MARKET_WEIGHT",
    "UNDERWEIGHT": "UNDERWEIGHT", "SELL": "SELL",
}


def _canon_rating(value) -> str | None:
    """Canonical rating token; None when the field cannot be interpreted."""
    if not isinstance(value, str):
        return None
    text = value.strip().upper().replace("-", "_")
    for key in ("OVERWEIGHT", "UNDERWEIGHT", "MARKET_WEIGHT", "BUY", "SELL", "HOLD"):
        if key in text:
            return _RATINGS[key]
    match = re.search(r"\bMARKET\s+WEIGHT\b", text)
    return "MARKET_WEIGHT" if match else None


_EXECUTABLE = {"BUY", "OVERWEIGHT"}


def _executable_signal(artifact: dict) -> bool:
    return _norm_signal((artifact or {}).get("signal")) in _EXECUTABLE


def _prior_executable_buy(artifact: dict) -> bool:
    """Could the trusted prior decision create or renew an executable BUY?

    Conservative: any buy-ish signal/PM/trader posture counts — zero-model
    REUSE must never carry a stale execution basis forward.
    """
    return any(
        _norm_signal(artifact.get(field)) in _EXECUTABLE
        for field in ("signal", "pm_rating", "trader_action")
    )


def _stable_facts_changed(ticker: str, prior_session: str, session: str,
                          facts_dir: Path):
    """True/False when both snapshots exist, None when either is missing."""
    prior_facts = reuse_shadow._facts_file(ticker, prior_session, facts_dir)
    current_facts = reuse_shadow._facts_file(ticker, session, facts_dir)
    if prior_facts is None or current_facts is None:
        return None
    return not reuse_shadow._same(prior_facts, current_facts)


def decide(ticker: str, session: str, *, case_dir=None, facts_dir=None,
           probe_fn=None, age_limit_days: int | None = None) -> dict:
    """Classify a repeated case into exactly one mode.

    Pure selection: loads the trusted prior case, verifies integrity, runs the
    delta probe and returns the decision record. Any uncertainty adds a
    FULL_REFRESH reason — fail closed, never optimize away safety.
    """
    reuse_shadow._validate_identity(ticker, session)
    case_dir = Path(case_dir or CASE_DIR)
    facts_dir = Path(facts_dir) if facts_dir else EV_DIR
    resolved = reuse_shadow.resolve_prior_case(ticker, session, case_dir, facts_dir)
    prior = resolved["prior_case"]
    artifact = resolved["artifact"]
    reasons = list(resolved["issues"])
    probe = None
    if prior is None:
        reasons.append("PRIOR_CASE_MISSING")
    else:
        if not prior.get("integrity_verified"):
            reasons.append(
                "PRIOR_CASE_INTEGRITY_INVALID" if "case_integrity" in artifact
                else "PRIOR_CASE_INTEGRITY_MISSING")
        age = (date.fromisoformat(session)
               - date.fromisoformat(prior["session"])).days
        if age_limit_days is None:
            age_limit_days = max_age_days()
        if age > age_limit_days:
            reasons.append("PRIOR_CASE_TOO_OLD")
        if artifact.get("schema_version") not in (None, reuse_shadow.SCHEMA_VERSION):
            reasons.append("PRIOR_SCHEMA_INCOMPATIBLE")
    if prior is not None and not reasons:
        cutoff = prior["info_cutoff"]["value"]
        prior_close = reuse_shadow._close(
            artifact, artifact.get("provider_metadata") or {}, prior["session"])
        if prior_close is None:
            reasons.append("PRIOR_CLOSE_UNAVAILABLE")
            probe = None
        else:
            try:
                probe = (probe_fn or delta_probe.probe_gap)(
                    ticker, cutoff, session, prior_close=prior_close)
            except Exception as exc:
                reasons.append("DELTA_PROBE_FAILED")
                probe = {"error": f"{type(exc).__name__}: {exc}", "coverage": {},
                         "filings": [], "earnings_or_guidance": [], "news": [],
                         "corporate_events": [], "unclassified_news": []}
        if probe is not None and "error" not in probe:
            coverage = probe.get("coverage") or {}
            incomplete = [
                family for family in reuse_shadow.REQUIRED_EVIDENCE
                if (coverage.get(family) or {}).get("status") != "COMPLETE"
            ]
            if incomplete:
                reasons.append("INCOMPLETE_COVERAGE")
            if probe.get("filings"):
                reasons.append("NEW_FILING")
            if probe.get("earnings_or_guidance"):
                reasons.append("EARNINGS_OR_GUIDANCE")
            if probe.get("corporate_events"):
                reasons.append("CORPORATE_EVENT")
            pct = (probe.get("price_technical") or {}).get("price_change_pct")
            if pct is not None and abs(pct) >= MATERIAL_PRICE_PCT:
                reasons.append("MATERIAL_PRICE_MOVE")
            facts_changed = _stable_facts_changed(
                ticker, prior["session"], session, facts_dir)
        else:
            reasons.append("INCOMPLETE_COVERAGE")
            facts_changed = None
    else:
        facts_changed = None
    delta_reasons = []
    if not reasons and probe is not None:
        if facts_changed is None:
            # Stable-facts comparison could not be proven — fail closed.
            reasons.append("STABLE_FACTS_UNKNOWN")
    if not reasons and probe is not None:
        if probe.get("unclassified_news") or probe.get("news"):
            delta_reasons.append("NEWS_DELTA")
        if (probe.get("social") or {}).get("item_count"):
            delta_reasons.append("SOCIAL_DELTA")
        if (probe.get("market_sector") or {}).get("item_count"):
            delta_reasons.append("MARKET_SECTOR_DELTA")
        pct = (probe.get("price_technical") or {}).get("price_change_pct")
        if pct is not None and abs(pct) > SMALL_PRICE_PCT:
            delta_reasons.append("PRICE_TECHNICAL_DELTA")
        if facts_changed:
            delta_reasons.append("STABLE_FACTS_CHANGED")
    if reasons:
        mode = "FULL_REFRESH"
    elif delta_reasons:
        mode = "UPDATE"
    elif _prior_executable_buy(artifact):
        mode = "UPDATE"
        delta_reasons.append("REUSE_UPGRADED_EXECUTABLE_BUY")
    else:
        mode = "REUSE"
    return {
        "schema_version": SCHEMA_VERSION,
        "ticker": ticker,
        "session": session,
        "mode": mode,
        "reasons": sorted(set(reasons)),
        "delta_reasons": delta_reasons,
        "prior_case": prior,
        "prior_artifact": artifact,
        "prior_integrity_hash": (
            (artifact.get("case_integrity") or {}).get("hash") if artifact else None),
        "delta_probe": probe,
        "stable_facts_changed": facts_changed,
        "decided_at": datetime.now(UTC).isoformat(),
    }


# ---------------------------------------------------------------- UPDATE path

_UPDATE_PROMPT = """You are updating an existing investment analysis for {ticker} as of {session}.
You are NOT re-analyzing from scratch. The previous trusted analysis and ONLY
the new information since its cutoff are provided.

=== KNOWN PRIOR FACTS (trusted, do not re-derive) ===
Prior session: {prior_session} | Information cutoff: {cutoff}
Previous decision: {prior_signal} | PM rating: {pm_rating} | RM rating: {rm_rating}
Previous thesis:
{thesis}
Previous portfolio-manager decision:
{pm_decision}
Previous risk-management decision:
{rm_decision}
Previous price target: {price_target} | Previous horizon: {horizon}

=== NEW INFORMATION SINCE CUTOFF ({cutoff} -> {session}) ===
Delta reasons: {delta_reasons}
New company news items:
{news_items}
New social-gap items (sentiment where recorded):
{social_items}
New market/sector gap items:
{market_items}
Stable facts changed: {facts_changed}

=== CURRENT PRICE / TECHNICAL DELTA ===
Prior close: {prior_close} | Current close: {current_close} | Change: {price_change_pct}%

=== PORTFOLIO CONTEXT ===
{portfolio}

Answer EXACTLY in this schema (one value per line):
THESIS_STATUS: UNCHANGED|STRENGTHENED|WEAKENED|INVALIDATED
FULL_REFRESH_REQUIRED: YES|NO
SIGNAL: BUY|HOLD|SELL
RATING: <one-line rating>
UPDATED_THESIS: <thesis paragraph: what changed, what did not change>
HORIZON: <updated horizon or UNCHANGED>
PRICE_TARGET: <number or UNCHANGED>
Reasoning must rely only on the prior trusted case plus the delta above.
If the new information may invalidate the thesis, or evidence is insufficient
to update safely, set FULL_REFRESH_REQUIRED: YES.
If SIGNAL is BUY you MUST also provide, on separate lines:
ENTRY_BASIS: <current entry price>
FAILURE_LEVEL: <failure/risk stop level below entry>
BASE_OBJECTIVE: <base-case objective above entry>
EXPECTED_UPSIDE_PCT: <percent>
EXPECTED_RR: <reward-to-risk>
SUCCESS_CRITERIA: <what proves the thesis>
PROFIT_PLAN: <how profits are realized>"""


def _item_lines(items, limit: int = 15) -> str:
    lines = []
    for item in (items or [])[:limit]:
        stamp = str(item.get("published_at") or item.get("date") or "")[:16]
        title = (item.get("title") or item.get("body") or item.get("id") or "")
        sentiment = item.get("sentiment")
        tag = f" [{sentiment}]" if sentiment else ""
        lines.append(f"- {stamp}{tag} {str(title)[:140]}")
    return "\n".join(lines) or "- (none)"


def build_update_prompt(decision: dict, session: str,
                        portfolio: str = "flat / entry analysis") -> str:
    """Prior thesis + compact structured delta only — never old payloads."""
    prior = decision["prior_case"]
    artifact = decision["prior_artifact"]
    probe = decision["delta_probe"] or {}
    price = probe.get("price_technical") or {}
    return _UPDATE_PROMPT.format(
        ticker=decision["ticker"], session=session,
        prior_session=prior["session"], cutoff=prior["info_cutoff"]["value"],
        prior_signal=artifact.get("signal"), pm_rating=artifact.get("pm_rating"),
        rm_rating=artifact.get("rm_rating"),
        thesis=prior.get("thesis_summary") or "(none)",
        pm_decision=str(artifact.get("final_trade_decision") or "")[:1500],
        rm_decision=str(artifact.get("risk_judge_decision") or "")[:1500],
        price_target=prior.get("previous_price_target"),
        horizon=prior.get("previous_time_horizon"),
        delta_reasons=", ".join(decision.get("delta_reasons") or ["NONE"]),
        news_items=_item_lines(probe.get("news")),
        social_items=_item_lines((probe.get("social") or {}).get("items")),
        market_items=_item_lines((probe.get("market_sector") or {}).get("items")),
        facts_changed=decision.get("stable_facts_changed"),
        prior_close=price.get("prior_close"),
        current_close=price.get("close"),
        price_change_pct=price.get("price_change_pct"),
        portfolio=portfolio,
    )


def default_update_llm():
    """One focused swe-2-high call through the existing SWE bridge."""
    from tradingagents.llm_clients.factory import build_llm_kwargs, create_llm_client
    from alpha_rnd.analysis_metrics import ModelCallMetrics

    config = {"temperature": 0}
    metrics = ModelCallMetrics({"quick": "devin-quick", "deep": "devin-deep"})
    kwargs = build_llm_kwargs(config)
    kwargs["callbacks"] = [metrics]
    client = create_llm_client(
        provider="openai_compatible", model=UPDATE_MODEL,
        base_url=BRIDGE_URL, **kwargs)
    llm = client.get_llm()

    def call(prompt: str) -> str:
        response = llm.invoke(prompt)
        content = getattr(response, "content", response)
        return content if isinstance(content, str) else str(content)

    return call, metrics


_FIELD = lambda name: re.compile(rf"^{name}:\s*(.+?)\s*$", re.M)  # noqa: E731


def _line(text: str, name: str):
    match = _FIELD(name).search(text)
    return match.group(1).strip() if match else None


def _num(text: str, name: str):
    value = _line(text, name)
    if value is None or value.upper() in ("UNCHANGED", "NONE", "N/A"):
        return None
    match = re.search(r"[\d,]+(?:\.\d+)?", value)
    return float(match.group(0).replace(",", "")) if match else None


def parse_update_response(text: str) -> dict:
    """Parse the update reasoner's structured answer. Missing signal = unsafe."""
    return {
        "thesis_status": (_line(text, "THESIS_STATUS") or "").upper() or None,
        "full_refresh_required": (_line(text, "FULL_REFRESH_REQUIRED") or "").upper() == "YES",
        "signal": _norm_signal(_line(text, "SIGNAL")),
        "rating": _line(text, "RATING"),
        "updated_thesis": _line(text, "UPDATED_THESIS"),
        "horizon": _line(text, "HORIZON"),
        "price_target": _num(text, "PRICE_TARGET"),
        "entry_basis": _num(text, "ENTRY_BASIS"),
        "failure_level": _num(text, "FAILURE_LEVEL"),
        "base_objective": _num(text, "BASE_OBJECTIVE"),
        "expected_upside_pct": _num(text, "EXPECTED_UPSIDE_PCT"),
        "expected_rr": _num(text, "EXPECTED_RR"),
        "success_criteria": _line(text, "SUCCESS_CRITERIA"),
        "profit_plan": _line(text, "PROFIT_PLAN"),
        "raw": text,
    }


def _buy_success_plan(parsed: dict):
    """Fresh Phase-G plan for an executable BUY; None entries -> invalid."""
    return {
        "base_case_value_range": (
            [parsed["base_objective"], parsed["base_objective"]]
            if parsed.get("base_objective") is not None else None),
        "bull_case_value_range": None,
        "expected_upside_pct": parsed.get("expected_upside_pct"),
        "expected_reward_to_risk": parsed.get("expected_rr"),
        "success_criteria": parsed.get("success_criteria"),
        "catalyst_milestones": parsed.get("horizon"),
        "priced_in_rule": None,
        "profit_realization_plan": parsed.get("profit_plan"),
        "legacy_target": parsed.get("price_target"),
    }


def _decision_text(parsed: dict, decision: dict, plan) -> str:
    """Current-session decision text — the only text allowed to speak for
    the new decision in the four synthesize-consumed fields."""
    prior = decision["prior_case"]
    lines = [
        f"INCREMENTAL UPDATE — {decision['session']} "
        f"(basis: trusted {prior['session']} case + delta probe)",
        f"Thesis status: {parsed['thesis_status']}",
        f"Signal: {parsed['signal']} | Rating: {parsed['rating'] or 'n/a'}",
        f"Updated thesis: {parsed['updated_thesis'] or '(none)'}",
        f"Horizon: {parsed['horizon'] or 'UNCHANGED'} | "
        f"Price target: {parsed['price_target'] or 'UNCHANGED'}",
    ]
    if plan:
        lines.append(
            "Executable BUY plan — entry {e}, stop {s}, base objective {b}, "
            "upside {u}%, R:R {r}. Success: {sc}. Realization: {pp}".format(
                e=parsed.get("entry_basis"), s=parsed.get("failure_level"),
                b=parsed.get("base_objective"),
                u=parsed.get("expected_upside_pct"),
                r=parsed.get("expected_rr"),
                sc=parsed.get("success_criteria"),
                pp=parsed.get("profit_plan")))
    return "\n".join(lines)


def run_update(decision: dict, *, llm_fn=None, portfolio: str = "flat / entry analysis"):
    """One focused update call over prior thesis + delta only.

    Returns {"artifact": dict, "fallback": reason|None, "model_calls": int,
    "tokens": dict, "elapsed_ms": float}. fallback set => caller runs
    FULL_REFRESH instead.
    """
    started = time.monotonic()
    metrics = None
    if llm_fn is None:
        llm_fn, metrics = default_update_llm()
    tokens = {"availability": "UNAVAILABLE", "input_tokens": None,
              "output_tokens": None, "total_tokens": None}
    try:
        text = llm_fn(build_update_prompt(decision, decision["session"], portfolio))
    except Exception as exc:
        return {"artifact": None,
                "fallback": f"UPDATE_LLM_FAILED:{type(exc).__name__}",
                "model_calls": 0, "tokens": tokens,
                "elapsed_ms": round((time.monotonic() - started) * 1000, 3)}
    if metrics is not None:
        snap = metrics.snapshot()
        tokens = snap.get("tokens", tokens)
    parsed = parse_update_response(text)
    elapsed = round((time.monotonic() - started) * 1000, 3)
    if parsed["full_refresh_required"] or parsed["thesis_status"] == "INVALIDATED":
        return {"artifact": None, "fallback": "UPDATE_REQUESTED_FULL_REFRESH",
                "model_calls": 1, "tokens": tokens, "elapsed_ms": elapsed,
                "update": parsed}
    if parsed["signal"] is None:
        return {"artifact": None, "fallback": "UPDATE_RESPONSE_UNPARSEABLE",
                "model_calls": 1, "tokens": tokens, "elapsed_ms": elapsed,
                "update": parsed}
    plan = None
    if parsed["signal"] == "BUY":
        # Phase G: an executable BUY needs a fresh, valid success plan —
        # stale prior execution parameters are never carried into a new BUY.
        plan, errs = validate_success_plan(
            _buy_success_plan(parsed),
            parsed.get("entry_basis"), parsed.get("failure_level"))
        if errs:
            return {"artifact": None,
                    "fallback": "UPDATE_BUY_PLAN_INVALID:" + ";".join(errs),
                    "model_calls": 1, "tokens": tokens, "elapsed_ms": elapsed,
                    "update": parsed}
    artifact = _coherent_update_artifact(decision, parsed, plan)
    return {"artifact": artifact, "fallback": None,
            "model_calls": 1, "tokens": tokens, "elapsed_ms": elapsed,
            "update": parsed, "success_plan": plan}


# --------------------------------------------------- artifact coherence chain

# Fields the publication translator reads as the CURRENT decision
# (synthesize.artifact_text) plus the rating/action fields other consumers
# compare against the signal.
_DECISION_FIELDS = (
    "final_trade_decision", "trader_investment_plan",
    "risk_judge_decision", "investment_plan",
    "signal", "pm_rating", "rm_rating", "trader_action",
)
# Analyst evidence intentionally reused across an update — labelled, never
# presented as regenerated today.
_REUSED_REPORT_FIELDS = (
    "market_report", "sentiment_report", "news_report", "fundamentals_report",
    "bull_history", "bear_history", "judge_decision",
)


def _advance_cutoff(artifact: dict, decision: dict, elapsed_ms: float,
                    extra_fields: dict | None = None) -> dict:
    """Make the optimized artifact a valid trusted prior for the NEXT session.

    Called only when gap coverage was proven COMPLETE: the artifact's
    information cutoff advances to the current session, run-specific
    metadata is refreshed (stale duration/hash are never carried forward),
    and provider metadata records the new gap evidence separately from the
    reused prior evidence.
    """
    session = decision["session"]
    prior = decision["prior_case"]
    probe = decision.get("delta_probe") or {}
    artifact["decision_session"] = session
    artifact["information_cutoff"] = session
    artifact["data_as_of"] = session
    artifact["duration_s"] = round(elapsed_ms / 1000, 3)
    artifact["model_routing"] = {
        **(artifact.get("model_routing") or {}),
        "update_reasoner": "swe-2-high",
    }
    artifact["provider_metadata"] = {
        "schema_version": 1,
        "captured_at": datetime.now(UTC).isoformat(),
        "information_cutoff": {
            "value": session, "precision": "date", "complete": True,
        },
        "coverage": probe.get("coverage"),
        "filings": probe.get("filings") or [],
        "news": probe.get("news") or [],
        "price_technical": probe.get("price_technical"),
        "social_sentiment": probe.get("social"),
        "market_sector": probe.get("market_sector"),
        "reused_from_session": prior["session"],
        "note": "Coverage/families above are the NEW gap-window probe evidence "
                f"from {prior['session']} -> {session}. Analyst reports and "
                "stable facts marked 'reused' originate from the trusted prior "
                "case and were NOT refetched.",
    }
    artifact["reused_fields"] = {
        **(artifact.get("reused_fields") or {}),
        **{
            field: {"source_session": prior["session"], "reused": True}
            for field in _REUSED_REPORT_FIELDS if artifact.get(field)
        },
    }
    if extra_fields:
        artifact.update(extra_fields)
    # final_state_hash: recompute over the CURRENT artifact the same way
    # run_one does, so the field keeps meaning "hash of this artifact",
    # never yesterday's full-run state.
    artifact.pop("final_state_hash", None)
    artifact["final_state_hash"] = hashlib.sha256(
        json.dumps(artifact, sort_keys=True, default=str).encode()
    ).hexdigest()
    return artifact


def _coherent_update_artifact(decision: dict, parsed: dict, plan) -> dict:
    """UPDATE artifact: the prior case supplies analyst evidence only.

    Every decision-bearing field is rewritten from the update reasoner so a
    signal change can never leave a stale BUY plan or prior decision text
    masquerading as the current decision.
    """
    prior = decision["prior_case"]
    artifact = {}
    source = decision["prior_artifact"]
    for field in _REUSED_REPORT_FIELDS:
        if source.get(field):
            artifact[field] = source[field]
    for field in ("portfolio_context_rendered", "schema_version"):
        if source.get(field) is not None:
            artifact[field] = source[field]
    artifact["ticker"] = decision["ticker"]
    signal = parsed["signal"].capitalize()
    rating = parsed["rating"] or signal
    text = _decision_text(parsed, decision, plan)
    artifact["signal"] = signal
    artifact["pm_rating"] = rating
    artifact["rm_rating"] = rating
    artifact["trader_action"] = signal
    artifact["final_trade_decision"] = text
    artifact["trader_investment_plan"] = text
    artifact["investment_plan"] = text
    artifact["risk_judge_decision"] = (
        f"[UPDATE {decision['session']}] Risk posture carried by the focused "
        "update reasoner; no separate risk debate ran.")
    artifact["update_reasoning"] = {
        "model": "swe-2-high", "thesis_status": parsed["thesis_status"],
        "updated_thesis": parsed["updated_thesis"],
        "horizon": parsed["horizon"], "price_target": parsed["price_target"],
        "basis": {"prior_session": prior["session"],
                  "cutoff": prior["info_cutoff"]["value"]},
        "raw_response": parsed["raw"],
    }
    if parsed["price_target"] is not None:
        artifact["price_target"] = parsed["price_target"]
    if plan is not None:
        artifact["success_plan"] = plan
        artifact["entry_basis"] = parsed.get("entry_basis")
        artifact["stop_level"] = parsed.get("failure_level")
    # The prior decision is archived for audit, not reused as decision text.
    artifact["prior_case_decision"] = {
        "source_session": prior["session"],
        "signal": source.get("signal"),
        "pm_rating": source.get("pm_rating"),
        "trader_action": source.get("trader_action"),
        "final_trade_decision": source.get("final_trade_decision"),
        "reused": True,
    }
    return artifact


# ----------------------------------------------------------------- REUSE path

def build_reuse_artifact(decision: dict) -> dict:
    """Zero-model carry-forward of the trusted prior decision.

    Only reachable for non-executable outcomes (a buy-ish prior upgrades to
    UPDATE first), so no stale execution parameters ever become a fresh order.
    The prior decision fields are internally consistent and are labelled
    reused rather than rewritten.
    """
    artifact = dict(decision["prior_artifact"])
    # Defence in depth: REUSE must never carry an executable BUY.
    if _executable_signal(artifact):
        raise ValueError("REUSE cannot carry an executable decision")
    artifact["source_session"] = decision["prior_case"]["session"]
    artifact["reused_fields"] = {
        field: {"source_session": decision["prior_case"]["session"], "reused": True}
        for field in (_REUSED_REPORT_FIELDS + _DECISION_FIELDS)
        if artifact.get(field)
    }
    return artifact


# ------------------------------------------------------------ orchestration

def _optimized_metrics(mode: str, decision: dict, extra: dict | None) -> dict:
    probe = decision.get("delta_probe") or {}
    elapsed = (probe.get("elapsed_ms") or 0) + ((extra or {}).get("elapsed_ms") or 0)
    return {
        "schema_version": 1,
        "wall_clock": {"elapsed_ms": elapsed},
        "model_calls": {
            "total": (extra or {}).get("model_calls", 0),
            "quick": 0,
            "deep": (extra or {}).get("model_calls", 0) if mode == "UPDATE" else 0,
        },
        "provider_calls": {
            "logical_data_calls": probe.get("provider_call_count"),
            "provider_attempts": probe.get("provider_attempts"),
            "cache_hits": probe.get("cache_hits"),
            "external_network_calls": probe.get("known_external_network_calls"),
            "external_network_quality": probe.get("external_network_quality"),
        },
        "tokens": (extra or {}).get("tokens") or {
            "availability": "UNAVAILABLE", "input_tokens": None,
            "output_tokens": None, "total_tokens": None},
        "delta_probe_ms": probe.get("elapsed_ms"),
    }


def _reuse_block(decision: dict, work_performed: list, work_skipped: list,
                 fallback: bool) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": decision["mode"],
        "prior_session": (decision.get("prior_case") or {}).get("session"),
        "prior_integrity_hash": decision.get("prior_integrity_hash"),
        "decision_reasons": decision.get("reasons", []),
        "delta_reasons": decision.get("delta_reasons", []),
        "delta_probe": {
            key: decision["delta_probe"].get(key)
            for key in ("coverage", "filings", "earnings_or_guidance",
                        "corporate_events", "price_technical", "social",
                        "market_sector", "provider_call_count",
                        "provider_attempts", "direct_provider_calls",
                        "cache_hits", "elapsed_ms",
                        "swe_calls", "reasons", "fetch_errors")
        } if isinstance(decision.get("delta_probe"), dict) else None,
        "fallback_to_full_refresh": fallback,
        "work_skipped": work_skipped,
        "work_performed": work_performed,
    }


def _write(path: Path, artifact: dict) -> dict:
    seal_case(artifact)
    path.write_text(json.dumps(artifact, indent=1, default=str))
    return artifact


def run_optimized(ticker: str, session: str, *, full_run, case_dir=None,
                  facts_dir=None, probe_fn=None, llm_fn=None,
                  artifact_path: Path | None = None, on_fallback=None,
                  full_run_kwargs: dict | None = None, decision=None,
                  portfolio: str = "flat / entry analysis") -> dict:
    """Execute one optimized path. ``full_run(ticker, session, out_name,
    **full_run_kwargs)`` is the existing full-graph runner.

    ``on_fallback(decision, update_result)`` may replace the fallback
    full-graph run (VALIDATE uses it so the research leg never double-runs
    the graph when UPDATE asks for FULL_REFRESH).
    """
    case_dir = Path(case_dir or CASE_DIR)
    artifact_path = Path(artifact_path) if artifact_path else (
        case_dir / f"{ticker}_{session}.optimized.json")
    run_kwargs = full_run_kwargs or {}
    decision = decision or decide(
        ticker, session, case_dir=case_dir, facts_dir=facts_dir,
        probe_fn=probe_fn)
    out_name = artifact_path.name
    if decision["mode"] == "FULL_REFRESH":
        artifact = full_run(ticker, session, out_name, **run_kwargs)
        artifact["reuse_execution"] = _reuse_block(
            decision, ["delta_probe", "full_graph"],
            ["prior_thesis_load", "update_reasoner"], fallback=False)
        return _write(artifact_path, artifact)
    if decision["mode"] == "REUSE":
        metrics = _optimized_metrics("REUSE", decision, None)
        artifact = build_reuse_artifact(decision)
        artifact["reuse_execution"] = _reuse_block(
            decision, ["delta_probe"],
            ["full_graph", "all_model_calls", "historical_provider_payloads"],
            fallback=False)
        artifact["analysis_metrics"] = metrics
        _advance_cutoff(artifact, decision,
                        metrics["wall_clock"]["elapsed_ms"])
        return _write(artifact_path, artifact)
    # UPDATE
    result = run_update(decision, llm_fn=llm_fn, portfolio=portfolio)
    if result["fallback"] or result["artifact"] is None:
        decision["reasons"] = sorted(set(
            decision["reasons"] + [result["fallback"] or "UPDATE_FAILED"]))
        decision["mode"] = "FULL_REFRESH"
        if on_fallback is not None:
            return on_fallback(decision, result, artifact_path)
        artifact = full_run(ticker, session, out_name, **run_kwargs)
        artifact["reuse_execution"] = _reuse_block(
            decision, ["delta_probe", "update_reasoner", "full_graph"],
            [], fallback=True)
        return _write(artifact_path, artifact)
    metrics = _optimized_metrics("UPDATE", decision, result)
    artifact = result["artifact"]
    artifact["reuse_execution"] = _reuse_block(
        decision, ["delta_probe", "update_reasoner"],
        ["full_graph", "analyst_agents", "bull_bear_debate", "risk_debate",
         "historical_provider_payloads"], fallback=False)
    artifact["analysis_metrics"] = metrics
    _advance_cutoff(artifact, decision, metrics["wall_clock"]["elapsed_ms"])
    return _write(artifact_path, artifact)


# -------------------------------------------------------- paired validation

def _plan_tuple(artifact: dict):
    plan = (artifact or {}).get("success_plan") or {}
    return (
        (artifact or {}).get("entry_basis"),
        (artifact or {}).get("stop_level"),
        plan.get("base_case_top") or plan.get("legacy_target"),
    )


def compare_decisions(optimized: dict, baseline: dict) -> dict:
    """Structured outcome comparison — order/stop/entry/size consequences,
    never wording diffs. Unknown ratings cannot silently agree."""
    opt_sig = _norm_signal(optimized.get("signal"))
    base_sig = _norm_signal(baseline.get("signal"))
    opt_rating = _canon_rating(optimized.get("pm_rating"))
    base_rating = _canon_rating(baseline.get("pm_rating"))
    opt_risk = _canon_rating(optimized.get("rm_rating"))
    base_risk = _canon_rating(baseline.get("rm_rating"))
    opt_trader = _norm_signal(optimized.get("trader_action"))
    base_trader = _norm_signal(baseline.get("trader_action"))
    rating_agreement = (
        None if opt_rating is None or base_rating is None
        else opt_rating == base_rating)
    opt_exec = _executable_signal(optimized)
    base_exec = _executable_signal(baseline)
    plan_differs = (
        opt_exec and base_exec and _plan_tuple(optimized) != _plan_tuple(baseline))
    executable_disagreement = (opt_exec != base_exec) or bool(plan_differs)
    research_disagreement = (
        opt_sig != base_sig or rating_agreement is False
        or opt_trader != base_trader)
    return {
        "optimized_signal": opt_sig, "baseline_signal": base_sig,
        "optimized_rating": opt_rating, "baseline_rating": base_rating,
        "optimized_risk_posture": opt_risk, "baseline_risk_posture": base_risk,
        "optimized_trader_action": opt_trader,
        "baseline_trader_action": base_trader,
        "optimized_executable": opt_exec, "baseline_executable": base_exec,
        "optimized_plan": dict(zip(
            ("entry_basis", "stop_level", "base_objective"),
            _plan_tuple(optimized))),
        "baseline_plan": dict(zip(
            ("entry_basis", "stop_level", "base_objective"),
            _plan_tuple(baseline))),
        "signal_agreement": opt_sig == base_sig,
        "rating_agreement": rating_agreement,
        "research_disagreement": bool(research_disagreement),
        "executable_action_agreement": not executable_disagreement,
        "executable_disagreement": executable_disagreement,
        "note": ("Signal/rating differences on a flat portfolio may both mean "
                 "no-entry; they are still recorded as research disagreement. "
                 "Any difference that changes an order, stop, entry, size, or "
                 "executable action sets executable_disagreement."),
    }


def persist_pair(record: dict, validation_dir=None) -> Path:
    path_dir = Path(validation_dir or VALIDATION_DIR)
    path_dir.mkdir(parents=True, exist_ok=True)
    path = path_dir / f"{record['ticker']}_{record['session']}.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)
    return path


def _probe_evidence(decision: dict) -> dict:
    """Independently consumable safety evidence for the rollout gate — the
    gate re-derives mandatory full-refresh triggers from this, not from the
    classifier's own reason list."""
    probe = decision.get("delta_probe") or {}
    return {
        "filings": probe.get("filings") or [],
        "earnings_or_guidance": probe.get("earnings_or_guidance") or [],
        "corporate_events": probe.get("corporate_events") or [],
        "price_change_pct": (probe.get("price_technical") or {}).get("price_change_pct"),
        "coverage": probe.get("coverage"),
        "fetch_errors": probe.get("fetch_errors") or [],
        "prior_integrity_valid": bool(
            (decision.get("prior_case") or {}).get("integrity_verified")),
    }


def _mandatory_refresh(evidence: dict) -> list[str]:
    triggers = []
    if evidence.get("filings"):
        triggers.append("NEW_FILING")
    if evidence.get("earnings_or_guidance"):
        triggers.append("EARNINGS_OR_GUIDANCE")
    if evidence.get("corporate_events"):
        triggers.append("CORPORATE_EVENT")
    pct = evidence.get("price_change_pct")
    if isinstance(pct, (int, float)) and abs(pct) >= MATERIAL_PRICE_PCT:
        triggers.append("MATERIAL_PRICE_MOVE")
    coverage = evidence.get("coverage") or {}
    if any((coverage.get(f) or {}).get("status") != "COMPLETE"
           for f in reuse_shadow.REQUIRED_EVIDENCE):
        triggers.append("INCOMPLETE_COVERAGE")
    if not evidence.get("prior_integrity_valid", True):
        triggers.append("PRIOR_INTEGRITY_FAILURE")
    return triggers


def _downgrade_savings(savings: dict, isolated: bool) -> dict:
    """Never label cache-contaminated wall-clock/network savings MEASURED."""
    if isolated:
        return savings
    for key in ("time_saved_ms", "time_saved_pct",
                "external_network_calls_avoided"):
        if savings.get("quality", {}).get(key) == "MEASURED":
            savings["quality"][key] = "PARTIAL"
    return savings


def _fallback_stub(decision: dict, result: dict, artifact_path: Path) -> dict:
    """VALIDATE fallback: record the failed UPDATE attempt without spending
    a second full graph. The research stub is never canonical authority."""
    metrics = _optimized_metrics("UPDATE", decision, result)
    artifact = {
        "ticker": decision["ticker"], "decision_session": decision["session"],
        "signal": None, "optimized_aborted": True,
        "abort_reason": result["fallback"],
        "reuse_execution": _reuse_block(
            decision, ["delta_probe", "update_reasoner"], ["full_graph"],
            fallback=True),
        "analysis_metrics": metrics,
    }
    artifact_path.write_text(json.dumps(seal_case(artifact), indent=1, default=str))
    return artifact


def run_validated_pair(ticker: str, session: str, *, full_run, case_dir=None,
                       facts_dir=None, probe_fn=None, llm_fn=None,
                       validation_dir=None, cache_dir=None,
                       portfolio: str = "flat / entry analysis") -> dict:
    """Paired controlled validation: optimized leg + isolated baseline.

    The canonical ``{ticker}_{session}.json`` artifact is ALWAYS produced by
    the existing full-refresh runner — it remains the economic and
    publication authority. The optimized result lands in
    ``{ticker}_{session}.optimized.json`` as research-only evidence.

    Isolation: the provider cache is cloned into two temporary roots BEFORE
    any provider work — including the delta probe — so both legs start from
    the identical pre-probe cache state and neither leg's writes can benefit
    the other. The optimized leg (probe included) runs inside its own cache
    context; the baseline runs against its own clone. If isolation is
    unavailable, time/network savings are downgraded to PARTIAL.
    """
    from alpha_rnd.savings_report import compare_metrics

    case_dir = Path(case_dir or CASE_DIR)
    canonical = case_dir / f"{ticker}_{session}.json"
    optimized_path = case_dir / f"{ticker}_{session}.optimized.json"
    # Isolation snapshot BEFORE ANY provider work (probe included): both legs
    # start from the identical PRE-PROBE cache state; neither leg observes the
    # other's cache writes. If no cache can be cloned, savings quality is
    # honestly downgraded — never labelled MEASURED.
    isolated = False
    tempdirs = []
    opt_cache: Path | None = None
    base_cache: Path | None = None
    src = Path(cache_dir) if cache_dir else CACHE_DIR
    try:
        if src.exists():
            for name in ("optimized", "baseline"):
                root = Path(tempfile.mkdtemp(prefix=f"reuse_cache_{name}_"))
                tempdirs.append(root)
                shutil.copytree(src, root / "cache", dirs_exist_ok=True)
            opt_cache = tempdirs[0] / "cache"
            base_cache = tempdirs[1] / "cache"
            isolated = True
    except Exception:
        isolated = False
    run_kwargs_base = (
        {"config_overrides": {"data_cache_dir": str(base_cache)}}
        if isolated else {})
    run_kwargs_opt = (
        {"config_overrides": {"data_cache_dir": str(opt_cache)}}
        if isolated else {})
    try:
        # Optimized leg: the ENTIRE optimized decision path — resolve, probe,
        # classify, execute — runs inside the optimized-only cache context so
        # its provider writes can never warm the baseline's clone.
        from contextlib import nullcontext

        from tradingagents.dataflows.config import run_config
        def opt_context():
            return (run_config({"data_cache_dir": str(opt_cache)})
                    if isolated else nullcontext())
        with opt_context():
            decision = decide(ticker, session, case_dir=case_dir,
                              facts_dir=facts_dir, probe_fn=probe_fn)
        if decision["mode"] == "FULL_REFRESH":
            # Both paths are the same run; do not double-spend the graph.
            # But the FULL_REFRESH selection still PAID for the delta probe:
            # in ENABLED operation the ticker incurs probe + full analysis.
            # That overhead is recorded honestly — zero model-call savings,
            # extra provider requests, measured probe time — never hidden.
            baseline = full_run(ticker, session, canonical.name, **run_kwargs_base)
            probe = decision.get("delta_probe") or {}
            base_metrics = baseline.get("analysis_metrics") or {}
            base_prov = (base_metrics.get("provider_calls") or {}).get(
                "logical_data_calls")
            probe_calls = probe.get("provider_call_count")
            provider_effect = (
                # Enabled path = probe + full graph. Like-for-like vs the
                # baseline's own logical calls: -(probe calls).
                -probe_calls
                if isinstance(base_prov, (int, float))
                and isinstance(probe_calls, (int, float))
                else None)
            record = {
                "schema_version": SCHEMA_VERSION, "ticker": ticker,
                "session": session, "authority": "FULL_REFRESH_BASELINE",
                "optimized_mode": "FULL_REFRESH",
                "note": "Optimized path selected full refresh; identical run, "
                        "no duplicate spend. The delta-probe overhead is real "
                        "cost of the optimized path and is recorded below.",
                "decision_reasons": decision["reasons"],
                "probe_evidence": _probe_evidence(decision),
                "probe_overhead": {
                    "elapsed_ms": probe.get("elapsed_ms"),
                    "provider_call_count": probe_calls,
                    "provider_attempts": probe.get("provider_attempts"),
                    "known_external_network_calls":
                        probe.get("known_external_network_calls"),
                    "external_network_quality":
                        probe.get("external_network_quality"),
                    "model_calls": 0,
                },
                "optimized_signal": _norm_signal(baseline.get("signal")),
                "baseline_signal": _norm_signal(baseline.get("signal")),
                "signal_agreement": True, "executable_disagreement": False,
                "cache_isolation": isolated,
                "savings": {
                    "realized_savings": "PROBE_OVERHEAD_ONLY",
                    "model_calls_avoided": 0,
                    # Negative when the probe added provider requests the
                    # baseline did not need — like-for-like logical calls.
                    "provider_calls_avoided": provider_effect,
                    "time_saved_ms": None,
                    "full_refresh_probe_overhead_ms": probe.get("elapsed_ms"),
                    "quality": {
                        "model_calls_avoided": "MEASURED",
                        "provider_calls_avoided": (
                            "MEASURED" if provider_effect is not None
                            else "UNAVAILABLE"),
                        # Enabled-path wall clock = probe + full graph, but the
                        # full graph may benefit from probe cache writes, so
                        # baseline_time + probe_time is not an exact total.
                        "time_saved_ms": "UNAVAILABLE",
                        "optimized_full_refresh_time": "PARTIAL",
                    },
                },
                "generated_at": datetime.now(UTC).isoformat(),
            }
            persist_pair(record, validation_dir)
            return baseline
        with opt_context():
            optimized = run_optimized(
                ticker, session, full_run=full_run, case_dir=case_dir,
                facts_dir=facts_dir,
                probe_fn=lambda *a, **k: decision["delta_probe"],
                llm_fn=llm_fn, artifact_path=optimized_path,
                on_fallback=_fallback_stub, full_run_kwargs=run_kwargs_opt,
                decision=decision, portfolio=portfolio)
        # Baseline leg: the existing full graph, canonical authority, running
        # against the baseline-only clone — untouched by the optimized probe.
        baseline = full_run(ticker, session, canonical.name, **run_kwargs_base)
        comparison = (
            compare_decisions(optimized, baseline)
            if optimized.get("signal") is not None
            else {"optimized_signal": None,
                  "baseline_signal": _norm_signal(baseline.get("signal")),
                  "optimized_aborted": True,
                  "signal_agreement": None, "rating_agreement": None,
                  "research_disagreement": None,
                  "executable_action_agreement": None,
                  "executable_disagreement": False})
        savings = _downgrade_savings(
            compare_metrics(baseline.get("analysis_metrics", {}),
                            optimized.get("analysis_metrics")), isolated)
        record = {
            "schema_version": SCHEMA_VERSION, "ticker": ticker,
            "session": session, "authority": "FULL_REFRESH_BASELINE",
            "optimized_mode": optimized["reuse_execution"]["mode"],
            "fallback_to_full_refresh":
                optimized["reuse_execution"]["fallback_to_full_refresh"],
            "decision_reasons": optimized["reuse_execution"]["decision_reasons"],
            "delta_reasons": optimized["reuse_execution"]["delta_reasons"],
            "probe_evidence": _probe_evidence(decision),
            "cache_isolation": isolated,
            **comparison,
            "optimized_metrics": optimized.get("analysis_metrics"),
            "baseline_metrics": baseline.get("analysis_metrics"),
            "savings": savings,
            "generated_at": datetime.now(UTC).isoformat(),
        }
        persist_pair(record, validation_dir)
        return baseline
    finally:
        for root in tempdirs:
            shutil.rmtree(root, ignore_errors=True)


# --------------------------------------------------------------- rollout gate

def load_pairs(validation_dir=None) -> list[dict]:
    records = []
    for path in sorted(Path(validation_dir or VALIDATION_DIR).glob("*_*.json")):
        try:
            record = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(record, dict) and record.get("ticker"):
            records.append(record)
    return records


def evaluate_readiness(validation_dir=None, min_pairs: int = 5,
                       min_tickers: int = 3) -> dict:
    """Objective rollout gate. Reports only — NEVER enables authority.

    Missed-trigger detection re-derives mandatory refresh conditions from the
    pair's persisted probe_evidence, independent of the classifier's own
    reasons.
    """
    pairs = load_pairs(validation_dir)
    tickers = {pair["ticker"] for pair in pairs}
    unsafe = [
        f"{p['ticker']}:{p['session']}" for p in pairs
        if p.get("executable_disagreement")
    ]
    missed = [
        f"{p['ticker']}:{p['session']}" for p in pairs
        if p.get("optimized_mode") in ("UPDATE", "REUSE")
        and not p.get("fallback_to_full_refresh")
        and _mandatory_refresh(p.get("probe_evidence") or {})
    ]
    integrity_failures = [
        f"{p['ticker']}:{p['session']}" for p in pairs
        if p.get("integrity_failure") or p.get("point_in_time_failure")
        or (p.get("probe_evidence") or {}).get("prior_integrity_valid") is False
    ]
    def _measured(pair, key):
        savings = pair.get("savings") or {}
        quality = savings.get("quality")
        value = savings.get(key)
        if not isinstance(quality, dict):  # legacy string label or missing
            return None
        if quality.get(key) != "MEASURED":  # PARTIAL/ESTIMATED/UNAVAILABLE never count
            return None
        return value if isinstance(value, (int, float)) else None

    time_saved = [
        value for p in pairs
        if (value := _measured(p, "time_saved_ms")) is not None
    ]
    calls_avoided = [
        value for p in pairs
        if (value := _measured(p, "model_calls_avoided")) is not None
    ]
    meaningful = (sum(calls_avoided) > 0) or (
        bool(time_saved) and sum(time_saved) > 0)
    ready = (
        len(pairs) >= min_pairs and len(tickers) >= min_tickers
        and not unsafe and not missed and not integrity_failures
        and meaningful
    )
    return {
        "ready_for_optimized_authority": "YES" if ready else "NO",
        "pairs_completed": len(pairs),
        "distinct_tickers": len(tickers),
        "required_pairs": min_pairs,
        "required_tickers": min_tickers,
        "unsafe_executable_disagreements": unsafe,
        "missed_full_refresh_triggers": missed,
        "integrity_or_pit_failures": integrity_failures,
        "measured_time_saved_ms": sum(time_saved),
        "measured_model_calls_avoided": sum(calls_avoided),
        "meaningful_measured_benefit": meaningful,
        "auto_enable": False,
        "note": "Operator approval is still required; this report never "
                "changes ALPHA_REUSE_ENGINE.",
    }
