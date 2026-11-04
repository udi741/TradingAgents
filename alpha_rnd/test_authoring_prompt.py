"""Regression: prompt contains binding rules; saved conflicting intents
still fail closed identically (behavior unchanged until fresh runs)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backtest"))
from alpha_rnd import synthesize as S  # noqa: E402

EV = Path("/home/udi/udi_provate/TradingAgents/evaluations/alpha_rnd_v1")


def main():
    import inspect
    src = inspect.getsource(S)
    for needle in ("NUMERIC BINDING SELF-CHECK", "omit the contract field",
                     "emit NO\n" , "FIELD COMPLETENESS"):
        assert needle.replace("emit NO\n", "emit NO\neconomic_authority") in src \
            or needle in src, needle
    # saved artifacts still validate fail-closed — prompt change must not
    # alter deterministic validator semantics
    d = json.loads(
        (EV / "publication_intents_2026-10-30.json").read_text())
    i = d["intents"]["REPL"]
    a = json.loads(
        (EV / "case_artifacts" / "REPL_2026-10-30.json").read_text())
    errs = S.validate(i, a)
    assert errs, "REPL must still fail closed on saved artifact"
    print("PASS prompt-rules present; REPL still rejected:",
          errs[:2])


if __name__ == "__main__":
    main()
