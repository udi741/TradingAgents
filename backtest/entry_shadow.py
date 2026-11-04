#!/usr/bin/env python3
"""Prospective paper-only entry-mechanism shadow ledger.

Two predefined approaches over ALPHA's authored decisions, split into two
explicit cohorts:

  VALID_AUTHORIZED     — disposition EXECUTABLE_WATCH with a valid contract
                         (entry prerequisites are the authored ones).
  DIRECTIONAL_UNRESOLVED — authored LONG/SHORT direction whose contract was
                         rejected or is conditionally gated. Every result for
                         this cohort is labeled HYPOTHETICAL — it is shadow
                         research, never an authorized decision.

Strategies (both predefined BEFORE any outcome is observed):

  A_pullback — faithful to authored semantics: fill when a session Low <=
               authored zone top (SHORT: High >= zone bottom); authored
               close_below stop; authored target on High touch. If any term
               missing -> NO_PLAN (nothing invented).

  B_confirmed — continuation entry with CONFIRMATION, not next-open:
               entry = the OPEN of the first session that FOLLOWS a session
               closing above decision close (within 5 sessions; SHORT mirrors
               with close below). Gap guard: skip if entry open gaps >3% past
               the confirming close. Stop = max(authored stop, entry -1.5*ATR)
               for LONG (min for SHORT mirror: authored stop if > entry else
               entry +1.5*ATR). Target = authored target if better else 2R.
               Stop executes intraday AT the stop price when Low/High breaches
               (gap-through exits at that day's open). Time exit = 20 sessions.
               5bps fill slippage + 10bps/side fees. $5k notional, whole
               shares, <=10 concurrent shadow positions/approach, $50k cap.

Durable state: entry_shadow_ledger.json in the research archive. Idempotent:
keyed (approach, cohort, session, ticker); reruns recompute from state +
fresh bars only forward of last mark; never duplicates fills.

Nothing here writes to production watches/monitors/ledgers. No AI calls.
"""
import json
import sys
from pathlib import Path

import datetime

import pandas as pd
import yfinance as yf

EV = Path("/home/udi/udi_provate/TradingAgents/evaluations/alpha_rnd_v1")
OUT = Path("/home/udi/udi_provate/research-results-archive")
LEDGER = OUT / "entry_shadow_ledger.json"
NOTIONAL, MAX_POS, MAX_EXPO = 5000.0, 10, 50000.0
RISK_BUDGET = 250.0          # $ risk per position (0.25% of $100k book)
SLIP, FEE = 0.0005, 0.001
GAP_GUARD, CONFIRM_WIN, TIME_STOP = 1.03, 5, 20
ATR_N, ATR_K, RR = 14, 1.5, 2.0


def authored(i):
    ea = i.get("economic_authority") or {}
    e = ea.get("entry") or {}
    d = (i.get("decision") or {}).get("direction") or \
        str(ea.get("direction") or "").upper() or None
    z = e.get("zone") if isinstance(e.get("zone"), list) and \
        len(e["zone"]) == 2 else None
    return (d, z, (ea.get("stop") or {}).get("level") or i.get("stop_level"),
            (ea.get("objective") or {}).get("target") or i.get("target"),
            i.get("classification"))


def atr14(b):
    if len(b) < ATR_N:
        return None
    tr = (b["High"] - b["Low"]).tail(ATR_N)
    m = float(tr.mean())
    return m if m > 0 else None


def sim_A(dr, z, stop, tgt, fut, dec_close, open_expo=0.0):
    """Faithful authored-pullback sim; authored risk governs size."""
    if not (z and stop):
        return {"result": "NO_PLAN"}
    ztop = z[1] if dr == "LONG" else z[0]
    sh = _size(ztop, abs(ztop - stop), open_expo)
    if not sh:
        return {"result": "NO_PLAN"}
    for d, r in fut.iterrows():
        if dr == "LONG" and float(r["Low"]) <= ztop:
            px = ztop; break
        if dr == "SHORT" and float(r["High"]) >= ztop:
            px = ztop; break
    else:
        return {"result": "NO_FILL"}
    rest = fut.loc[fut.index > d]
    return _manage_A(dr, px, sh, stop, tgt, rest, str(d.date()))


