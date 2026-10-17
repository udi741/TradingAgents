#!/usr/bin/env python3
"""Phase G — professional profit-objective contract.

EVERY EXECUTABLE BUY DEFINES FAILURE AND SUCCESS.
NO RUNNER WITHOUT A REMAINING THESIS.

Extracts/validates a structured success plan for a long entry, freezes it
in the immutable entry snapshot, and exposes it to management context.
"""
import json
import re
from pathlib import Path

FIELDS = ["base_case_value_range", "bull_case_value_range",
          "expected_upside_pct", "expected_reward_to_risk",
          "success_criteria", "catalyst_milestones",
          "priced_in_rule", "profit_realization_plan"]


def extract(intent: dict | None) -> dict:
    """Build a success plan from an intent. Legacy single `target` becomes
    base-case top when no explicit range exists — recorded, not invented."""
    i = intent or {}
    p = i.get("params") or {}
    tgt = i.get("target")
    try:
        tgt = float(tgt) if tgt is not None else None
    except (TypeError, ValueError):
        tgt = None
    bc = i.get("base_case_value_range")
    bl = i.get("bull_case_value_range")
    if not bc and tgt:
        bc = [tgt, tgt]
    return {
        "base_case_value_range": bc,
        "bull_case_value_range": bl,
        "expected_upside_pct": i.get("expected_upside_pct"),
        "expected_reward_to_risk": i.get("expected_reward_to_risk"),
        "success_criteria": i.get("success_criteria")
            or i.get("reevaluation") or p.get("success_criteria"),
        "catalyst_milestones": i.get("catalysts") or i.get("reevaluation"),
        "priced_in_rule": i.get("priced_in_rule"),
        "profit_realization_plan": i.get("profit_realization_plan")
            or i.get("target"),
        "legacy_target": tgt,
    }


def _hi(rng):
    try:
        return float(rng[1] if isinstance(rng, list) and len(rng) == 2 else rng)
    except (TypeError, ValueError, IndexError):
        return None


def validate(plan: dict, entry: float, stop: float | None,
             policy: dict | None = None) -> tuple[dict | None, list[str]]:
    """Fail-closed validation for a LONG success plan. Returns (plan, errs).
    Minimums live in policy['success_plan'], never hardcoded thresholds."""
    errs = []
    pol = (policy or {}).get("success_plan") or {}
    if not plan.get("success_criteria"):
        errs.append("missing success_criteria")
    if not plan.get("profit_realization_plan"):
        errs.append("missing profit_realization_plan")
    bc_hi = _hi(plan.get("base_case_value_range"))
    if bc_hi is None:
        errs.append("missing/unparsable base_case_value_range")
    elif entry and bc_hi <= entry:
        errs.append(f"base_case objective {bc_hi} <= long entry {entry}")
    up = plan.get("expected_upside_pct")
    if up is None and bc_hi and entry:
        up = round((bc_hi / entry - 1) * 100, 2)
    if up is not None and up <= 0:
        errs.append("expected_upside_pct <= 0")
    min_up = pol.get("min_upside_pct")
    if min_up is not None and up is not None and up < min_up:
        errs.append(f"expected upside {up}% < policy min {min_up}%")
    rr = plan.get("expected_reward_to_risk")
    if rr is None and bc_hi and entry and stop and stop < entry:
        rr = round((bc_hi - entry) / (entry - stop), 2)
    if rr is not None and rr <= 0:
        errs.append("expected_reward_to_risk <= 0")
    min_rr = pol.get("min_rr")
    if min_rr is not None and rr is not None and rr < min_rr:
        errs.append(f"expected RR {rr} < policy min {min_rr}")
    if errs:
        return None, errs
    out = dict(plan, expected_upside_pct=up, expected_reward_to_risk=rr,
               base_case_top=bc_hi, bull_case_top=_hi(
                   plan.get("bull_case_value_range")))
    return out, []


def upside_realized_pct(entry: float, base_top: float, price: float) -> float:
    """% of original upside objective achieved (can exceed 100)."""
    if not entry or not base_top or base_top <= entry:
        return 0.0
    return round((price - entry) / (base_top - entry) * 100, 1)


def mgmt_context_fields(plan: dict, entry: float, price: float) -> dict:
    """Success-plan block injected into every reassessment context."""
    bc = _hi((plan or {}).get("base_case_value_range")) \
        or (plan or {}).get("base_case_top")
    bl = _hi((plan or {}).get("bull_case_value_range")) \
        or (plan or {}).get("bull_case_top")
    rem = round((bc / price - 1) * 100, 2) if bc and price else None
    rem_bull = round((bl / price - 1) * 100, 2) if bl and price else None
    return {"original_base_case_top": bc, "original_bull_case_top": bl,
            "original_target": (plan or {}).get("legacy_target"),
            "pct_original_upside_realized":
                upside_realized_pct(entry, bc, price) if bc else None,
            "base_case_reached": bool(bc and price >= bc),
            "bull_case_reached": bool(bl and price >= bl),
            "remaining_upside_pct_to_base": rem,
            "remaining_upside_pct_to_bull": rem_bull,
            "success_criteria": (plan or {}).get("success_criteria"),
            "priced_in_rule": (plan or {}).get("priced_in_rule"),
            "profit_realization_plan":
                (plan or {}).get("profit_realization_plan")}


def runner_contract_ok(analysis: dict) -> tuple[bool, str]:
    """HOLD*/runner on a realized objective requires remaining thesis +
    objective + upside. Returns (ok, reason)."""
    rt = analysis.get("remaining_thesis") or \
        analysis.get("runner", {}).get("remaining_thesis")
    ro = analysis.get("revised_objective") or \
        analysis.get("runner", {}).get("revised_objective")
    ru = analysis.get("remaining_upside_pct")
    if ru is None:
        ru = (analysis.get("runner") or {}).get("remaining_upside_pct")
    if not rt:
        return False, "runner lacks remaining_thesis"
    if ro is None:
        return False, "runner lacks revised/remaining value objective"
    if ru is None or (isinstance(ru, (int, float)) and ru <= 0):
        return False, "runner lacks meaningful remaining upside"
    return True, "runner contract satisfied"
