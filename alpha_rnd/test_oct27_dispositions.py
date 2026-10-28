#!/usr/bin/env python3
"""Regression test: 2026-10-27 production intents through the corrected
disposition pipeline (read-only artifacts, no inference).

Expected corrected outcomes:
  AMPL, CAI, GRAL, IOVA -> REANALYZE_ON_TRIGGER (binary events pending;
    model-declared ambiguity is the substance of the class, not a defect)
  MRNA -> PUBLISHED_NON_EXECUTABLE (resolved SHORT contract, paper-only)
  BRZE, HTFL, NTSK, TEAM, XNCR -> AMBIGUOUS_REJECTED (genuine content
    contradictions: conflicting stops/zones/sizes)
  fabricated number still fails closed.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from alpha_rnd import synthesize as S  # noqa: E402
from alpha_rnd import econ_contract  # noqa: E402
from alpha_rnd import decision as _dec  # noqa: E402

EV = Path("/home/udi/udi_provate/TradingAgents/evaluations/alpha_rnd_v1")
SESSION = "2026-10-27"

EXPECT = {
    "AMPL": "REANALYZE_ON_TRIGGER", "CAI": "REANALYZE_ON_TRIGGER",
    "GRAL": "REANALYZE_ON_TRIGGER", "IOVA": "REANALYZE_ON_TRIGGER",
    "MRNA": "PUBLISHED_NON_EXECUTABLE",
    "BRZE": "AMBIGUOUS_REJECTED", "HTFL": "AMBIGUOUS_REJECTED",
    "NTSK": "AMBIGUOUS_REJECTED", "TEAM": "AMBIGUOUS_REJECTED",
    "XNCR": "AMBIGUOUS_REJECTED",
}


def main():
    # alpha_rnd import chain may place tradingagents/ on sys.path, which
    # shadows the root `backtest/` namespace dir with tradingagents/
    # backtest.py. Rebind the root dir before decision.from_intent runs.
    sys.path.insert(0, str(ROOT))
    sys.modules.pop("backtest", None)
    doc = json.loads(
        (EV / f"publication_intents_{SESSION}.json").read_text())
    intents = doc["intents"]
    assert set(intents) == set(EXPECT), set(intents) ^ set(EXPECT)
    held = set()
    for t, expect in EXPECT.items():
        a = json.loads(
            (EV / "case_artifacts" / f"{t}_{SESSION}.json").read_text())
        i = dict(intents[t])
        errs = S.validate(i, a)
        ec_errs, resolved = econ_contract.validate(
            i.get("economic_authority"), a, i,
            S._nums_in_text(S.artifact_text(a)))
        if resolved is not None:
            i["economic_authority_resolved"] = resolved
        errs = ec_errs + errs
        i["decision"] = _dec.from_intent(
            i, a.get("signal"), S._bearish_geometry(i), SESSION)
        d = S.disposition(i, errs, held)
        if resolved is not None and resolved.get("direction") == "SHORT":
            d = "PUBLISHED_NON_EXECUTABLE"
        elif d == "EXECUTABLE_WATCH" and resolved is not None and \
                not econ_contract.has_authority(i, resolved):
            d = "PUBLISHED_NON_EXECUTABLE"
        assert d == expect, f"{t}: got {d}, want {expect} (errs={errs})"
        print(f"PASS {t:5s} {d:28s} "
              f"dec={i['decision'].get('direction')}"
              f"/{i['decision'].get('reason')}")
    # fail-closed: fabricated entry level not present in artifact text
    a = json.loads(
        (EV / "case_artifacts" / "XNCR_2026-10-27.json").read_text())
    bad = dict(intents["XNCR"])
    bad["params"] = {"zone": [999.99, 1000.5]}
    bad["classification"] = "WATCH_FOR_ENTRY"
    errs = S.validate(bad, a)
    assert any("unsupported number" in e for e in errs), errs
    d = S.disposition(bad, errs, held)
    assert d == "AMBIGUOUS_REJECTED", d
    print("PASS fabricated-number fail-closed")


if __name__ == "__main__":
    main()