def _manage_A(dr, px, sh, stop, tgt, rest, fill_day):
    fees = NOTIONAL * FEE * 2 + NOTIONAL * SLIP
    for d, r in rest.iterrows():
        cl, hi, lo = float(r["Close"]), float(r["High"]), float(r["Low"])
        if dr == "LONG":
            if cl <= stop:
                return _r("stopped", cl, px, sh, fees, d, fill_day)
            if tgt and hi >= tgt:
                return _r("target", tgt, px, sh, fees, d, fill_day)
        else:
            if cl >= stop:
                return _r("stopped", cl, px, sh, fees, d, fill_day)
            if tgt and lo <= tgt:
                return _r("target", tgt, px, sh, fees, d, fill_day)
    if rest.empty:
        return {"result": "OPEN", "entry_px": px, "shares": sh,
                "fill_day": fill_day}
    last = float(rest["Close"].iloc[-1])
    st = "time_stop" if len(rest) >= TIME_STOP else "OPEN"
    return _r(st, last, px, sh, fees, rest.index[-1], fill_day)


def sim_B(dr, stop, tgt, dec_close, a14, fut, open_expo=0.0):
    """Confirmed continuation; synthetic ATR risk, labeled separately."""
    if a14 is None or fut.empty:
        return {"result": "NO_PLAN"}
    conf = None
    for i, (d, r) in enumerate(fut.head(CONFIRM_WIN).iterrows()):
        cl = float(r["Close"])
        if (dr == "LONG" and cl > dec_close) or \
           (dr == "SHORT" and cl < dec_close):
            conf = i + 1
            break
    if conf is None or conf >= len(fut):
        return {"result": "NO_FILL"}
    eday = fut.index[conf]
    o = float(fut.loc[eday, "Open"])
    conf_close = float(fut.iloc[conf - 1]["Close"])
    if dr == "LONG" and o > conf_close * GAP_GUARD:
        return {"result": "NO_FILL", "why": "gap_guard"}
    if dr == "SHORT" and o < conf_close / GAP_GUARD:
        return {"result": "NO_FILL", "why": "gap_guard"}
    px = round(o * (1 + SLIP if dr == "LONG" else 1 - SLIP), 4)
    s = max(stop or 0, px - ATR_K * a14) if dr == "LONG" else \
        min(stop or 9e9, px + ATR_K * a14)
    if (dr == "LONG" and s >= px) or (dr == "SHORT" and s <= px):
        return {"result": "NO_PLAN"}
    t = tgt if (tgt and (tgt > px) == (dr == "LONG")) else \
        (px + RR * (px - s) if dr == "LONG" else px - RR * (s - px))
    sh = _size(px, abs(px - s), open_expo)
    if not sh:
        return {"result": "NO_PLAN"}
    rest = fut.loc[fut.index >= eday]
    return _manage_B(dr, px, sh, s, t, rest, str(eday.date()))


def _manage_B(dr, px, sh, stop, tgt, rest, fill_day):
    fees = NOTIONAL * (FEE * 2 + SLIP)
    for d, r in rest.iterrows():
        o, hi, lo = float(r["Open"]), float(r["High"]), float(r["Low"])
        if dr == "LONG":
            if o < stop:
                return _r("stopped_gap", o, px, sh, fees, d, fill_day)
            if lo <= stop:
                return _r("stopped", stop, px, sh, fees, d, fill_day)
            if tgt and hi >= tgt:
                return _r("target", tgt, px, sh, fees, d, fill_day)
        else:
            if o > stop:
                return _r("stopped_gap", o, px, sh, fees, d, fill_day)
            if hi >= stop:
                return _r("stopped", stop, px, sh, fees, d, fill_day)
            if tgt and lo <= tgt:
                return _r("target", tgt, px, sh, fees, d, fill_day)
    last = float(rest["Close"].iloc[-1])
    st = "time_stop" if len(rest) >= TIME_STOP else "OPEN"
    return _r(st, last, px, sh, fees, rest.index[-1], fill_day)


