#!/usr/bin/env python3
"""Canonical economic-authority contract for constructive ALPHA ideas.

Narrative prose is research/explanation. When a TA artifact resolves to one
authoritative plan, the translator emits `economic_authority` — a single
machine-readable contract — and the publication validator validates THAT
contract instead of rejecting the idea over superseded exploratory prose
(multiple sizing examples, alternative tranche wording, slightly different
entry ranges).

Fail-closed rules preserved:
- a contract that is itself contradictory/invalid fails closed with a
  precise ECON_* reason;
- missing risk plan still fails closed (stop required for LONG);
- executable LONG still requires a valid Phase-G success plan
  (success_plan.validate over the contract's objective fields);
- every number must bind to the source artifact text (no invented
  economics);
- stale provenance fails closed;
- non-LONG or absent contracts can never create executable authority.
"""
import re
from alpha_rnd import success_plan

SCHEMA_VERSION = 1

# Fraction fields inside a contract that must stay within (0, 1].
_FRAC_MAX = 1.0


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _zone(e):
    """Entry zone [lo, hi] or None."""
    z = (e or {}).get("zone")
    if isinstance(z, (list, tuple)) and len(z) == 2:
        lo, hi = _num(z[0]), _num(z[1])
        if lo is not None and hi is not None:
            return [lo, hi]
    return None


def validate(contract: dict | None, artifact: dict, intent: dict,
             src_nums: set) -> tuple[list[str], dict | None]:
    """Validate the authoritative contract. Returns (errors, resolved).

    resolved is a normalized contract only when errors is empty.
    src_nums is the artifact's evidence-binding number set
    (synthesize._nums_in_text).
    """
    if contract is None:
        return [], None
    errs = []
    if not isinstance(contract, dict):
        return ["ECON_CONTRACT_NOT_OBJECT"], None
    # --- provenance -----------------------------------------------------
    sess = contract.get("session")
    if sess and artifact.get("decision_session") and \
            sess != artifact["decision_session"]:
        errs.append("ECON_PROVENANCE_STALE: contract session "
                    f"{sess} != artifact {artifact['decision_session']}")
    if contract.get("ticker") and contract["ticker"] != artifact.get("ticker"):
        errs.append("ECON_TICKER_MISMATCH")
    # --- direction ------------------------------------------------------
    direction = str(contract.get("direction") or "").upper()
    if direction not in ("LONG", "SHORT", "NONE"):
        errs.append("ECON_DIRECTION_INVALID")
        return errs, None
    if direction == "NONE":
        return errs or ["ECON_NONE_CONTRACT"], None
    if direction == "LONG" and artifact.get("signal") not in (
            "Buy", "Overweight"):
        errs.append(f"ECON_LONG_CONTRADICTS_SIGNAL:{artifact.get('signal')}")
    if direction == "SHORT":
        # no short execution path exists — descriptive only, never errors
        return errs, {"direction": "SHORT"}
    # --- entry ----------------------------------------------------------
    entry = contract.get("entry") or {}
    zone = _zone(entry)
    trig = _num(entry.get("trigger_level") or entry.get("level"))
    mode = entry.get("mode")
    if mode not in ("LIMIT_ZONE", "NEXT_OPEN", "CONDITIONAL", "STOP_ENTRY"):
        errs.append("ECON_ENTRY_MODE_INVALID")
    if zone is None and trig is None and not entry.get("condition"):
        errs.append("ECON_NO_ENTRY_CONDITION")
    if zone is not None and not (0 < zone[0] < zone[1]):
        errs.append("ECON_ZONE_INVALID")
    entry_ref = zone[1] if zone else trig
    # --- sizing ---------------------------------------------------------
    sz = contract.get("sizing") or {}
    init = _num(sz.get("initial_frac"))
    mx = _num(sz.get("max_frac"))
    tr = sz.get("tranches") or []
    if init is None and not tr:
        errs.append("ECON_NO_INITIAL_SIZE")
    for f, name in ((init, "initial_frac"), (mx, "max_frac")):
        if f is not None and not (0 < f <= _FRAC_MAX):
            errs.append(f"ECON_{name.upper()}_OUT_OF_RANGE:{f}")
    if init is not None and mx is not None and init > mx:
        errs.append("ECON_INIT_EXCEEDS_MAX")
    tsum = 0.0
    for i, t in enumerate(tr):
        tf = _num((t or {}).get("frac"))
        if tf is None or not (0 < tf <= _FRAC_MAX):
            errs.append(f"ECON_TRANCHE_{i}_FRAC_INVALID")
        else:
            tsum += tf
    if tr and mx is not None:
        base = init or 0.0
        if base + tsum - mx > 1e-9:
            errs.append(f"ECON_TRANCHES_EXCEED_MAX:{round(base + tsum, 4)}>{mx}")
    # --- stop / invalidation (risk plan) ---------------------------------
    stop = contract.get("stop") or {}
    sl = _num(stop.get("level"))
    stype = stop.get("type")
    if sl is None:
        errs.append("ECON_NO_STOP")  # missing risk plan: fail closed
    elif sl <= 0:
        errs.append("ECON_STOP_NONPOSITIVE")
    elif entry_ref is not None and sl >= entry_ref:
        errs.append(f"ECON_STOP_ABOVE_ENTRY:{sl}>={entry_ref}")
    if stype not in ("close_below", "intraday_stop", "price_below"):
        errs.append("ECON_STOP_TYPE_INVALID")
    # --- objective / Phase-G success plan -------------------------------
    obj = contract.get("objective") or {}
    plan = success_plan.extract({
        "target": obj.get("target"),
        "base_case_value_range": obj.get("base_case_value_range"),
        "bull_case_value_range": obj.get("bull_case_value_range"),
        "expected_upside_pct": obj.get("expected_upside_pct"),
        "expected_reward_to_risk": obj.get("expected_reward_to_risk"),
        "success_criteria": contract.get("success_criteria"),
        "reevaluation": contract.get("event_constraints") and
            "; ".join(map(str, contract["event_constraints"])) or None,
        "profit_realization_plan": contract.get("profit_realization_plan"),
    })
    vplan, perr = success_plan.validate(
        plan, entry_ref or 0, sl, policy=None)
    errs += [f"ECON_SUCCESS_PLAN:{e}" for e in perr]
    # --- horizon ---------------------------------------------------------
    if not contract.get("horizon"):
        errs.append("ECON_NO_HORIZON")
    # --- evidence binding: every contract number exists in source text ---
    for v in _contract_numbers(contract):
        if not any(abs(v - s) <= max(0.005 * abs(s), 0.01)
                   for s in src_nums):
            errs.append(f"ECON_UNSUPPORTED_NUMBER:{v}")
    if errs:
        return errs, None
    return [], {"schema_version": SCHEMA_VERSION, "direction": direction,
                "entry": entry, "sizing": sz, "stop": stop,
                "objective": vplan, "horizon": contract["horizon"],
                "event_constraints": contract.get("event_constraints") or [],
                "no_entry_conditions":
                    contract.get("no_entry_conditions") or [],
                "resolves": contract.get("resolves") or []}


