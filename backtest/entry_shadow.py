#!/usr/bin/env python3
"""Prospective paper-only entry-mechanism comparison (shadow).

Two PRE-DEFINED approaches applied to each authored ALPHA decision.
Nothing here touches production ledgers, watchlists or orders — output
goes only to the research archive. No AI inference.

A) ORIGINAL_PULLBACK — the authored zone/stop/target evaluated day-by-day:
   fill when a session's Low <= zone top; stop = authored close_below;
   target = authored target (High >= target).
B) CONTINUATION — predefined, uses ONLY decision-day-and-prior market data:
   eligibility: an authored LONG/SHORT direction exists (decision.direction
   or economic_authority.direction) AND a protective stop is derivable
   (authored stop, else 1.5*ATR14(decision-day) below/above entry).
   Entry: first session's OPEN after the decision session, but only if
   open <= decision_close * 1.03 (no chase beyond a 3% overnight gap —
   predefined slippage guard, not hindsight-tuned).
   Stop: authored stop if present else entry - 1.5*ATR14 (LONG).
   Target: entry + 2*risk (LONG) when no authored target; authored target
   if better economics exist. Time stop: 20 sessions.
   Size: $5,000 notional, whole shares, both approaches; 10 bps each side.
   SHORT variants: paper-only mirror (stop above, target entry - 2*risk).

Determinism: pure function of intents + daily bars. No lookahead: entry/
stop/ATR use bars strictly <= decision session for planning, > session
for fills.
"""
import json
import math
import sys
from pathlib import Path

import yfinance as yf

EV = Path("/home/udi/udi_provate/TradingAgents/evaluations/alpha_rnd_v1")
OUT = Path("/home/udi/udi_provate/research-results-archive")
NOTIONAL = 5000.0
FEE_BPS = 0.001
GAP_GUARD = 1.03
ATR_N, ATR_K, TIME_STOP, RR = 14, 1.5, 20, 2.0


def authored(i):
    ea = i.get("economic_authority") or {}
    e = ea.get("entry") or {}
    d = (i.get("decision") or {}).get("direction") or \
        str(ea.get("direction") or "").upper() or None
    z = e.get("zone") if isinstance(e.get("zone"), list) and \
        len(e["zone"]) == 2 else None
    stop = (ea.get("stop") or {}).get("level") or i.get("stop_level")
    tgt = (ea.get("objective") or {}).get("target") or i.get("target")
    return d, z, stop, tgt


def atr14(bars_before):
    if len(bars_before) < ATR_N:
        return None
    tr = [(h - l) for h, l in zip(bars_before["High"].tolist()[-ATR_N:],
                                bars_before["Low"].tolist()[-ATR_N:])]
    m = sum(tr) / len(tr)
    return m if m > 0 else None


