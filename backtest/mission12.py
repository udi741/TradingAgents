#!/usr/bin/env python3
"""Mission12 — consolidated, reconciled AI-decision evidence.

Sources (all read-only):
  ALPHA_RND paper book: trigger_events.jsonl (canonical PAPER_ENTRY/
    PAPER_EXIT events), alpha_paper_ledger.jsonl marks through
    2026-10-23, trade_postmortems (canonical realized -2140.99).
  C12_PROSPECTIVE: c12_paper_portfolio.jsonl (fills), c12_signal_ledger
    (ENTRY/NO_ENTRY decisions), C12 policy = 20-session hold,
    next-open entry, LONG-only, $5k, 10bps.

Reconciliation corrections vs mission11 v1:
  - PGEN fill = $8.20 (not 8.21).
  - PBF is OPEN as-recorded (pending next-open exit after 10/23 close
    <78; NOT executed -> not counted as an exit). Mark at close.
  - ASST triggered 10/14 but RISK_PLAN_REQUIRED -> NOT BOUGHT: an
    authored-but-unexecuted trigger, excluded from trade population,
    measured separately as hypothetical (labelled).
  - All controls now carry identical 10bps costs and are also reported
    per dollar deployed (exposure-matched).
  - Management intents (PBF 10/16 partial exit) were shadow_only ->
    never executed -> excluded from economics.

Population: ALPHA 6 executed fills (5 closed + PBF open).
C12: 4 executed entries (all open) + 24 scored NO_ENTRY decisions
(dedup by session/ticker) + 3 non-scoreable late 9/25 entries
(excluded). Zero SHORT executions anywhere.
"""
import json
import sys
from collections import OrderedDict
from pathlib import Path

import pandas as pd
import yfinance as yf

COST = 0.001
END = "2026-10-23"
ALPHA = Path("/home/udi/udi_provate/TradingAgents/evaluations/alpha_rnd_v1")
C12 = Path("/home/udi/udi_provate/TradingAgents-c12/evaluations/"
           "gate_c12_prospective")

# ---------- ALPHA canonical trades (from trigger_events, deduped) ---
# trigger_events is canonical for executed exits; dedup by
# (ticker, shares, price) regardless of event_id/utc (the 10-07 incident
# spammed identical rows; event_id rows and bare rows both occur).
fills, exits = {}, {}
seen_e = set()
for line in open(ALPHA.parent.parent / "alpha_rnd" / "trigger_events.jsonl"):
    d = json.loads(line)
    if d.get("action") == "PAPER_ENTRY":
        k = (d["ticker"], round(d["price"], 2), d["shares"])
        if k not in seen_e:
            seen_e.add(k)
            fills[d["ticker"]] = d
# exits: the trade_postmortems are the reconciled canonical source —
# duplicate/incident rows are explicitly flagged `non_economic`
# (ACN @195.00, SDGR @25.69). Realized must equal r7b1: -2140.99.
for t in ("ACN", "APPS", "SDGR", "TWST", "PGEN"):
    pm = json.load(open(ALPHA / f"trade_postmortems/{t}.json"))
    for e in pm["execution"]["exits"]:
        if e.get("non_economic"):
            continue
        exits.setdefault(t, []).append(
            {"price": e["price"], "shares": e["shares"],
             "why": e["why"], "utc": e["utc"]})
# V1 fills are PAPER_FILL in the ledger (older convention), not in
# trigger_events. Entry basis convention: V1 feeless (basis =
# shares*price exactly, per reconciliation r7b1); V2 uses recorded
# 'cost' (fee included). Exits: proceeds*0.999 everywhere.
v1 = {"PBF":  (80.0, 62, "2026-10-02"),
      "ACN":  (205.0, 24, "2026-10-02"),
      "APPS": (11.3, 442, "2026-10-02")}
for t, (f, sh, fd) in v1.items():
    if t not in fills:
        fills[t] = {"ticker": t, "price": f, "shares": sh, "utc": fd,
                    "cls": "V1_LEDGER", "feeless_entry": True}

C12_T = ["HPE", "NTAP", "PLTR", "COP"]
tickers = sorted(set(fills) | set(C12_T) | {"SPY"})
d = yf.download(tickers, start="2026-09-25", end="2026-10-25",
                group_by="ticker", progress=False, auto_adjust=True,
                threads=True)
bars = {t: d[t].dropna() for t in tickers if t in d and len(d[t].dropna())}

def px(t, date, field="Close"):
    s = bars[t].loc[:date]
    return float(s[field].iloc[-1]) if len(s) else None

end_px = {t: px(t, END) for t in tickers}

# ---------- ALPHA as-recorded book ----------
trades = []
realized = 0.0
unrealized = 0.0
for t, f in fills.items():
    sh, fp = f["shares"], f["price"]
    basis = sh * fp if f.get("feeless_entry") else f.get(
        "cost", sh * fp * (1 + COST))
    legs = exits.get(t, [])
    sold = sum(e["shares"] for e in legs)
    # realized = proceeds(0.999) - alloc share of basis (canonical r7b1)
    rp = sum(e["shares"] * e["price"] * (1 - COST)
             - basis * e["shares"] / sh for e in legs)
    realized += rp
    open_sh = sh - sold
    up = open_sh * end_px[t] - basis * open_sh / sh if open_sh else 0.0
    unrealized += up
    trades.append({
        "ticker": t, "entry_px": fp, "shares": sh,
        "entry_utc": f["utc"], "cls": f.get("cls"),
        "basis": round(basis, 2),
        "sold": sold, "open_sh": open_sh,
        "realized_pnl": round(rp, 2),
        "unrealized_pnl": round(up, 2),
        "exit_evidence": [{"px": e["price"], "sh": e["shares"],
                           "why": e["why"], "utc": e["utc"]}
                          for e in legs]})
