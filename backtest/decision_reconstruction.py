#!/usr/bin/env python3
"""Frozen-artifact replay: OLD pipeline outcome vs REVISED pipeline.

For every frozen publication intent (production evaluations dir, read-only)
the REVISED deterministic pipeline is re-run through the SAME code path
synthesize.run uses (evaluate_intent) — authored contract validation,
evidence-bound repair, POLICY_DERIVED construction, projection — and the
result is compared to the frozen original disposition.

Everything here is IN-SAMPLE engineering/economic reconstruction, not a
prospective claim. No model calls. Market data via yfinance only.

  python3 backtest/decision_reconstruction.py [--econ] [--tickers T..]
"""
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
import yfinance as yf

from alpha_rnd import synthesize as sz
from alpha_rnd import econ_contract as ec
from alpha_rnd import econ_policy as ep
from alpha_rnd import monitor as mon

EV = Path("/home/udi/udi_provate/TradingAgents/evaluations/alpha_rnd_v1")
OUT = Path(__file__).parent / "results" / "decision_reconstruction.json"

FOCUS = ["RHI", "REPL", "HOG", "CDNA", "TDOC", "LNG", "GKOS", "MANH", "PSX"]

FEE, SLIP = 0.001, 0.0005      # monitor.COST_BPS / entry_shadow slippage
NOTIONAL = 5000.0              # monitor.POS_NOTIONAL
TIME_STOP = 20                 # entry_shadow time exit
_BAR_CACHE = {}


def bars_for(ticker: str, session: str):
    """Daily bars for ticker, split at session: (decision frame <=session,
    future frame >session). One download per ticker, no lookahead."""
    if ticker not in _BAR_CACHE:
        try:
            df = yf.download(ticker, start="2026-08-15", progress=False,
                             auto_adjust=True)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            _BAR_CACHE[ticker] = df.dropna()
        except Exception:
            _BAR_CACHE[ticker] = pd.DataFrame()
    df = _BAR_CACHE[ticker]
    if df.empty:
        return df, df
    return df[df.index <= session], df[df.index > session]


