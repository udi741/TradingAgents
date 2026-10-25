#!/usr/bin/env python3
"""Research→execution funnel over ALL saved research (prod + R5B replays).

Stages: discovered -> researched -> direction -> valid contract ->
authorized/executable -> filled -> P&L.

Directions: LONG via existing classify()/simulate(). SHORT candidates are
EXPERIMENTAL paper-only contracts: authored only when the intent carries an
explicit bearish plan (is_short_plan + short_zone/level + numeric stop).
Plain Sell/Underweight opinions are NOT short contracts.

Direction-safety gates applied via current production synthesize (the
merged fix), so the funnel reflects post-fix truth.
"""
import collections
import json
import sys
from pathlib import Path

import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, "/home/udi/udi_provate/TradingAgents")
import historical_backtest as hb
from alpha_rnd import synthesize as sz  # post-fix gates (production main)

EV = Path("/home/udi/udi_provate/TradingAgents/evaluations/alpha_rnd_v1")
OUT = Path(__file__).parent / "results"


def load_research():
    """All recorded intents: prod sessions + R5B replays (dedup)."""
    rows, pool_by_sess = [], collections.defaultdict(set)
    for f in sorted(EV.glob("publication_intents_*.json")):
        d = json.loads(f.read_text())
        sess = d.get("session") or f.stem.rsplit("_", 1)[-1]
        for t, i in (d.get("intents") or {}).items():
            rows.append({"session": sess, "intent": i, "source": "prod",
                         "disposition": (d.get("dispositions") or {})
                         .get(t, {}).get("disposition") if isinstance(
                             (d.get("dispositions") or {}).get(t),
                             dict) else (d.get("dispositions") or {}).get(t)})
    for f in sorted(EV.glob("replays/*/ANALYZE_ALL_CANDIDATES/"
                            "publication.json")):
        d = json.loads(f.read_text())
        sess = f.parts[-3]
        for i in d["intents"]:
            rows.append({"session": sess, "intent": i, "source": "R5B",
                         "disposition": (d.get("dispositions") or {})
                         .get(i["ticker"], {}).get("disposition")})
    for f in sorted(EV.glob("candidate_pool_frozen_*.json")):
        d = json.loads(f.read_text())
        for c in d.get("candidates", []):
            pool_by_sess[d["session"]].add(c["ticker"])
    return rows, pool_by_sess


def contract_check(r):
    """Smallest valid-contract predicate: direction + entry + finite
    positive stop + deterministic exit wording present."""
    i = r["intent"]
    reasons = []
    if sz._bearish_geometry(i):
        # SHORT-shaped -> not a LONG contract; check SHORT supportability
        stop = sz._stop_level(i)
        szn = hb._pair((i.get("params") or {}).get("short_zone"))
        lv = hb.entry_spec(i)[1]
        if not (szn or lv):
            reasons.append("SHORT_NO_ENTRY_SPEC")
        if stop is None:
            reasons.append("SHORT_NO_VALID_STOP")
        tg = hb._num(i.get("target"))
        if stop is not None and tg is not None and tg >= stop:
            reasons.append("SHORT_TARGET_NOT_BELOW_ENTRY_SIDE")
        r["short_contract"] = not reasons
        r["direction"] = "SHORT" if not reasons else "BEARISH_NO_CONTRACT"
        r["reject"] = ";".join(reasons) or None
        return
    lvl = sz._entry_levels(i.get("params") or {})
    if not lvl:
        reasons.append("NO_ENTRY_SPEC")
    st = sz._stop_level(i)
    if st is None:
        reasons.append("NO_VALID_STOP")
    elif lvl and st >= min(lvl):
        reasons.append("STOP_ABOVE_ENTRY")
    tg = hb._num(i.get("target"))
    rr = None
    if st and lvl and tg:
        ref = min(lvl)
        rr = (tg - ref) / (ref - st) if ref > st else None
        if rr is not None and rr <= 0:
            reasons.append("NON_POSITIVE_RR")
    r["rr"] = rr
    r["short_contract"] = False
    r["direction"] = "LONG" if not reasons else "NO_LONG_CONTRACT"
    r["reject"] = ";".join(reasons) or None


def main():
    rows, pools = load_research()
    signals = hb.load_signals(EV)
    items = hb.classify(rows, signals)
    for r in items:
        contract_check(r)
    funnel = collections.Counter()
    for r in items:
        funnel["researched"] += 1
        funnel[f"dir_{r['direction']}"] += 1
        funnel[f"status_{r['status']}"] += 1
        if r["reject"]:
            funnel[f"reject_{r['reject']}"] += 1
    # executable sets
    long_exec = [r for r in items if r["direction"] == "LONG"
                 and r["status"] in ("AUTHORIZED", "AUTH_INTENT_GATE_BLOCKED")]
    short_exec = [r for r in items if r.get("short_contract")]
    print("FUNNEL:")
    for k, v in sorted(funnel.items()):
        print(f"  {k:40s} {v}")
    print(f"LONG executable candidates: {len(long_exec)}")
    print(f"SHORT supportable contracts: {len(short_exec)}")
    # simulate
    tickers = {r["intent"]["ticker"] for r in long_exec + short_exec}
    bars = hb.fetch_bars(tickers | {"SPY"}, "2026-10-24")
    for tr in (long_exec + short_exec):
        df = bars.get(tr["intent"]["ticker"])
        tr["sim"] = None
        if df is not None and tr["spec"]:
            tr["sim"] = hb.simulate(tr, df,
                                    hb.next_sessions(df, tr["session"]))
    res = {"funnel": dict(funnel),
           "long": [r for r in long_exec],
           "short": [r for r in short_exec]}
    def trd(rs):
        return [r["sim"] for r in rs if r.get("sim") and r["sim"].get("pnl")
                is not None]
    for name, rs in (("LONG", long_exec), ("SHORT_exp", short_exec)):
        trs = trd(rs)
        untrig = sum(1 for r in rs if r.get("sim") and
                     r["sim"].get("status") == "UNTRIGGERED")
        print(f"{name}: sim trades={len(trs)} untriggered={untrig} "
              f"stats={hb.stats(trs)}")
        for t in trs:
            print(f"   {t['ticker']:6s} {t['entry_date']}@{t['entry_px']} -> "
                  f"{t['exit_date']}@{t['exit_px']} {t['exit_reason']:24s} "
                  f"pnl={t['pnl']}")
    (OUT / "funnel.json").write_text(json.dumps(
        {"funnel": dict(funnel),
         "long_stats": hb.stats(trd(long_exec)),
         "short_stats": hb.stats(trd(short_exec)),
         "long_trades": trd(long_exec),
         "short_trades": trd(short_exec),
         "short_candidates": [{ "t": r["intent"]["ticker"],
                                "sess": r["session"],
                                "spec": r["spec"], "stop": r["stop"]}
                              for r in short_exec]}, indent=1))


if __name__ == "__main__":
    main()
