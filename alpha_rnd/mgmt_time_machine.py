#!/usr/bin/env python3
"""Time-machine evaluation of the frozen adaptive post-entry manager.

RESEARCH ONLY — never touches live state. Cohort A: the five closed
historical ALPHA positions (MANAGEMENT_RESEARCH_ONLY per R7 caveat).
PBF excluded: live canary, no post-10-16 outcome exists.

CONTROL: original deterministic stop semantics only.
TREATMENT: frozen triggers -> real shadow reassessment (as-of bounded) ->
frozen validator -> simulated canonical execution (next-open fills,
deferred remainder stop). No lookahead.

Usage: python -m alpha_rnd.mgmt_time_machine [--no-model]
"""
import json
import sys
import hashlib
from datetime import datetime, timezone
from pathlib import Path

from alpha_rnd import mgmt
from alpha_rnd import mgmt_reassess as mr
from alpha_rnd import mgmt_validate as mv

ROOT = Path(__file__).resolve().parents[1]
EV = ROOT / "evaluations" / "alpha_rnd_v1"
OUT = EV / "mgmt_time_machine"

# entry_session, fill, shares, stop(level,type), horizon checkpoint
TRADES = {
 "ACN": ("2026-10-02", 205.0, 24, 194.0, "close_below", "2026-10-16"),
 "APPS": ("2026-10-02", 11.30, 442, 10.42, "intraday_stop", "2026-10-16"),
 "PGEN": ("2026-10-05", 8.20, 609, 7.75, "intraday_stop", "2026-10-16"),
 "TWST": ("2026-10-06", 209.55, 11, 164.0, "intraday_stop", "2026-10-16"),
 "SDGR": ("2026-10-06", 31.00, 161, 27.29, "close_below", "2026-10-16"),
}


def _atomic(p, doc):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, indent=1, default=str, sort_keys=True))
    tmp.replace(p)


def snap_for(t, ent, fill, stop, stype, horizon):
    return {"ticker": t, "entry_session": ent, "entry_price": fill,
            "risk_plan": {"stop_rule": {"type": stype, "level": stop}},
            "horizon": "2-3wk", "reevaluation": f"review {horizon}"}


def _fill_at(df, date_):
    return float(df[df.index.strftime("%Y-%m-%d") == date_]["Open"].iloc[0])


def control(df, ent, fill, shares, stop, stype):
    """Deterministic baseline: intraday stop -> level/open on gap;
    close_below -> next open after the closing breach. Marks flat."""
    evs = []
    for i in range(len(df)):
        sess = str(df.index[i].date())
        if sess <= ent:
            continue
        h, l, c, o = (float(df[k].iloc[i]) for k in
                      ("High", "Low", "Close", "Open"))
        if stype == "intraday_stop" and l <= stop:
            px = o if o <= stop else stop
            return {"exit_session": sess, "exit_px": px,
                    "events": evs + [{"t": sess, "kind": "stop", "px": px}],
                    "shares_out": shares}
        if stype == "close_below" and c < stop:
            nxt = str(df.index[i + 1].date()) if i + 1 < len(df) else None
            px = _fill_at(df, nxt) if nxt else c
            return {"exit_session": nxt or sess, "exit_px": px,
                    "events": evs + [{"t": sess, "kind": "close_below",
                                      "px": px}],
                    "shares_out": shares}
    last_c = float(df["Close"].iloc[-1])
    return {"exit_session": str(df.index[-1].date()), "exit_px": last_c,
            "events": evs + [{"t": str(df.index[-1].date()),
                              "kind": "mark_to_end", "px": last_c}],
            "shares_out": shares, "open_at_end": True}


