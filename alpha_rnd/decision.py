#!/usr/bin/env python3
"""Unified decision contract — LONG / SHORT / NO_TRADE.

Single canonical outcome object for AI-authored research. Adapts either
an `economic_authority` contract (canonical production contract) or a
legacy prose intent, then validates the complete economic plan.

LONG contracts keep flowing through production gates
(econ_contract.has_authority + project_execution). SHORT contracts are
paper-simulation objects only — they never grant execution authority.
"""
import math

ENTRY_TYPES = {"limit_zone", "limit_level", "close_above", "close_below",
               "next_open", "conditional", "stop_entry"}
SHORT_BORROW_BPS_PER_DAY = 0.02 / 365  # ~2%/yr financing assumption

REQUIRED = ("direction", "entry", "stop", "target", "horizon",
            "provenance")


def _f(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) and v > 0 else None


def _zone(v):
    if isinstance(v, (list, tuple)) and len(v) == 2:
        a, b = _f(v[0]), _f(v[1])
        if a and b:
            return [min(a, b), max(a, b)]
    return None


def validate(c: dict) -> list[str]:
    """[] = valid. NO_TRADE needs only a reason; everything else is fully
    validated. Mutates c to fill reward_risk on success."""
    if c.get("direction") == "NO_TRADE":
        return [] if c.get("reason") else ["NO_TRADE_WITHOUT_REASON"]
    errs = [f"MISSING_{k.upper()}" for k in REQUIRED if c.get(k) is None]
    if errs:
        return errs
    d = c["direction"]
    if d not in ("LONG", "SHORT"):
        return ["BAD_DIRECTION"]
    e = c["entry"]
    zone, lvl = _zone(e.get("zone")), _f(e.get("level") or
                                        e.get("trigger_level"))
    if not zone and not lvl:
        return ["NO_ENTRY_PRICE"]
    ref = (zone[1] if zone else lvl) if d == "LONG" else \
        (zone[0] if zone else lvl)
    stop, tgt = _f(c.get("stop")), _f(c.get("target"))
    if not stop:
        return ["BAD_STOP"]
    if not tgt:
        return ["BAD_TARGET"]
    if d == "LONG":
        if stop >= ref:
            return ["STOP_NOT_BELOW_ENTRY"]
        if tgt <= ref:
            return ["TARGET_NOT_ABOVE_ENTRY"]
        rr = (tgt - ref) / (ref - stop)
    else:
        if stop <= ref:
            return ["STOP_NOT_ABOVE_ENTRY"]
        if tgt >= ref:
            return ["TARGET_NOT_BELOW_ENTRY"]
        if not c.get("paper_only", True):
            return ["SHORT_MUST_BE_PAPER_ONLY"]
        rr = (ref - tgt) / (stop - ref)
    sf = c.get("size_frac")
    if sf is not None and not (isinstance(sf, (int, float))
                               and 0 < sf <= 1):
        return ["BAD_SIZE_FRAC"]
    # missing AI-authored size is not a rejection: the risk engine derives
    # the permissible allocation from stop distance + risk budget
    c["permissible_size_frac"] = permissible_size(
        c, risk_budget_frac=0.01)
    if c["permissible_size_frac"] <= 0:
        return ["NO_PERMISSIBLE_SIZE"]
    c["reward_risk"] = round(rr, 3)
    if rr <= 0:
        return ["NON_POSITIVE_RR"]
    return []


def permissible_size(c: dict, risk_budget_frac: float = 0.01) -> float:
    """Deterministic sizing: frac = risk_budget / stop_distance, capped 1.0.
    risk_budget_frac = portfolio fraction risked per trade (default 1%)."""
    d = c["direction"]
    e = c["entry"]
    zone, lvl = _zone(e.get("zone")), _f(e.get("level") or
                                        e.get("trigger_level"))
    ref = (zone[1] if zone else lvl) if d == "LONG" else \
        (zone[0] if zone else lvl)
    stop = _f(c.get("stop"))
    if not ref or not stop or ref == stop:
        return 0.0
    dist = abs(ref - stop) / ref
    return round(min(1.0, risk_budget_frac / dist), 4)


def from_economic_authority(contract: dict, session: str,
                            ticker: str, signal=None) -> dict:
    """Adapt the canonical economic_authority contract to a decision."""
    d = contract.get("direction")
    if d in (None, "NONE"):
        return {"direction": "NO_TRADE", "reason": "contract direction NONE",
                "provenance": {"session": session, "ticker": ticker}}
    e = contract.get("entry") or {}
    sizing = contract.get("sizing") or {}
    stop = (contract.get("stop") or {}).get("level")
    obj = contract.get("objective") or {}
    tgt = obj.get("target")
    if tgt is None and _zone(obj.get("base_case_value_range")):
        tgt = _zone(obj["base_case_value_range"])[1]
    c = {"direction": d,
         "entry": {"type": "limit_zone" if e.get("zone") else
                   ("conditional" if e.get("trigger_level") else
                    (e.get("mode") or "").lower() or None),
                   "zone": e.get("zone"),
                   "level": e.get("trigger_level"),
                   "activation": e.get("condition")},
         "stop": stop, "target": tgt,
         "horizon": contract.get("horizon"),
         "size_frac": sizing.get("initial_frac"),
         "provenance": {"session": session, "ticker": ticker,
                        "signal": signal, "source": "economic_authority"},
         "costs_bps_per_side": 10, "paper_only": True}
    if d == "SHORT":
        c["borrow_bps_per_day"] = SHORT_BORROW_BPS_PER_DAY
        c["exit_mode"] = "buy_to_cover"
    errs = validate(c)
    if errs:
        return {"direction": "NO_TRADE", "reason": ";".join(errs),
                "provenance": c["provenance"], "attempted": d,
                "_rejected_contract": c}
    return c


def from_intent(intent: dict, signal, is_short: bool, session: str) -> dict:
    """Adapt a legacy prose intent. Prefer its resolved contract when one
    exists; never fabricate missing terms."""
    ea = intent.get("economic_authority_resolved") or \
        intent.get("economic_authority")
    if ea:
        return from_economic_authority(ea, session,
                                       intent.get("ticker"), signal)
    from backtest.decision_contract import author  # legacy adapter
    return author(intent, signal, is_short, session)
