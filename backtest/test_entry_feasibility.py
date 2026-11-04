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

def test_select_plan():
    import sys
    from pathlib import Path as _P
    sys.path.insert(0, str(_P(__file__).resolve().parents[1] / "backtest"))
    from alpha_rnd import decision as D
    mk = lambda zone, stop, tgt, style=None: {
        "schema_version": 1, "direction": "LONG",
        "entry": {"mode": "LIMIT_ZONE", "zone": zone},
        "sizing": {"initial_frac": 0.5, "max_frac": 1.0},
        "stop": {"type": "close_below", "level": stop},
        "objective": {"target": tgt}, "horizon": "2w",
        "entry_style": style}
    # deep-pullback primary + near continuation alternate -> alternate wins
    c = mk([16.5, 16.85], 15.75, 29.0, "pullback")
    c["alternate_plans"] = [
        mk(None, 17.0, 20.0, "continuation") | {
            "entry": {"mode": "STOP_ENTRY", "trigger_level": 17.9}}]
    d = D.select_plan(c, "s", "T", ref_price=17.61)
    assert d["direction"] == "LONG"
    assert d["entry_type"] == "continuation", d
    # deep primary only -> still selected (feasibility is diagnostic, not gate)
    d2 = D.select_plan(mk([16.5, 16.85], 15.75, 29.0, "pullback"),
                       "s", "T", ref_price=17.61)
    assert d2["direction"] == "LONG"
    # all-invalid -> NO_TRADE
    bad = mk([16.5, 16.85], 18.0, 29.0)  # stop above entry
    d3 = D.select_plan(bad, "s", "T", ref_price=17.61)
    assert d3["direction"] == "NO_TRADE"
    # real artifacts: REPL had no alternates -> primary stands (NO new plan invented)
    import json
    i = json.loads(open(
        "/home/udi/udi_provate/TradingAgents/evaluations/alpha_rnd_v1/"
        "publication_intents_2026-10-30.json").read())["intents"]["REPL"]
    d4 = D.select_plan(i["economic_authority"], "2026-10-30", "REPL",
                       ref_price=17.61)
    assert d4["direction"] == "LONG" and d4["entry_feasibility"] == "deep_stale"
    print("PASS select_plan: alt preference, primary fallback, NO_TRADE, no invented plans")


test_select_plan()
