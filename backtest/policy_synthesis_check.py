#!/usr/bin/env python3
"""Bounded model validation (Phase 5) — fresh synthesis on held-out artifacts.

One devin-deep bridge call per session batch (mirrors production batching),
then the REVISED deterministic pipeline (evaluate_intent) on the fresh
intents, compared to the frozen originals for the same tickers.

HELD-OUT: sessions never used to design the policy construction or its
constants (design inputs were the 12-case A/B set from 10-28..11-02 pilots
and the RHI case). Hard cap: MAX_CALLS bridge invocations total.

  python3 backtest/policy_synthesis_check.py 2026-10-19 2026-10-20
"""
import copy
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
import yfinance as yf

from alpha_rnd import synthesize as sz
from alpha_rnd import econ_contract as ec

EV = Path("/home/udi/udi_provate/TradingAgents/evaluations/alpha_rnd_v1")
OUT = Path(__file__).parent / "results"
MAX_CALLS = 24
CALLS = {"n": 0}


def bars_for(ticker, session):
    try:
        df = yf.download(ticker, start="2026-08-15", progress=False,
                         auto_adjust=True)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.dropna()
        return df[df.index <= session]
    except Exception:
        return pd.DataFrame()


def run_session(sess):
    arts = {}
    for p in sorted((EV / "case_artifacts").glob(f"*_{sess}.json")):
        a = json.loads(p.read_text())
        arts[a["ticker"]] = a
    if not arts:
        return None
    frozen = json.loads((EV / f"publication_intents_{sess}.json").read_text())
    t0 = time.time()
    CALLS["n"] += 1
    if CALLS["n"] > MAX_CALLS:
        raise SystemExit(f"invocation cap {MAX_CALLS} exceeded")
    fresh = sz.synthesize(arts)
    dt = time.time() - t0
    out = {"session": sess, "invocations": 1, "call_seconds": round(dt, 1),
           "tickers": sorted(arts), "results": []}
    for i in fresh:
        t = i.get("ticker")
        a = arts.get(t)
        if a is None:
            continue
        before = bars_for(t, sess)
        out_i = sz.evaluate_intent(copy.deepcopy(i), a, sess, set(),
                                   bars=before if not before.empty else None)
        old = (frozen.get("dispositions") or {}).get(t) or {}
        res = i.get("economic_authority_resolved")
        out["results"].append({
            "ticker": t, "signal": a.get("signal"),
            "fresh_classification": i.get("classification"),
            "old_disposition": old.get("disposition"),
            "new_disposition": out_i["disposition"],
            "violations": out_i["violations"],
            "policy_constructed": bool(i.get("policy_constructed")),
            "policy_rejected": i.get("policy_rejected"),
            "trigger_type": (ec.project_execution(res) or {})
            .get("trigger_type") if res else None,
            "provenance": (res or {}).get("number_provenance")})
    return out


def main():
    sessions = [a for a in sys.argv[1:] if not a.startswith("-")]
    all_out = {"calls": 0, "sessions": []}
    for s in sessions:
        r = run_session(s)
        if r:
            all_out["sessions"].append(r)
    all_out["calls"] = CALLS["n"]
    path = OUT / "policy_synthesis_check.json"
    path.write_text(json.dumps(all_out, indent=1, default=str))
    for s in all_out["sessions"]:
        print(f"== {s['session']} ({s['call_seconds']}s, {len(s['tickers'])} "
              f"tickers)")
        for r in s["results"]:
            flag = " *" if (r["new_disposition"] != r["old_disposition"]
                            or r["policy_constructed"]) else ""
            print(f"  {r['ticker']:<5} {r['signal']:<12} "
                  f"{r['old_disposition']} -> {r['new_disposition']}"
                  f" trig={r['trigger_type']} pol={r['policy_constructed']}"
                  f"{flag}")
            if r["violations"]:
                print(f"        viol: {r['violations'][:2]}")
    print(f"\ntotal bridge invocations: {CALLS['n']} (cap {MAX_CALLS})")


if __name__ == "__main__":
    main()
