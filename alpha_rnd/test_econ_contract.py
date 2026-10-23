#!/usr/bin/env python3
"""Canonical economic-authority contract tests — no live calls.

Regression shapes from the 2026-10-14..21 effectiveness audit: prose-level
sizing/tranche/zone conflicts must not kill a resolved structured contract;
contradictions inside the contract itself still fail closed.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from alpha_rnd import econ_contract as ec, synthesize as syn  # noqa: E402


def artifact(ticker="VSTM", signal="Overweight", session="2026-10-15",
             text=None):
    return {"ticker": ticker, "signal": signal, "decision_session": session,
            "final_trade_decision": text or "",
            "trader_investment_plan": "", "risk_judge_decision": "",
            "investment_plan": ""}


def intent(ticker="VSTM", signal_ok=True, contract=None, ambiguity=None,
           ambiguities=None, cls="ACTIONABLE_NOW", mode="AUTO_ENTRY"):
    i = {"ticker": ticker, "classification": cls, "watch_mode": mode,
         "trigger": "limit buy zone 8.60-8.80", "params": {"zone": [8.6, 8.8]},
         "stop_level": 7.45, "target": 9.73, "horizon": "4-8 weeks",
         "auto_execution_authorized": True, "size_frac": 0.5,
         "ambiguity": ambiguity}
    if ambiguities:
        i["ambiguities"] = [{"type": t, "detail": t} for t in ambiguities]
    if contract is not None:
        i["economic_authority"] = contract
    return i


def contract(ticker="VSTM", session="2026-10-15", **kw):
    c = {"schema_version": 1, "ticker": ticker, "session": session,
         "direction": "LONG",
         "entry": {"mode": "LIMIT_ZONE", "zone": [8.6, 8.8]},
         "sizing": {"initial_frac": 0.05, "max_frac": 0.05, "tranches": []},
         "stop": {"type": "close_below", "level": 7.45},
         "objective": {"target": 9.73},
         "success_criteria": "breakout holds above 9.73 on volume",
         "profit_realization_plan": "sell into 9.0-9.73 strength",
         "horizon": "4-8 weeks", "event_constraints": [],
         "no_entry_conditions": [], "resolves": []}
    c.update(kw)
    return c


# artifact text containing every number the contract uses
VSTM_TEXT = ("Zone 8.60-8.80 for the band retest, stop below 7.45, "
             "target 9.73, ~5% of portfolio max, half position. "
             "Alternative exploratory sizing: $50-55k vs $70-75k.")


def run_validate(i, a):
    errs = syn.validate(i, a)
    ec_errs, resolved = ec.validate(
        i.get("economic_authority"), a, i,
        syn._nums_in_text(syn.artifact_text(a)))
    if resolved is not None:
        resolved_types = {str(r).upper() for r in resolved.get("resolves") or []} \
            & ec.RESOLVABLE_AMBIGUITY_TYPES
        errs = [e for e in errs
                if not (e.startswith("ambiguous_type:") and
                        e.split(":", 1)[1].upper() in resolved_types)]
    return ec_errs + errs, resolved


class ContractValidation(unittest.TestCase):
    def test_valid_long_contract(self):
        a = artifact(text=VSTM_TEXT)
        c = contract()
        errs, res = ec.validate(c, a, intent(contract=c),
                                syn._nums_in_text(syn.artifact_text(a)))
        self.assertEqual(errs, [])
        self.assertEqual(res["direction"], "LONG")

    def test_prose_ambiguity_superseded_by_contract(self):
        # regression 1 (VSTM shape): SIZING_CONFLICT typed ambiguity,
        # contract explicitly resolves it => suppressed, nothing else fails
        a = artifact(text=VSTM_TEXT)
        i = intent(contract=contract(resolves=["SIZING_CONFLICT"]),
                   ambiguities=["SIZING_CONFLICT"])
        errs, res = run_validate(i, a)
        self.assertEqual(errs, [])
        self.assertIsNotNone(res)

    def test_tranche_and_zone_conflict_resolved(self):
        # regressions 2-5: TRANCHE_CONFLICT + ENTRY_ZONE_CONFLICT resolved
        a = artifact(text=VSTM_TEXT)
        i = intent(contract=contract(
            resolves=["TRANCHE_CONFLICT", "ENTRY_ZONE_CONFLICT"]),
            ambiguities=["TRANCHE_CONFLICT", "ENTRY_ZONE_CONFLICT"])
        errs, res = run_validate(i, a)
        self.assertEqual(errs, [])
        self.assertIsNotNone(res)

    def test_nonresolvable_ambiguities_fail_closed(self):
        # catalyst/direction/thesis/risk/event/evidence/unknown all fail
        for amb in ("CATALYST_UNRESOLVED", "DIRECTION_CONFLICT",
                    "THESIS_CONTRADICTION", "RISK_CONTRADICTION",
                    "EVENT_OUTCOME_UNKNOWN", "EVIDENCE_CONFLICT", "UNKNOWN"):
            a = artifact(text=VSTM_TEXT)
            i = intent(contract=contract(resolves=["SIZING_CONFLICT"]),
                       ambiguities=["SIZING_CONFLICT", amb])
            errs, res = run_validate(i, a)
            self.assertIsNotNone(res)
            self.assertIn(f"ambiguous_type:{amb}", errs)
            self.assertEqual(syn.disposition(i, errs, set()),
                             "AMBIGUOUS_REJECTED")

    def test_untyped_prose_ambiguity_never_suppressed(self):
        # legacy free-form ambiguity string is not a code — stays fatal
        a = artifact(text=VSTM_TEXT)
        i = intent(contract=contract(resolves=["SIZING_CONFLICT"]),
                   ambiguities=["SIZING_CONFLICT"],
                   ambiguity="sizing conflict $50-55k vs $70-75k")
        errs, res = run_validate(i, a)
        self.assertTrue(any(e.startswith("ambiguous:") for e in errs))
        self.assertEqual(syn.disposition(i, errs, set()),
                         "AMBIGUOUS_REJECTED")

    def test_mixed_sizing_plus_catalyst(self):
        # sizing resolved, catalyst remains -> not executable
        a = artifact(text=VSTM_TEXT)
        i = intent(contract=contract(resolves=["SIZING_CONFLICT"]),
                   ambiguities=["SIZING_CONFLICT", "CATALYST_UNRESOLVED"])
        errs, res = run_validate(i, a)
        self.assertNotIn("ambiguous_type:SIZING_CONFLICT", errs)
        self.assertIn("ambiguous_type:CATALYST_UNRESOLVED", errs)
        self.assertNotEqual(syn.disposition(i, errs, set()),
                            "EXECUTABLE_WATCH")

    def test_unsupported_resolves_claim_fails(self):
        a = artifact(text=VSTM_TEXT)
        c = contract(resolves=["CATALYST_UNRESOLVED"])
        i = intent(contract=c, ambiguities=["CATALYST_UNRESOLVED"])
        errs, res = run_validate(i, a)
        self.assertIsNone(res)
        self.assertTrue(any("ECON_RESOLVES_UNSUPPORTED" in e for e in errs))
        self.assertIn("ambiguous_type:CATALYST_UNRESOLVED", errs)

    def test_phantom_resolves_claim_fails(self):
        # contract claims SIZING_CONFLICT that the intent does not carry
        a = artifact(text=VSTM_TEXT)
        i = intent(contract=contract(resolves=["SIZING_CONFLICT"]),
                   ambiguities=["ENTRY_ZONE_CONFLICT"])
        errs, res = run_validate(i, a)
        self.assertIsNone(res)
        self.assertTrue(any("ECON_RESOLVES_PHANTOM" in e for e in errs))
        self.assertIn("ambiguous_type:ENTRY_ZONE_CONFLICT", errs)

    def test_no_ambiguity_valid_contract_clean_path(self):
        a = artifact(text=VSTM_TEXT)
        i = intent(contract=contract())
        errs, res = run_validate(i, a)
        self.assertEqual(errs, [])
        self.assertEqual(syn.disposition(i, errs, set()),
                         "EXECUTABLE_WATCH")

    def test_anf_tranche_shape_resolved(self):
        # regression 3: 20/40/40 vs 40/35/25 — contract resolves one ladder
        text = ("Tranche ladder 20/40/40 vs alternative 40/35/25; "
                "cap 10% vs 15%. Final: enter 146.0-147.0, adds 140.0, "
                "133.0, stop 129.0, target 165.0, "
                "2.5% 4% 3.5% 10% 25% 40% 35% 15% 20% 40%")
        a = artifact("ANF", "Overweight", "2026-10-16", text)
        c = contract("ANF", "2026-10-16",
                     entry={"mode": "LIMIT_ZONE", "zone": [146.0, 147.0]},
                     sizing={"initial_frac": 0.025, "max_frac": 0.10,
                             "tranches": [{"frac": 0.04, "level": 140.0},
                                          {"frac": 0.035, "level": 133.0}]},
                     stop={"type": "close_below", "level": 129.0},
                     objective={"target": 165.0},
                     resolves=["TRANCHE_CONFLICT", "POSITION_CAP_CONFLICT"])
        i = intent("ANF", contract=c,
                   ambiguities=["TRANCHE_CONFLICT", "POSITION_CAP_CONFLICT"])
        errs, res = run_validate(i, a)
        self.assertIsNotNone(res)

    def test_contract_internal_contradiction_fails(self):
        # B: contradiction INSIDE the contract (tranches exceed max) fails
        a = artifact(text=VSTM_TEXT)
        c = contract(sizing={"initial_frac": 0.05, "max_frac": 0.06,
                             "tranches": [{"frac": 0.05}]})
        errs, res = ec.validate(c, a, intent(contract=c),
                                syn._nums_in_text(syn.artifact_text(a)))
        self.assertTrue(any("TRANCHES_EXCEED_MAX" in e for e in errs))
        self.assertIsNone(res)

    def test_zone_conflict_inside_contract_fails(self):
        # regression 5 shape (APPN 42-43 vs 42-44): if the CONTRACT itself
        # is contradictory, fail — here stop above entry
        a = artifact(text="zone 42.0-43.0 stop 44.0 target 50.0")
        c = contract(entry={"mode": "LIMIT_ZONE", "zone": [42.0, 43.0]},
                     stop={"type": "close_below", "level": 44.0},
                     objective={"target": 50.0})
        errs, res = ec.validate(c, a, intent(contract=c),
                                syn._nums_in_text(syn.artifact_text(a)))
        self.assertTrue(any("STOP_ABOVE_ENTRY" in e for e in errs))
        self.assertIsNone(res)

    def test_missing_risk_plan_fails(self):
        # C
        a = artifact(text=VSTM_TEXT)
        c = contract(stop={"type": "close_below", "level": None})
        errs, _ = ec.validate(c, a, intent(contract=c),
                              syn._nums_in_text(syn.artifact_text(a)))
        self.assertIn("ECON_NO_STOP", errs)

    def test_missing_success_plan_fails(self):
        # D: no criteria/objective -> Phase-G fail
        a = artifact(text=VSTM_TEXT)
        c = contract(success_criteria=None, profit_realization_plan=None,
                     objective={})
        errs, _ = ec.validate(c, a, intent(contract=c),
                              syn._nums_in_text(syn.artifact_text(a)))
        self.assertTrue(any(e.startswith("ECON_SUCCESS_PLAN") for e in errs))

    def test_long_contract_on_sell_fails(self):
        # E
        a = artifact(signal="Sell", text=VSTM_TEXT)
        c = contract()
        errs, _ = ec.validate(c, a, intent(contract=c),
                              syn._nums_in_text(syn.artifact_text(a)))
        self.assertTrue(any("LONG_CONTRADICTS_SIGNAL" in e for e in errs))

    def test_reanalyze_never_authority(self):
        # F: REANALYZE mode can never be machine-executable, contract or not
        i = intent(contract=contract(), cls="REANALYZE_ON_TRIGGER",
                   mode="REANALYZE_ON_TRIGGER")
        self.assertFalse(syn._machine_executable(i))

    def test_nonlong_contract_no_executable(self):
        for d in ("SHORT", "NONE"):
            i = intent(contract=contract(direction=d))
            self.assertFalse(syn._machine_executable(i))

    def test_unsupported_number_fails(self):
        # invented economics: 99.0 appears nowhere in source text
        a = artifact(text=VSTM_TEXT)
        c = contract(objective={"target": 99.0})
        errs, _ = ec.validate(c, a, intent(contract=c),
                              syn._nums_in_text(syn.artifact_text(a)))
        self.assertTrue(any("UNSUPPORTED_NUMBER:99.0" in e for e in errs))

    def test_stale_provenance_fails(self):
        a = artifact(text=VSTM_TEXT)
        c = contract(session="2026-10-01")
        errs, _ = ec.validate(c, a, intent(contract=c),
                              syn._nums_in_text(syn.artifact_text(a)))
        self.assertTrue(any("PROVENANCE_STALE" in e for e in errs))

    def test_no_contract_unchanged(self):
        # I/J: absent contract => legacy behavior untouched, ambiguity kills
        a = artifact(text=VSTM_TEXT)
        i = intent(contract=None, ambiguity="sizing conflict")
        errs, res = run_validate(i, a)
        self.assertIsNone(res)
        self.assertTrue(any(e.startswith("ambiguous") for e in errs))
        self.assertEqual(syn.disposition(i, errs, set()),
                         "AMBIGUOUS_REJECTED")

    def test_valid_contract_path_to_disposition(self):
        # resolved contract + evaluable params + risk plan + auth =>
        # EXECUTABLE_WATCH survives (entry_gate still gates actual orders)
        a = artifact(text=VSTM_TEXT)
        i = intent(contract=contract(resolves=["SIZING_CONFLICT"]),
                   ambiguities=["SIZING_CONFLICT"])
        errs, res = run_validate(i, a)
        self.assertEqual(errs, [])
        self.assertEqual(syn.disposition(i, errs, set()),
                         "EXECUTABLE_WATCH")


if __name__ == "__main__":
    unittest.main()