def sim_A(dr, z, stop, tgt, fut):
    """Original pullback mechanics. Returns dict or None (no fill)."""
    if not z or not stop:
        return None
    ztop = z[1] if dr == "LONG" else z[0]
    sh = int(NOTIONAL // ztop) or None
    if not sh:
        return None
    for d, row in fut.iterrows():
        lo, hi, cl = float(row["Low"]), float(row["High"]), float(row["Close"])
        if dr == "LONG" and lo <= ztop:
            px = ztop
            break
        if dr == "SHORT" and hi >= ztop:
            px = ztop
            break
    else:
        return None
    rest = fut.loc[fut.index > d]
    return _manage(dr, px, sh, stop, tgt, rest)


def sim_B(dr, stop, tgt, dec_close, a14, fut):
    """Continuation: next-open entry behind a 3% gap guard."""
    if fut.empty or a14 is None:
        return None
    o = float(fut["Open"].iloc[0])
    if dr == "LONG" and o > dec_close * GAP_GUARD:
        return {"no_fill": "gap_guard"}
    if dr == "SHORT" and o < dec_close / GAP_GUARD:
        return {"no_fill": "gap_guard"}
    px = o
    if dr == "LONG":
        s = stop if stop and stop < px else px - ATR_K * a14
        t = tgt if tgt and tgt > px else px + RR * (px - s)
    else:
        s = stop if stop and stop > px else px + ATR_K * a14
        t = tgt if tgt and tgt < px else px - RR * (s - px)
    sh = int(NOTIONAL // px)
    if not sh or (dr == "LONG" and s >= px) or (dr == "SHORT" and s <= px):
        return None
    return _manage(dr, px, sh, s, t, fut.iloc[1:].head(TIME_STOP))


def _manage(dr, px, sh, stop, tgt, rest):
    fees = NOTIONAL * FEE_BPS * 2
    for d, row in rest.iterrows():
        cl = float(row["Close"]); hi = float(row["High"])
        if dr == "LONG":
            if cl <= stop:
                return _r("stopped", cl, px, sh, fees, d)
            if tgt and hi >= tgt:
                return _r("target", tgt, px, sh, fees, d)
        else:
            if cl >= stop:
                return _r("stopped", cl, px, sh, fees, d)
            if tgt and float(row["Low"]) <= tgt:
                return _r("target", tgt, px, sh, fees, d)
    if rest.empty:
        return {"status": "no_bars"}
    last = float(rest["Close"].iloc[-1])
    return _r("time_stop" if len(rest) >= TIME_STOP else "open", last, px,
              sh, fees, rest.index[-1])


def _r(status, exit_px, px, sh, fees, d):
    sgn = 1 if px else 1
    return {"status": status, "exit_px": round(exit_px, 2), "exit_day":
            str(d.date()) if hasattr(d, "date") else str(d),
            "entry_px": round(px, 2), "shares": sh,
            "pnl": round((exit_px - px) * sh * sgn - fees, 2)}


def run(sessions, end="2026-11-05"):
    recs = []
    for s in sessions:
        f = EV / f"publication_intents_{s}.json"
        if not f.exists():
            continue
        d = json.loads(f.read_text())
        for t in (d.get("dispositions") or {}):
            i = d["intents"].get(t) or {}
            dr, z, stop, tgt = authored(i)
            if dr not in ("LONG", "SHORT"):
                continue
            df = yf.download(t, start="2026-09-01", end=end,
                             progress=False, auto_adjust=True)
            df = df.xs(t, axis=1, level=1, drop_level=True)
            before = df[df.index <= s]
            fut = df[df.index > s]
            if before.empty:
                continue
            dec_close = float(before["Close"].iloc[-1])
            a14 = atr14(before)
            rec = {"session": s, "ticker": t, "direction": dr,
                   "disposition": (d["dispositions"][t] or {})["disposition"],
                   "dec_close": round(dec_close, 2),
                   "zone": z, "stop": stop, "target": tgt,
                   "atr14": round(a14, 3) if a14 else None,
                   "A_pullback": sim_A(dr, z, stop, tgt, fut),
                   "B_continuation": sim_B(dr, stop, tgt, dec_close, a14,
                                          fut)}
            recs.append(rec)
    return recs


if __name__ == "__main__":
    sess = sys.argv[1:] or ["2026-10-28", "2026-10-30", "2026-11-02",
                            "2026-11-03"]
    recs = run(sess)
    OUT.mkdir(exist_ok=True)
    (OUT / "entry_shadow_baseline.json").write_text(json.dumps(recs,
                                                             indent=1))
    for label in ("A_pullback", "B_continuation"):
        rs = [r[label] for r in recs if r.get(label)]
        fills = [r for r in rs if r.get("pnl") is not None]
        print(f"{label}: intents={len(recs)} evaluated={len(rs)} "
              f"fills={len(fills)} "
              f"no_fill={sum(1 for r in rs if r.get('no_fill'))} "
              f"net_pnl={round(sum(r['pnl'] for r in fills),2)} "
              f"stopped={sum(1 for r in fills if r['status']=='stopped')} "
              f"target={sum(1 for r in fills if r['status']=='target')}")