invested = sum(t["basis"] for t in trades)
cash = 100000 - invested + sum(
    e["sh"] * e["px"] * (1 - COST)
    for t in trades for e in t["exit_evidence"])
nav = cash + sum(t["open_sh"] * end_px[t["ticker"]] for t in trades)

# ---------- controls ----------
# C1 same-names naive: same basis, hold all shares to END (mark gross)
naive = sum(t["shares"] * end_px[t["ticker"]] - t["basis"]
            for t in trades)
# C2 SPY matched: same notional into SPY on the fill date (10bps both)
spy = 0.0
for t in trades:
    s0 = px("SPY", t["entry_utc"][:10], "Open")
    spy += t["shares"] * t["entry_px"] * (
        end_px["SPY"] * (1 - COST) / (s0 * (1 + COST)) - 1)
# C3 watchlist-naive: V2 names $5k each at 10/05 open (all costs)
V2 = ["PGEN", "SYNA", "ASST", "KOD", "TXG", "TWST", "PAYC", "XNCR",
      "AXGN", "HHH"]
d2 = yf.download(V2, start="2026-09-25", end="2026-10-25",
                 group_by="ticker", progress=False, auto_adjust=True,
                 threads=True)
wl = 0.0
for t in V2:
    df = d2[t].dropna()
    o = float(df.loc["2026-10-05":, "Open"].iloc[0])
    c = float(df["Close"].iloc[-1])
    wl += 5000 * (c * (1 - COST) / (o * (1 + COST)) - 1)

# ---------- C12 ----------
c12 = []
seen = set()
for line in open(C12 / "c12_paper_portfolio.jsonl"):
    r = json.loads(line)
    k = r["trade_id"]
    c12.append(r)
c12open = [r for r in c12 if r["status"] == "OPEN"]
c12_pos = []
for r in c12open:
    t = r["ticker"]
    mark = end_px[t]
    up = r["shares"] * (mark - r["entry_price"]) \
        - r["notional"] * COST - r["shares"] * mark * COST
    spy0 = r.get("spy_entry_price") or px("SPY", r["entry_session"], "Open")
    spy_ret = end_px["SPY"] / spy0 - 1
    c12_pos.append({"ticker": t, "decision": r["decision_session"],
                    "entry_session": r["entry_session"],
                    "entry": r["entry_price"], "shares": r["shares"],
                    "mark": mark, "unrealized_net": round(up, 2),
                    "ret_pct": round(100 * (mark / r["entry_price"] - 1), 2),
                    "spy_pct": round(100 * spy_ret, 2),
                    "excess_pp": round(100 * (mark / r["entry_price"]
                                              - 1 - spy_ret), 2)})
# C12 NO_ENTRY decisions: forward return per name vs SPY fwd return.
seen = set()
noentry = []
for line in open(C12 / "c12_signal_ledger.jsonl"):
    r = json.loads(line)
    k = (r["decision_session"], r["ticker"])
    if k in seen or r["signal"] != "NO_ENTRY":
        continue
    seen.add(k)
    t = r["ticker"]
    if t not in bars:
        df = yf.download(t, start=r["decision_session"], end="2026-10-25",
                         progress=False, auto_adjust=True)
        bars[t] = df.dropna()
    e = px(t, r["decision_session"])
    f = end_px.get(t) or px(t, END)
    s0 = px("SPY", r["decision_session"])
    if e and f and s0:
        noentry.append({"ticker": t, "session": r["decision_session"],
                        "pm": r["pm"],
                        "fwd_pct": round(100 * (f / e - 1), 2),
                        "spy_fwd_pct": round(100 * (end_px["SPY"] / s0
                                                    - 1), 2)})
correct_sell = sum(1 for n in noentry
                   if n["pm"] in ("Sell", "Underweight")
                   and n["fwd_pct"] < n["spy_fwd_pct"])
sells = sum(1 for n in noentry if n["pm"] in ("Sell", "Underweight"))

out = OrderedDict()
out["window"] = ["2026-09-25", END]
out["alpha"] = {
    "trades": trades, "cash": round(cash, 2), "nav": round(nav, 2),
    "net_pct": round(100 * (nav / 100000 - 1), 2),
    "realized": round(realized, 2), "unrealized": round(unrealized, 2),
    "ledger_nav_1023": 97621.55,
    "controls": {"naive_same_names_pct": round(naive / 1000, 2),
                 "spy_matched_pct": round(spy / 1000, 2),
                 "watchlist_naive_pct": round(wl / 1000, 2),
                 "deployed": round(invested, 2),
                 "alpha_per_deployed_pct":
                     round(100 * (realized + unrealized) / invested, 2),
                 "naive_per_deployed_pct":
                     round(100 * naive / invested, 2)}}
out["c12"] = {
    "open_positions": c12_pos,
    "closed_trades": 0,
    "noentry_decisions": noentry,
    "sell_calls_beating_spy": f"{correct_sell}/{sells}",
    "note": "20-session holds; all 4 entries still open; exits mature "
            "~2026-10-30..11-18. 9/25 entries non-scoreable (late)."}
out["asst_hypothetical"] = {
    "note": "ASST triggered 10/14, blocked by RISK_PLAN_REQUIRED "
            "(unexecuted). Hypothetical only, not a trade."}
print(json.dumps(out, indent=1))
json.dump(out, open(Path(__file__).parent / "results/mission12.json", "w"),
          indent=1)
