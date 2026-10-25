#!/usr/bin/env python3
"""Experimental decision contract — LONG/SHORT/NO_TRADE, paper-only.

Unifies what an AI intent must state to be economically testable:
direction, entry (type + price/zone + activation), stop, target, horizon,
sizing, R/R, costs, provenance, and — for NO_TRADE — an explicit reason.

Never grants execution authority: SHORT contracts are paper-simulation
objects only; LONG contracts still must pass production gates
(synthesize._machine_executable / econ_contract.has_authority) downstream.
"""
import math
import re

ENTRY_TYPES = {"limit_zone", "limit_level", "close_above", "close_below"}
SHORT_BORROW_BPS_PER_DAY = 0.02 / 365  # ~2%/yr assumption, flagged

REQUIRED = ("direction", "entry", "stop", "target", "horizon",
            "size_frac", "provenance")


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
    """Return rejection reasons ([] = valid). NO_TRADE needs only a
    reason; everything else validated fully."""
    if c.get("direction") == "NO_TRADE":
        return [] if c.get("reason") else ["NO_TRADE_WITHOUT_REASON"]
    errs = [f"MISSING_{k.upper()}" for k in REQUIRED if c.get(k) is None]
    if errs:
        return errs
    d = c["direction"]
    if d not in ("LONG", "SHORT"):
        return ["BAD_DIRECTION"]
    e = c["entry"]
    if e.get("type") not in ENTRY_TYPES:
        return ["BAD_ENTRY_TYPE"]
    zone, lvl = _zone(e.get("zone")), _f(e.get("level"))
    if not zone and not lvl:
        return ["NO_ENTRY_PRICE"]
    ref = zone[1] if zone else lvl  # LONG fill ref = zone top
    stop, tgt = _f(c.get("stop")), _f(c.get("target"))
    if not stop:
        return ["BAD_STOP"]
    if not tgt:
        return ["BAD_TARGET"]
    if d == "LONG":
        if stop >= ref:
            return ["STOP_NOT_BELOW_ENTRY"]   # LONG geometry
        if tgt <= ref:
            return ["TARGET_NOT_ABOVE_ENTRY"]
        rr = (tgt - ref) / (ref - stop)
    else:
        ref = zone[0] if zone else lvl  # SHORT fill ref = zone bottom
        if stop <= ref:
            return ["STOP_NOT_ABOVE_ENTRY"]   # SHORT geometry
        if tgt >= ref:
            return ["TARGET_NOT_BELOW_ENTRY"]
        rr = (ref - tgt) / (stop - ref)
        if not c.get("paper_only", True):
            return ["SHORT_MUST_BE_PAPER_ONLY"]
    sf = c.get("size_frac")
    if not (isinstance(sf, (int, float)) and 0 < sf <= 1):
        return ["BAD_SIZE_FRAC"]
    c["reward_risk"] = round(rr, 3)
    if rr <= 0:
        return ["NON_POSITIVE_RR"]
    return []


def author(intent: dict, signal: str | None, is_short: bool,
           session: str) -> dict:
    """Build a contract from a saved intent — or a NO_TRADE contract with
    the precise reason. Never fabricates missing terms."""
    p = intent.get("params") or {}
    entry = None
    for k in ("zone", "entry_zone", "zone1", "pb_zone", "retest_zone",
              "reentry_zone", "probe_zone"):
        z = _zone(p.get(k))
        if z:
            entry = {"type": "limit_zone", "zone": z,
                     "activation": "low touches zone top"}
            break
    szn = _zone(p.get("short_zone"))
    if is_short and szn:
        entry = {"type": "limit_zone", "zone": szn,
                 "activation": "high bounces into zone"}
    if entry is None:
        for k in ("reclaim", "bo_level", "alt_level", "entry",
                  "entry_price"):
            lv = _f(p.get(k))
            if lv:
                entry = {"type": "close_above" if not is_short else
                         "limit_level", "level": lv,
                         "activation": "daily close above level"
                         if not is_short else "high touches level"}
                break
    c = {"direction": "SHORT" if is_short else "LONG",
         "entry": entry, "stop": intent.get("stop_level"),
         "target": intent.get("target"),
         "horizon": intent.get("horizon"),
         "invalidation": intent.get("invalidation"),
         "size_frac": intent.get("size_frac"),
         "provenance": {"session": session, "ticker": intent.get("ticker"),
                        "signal": signal,
                        "classification": intent.get("classification")},
         "costs_bps_per_side": 10,
         "paper_only": True}
    if is_short:
        c["borrow_bps_per_day"] = SHORT_BORROW_BPS_PER_DAY
        c["exit_mode"] = "buy_to_cover"
    errs = validate(c)
    if errs:
        nt = {"direction": "NO_TRADE",
              "reason": ";".join(errs),
              "provenance": c["provenance"], "attempted": c["direction"]}
        nt["_rejected_contract"] = c
        return nt
    return c
