#!/usr/bin/env python3
"""Deterministic tests for the contract-authoring structural fixes.

Covers: caller-owned provenance, tranche accounting invariant, resolves
claims, direction consistency, word-fraction evidence binding, and the
absence of economic-field repair.
"""
from alpha_rnd import econ_contract as ec
from alpha_rnd import synthesize as syn

ART = {"ticker": "XYZ", "decision_session": "2026-10-16", "signal": "Overweight",
       "final_trade_decision": "", "trader_investment_plan": "",
       "risk_judge_decision": "", "investment_plan": ""}

BASE_CONTRACT = {
    "schema_version": 1, "direction": "LONG",
    "entry": {"mode": "LIMIT_ZONE", "zone": [100.0, 105.0]},
    "sizing": {"initial_frac": 0.4, "max_frac": 1.0,
               "tranches": [{"frac": 0.35}, {"frac": 0.25}]},
    "stop": {"type": "close_below", "level": 95.0},
    "objective": {"target": 130.0},
    "success_criteria": "x", "profit_realization_plan": "x",
    "horizon": "3-6 months", "event_constraints": [],
    "no_entry_conditions": [], "resolves": []}

SRC = {100.0, 105.0, 95.0, 130.0, 0.4, 0.35, 0.25, 1.0}


def _validate(contract, artifact=None, intent=None, src=None):
    return ec.validate(contract, artifact or ART, intent or {},
                       src if src is not None else SRC)


def test_provenance_caller_owned():
    """Model-written stale session/wrong ticker is bound to the artifact
    identity — deterministic metadata, not economics."""
    c = dict(BASE_CONTRACT, session="2026-10-24", ticker="WRONG")
    errs, resolved = _validate(c)
    assert resolved is not None, errs
    assert not any("PROVENANCE" in e or "TICKER" in e for e in errs)


def test_tranche_arithmetic_valid():
    errs, resolved = _validate(BASE_CONTRACT)
    assert resolved is not None and errs == [], errs


def test_tranche_double_count_rejected():
    """Restating the opening allocation inside tranches still fails."""
    c = dict(BASE_CONTRACT)
    c["sizing"] = {"initial_frac": 0.4, "max_frac": 1.0,
                   "tranches": [{"frac": 0.4}, {"frac": 0.35}, {"frac": 0.25}]}
    errs, resolved = _validate(c)
    assert resolved is None
    assert any(e.startswith("ECON_TRANCHES_EXCEED_MAX") for e in errs)


def test_no_phantom_resolves():
    c = dict(BASE_CONTRACT, resolves=["SIZING_CONFLICT"])
    errs, _ = _validate(c, intent={"ambiguities": []})
    assert any(e.startswith("ECON_RESOLVES_PHANTOM") for e in errs)


def test_allowed_resolves_accepted():
    c = dict(BASE_CONTRACT, resolves=["SIZING_CONFLICT"])
    intent = {"ambiguities": [{"type": "SIZING_CONFLICT", "detail": "x"}]}
    errs, resolved = _validate(c, intent=intent)
    assert resolved is not None and not any("RESOLVES" in e for e in errs), errs


def test_nonresolvable_resolve_rejected():
    c = dict(BASE_CONTRACT, resolves=["EVENT_OUTCOME_UNKNOWN"])
    intent = {"ambiguities": [{"type": "EVENT_OUTCOME_UNKNOWN"}]}
    errs, _ = _validate(c, intent=intent)
    assert any(e.startswith("ECON_RESOLVES_UNSUPPORTED") for e in errs)


def test_sell_long_rejected():
    art = dict(ART, signal="Sell")
    errs, resolved = _validate(BASE_CONTRACT, artifact=art)
    assert resolved is None
    assert any(e.startswith("ECON_LONG_CONTRADICTS_SIGNAL") for e in errs)


def test_short_for_buy_rejected_semantically():
    """SHORT on a constructive artifact is descriptive-only, never
    executable authority."""
    c = dict(BASE_CONTRACT, direction="SHORT")
    errs, resolved = _validate(c)
    assert resolved == {"direction": "SHORT"}
    assert not ec.has_authority({}, resolved)


def test_event_ambiguity_remains_blocking():
    i = {"ticker": "XYZ", "classification": "WATCH_FOR_ENTRY",
         "watch_mode": "AUTO_ENTRY", "auto_execution_authorized": True,
         "params": {"zone": [100.0, 105.0]}, "stop_level": 95.0,
         "ambiguities": [{"type": "EVENT_OUTCOME_UNKNOWN"}]}
    errs = syn.validate(i, ART)
    assert any("EVENT_OUTCOME_UNKNOWN" in e for e in errs)
    c = dict(BASE_CONTRACT, resolves=["EVENT_OUTCOME_UNKNOWN"])
    ec_errs, _ = _validate(c, intent=i)
    assert any("RESOLVES_UNSUPPORTED" in e for e in ec_errs)


def test_word_fraction_binding():
    nums = syn._nums_in_text("deploy half now, a quarter later")
    assert 0.5 in nums and 0.25 in nums
    nums2 = syn._nums_in_text("three-quarters of the position")
    assert 0.75 in nums2 and 0.25 not in nums2
    nums3 = syn._nums_in_text("quarterly report noted")
    assert 0.25 not in nums3


def test_no_economic_field_repair():
    """Provenance binding must not touch economics: a contract with a bad
    stop still fails; direction is never rewritten."""
    c = dict(BASE_CONTRACT, session="bogus", ticker="bogus",
             stop={"type": "close_below", "level": 200.0})
    errs, resolved = _validate(c)
    assert resolved is None
    assert any("STOP" in e for e in errs)
    c2 = dict(BASE_CONTRACT, direction="LONG")
    errs2, r2 = _validate(c2, artifact=dict(ART, signal="Sell"))
    assert r2 is None and any("CONTRADICTS_SIGNAL" in e for e in errs2)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for f in fns:
        f()
        print("PASS", f.__name__)
    print(f"{len(fns)} tests passed")