def _contract_numbers(c: dict) -> list[float]:
    out = []
    e = c.get("entry") or {}
    for v in (_zone(e) or []):
        out.append(v)
    for k in ("trigger_level", "level"):
        v = _num(e.get(k))
        if v is not None:
            out.append(v)
    sz = c.get("sizing") or {}
    for k in ("initial_frac", "max_frac"):
        v = _num(sz.get(k))
        if v is not None:
            out.append(v)
    for t in sz.get("tranches") or []:
        v = _num((t or {}).get("frac"))
        lv = _num((t or {}).get("level"))
        for x in (v, lv):
            if x is not None:
                out.append(x)
    sl = _num((c.get("stop") or {}).get("level"))
    if sl is not None:
        out.append(sl)
    obj = c.get("objective") or {}
    for k in ("target", "expected_upside_pct", "expected_reward_to_risk"):
        v = _num(obj.get(k))
        if v is not None:
            out.append(v)
    for k in ("base_case_value_range", "bull_case_value_range"):
        r = obj.get(k)
        if isinstance(r, (list, tuple)):
            out += [x for x in (_num(v) for v in r) if x is not None]
    return out


def has_authority(intent: dict, resolved: dict | None) -> bool:
    """True only when a validated LONG contract grants economic authority.
    REANALYZE watches and SHORT/NONE contracts never qualify."""
    return bool(resolved and resolved.get("direction") == "LONG")