def treatment(t, df, ent, fill, shares, stop, stype, horizon, pol,
              model_fn, slip_bps=0.0, trace=None):
    """Frozen manager over the same path. Returns fills + decisions."""
    snap = snap_for(t, ent, fill, stop, stype, horizon)
    pos = {"shares": shares, "fill": fill}
    rule = {"type": stype, "level": stop}
    pend = None          # {qty(px next open), rem_rule}
    rem_rule = None
    cur_stop = stop
    fills = []
    rec_trig = {"triggers": {}}
    closed = False
    exits = []
    sessions = [str(d.date()) for d in df.index]
    for i in range(len(df)):
        sess = sessions[i]
        if sess <= ent:
            continue
        h, l, c, o = (float(df[k].iloc[i]) for k in
                      ("High", "Low", "Close", "Open"))
        # 1. pending order fills at THIS open (canonical next-open)
        if pend and sess > pend["confirm"]:
            px = o * (1 - slip_bps / 1e4)
            sell = min(pend["qty"], pos["shares"])
            pos["shares"] -= sell
            fills.append({"t": sess, "px": round(px, 4), "shares": sell,
                          "kind": "adaptive_" + pend["action"]})
            trace and trace.append({"sess": sess, "fill": px,
                                    "shares": sell})
            if pend.get("rem"):
                errs = [] if pend["rem"]["level"] > cur_stop \
                    else ["no tightening"]
                if not errs:
                    rem_stop = pend["rem"]["level"]
                else:
                    rem_stop = cur_stop
                rule = {"type": pend["rem"]["type"], "level": rem_stop}
            pend = None
            if pos["shares"] <= 0:
                closed = True
        if closed:
            break
        # 2. deterministic safety — hard stop always wins, same day
        rl = rule["level"]; rt = rule["type"]
        if rt == "intraday_stop" and l <= rl:
            px = o if o <= rl else rl
            exits.append({"sess": sess, "px": px, "kind": "stop"})
            fills.append({"t": sess, "px": px, "shares": pos["shares"],
                          "kind": "deterministic_stop"})
            pos["shares"] = 0
            closed = True
            break
        if rt == "close_below" and c < rl:
            exits.append({"sess": sess, "px": c, "kind": "close_below"})
            nxt = sessions[i + 1] if i + 1 < len(sessions) else None
            px = _fill_at(df, nxt) if nxt else c
            fills.append({"t": nxt or sess, "px": px,
                          "shares": pos["shares"], "kind": "close_below"})
            pos["shares"] = 0
            closed = True
            break
        # 3. metrics + triggers (end of session)
        sub = df[(df.index.strftime("%Y-%m-%d") >= ent) &
                 (df.index <= df.index[i])]
        rec = {"entry_price": fill,
               "unrealized_pct": (c / fill - 1) * 100,
               "peak_unrealized_pct": (float(sub["High"].max()) / fill - 1) * 100,
               "drawdown_from_peak_pct": (float(sub["High"].max()) - c) / fill * 100,
               "mae_pct": (float(sub["Low"].min()) / fill - 1) * 100,
               "sessions_held": i + 1}
        for ev in mgmt.evaluate(t, rec, snap, pol, sess):
            fam = ev["family"]
            if fam == "R_CONTEXT_UNAVAILABLE":
                continue
            if rec_trig["triggers"].get(fam, {}).get("fired_at"):
                continue
            rec_trig["triggers"][fam] = {"fired_at": sess}
            trace and trace.append({"sess": sess, "trigger": fam,
                                    "reason": ev["reason"]})
            # model reassessment, as-of this session
            if model_fn is None:
                continue
            ctx = {"entry_snapshot": snap, "metrics": rec,
                   "trigger": ev, "session": sess,
                   "recent_bars": [{"d": str(x.date()),
                                    "c": round(r.Close, 2),
                                    "l": round(r.Low, 2),
                                    "h": round(r.High, 2)}
                                   for x, r in df.tail(10).iterrows()
                                   if str(x.date()) <= sess]}
            try:
                raw = model_fn(ctx)
                d2 = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
                val, errs = mr.validate_result(t, d2)
            except Exception as e:
                val, errs = None, [repr(e)[:80]]
            if val is None:
                trace and trace.append({"sess": sess, "model": "FAILED",
                                        "errs": errs})
                continue
            act = val["recommended_action"]
            trace and trace.append({"sess": sess, "model": act,
                                    "thesis": val["thesis_status"]})
            if act == "FULL_EXIT":
                pend = {"qty": pos["shares"], "confirm": sess,
                        "action": "FULL_EXIT"}
            elif act == "PARTIAL_EXIT":
                f = (val.get("partial_exit") or {}).get("fraction")
                if f and 0 < f < 1:
                    q = int(round(f * pos["shares"]))
                    if 0 < q < pos["shares"]:
                        rem = val.get("proposed_stop") or {}
                        remr = None
                        if rem.get("level") and rem["level"] > cur_stop:
                            remr = {"type": "close_below",
                                    "level": rem["level"]}
                        pend = {"qty": q, "confirm": sess,
                                "action": "PARTIAL_EXIT", "rem": remr}
            elif act == "HOLD_AND_TIGHTEN_RISK":
                ps = val.get("proposed_stop") or {}
                if ps.get("level") and ps["level"] > cur_stop:
                    typ = ps.get("type")
                    rule = {"type": "close_below" if typ != "intraday_stop"
                            else "intraday_stop",
                            "level": ps["level"]}
                    trace and trace.append({"sess": sess,
                                            "tightened": ps["level"]})
    # end mark
    if pos["shares"] > 0:
        fills.append({"t": sessions[-1], "px": float(df["Close"].iloc[-1]),
                      "shares": pos["shares"], "kind": "mark_to_end"})
    return {"fills": fills, "exits": exits, "triggers": rec_trig,
            "final_shares": pos["shares"]}


