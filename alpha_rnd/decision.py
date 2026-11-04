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


def entry_feasibility(c: dict, ref_price: float | None) -> dict:
    """Decision-time entry evaluation — classifies the authored entry type
    and whether its terms are plausibly reachable, using ONLY the price
    known at decision time. Never invents levels.

    pullback:    authored fill sits below market (LONG) — requires a dip;
                 'near' when <=3% below ref, 'deep_stale' beyond it.
    continuation: authored trigger sits above market (LONG) — needs the
                 breakout/confirm to occur first (conditional by nature).
    market:      entry at/through current price — reachable now.
    """
    d = c.get("direction")
    e = c.get("entry") or {}
    zone, lvl = _zone(e.get("zone")), _f(e.get("level") or
                                        e.get("trigger_level"))
    out = {"entry_type": None, "entry_feasibility": "unspecified",
           "ref_price": ref_price}
    if not zone and not lvl:
        return out
    anchor = (zone[1] if zone else lvl) if d == "LONG" else         (zone[0] if zone else lvl)
    if anchor is None:
        return out
    if ref_price is None:
        out["entry_type"] = "pullback" if zone else "conditional"
        out["entry_feasibility"] = "unpriced"
        return out
    if zone and zone[0] <= ref_price <= zone[1]:
        out["entry_type"] = "pullback"
        out["entry_feasibility"] = "near"
        out["entry_distance_pct"] = 0.0
        return out
    if d == "SHORT":
        if anchor >= ref_price:
            out["entry_type"] = "pullback"      # bounce-entry: needs rally
            dist = (anchor - ref_price) / ref_price
            out["entry_feasibility"] =                 "near" if dist <= 0.03 else "deep_stale"
        else:
            out["entry_type"] = "continuation"
            out["entry_feasibility"] = "conditional_breakdown"
        out["entry_distance_pct"] = round(
            100 * abs(anchor - ref_price) / ref_price, 2)
        return out
    if anchor >= ref_price:
        out["entry_type"] = "continuation"
        out["entry_feasibility"] =             "conditional_breakout" if anchor > ref_price else "market"
    else:
        out["entry_type"] = "pullback"
        dist = (ref_price - anchor) / ref_price
        out["entry_feasibility"] = "near" if dist <= 0.03 else             "deep_stale"
    out["entry_distance_pct"] = round(
        100 * abs(anchor - ref_price) / ref_price, 2)
    return out


def select_plan(contract: dict, session: str, ticker: str,
                signal=None, ref_price: float | None = None) -> dict:
    """Pre-authorization plan evaluation. Validates the primary contract and
    each authored alternate; returns the best COHERENT decision, or NO_TRADE
    when none survive. Never invents levels — alternates must be authored
    and evidence-bound by the model (validator enforces binding elsewhere).

    Selection (deterministic): the plan with the best ECONOMICS wins —
    higher authored reward_risk first; entry feasibility only breaks ties
    (a closer but economically inferior plan does not defeat a sounder
    one). When reward_risk is unavailable, feasibility is the fallback
    ordering. Feasibility is never a gate.
    """
    candidates = [contract] + list(contract.get("alternate_plans") or [])
    scored = []
    for cand in candidates:
        c = from_economic_authority(cand, session, ticker, signal,
                                    ref_price=ref_price)
        if c.get("direction") == "NO_TRADE":
            continue
        fe = c.get("entry_feasibility")
        rank = {"near": 0, "market": 0,
                "conditional_breakout": 1, "conditional_breakdown": 1,
                "deep_stale": 2, "unpriced": 3,
                "unspecified": 4}.get(fe, 5)
        scored.append((rank, cand.get("entry_style"), c))
    if not scored:
        return {"direction": "NO_TRADE", "reason": "NO_VALID_PLAN",
                "provenance": {"session": session, "ticker": ticker}}
    # authored primary is the intended trade — it stands while valid.
    # Alternates are evaluated only when the primary is invalid; then the
    # best-RR alternate wins, feasibility breaking ties. Never silently
    # replace a valid intended trade for a nominally-better RR.
    prim = [x for x in scored if x[1] is None]
    if prim:
        return prim[0][2]
    scored.sort(key=lambda x: (-(x[2].get("reward_risk") or 0),
                               x[0], x[1] is None))
    return scored[0][2]


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
                            ticker: str, signal=None,
                            ref_price: float | None = None) -> dict:
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
                "_rejected_contract": c,
                **entry_feasibility(c, ref_price)}
    c.update(entry_feasibility(c, ref_price))
    return c


def from_intent(intent: dict, signal, is_short: bool, session: str) -> dict:
    """Adapt a legacy prose intent. Prefer its resolved contract when one
    exists; never fabricate missing terms."""
    ea = intent.get("economic_authority_resolved") or \
        intent.get("economic_authority")
    if ea:
        ref = _f((intent.get("params") or {}).get("current_price"))
        return from_economic_authority(ea, session,
                                       intent.get("ticker"), signal,
                                       ref_price=ref)
    from backtest.decision_contract import author  # legacy adapter
    return author(intent, signal, is_short, session)
