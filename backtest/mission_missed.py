#!/usr/bin/env python3
"""Missed-opportunity audit for ALPHA pilot sessions (read-only).

Original direction comes ONLY from contemporaneous authored fields:
  decision.direction (LONG/SHORT/NO_TRADE), classification
  (WATCH_FOR_ENTRY/AUTO_ENTRY vs REANALYZE vs REJECT), TA signal,
  economic_authority contract. Prices are point-in-time daily bars.
Never inferred from hindsight.
"""
import json
import sys
from pathlib import Path

import yfinance as yf

EV = Path("/home/udi/udi_provate/TradingAgents/evaluations/alpha_rnd_v1")
OUT = Path("/home/udi/udi_provate/research-results-archive")
SESSIONS = ["2026-10-28", "2026-10-30", "2026-11-02", "2026-11-03"]
RANK10 = {"2026-10-28", "2026-10-30", "2026-11-02"}   # tiered sessions
LAST = "2026-11-05"  # yf end exclusive -> through Nov 4 open/close data


def direction(i, a_signal):
    d = (i.get("decision") or {}).get("direction")
    ea = i.get("economic_authority") or {}
    ea_dir = str(ea.get("direction") or "").upper()
    cls = i.get("classification")
    if d == "LONG" or ea_dir == "LONG":
        return "LONG", f"decision={d} econ={ea_dir} cls={cls}"
    if d == "SHORT" or ea_dir == "SHORT":
        return "SHORT", f"decision={d} econ={ea_dir} cls={cls}"
    if cls in ("WATCH_FOR_ENTRY", "AUTO_ENTRY") and a_signal in ("Buy", "Overweight"):
        return "CONDITIONAL_LONG", f"watch+signal {a_signal}"
    if cls in ("WATCH_FOR_ENTRY", "AUTO_ENTRY") and a_signal in ("Sell", "Underweight"):
        return "CONDITIONAL_SHORT", f"watch+signal {a_signal}"
    if cls == "REANALYZE_ON_TRIGGER":
        side = ("LONG" if a_signal in ("Buy", "Overweight")
                else "SHORT" if a_signal in ("Sell", "Underweight") else None)
        return f"CONDITIONAL_{side}" if side else "CONDITIONAL", \
            f"reanalyze, signal {a_signal}"
    if cls in ("REJECT", "NO_WATCH"):
        return "NO_TRADE", f"cls={cls}"
    return ("CONFLICTED" if (i.get("ambiguities") or i.get("ambiguity"))
            else "UNKNOWN"), f"cls={cls} signal={a_signal}"


def contract_terms(i):
    ea = i.get("economic_authority") or {}
    z = ((ea.get("entry") or {}).get("zone"))
    p = i.get("params") or {}
    zone = None
    for k in ("zone", "zone1", "reentry_zone", "entry_zone", "pb_zone"):
        if isinstance(p.get(k), list) and len(p[k]) == 2:
            zone = [float(p[k][0]), float(p[k][1])]; break
    if z and isinstance(z, list) and len(z) == 2:
        zone = [float(z[0]), float(z[1])]
    stop = ea.get("stop", {}).get("level") or i.get("stop_level")
    tgt = (ea.get("objective") or {}).get("target") or i.get("target")
    return zone, stop, tgt