def pnl(fills, fill):
    return round(sum(f["shares"] * (f["px"] / fill - 1) * 100
                     for f in fills) / 100 * fill, 2) / fill


def ret(fills, fill, shares0):
    """% return on original notional."""
    gain = sum(f["shares"] * (f["px"] - fill) for f in fills)
    return round(gain / (fill * shares0) * 100, 2)


def run(no_model=False):
    import pandas as pd  # noqa
    from ta_eval_alpha import e17_screener as e17
    pol = mgmt.policy()
    OUT.mkdir(exist_ok=True)
    results = {}
    n_calls = 0
    d, _ = e17.fetch_batch_ohlcv(list(TRADES) + ["SPY"], "2026-09-15",
                                 "2026-10-17", batch_size=3)
    for t, (ent, fill, shares, stop, stype, horizon) in TRADES.items():
        df = d.get(t)
        if df is None:
            results[t] = {"error": "no data"}
            continue
        df = df[df.index.strftime("%Y-%m-%d") <= "2026-10-16"]
        ctrl = control(df, ent, fill, shares, stop, stype)
        trace = []
        calls = [0]

        def mfn(ctx, c=calls):
            c[0] += 1
            return mr._default_model(
                {"position_management_request": mr.PROMPT,
                 "context": ctx})
        treat = treatment(t, df, ent, fill, shares, stop, stype, horizon,
                          pol, None if no_model else mfn, trace=trace)
        n_calls += calls[0]
        ctrl_ret = ret([{"shares": ctrl["shares_out"],
                         "px": ctrl["exit_px"]}], fill, shares)
        trt_ret = ret(treat["fills"], fill, shares)
        results[t] = {"control": {**ctrl, "ret_pct": ctrl_ret},
                      "treatment": {"fills": treat["fills"],
                                    "ret_pct": trt_ret,
                                    "triggers": {k: v.get("fired_at") for k, v
                                                 in treat["triggers"]["triggers"].items()},
                                    "trace": trace,
                                    "model_calls": calls[0]},
                      "delta_pct": round(trt_ret - ctrl_ret, 2)}
    _atomic(OUT / "results.json",
            {"generated_at": datetime.now(timezone.utc).isoformat(),
             "frozen_manager": {"alpha_sha": "8355c176",
                                "policy_sha": "cc8a406e350db057",
                                "model": mr.MODEL,
                                "validator": "mgmt_validate.py"},
             "cohort": "A_MANAGEMENT_RESEARCH_ONLY",
             "note": "5 closed historical trades; PBF excluded (live). "
                     "Trigger-fired sessions got a real as-of-bounded model "
                     "call; no lookahead.",
             "model_calls": n_calls, "results": results})
    for t, r in results.items():
        if "control" in r:
            print(f"{t}: control {r['control']['ret_pct']}% "
                  f"(exit {r['control']['exit_session']} "
                  f"@ {round(r['control']['exit_px'],2)}) | "
                  f"treatment {r['treatment']['ret_pct']}% | "
                  f"delta {r['delta_pct']}pp | calls "
                  f"{r['treatment']['model_calls']}")
    print("model calls:", n_calls)


if __name__ == "__main__":
    run("--no-model" in sys.argv)
