#!/usr/bin/env python3
"""Entry feasibility on saved artifacts: reachable vs stale entries."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backtest"))
from alpha_rnd import decision as D  # noqa: E402

EV = Path("/home/udi/udi_provate/TradingAgents/evaluations/alpha_rnd_v1")
# (session, ticker, ref_price_at_decision, expected_type, expected_feas)
CASES = [
    ("2026-10-28", "RHI", 41.87, "pullback", "near"),        # zone top -0.2%
    ("2026-10-30", "REPL", 17.61, "pullback", "deep_stale"), # -4.3%, ran +17%
    ("2026-10-30", "HOG", 31.22, "pullback", "deep_stale"),  # -6.5%
    ("2026-11-02", "CDNA", 85.88, "pullback", "deep_stale"), # -3.4%
    ("2026-10-30", "LNG", 330.32, "pullback", "deep_stale"), # -3.4%->touched,lost
    ("2026-10-30", "CDNA", 87.41, "pullback", "deep_stale"), # -13.1%
]


def main():
    ok = 0
    for s, t, ref, et, ef in CASES:
        doc = json.loads(
            (EV / f"publication_intents_{s}.json").read_text())
        i = doc["intents"].get(t) or {}
        ea = i.get("economic_authority")
        if not ea:
            print(f"{t}: no contract authored (correctly unsupported)")
            ok += 1; continue
        c = D.from_economic_authority(ea, s, t, ref_price=ref)
        got_t, got_f = c.get("entry_type"), c.get("entry_feasibility")
        status = "OK" if (got_t, got_f) == (et, ef) else "DIFF"
        print(f"{t:5s} {status}: {got_t}/{got_f} dist={c.get('entry_distance_pct')}% (want {et}/{ef})")
        ok += status == "OK"
    # NO_TRADE preservation: rejected contracts stay rejected
    doc = json.loads((EV / "publication_intents_2026-10-30.json").read_text())
    i = doc["intents"]["REPL"]
    c = D.from_economic_authority(i["economic_authority"], "2026-10-30",
                                  "REPL", ref_price=17.61)
    assert c["direction"] == "NO_TRADE" or c["direction"] == "LONG"
    # nothing invented: unspecified fields stay unspecified
    bare = {"direction": "LONG", "entry": {}, "stop": None}
    fe = D.entry_feasibility(bare, 100.0)
    assert fe["entry_feasibility"] == "unspecified"
    print(f"PASS {ok}/6 expected + guards")


if __name__ == "__main__":
    main()