def main():
    rows = []
    tickers = set()
    docs = {}
    for s in SESSIONS:
        f = EV / f"publication_intents_{s}.json"
        pool = EV / f"candidate_pool_frozen_{s}.json"
        if not f.exists():
            continue
        d = json.loads(f.read_text())
        docs[s] = d
        rk = {}
        if pool.exists():
            c = json.loads(pool.read_text()).get("candidates") or []
            c = sorted(c, key=lambda x: (-x.get("deep_score", 0), x["ticker"]))
            rk = {x["ticker"]: i + 1 for i, x in enumerate(c)}
        for t, disp in (d.get("dispositions") or {}).items():
            i = d["intents"].get(t) or {}
            a = {}
            af = EV / "case_artifacts" / f"{t}_{s}.json"
            if af.exists():
                a = json.loads(af.read_text())
            dr, ev = direction(i, a.get("signal"))
            zone, stop, tgt = contract_terms(i)
            rows.append({"session": s, "ticker": t, "rank": rk.get(t),
                         "direction": dr, "dir_evidence": ev,
                         "signal": a.get("signal"),
                         "disposition": disp["disposition"],
                         "violations": disp.get("violations") or [],
                         "zone": zone, "stop": stop, "target": tgt,
                         "cls": i.get("classification")})
            tickers.add(t)
    px = {}
    for t in sorted(tickers):
        df = yf.download(t, start="2026-10-28", end=LAST, progress=False,
                         auto_adjust=True)
        px[t] = df
    ledger = Path("/home/udi/udi_provate/TradingAgents/alpha_rnd/"
                  "trigger_events.jsonl").read_text()
    for r in rows:
        df = px.get(r["ticker"])
        s = r["session"]
        if df is None or df.empty:
            r["miss"] = "INDETERMINATE"; r["note"] = "no price data"
            continue
        if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
            df = df.xs(r["ticker"], axis=1, level=1, drop_level=True)
        sub = df[df.index >= s]
        if sub.empty:
            r["miss"] = "INDETERMINATE"; r["note"] = "no data at/after session"
            continue
        ref = float(sub["Close"].iloc[0])
        latest = float(sub["Close"].iloc[-1])
        after = sub.iloc[1:] if len(sub) > 1 else sub
        hi, lo = float(after["High"].max()), float(after["Low"].min())
        r["ref_px"], r["latest_px"] = round(ref, 2), round(latest, 2)
        r["ret_pct"] = round(100 * (latest / ref - 1), 2)
        r["mfe_pct"] = round(100 * (hi / ref - 1), 2)
        r["mae_pct"] = round(100 * (lo / ref - 1), 2)
        # zone touch / path
        z = r["zone"]
        r["zone_touched"] = bool(z and (after["Low"].min() <= z[1]
                                        and after["High"].max() >= z[0]))
        dr = r["direction"]
        fav = r["mfe_pct"] if "SHORT" not in dr else round(-r["mae_pct"], 2)
        r["fav_pct"] = fav
        filled = (f'paper_entry:{r["ticker"]}:{s}' in ledger or
                  any(f'"ticker": "{r["ticker"]}"' in ln and
                      '"action": "PAPER_ENTRY"' in ln
                      for ln in ledger.splitlines()))
        r["traded"] = filled
        if filled:
            r["miss"] = "TRADED"
        elif r["disposition"] == "EXECUTABLE_WATCH":
            r["miss"] = "MISSED_EXECUTION" if r["zone_touched"] else \
                "CONDITIONAL_NOT_TRIGGERED"
        elif dr in ("LONG", "SHORT") and fav > 3:
            r["miss"] = "POTENTIAL_AUTHORING_MISS"
        elif dr.startswith("CONDITIONAL"):
            r["miss"] = "CONDITIONAL_NOT_TRIGGERED" if fav <= 3 else \
                ("CORRECTLY_BLOCKED" if r["signal"] in ("Sell", "Underweight")
                 else "POTENTIAL_AUTHORING_MISS")
        elif r["disposition"] == "AMBIGUOUS_REJECTED":
            r["miss"] = "CORRECTLY_BLOCKED" if fav <= 3 else \
                ("POTENTIAL_AUTHORING_MISS" if r["signal"]
                 in ("Buy", "Overweight", "Sell", "Underweight")
                 else "NO_PRIOR_SIGNAL")
        else:
            r["miss"] = "NO_PRIOR_SIGNAL"
    OUT.mkdir(exist_ok=True)
    (OUT / "missed_opportunity_audit.json").write_text(
        json.dumps(rows, indent=1))
    from collections import Counter
    print(Counter(r["miss"] for r in rows))
    for r in sorted(rows, key=lambda x: -x.get("fav_pct") or 0):
        print(f"{r['session']} r{r['rank']} {r['ticker']:5s} {r['direction'][:14]:14s}"
              f" {r['disposition'][:22]:22s} ref={r.get('ref_px')} "
              f"ret={r.get('ret_pct')}% fav={r.get('fav_pct')}% "
              f"zone={r.get('zone_touched')} -> {r['miss']}")


if __name__ == "__main__":
    main()
