#!/usr/bin/env python3
"""Bounded real-model eval: ONE bridge call over selected saved
case_artifacts. Counts only genuinely AI-authored `decision` fields.
Cost: single batch translator call (~$0.5-2, ceiling $5)."""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, "/home/udi/udi_provate/TradingAgents-contract")
import historical_backtest as hb
from alpha_rnd import synthesize as sz, decision as dec

EV = Path("/home/udi/udi_provate/TradingAgents/evaluations/alpha_rnd_v1")
OUT = Path(__file__).parent / "results" / "eval_model"
OUT.mkdir(parents=True, exist_ok=True)
PICK = ["IOVA", "PCVX", "TWST", "ACN", "ABCL", "AMPL", "ANF", "CDNA"]


def main():
    arts = {}
    for t in PICK:
        files = sorted(EV.glob(f"case_artifacts/{t}_*.json"))
        if files:
            a = json.loads(files[-1].read_text())
            arts[t] = a
    print("artifacts:", {t: arts[t].get("decision_session") for t in arts})
    t0 = time.time()
    raw_out = None
    try:
        # exactly ONE bounded translator call
        emitted = sz.synthesize(arts)
        raw_out = emitted
    except Exception as e:
        print("TRANSLATOR FAILED:", e)
        (OUT / "failure.txt").write_text(repr(e))
        return
    dt = time.time() - t0
    (OUT / "raw_intents.json").write_text(json.dumps(raw_out, indent=1))
    print(f"call done in {dt:.0f}s, intents: {len(raw_out)}")
    results = []
    for i in raw_out:
        t = i.get("ticker")
        a = arts.get(t, {})
        sig = a.get("signal")
        authored = i.get("decision")  # genuinely AI-authored field
        d = dec.from_intent(i, sig, sz._bearish_geometry(i),
                            a.get("decision_session", "?"))
        rec = {"ticker": t, "signal": sig,
               "authored_decision": authored,
               "resolved": {k: d.get(k) for k in
                            ("direction", "reason", "entry", "stop",
                             "target", "horizon", "size_frac",
                             "permissible_size_frac", "reward_risk")}}
        # paper-sim valid contracts on real bars
        if d["direction"] != "NO_TRADE" and d["entry"]:
            df = hb.fetch_bars({t, "SPY"}, "2026-10-24").get(t)
            if df is not None:
                z = d["entry"].get("zone")
                lv = d["entry"].get("level")
                item = {"intent": i, "session": a.get("decision_session"),
                        "short": d["direction"] == "SHORT",
                        "spec": {"kind": "SHORT_ZONE" if d["direction"] == "SHORT" and z else
                                 "SHORT_LEVEL" if d["direction"] == "SHORT" else
                                 "LIMIT_ZONE" if z else
                                 "LIMIT_LEVEL" if lv else "CLOSE_ABOVE",
                                 "zone": z, "level": lv},
                        "stop": hb._num(d["stop"]),
                        "target": hb._num(d["target"]),
                        "stop_type": "close_below" if "close" in
                        str(i.get("invalidation") or "").lower()
                        else "intraday_stop",
                        "frac": d.get("size_frac") or
                        d.get("permissible_size_frac") or 1.0,
                        "expiry": hb.EXPIRY}
                rec["sim"] = hb.simulate(
                    item, df, hb.next_sessions(df, a["decision_session"]))
        results.append(rec)
    (OUT / "eval_results.json").write_text(json.dumps(results, indent=1))
    for r in results:
        ad = r["authored_decision"] or {}
        res = r["resolved"]
        sim = r.get("sim")
        sims = f" sim:{sim['status']} pnl={sim.get('pnl')}" if sim else ""
        print(f"{r['ticker']:6s} sig={r['signal']:<10s} ai={ad.get('direction')}"
              f" -> {res.get('direction')} {res.get('reason') or ''}"
              f" sz={res.get('permissible_size_frac')} rr={res.get('reward_risk')}{sims}")


if __name__ == "__main__":
    main()