def sim_contract(proj: dict, fut: pd.DataFrame) -> dict:
    """Monitor-verbatim execution simulation of a projected watch.

    Mirrors the monitor: intraday_zone_touch fills at zone top on touch;
    confirmed_close_above fills at the NEXT open after a completed close
    past trigger (inside confirm window, under gap guard). close_below
    stop exits at next open; intraday_stop exits at level (gap-through at
    open). target exits on High touch. Time exit at 20 sessions.
    Costs: 10bps/side fee + 5bps entry slippage. $5k notional cap x frac.
    """
    if fut.empty:
        return {"result": "NO_BARS"}
    tt, p = proj.get("trigger_type"), proj.get("params") or {}
    frac = proj.get("size_frac") or 1.0
    stop_rule = proj.get("stop_rule") or {}
    stop, stype = stop_rule.get("level"), stop_rule.get("type")
    tgt = proj.get("target")
    fill, fill_day, why = None, None, None
    if tt == "intraday_zone_touch" and p.get("zone"):
        ztop = p["zone"][1]
        cap = p.get("max_entry_price")
        for d, r in fut.iterrows():
            if float(r["Low"]) <= ztop:
                if cap is not None and ztop > cap:
                    return {"result": "NO_FILL", "why": "max_entry_price"}
                fill, fill_day = ztop, d
                break
        else:
            return {"result": "NO_FILL"}
    elif tt == "confirmed_close_above" and p.get("trigger_level") is not None:
        lvl = p["trigger_level"]
        win = int(p.get("confirm_within_sessions") or 10**9)
        gap = p.get("max_gap_pct")
        rows = list(fut.head(win).iterrows())
        for i, (d, r) in enumerate(rows):
            if float(r["Close"]) > lvl:
                if i + 1 >= len(fut):
                    return {"result": "NO_FILL", "why": "no_next_session"}
                eday = fut.index[i + 1]
                o = float(fut.loc[eday, "Open"])
                if gap and o > float(r["Close"]) * (1 + gap):
                    return {"result": "NO_FILL", "why": "gap_guard"}
                fill, fill_day = o, eday
                break
        else:
            return {"result": "NO_FILL"}
    else:
        return {"result": "NO_PLAN", "why": f"unsupported trigger {tt}"}
    if fill is None:
        return {"result": "NO_FILL"}
    px = round(fill * (1 + SLIP), 4)
    shares = int(NOTIONAL * frac // px)
    if shares <= 0:
        return {"result": "NO_PLAN", "why": "zero shares"}
    fees = shares * px * FEE + shares * px * FEE

    def _r(status, x, d):
        return {"result": status, "entry_px": px, "exit_px": round(x, 2),
                "shares": shares, "fill_day": str(fill_day.date()),
                "exit_day": str(d.date()),
                "pnl": round((x - px) * shares - fees, 2)}

    rest = fut.loc[fut.index >= fill_day]
    # entries take effect at the open: evaluate the fill session from Open
    for d, r in rest.iterrows():
        o, hi, lo, cl = (float(r[k]) for k in
                         ("Open", "High", "Low", "Close"))
        if stype == "intraday_stop" and stop is not None:
            if o < stop:
                return _r("stopped_gap", o, d)
            if lo <= stop:
                return _r("stopped", stop, d)
        elif stype == "close_below" and stop is not None and cl < stop:
            after = rest.loc[rest.index > d]
            xp = float(after["Open"].iloc[0]) if len(after) else cl
            return _r("stopped_close", xp, d)
        if tgt and hi >= tgt:
            return _r("target", tgt, d)
    last = float(rest["Close"].iloc[-1])
    st_ = "time_stop" if len(rest) >= TIME_STOP else "OPEN"
    return _r(st_, last, rest.index[-1])


def main():
    econ = "--econ" in sys.argv
    focus_only = [a for a in sys.argv[1:] if not a.startswith("--")]
    held = set()
    try:
        held = set(json.loads(
            (EV.parents[1] / "alpha_rnd" / "monitor_state.json")
            .read_text()).get("positions") or {})
    except Exception:
        pass
    spy = None
    if econ:
        spy = yf.download("SPY", start="2026-08-15", progress=False,
                          auto_adjust=True)
        if isinstance(spy.columns, pd.MultiIndex):
            spy.columns = spy.columns.get_level_values(0)
    docs = sorted(EV.glob("publication_intents_*.json"))
    recs, agg = [], {"n": 0}
    for f in docs:
        sess = f.stem.rsplit("_", 1)[-1]
        doc = json.loads(f.read_text())
        for t, i in (doc.get("intents") or {}).items():
            if focus_only and t not in focus_only:
                continue
            ap = EV / "case_artifacts" / f"{t}_{sess}.json"
            if not ap.exists():
                continue
            a = json.loads(ap.read_text())
            old = (doc.get("dispositions") or {}).get(t) or {}
            old_c = bool(i.get("economic_authority_resolved"))
            before, fut = bars_for(t, sess)
            i2 = copy.deepcopy(i)
            out = sz.evaluate_intent(i2, a, sess, held,
                                     bars=before if not before.empty
                                     else None)
            res = i2.get("economic_authority_resolved")
            proj = ec.project_execution(res) if res else None
            npol = sum(1 for v in (res or {}).get(
                "number_provenance", {}).values() if v == "POLICY_DERIVED")
            nsrc = sum(1 for v in (res or {}).get(
                "number_provenance", {}).values()
                if v == "SOURCE_AUTHORED")
            rec = {"session": sess, "ticker": t,
                   "signal": a.get("signal"),
                   "old_disposition": old.get("disposition"),
                   "old_executable": bool(old.get("executable")),
                   "old_contract_resolved": old_c,
                   "old_violations": old.get("violations") or [],
                   "new_disposition": out["disposition"],
                   "new_executable": out["executable"],
                   "new_violations": out["violations"],
                   "policy_constructed": bool(i2.get("policy_constructed")),
                   "policy_rejected": i2.get("policy_rejected"),
                   "policy_non_executable": i2.get("policy_non_executable"),
                   "n_policy_terms": npol, "n_source_terms": nsrc,
                   "trigger_type": proj and proj.get("trigger_type"),
                   "unverified_events": (proj or {}).get("event_constraints"),
                   "decision": (i2.get("decision") or {}).get("direction")}
            if econ and proj is not None:
                sim = sim_contract(proj, fut)
                rec["sim"] = sim
                if spy is not None and sim.get("fill_day"):
                    f0 = pd.Timestamp(sim["fill_day"])
                    f1 = (pd.Timestamp(sim["exit_day"])
                          if sim.get("exit_day") else fut.index[-1])
                    s0 = spy[spy.index <= f0]["Close"]
                    s1 = spy[spy.index <= f1]["Close"]
                    if len(s0) and len(s1):
                        rec["spy_ret_pct"] = round(
                            (float(s1.iloc[-1]) / float(s0.iloc[-1]) - 1)
                            * 100, 2)
            recs.append(rec)
    OUT.write_text(json.dumps({"generated": pd.Timestamp.now(
        "UTC").isoformat(), "records": recs}, indent=1, default=str))
    # ── summary ──────────────────────────────────────────────────────────
    def cnt(pred):
        return sum(1 for r in recs if pred(r))
    print(f"cases evaluated: {len(recs)}")
    print(f"  old EXECUTABLE_WATCH: {cnt(lambda r: r['old_executable'])}")
    print(f"  new EXECUTABLE_WATCH: {cnt(lambda r: r['new_executable'])}")
    print(f"  newly executable:     "
          f"{cnt(lambda r: r['new_executable'] and not r['old_executable'])}"
          f"  {[r['ticker'] + '@' + r['session'] for r in recs if r['new_executable'] and not r['old_executable']]}")
    print(f"  lost executable:      "
          f"{cnt(lambda r: r['old_executable'] and not r['new_executable'])}"
          f"  {[r['ticker'] + '@' + r['session'] for r in recs if r['old_executable'] and not r['new_executable']]}")
    print(f"  policy constructed:   {cnt(lambda r: r['policy_constructed'])}")
    print(f"  policy rejected:      {cnt(lambda r: bool(r['policy_rejected']))}")
    print(f"  policy non-exec:      {cnt(lambda r: bool(r['policy_non_executable']))}")
    print(f"  event-gated (unverified): {cnt(lambda r: bool(r['unverified_events']))}")
    print("\nfocus cases:")
    for r in recs:
        if r["ticker"] in FOCUS:
            print(f"  {r['ticker']:<5} {r['session']} sig={r['signal']:<12}"
                  f" {r['old_disposition']}->{r['new_disposition']}"
                  f" trig={r['trigger_type']} sim={(r.get('sim') or {}).get('result')}"
                  f" pnl={(r.get('sim') or {}).get('pnl')}")
    if econ:
        filled = [r for r in recs if (r.get("sim") or {}).get("pnl")
                  is not None]
        tot = sum(r["sim"]["pnl"] for r in filled)
        print(f"\nrevised executable fills: {len(filled)}  net PnL ${tot:.2f}")
        for r in filled:
            print(f"  {r['ticker']:<5} {r['session']} {r['sim']['result']:<12}"
                  f" pnl={r['sim']['pnl']:>9} spy={r.get('spy_ret_pct')}")


if __name__ == "__main__":
    main()
