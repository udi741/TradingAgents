#!/usr/bin/env python3
"""Phase 2 — run every saved intent through decision contracts + sim.

For each researched intent: author contract (LONG/SHORT/NO_TRADE with
reason), simulate valid ones through corrected causal engine, report
fills/exits/P&L per direction, plus exact blocker counts.
"""
import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, "/home/udi/udi_provate/TradingAgents-contract")
import historical_backtest as hb
import decision_contract as dc

EV = Path("/home/udi/udi_provate/TradingAgents/evaluations/alpha_rnd_v1")
OUT = Path(__file__).parent / "results"


def main():
    rows, pools = [], {}
    for f in sorted(EV.glob("publication_intents_*.json")):
        d = json.loads(f.read_text())
        sess = d.get("session") or f.stem.rsplit("_", 1)[-1]
        for t, i in (d.get("intents") or {}).items():
            rows.append({"session": sess, "intent": i})
    for f in sorted(EV.glob("replays/*/ANALYZE_ALL_CANDIDATES/"
                            "publication.json")):
        d = json.loads(f.read_text())
        sess = f.parts[-3]
        for i in d["intents"]:
            rows.append({"session": sess, "intent": i})
    signals = hb.load_signals(EV)
    blockers = collections.Counter()
    contracts = []
    for r in rows:
        i, sess = r["intent"], r["session"]
        sig = signals.get((sess, i["ticker"]))
        is_short = hb.is_short_plan(i, sig)
        c = dc.author(i, sig, is_short, sess)
        contracts.append((r, c))
        if c["direction"] == "NO_TRADE":
            for k in c["reason"].split(";"):
                blockers[k] += 1
    n_tr = [c for _, c in contracts if c["direction"] != "NO_TRADE"]
    shorts = [c for c in n_tr if c["direction"] == "SHORT"]
    longs = [c for c in n_tr if c["direction"] == "LONG"]
    print(f"researched={len(contracts)} valid={len(n_tr)} "
          f"LONG={len(longs)} SHORT={len(shorts)} "
          f"NO_TRADE={len(contracts) - len(n_tr)}")
    print("blockers:", dict(blockers))
    # simulate all valid contracts (paper)
    tickers = {c["provenance"]["ticker"] for c in n_tr}
    bars = hb.fetch_bars(tickers | {"SPY"}, "2026-10-24")
    trades = {"LONG": [], "SHORT": []}
    untrig = {"LONG": 0, "SHORT": 0}
    for r, c in contracts:
        if c["direction"] == "NO_TRADE":
            continue
        t = c["provenance"]["ticker"]
        untriggered = {}
        df = bars.get(t)
        if df is None:
            continue
        # adapt contract to hb.simulate item shape
        z = lv = None
        if c["entry"].get("zone"):
            z = c["entry"]["zone"]
        if c["entry"].get("level"):
            lv = c["entry"]["level"]
        kind = ("SHORT_ZONE" if c["direction"] == "SHORT" and z else
                "SHORT_LEVEL" if c["direction"] == "SHORT" else
                "LIMIT_ZONE" if z else
                "CLOSE_ABOVE" if "close above" in
                c["entry"].get("activation", "") else "LIMIT_LEVEL")
        item = {"intent": r["intent"], "session": r["session"],
                "short": c["direction"] == "SHORT",
                "spec": {"kind": kind, "zone": z, "level": lv},
                "stop": hb._num(c["stop"]), "target": hb._num(c["target"]),
                "stop_type": "close_below" if "close" in
                str(r["intent"].get("invalidation") or "").lower()
                else "intraday_stop",
                "frac": c["size_frac"] or 1.0, "expiry": hb.EXPIRY}
        sim = hb.simulate(item, df, hb.next_sessions(df, r["session"]))
        if sim and sim.get("status") == "UNTRIGGERED":
            untrig[c["direction"]] += 1
        elif sim and sim.get("pnl") is not None:
            sim["ticker"] = t
            trades[c["direction"]].append(sim)
    for d in ("LONG", "SHORT"):
        ts = trades[d]
        un = untrig[d]
        st = hb.stats(ts)
        print(f"\n{d}: filled={len(ts)} untriggered≈{un} stats={st}")
        for t in ts:
            print(f"  {t['ticker']:6s} {t['entry_date']}@{t['entry_px']} -> "
                  f"{t['exit_date']}@{t['exit_px']} {t['exit_reason']} "
                  f"pnl={t['pnl']}")
    (OUT / "pipeline.json").write_text(json.dumps(
        {"counts": {"researched": len(contracts),
                    "valid_long": len(longs), "valid_short": len(shorts),
                    "no_trade": len(contracts) - len(n_tr)},
         "blockers": dict(blockers),
         "long_stats": hb.stats(trades["LONG"]),
         "short_stats": hb.stats(trades["SHORT"]),
         "long_trades": trades["LONG"],
         "short_trades": trades["SHORT"],
         "no_trade_reasons": [{"t": c["provenance"]["ticker"],
                               "sess": c["provenance"]["session"],
                               "reason": c["reason"]}
                              for _, c in contracts
                              if c["direction"] == "NO_TRADE"]},
        indent=1))


if __name__ == "__main__":
    main()