def _size(px, stop_dist, open_expo):
    """Risk-based shares: min(notional cap, risk-budget cap, exposure left).
    Zero/negative-risk plans -> 0 (caller treats as NO_PLAN)."""
    if stop_dist <= 0 or px <= 0:
        return 0
    room = max(MAX_EXPO - open_expo, 0.0)
    return max(min(int(NOTIONAL // px), int(RISK_BUDGET // stop_dist),
                   int(room // px)), 0)


def _r(status, x, px, sh, fees, d, fill_day):
    return {"result": status, "entry_px": px, "exit_px": round(x, 2),
            "shares": sh, "fill_day": fill_day,
            "exit_day": str(d.date()) if hasattr(d, "date") else str(d),
            "pnl": round((x - px) * sh - fees, 2)}


def cohort_of(disp, contract_ok):
    if disp == "EXECUTABLE_WATCH" and contract_ok:
        return "VALID_AUTHORIZED"
    return "DIRECTIONAL_UNRESOLVED"


def run(sessions, end=None, ledger_path=LEDGER):
    """Idempotent: existing closed results are kept; OPEN/none recomputed."""
    ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() \
        else {"records": {}, "last_marks": {}}
    recs = ledger["records"]
    for s in sessions:
        f = EV / f"publication_intents_{s}.json"
        if not f.exists():
            continue
        doc = json.loads(f.read_text())
        for t, disp in (doc.get("dispositions") or {}).items():
            i = doc["intents"].get(t) or {}
            dr, z, stop, tgt, cls = authored(i)
            if dr not in ("LONG", "SHORT"):
                continue
            coh = cohort_of(disp["disposition"],
                            bool(z and stop and dr))
            df = yf.download(t, start="2026-09-01", end=end,
                             progress=False, auto_adjust=True)
            df = df.xs(t, axis=1, level=1, drop_level=True)
            before, fut = df[df.index <= s], df[df.index > s]
            if before.empty:
                continue
            dec_close = float(before["Close"].iloc[-1])
            a14 = atr14(before)
            key = f"{s}|{t}"
            rec = recs.setdefault(key, {
                "session": s, "ticker": t, "direction": dr,
                "cohort": coh, "disposition": disp["disposition"],
                "dec_close": dec_close, "zone": z, "stop": stop,
                "target": tgt, "hypothetical": coh != "VALID_AUTHORIZED"})
            # recompute only non-closed legs (idempotent for closed)
            expo = {"A_pullback": _open_expo(recs, "A_pullback"),
                    "B_confirmed": _open_expo(recs, "B_confirmed")}
            for leg, fn in (("A_pullback",
                             lambda: sim_A(dr, z, stop, tgt, fut, dec_close,
                                          expo["A_pullback"])),
                            ("B_confirmed",
                             lambda: sim_B(dr, stop, tgt, dec_close, a14,
                                          fut, expo["B_confirmed"]))):
                cur = rec.get(leg)
                if cur and cur.get("result") not in ("OPEN", None):
                    continue  # closed/terminal -> keep
                rec[leg] = fn()
    ledger["last_mark"] = datetime.datetime.now(
        datetime.timezone.utc).isoformat()
    ledger_path.write_text(json.dumps(ledger, indent=1))
    return ledger


def update(end=None, ledger_path=LEDGER):
    """Daily lifecycle: register any new published decisions, re-mark every
    OPEN leg forward with the latest bars, leave terminals untouched.
    Idempotent and resumable; safe on days with no new research.
    At most once per UTC day unless `end` is given (backfill/test mode)."""
    if end is None and ledger_path.exists():
        try:
            lm = json.loads(ledger_path.read_text()).get("last_mark") or ""
            if lm[:10] == datetime.datetime.now(
                    datetime.timezone.utc).date().isoformat():
                return json.loads(ledger_path.read_text())
        except Exception:
            pass
    sessions = sorted(
        p.stem.replace("publication_intents_", "")
        for p in EV.glob("publication_intents_*.json"))
    return run(sessions, end=end, ledger_path=ledger_path)


def _open_expo(recs, leg):
    """Open-position notional under one approach (synthetic risk labeled
    separately from authored risk by caller)."""
    tot = 0.0
    for r in recs.values():
        v = r.get(leg) or {}
        if v.get("result") == "OPEN":
            tot += (v.get("entry_px") or 0) * (v.get("shares") or 0)
    return tot


def summary(ledger):
    rows = []
    for k, r in ledger["records"].items():
        for leg in ("A_pullback", "B_confirmed"):
            v = r.get(leg) or {}
            rows.append((r["session"], r["ticker"], r["cohort"], leg,
                         v.get("result"), v.get("pnl")))
    return rows


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "update":
        lg = update()
    else:
        sess = sys.argv[1:] or ["2026-10-28", "2026-10-30", "2026-11-02",
                                "2026-11-03"]
        lg = run(sess)
    for row in summary(lg):
        print("%s %-5s %-22s %-13s %-10s %s" % row)
