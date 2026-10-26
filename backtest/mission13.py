#!/usr/bin/env python3
"""Mission13 — investment-SELECTION research on saved decision-time data.

Population (all retrospective, timestamped, no re-inference):
  ALPHA production case_artifacts (10/session, 10/01-10/23)
  R5B replays ANALYZE_ALL_CANDIDATES (~28/session, 10/07,09,12) —
    dedup vs production artifact for same (ticker, session)
  C12 weekly decisions (5 cycles, rm/trader/pm + lane_a_rank)

Features (decision-time only):
  pm_rating, trader_action, rm_rating, consensus
  pool labels (FUNDAMENTAL_ACCELERATION, MOMENTUM, RS, CATALYST,
    PULLBACK, MULTI_SIGNAL), rsi_14, ret_20, rs_60, vol_ratio, catalyst_events
  fundamental_facts (PIT via last_filed): revenue/net_income yoy signs

Outcomes: next-regular-open entry, H1/H5 fwd return, SPY excess,
  MFE/MAE — same semantics as cohort_outcomes. H5 mature <=10/16.

Pre-registered selection rules (chosen on economic reasoning BEFORE
scoring; losers TWST/SDGR/APPS/PGEN were pre-profit story names with
dissent or binaries — that observation motivates direction, thresholds
are NOT fitted):
  R_FUND   = long entry only if net_income.yoy_last_q > 0 AND
             revenue.yoy_last_q > 0 (positive, growing earnings)
  R_CONS   = entry only if pm in {Buy,Overweight} AND trader in
             {Buy,Overweight} AND rm not in {Sell,Underweight}
  R_ACCEL  = entry only if FUNDAMENTAL_ACCELERATION label present
  BASELINE = all pm in {Buy,Overweight} signals (production behavior)
Each scored as equal-weight $5k next-open entries, H5 close exit,
10bps/side, on the ALPHA artifact population (C12 scored separately
under its own 20-session convention for entries only).

SHORT evaluation: Sell/Underweight-rated cohorts' H5 excess — a Sell
call only has short value if mean excess < 0; no entry-equivalence.

Coverage question: outcomes by pool tier (deep_selected top-10 vs
RANK_11_28) + marginal deep-run cost (mean duration_s x added runs).
"""
import json
import sys
from pathlib import Path

import pandas as pd
import yfinance as yf

A = Path("/home/udi/udi_provate/TradingAgents/evaluations/alpha_rnd_v1")
C12 = Path("/home/udi/udi_provate/TradingAgents-c12/evaluations/"
           "gate_c12_prospective")
OUT = Path(__file__).parent / "results"

BULL = {"Buy", "Overweight"}
BEAR = {"Sell", "Underweight"}

# ---------- 1. assemble decision records ----------
recs = []
seen = set()
for p in sorted((A / "case_artifacts").glob("*_2*.json")):
    if ".error." in p.name:
        continue
    a = json.loads(p.read_text())
    t, s = a["ticker"], a["decision_session"]
    if (t, s) in seen:
        continue
    seen.add((t, s))
    recs.append({"src": "ALPHA", "session": s, "ticker": t,
                 "pm": a.get("pm_rating"), "trader": a.get("trader_action"),
                 "rm": a.get("rm_rating"), "signal": a.get("signal"),
                 "duration_s": a.get("duration_s"),
                 "deep_selected": True})
for sdir in sorted((A / "replays").glob("2026-*")):
    s = sdir.name
    adir = sdir / "ANALYZE_ALL_CANDIDATES" / "case_artifacts"
    if not adir.exists():
        continue
    for p in sorted(adir.glob("*.json")):
        a = json.loads(p.read_text())
        t = a["ticker"]
        if (t, s) in seen:
            continue
        seen.add((t, s))
        recs.append({"src": "R5B", "session": s, "ticker": t,
                     "pm": a.get("pm_rating"), "trader": a.get("trader_action"),
                     "rm": a.get("rm_rating"), "signal": a.get("signal"),
                     "duration_s": a.get("duration_s"),
                     "deep_selected": t in (json.loads((A / "case_artifacts" /
                        f"{t}_{s}.json")).read_text()
                        if (A / "case_artifacts" / f"{t}_{s}.json").exists()
                        else {}) or p.stem.rsplit("_", 1)[0] in set()})
for p in sorted((C12 / "decisions").glob("c12_decisions_*.json")):
    d = json.loads(p.read_text())
    for t, dec in d["decisions"].items():
        recs.append({"src": "C12", "session": d["decision_session"],
                     "ticker": t, "pm": dec.get("pm"),
                     "trader": dec.get("trader"), "rm": dec.get("rm"),
                     "signal": None, "duration_s": None,
                     "deep_selected": dec.get("entry")})
print("records:", len(recs))

# ---------- 2. enrich: pool labels + fundamentals ----------
pools = {}
for p in sorted(A.glob("candidate_pool_frozen_2026-*.json")):
    d = json.loads(p.read_text())
    pools[d["session"]] = {c["ticker"]: c
                           for c in d.get("candidates", [])}
ffacts = {}
for p in sorted(A.glob("fundamental_facts_2026-*.json")):
    ffacts[p.stem.split("_")[-1]] = json.loads(p.read_text())
ff_sessions = sorted(ffacts)

def ff_for(s):
    elig = [x for x in ff_sessions if x <= s]
    return ffacts[elig[-1]] if elig else {}

def yoy(rec, k):
    f = (rec.get("facts") or {}).get(k)
    return (f or {}).get("yoy_last_q")

for r in recs:
    c = pools.get(r["session"], {}).get(r["ticker"]) or {}
    r["labels"] = c.get("labels") or []
    r["rsi_14"] = c.get("rsi_14")
    r["ret_20"] = c.get("ret_20")
    r["rs_60"] = c.get("rs_60")
    r["catalyst_events"] = len(c.get("catalyst_events") or [])
    r["accel_flags"] = len(c.get("acceleration_flags") or [])
    f = ff_for(r["session"]).get(r["ticker"]) or {}
    r["rev_yoy"] = yoy(f, "revenue")
    r["ni_yoy"] = yoy(f, "net_income")
    r["ocf_yoy"] = yoy(f, "ocf")
    r["fund_support"] = (r["ni_yoy"] is not None and r["ni_yoy"] > 0
                         and r["rev_yoy"] is not None and r["rev_yoy"] > 0)
    r["consensus"] = (r["pm"] in BULL and r["trader"] in BULL
                      and r["rm"] not in BEAR)
    r["accel_label"] = "FUNDAMENTAL_ACCELERATION" in r["labels"]

# ---------- 3. outcomes ----------
tickers = sorted({r["ticker"] for r in recs} | {"SPY"})
d = yf.download(tickers, start="2026-09-25", end="2026-10-25",
                group_by="ticker", progress=False, auto_adjust=True,
                threads=True)
bars = {t: d[t].dropna() for t in tickers if t in d.columns.get_level_values(0)}
spy = bars["SPY"]
cal = [str(x.date()) for x in spy.index]

def outcome(t, session):
    """entry = first session AFTER decision session; H1/H5 closes."""
    aft = [x for x in cal if x > session]
    if not aft:
        return {}
    ent = aft[0]
    df = bars.get(t)
    if df is None:
        return {}
    di = {str(x.date()): i for i, x in enumerate(df.index)}
    if ent not in di:
        return {}
    i = di[ent]
    eo = float(df["Open"].iloc[i])
    so = float(spy["Open"].iloc[list(spy.index.date).index(
        pd.Timestamp(ent).date())])
    out = {"entry": ent, "entry_open": eo}
    for h, n in (("H1", 0), ("H5", 4), ("H20", 19)):
        j = i + n
        if j >= len(df.index):
            out[h] = None
            continue
        tc = float(df["Close"].iloc[j])
        ts = str(df.index[j].date())
        sj = list(spy.index.date).index(pd.Timestamp(ts).date())
        sc = float(spy["Close"].iloc[sj])
        out[h] = {"ret": round(100 * (tc / eo - 1), 2),
                  "excess": round(100 * (tc / eo - sc / so), 2),
                  "t": ts}
    hi = float(df["High"].iloc[i:i + 20].max())
    lo = float(df["Low"].iloc[i:i + 20].min())
    out["MFE"] = round(100 * (hi / eo - 1), 2)
    out["MAE"] = round(100 * (lo / eo - 1), 2)
    return out

for r in recs:
    r.update(outcome(r["ticker"], r["session"]))

json.dump(recs, open(OUT / "mission13_dataset.json", "w"), indent=1)

# ---------- 4. analyses ----------
def agg(rs, h="H5"):
    xs = [r[h]["excess"] for r in rs if r.get(h)]
    rr = [r[h]["ret"] for r in rs if r.get(h)]
    if not xs:
        return {"n": 0}
    xs2 = sorted(xs)
    return {"n": len(xs), "mean_excess": round(sum(xs) / len(xs), 2),
            "median_excess": xs2[len(xs2) // 2],
            "mean_ret": round(sum(rr) / len(rr), 2),
            "hit_rate_excess_pos": round(sum(1 for x in xs if x > 0)
                                         / len(xs), 2)}

res = {"n_records": len(recs)}
for src in ("ALPHA", "R5B", "C12"):
    sub = [r for r in recs if r["src"] == src]
    res[f"n_{src}"] = len(sub)
    res[f"rating_outcomes_{src}"] = {
        rt: agg([r for r in sub if r["pm"] == rt])
        for rt in ("Buy", "Overweight", "Hold", "Underweight", "Sell")}

al = [r for r in recs if r["src"] in ("ALPHA", "R5B")]
res["groups_ALPHA_R5B"] = {
    "fund_support": agg([r for r in al if r["fund_support"]]),
    "no_fund_support": agg([r for r in al if not r["fund_support"]]),
    "accel_label": agg([r for r in al if r["accel_label"]]),
    "no_accel_label": agg([r for r in al if not r["accel_label"]]),
    "consensus": agg([r for r in al if r["consensus"]]),
    "no_consensus": agg([r for r in al if not r["consensus"]]),
    "rsi>=70": agg([r for r in al if (r["rsi_14"] or 0) >= 70]),
    "rsi<70": agg([r for r in al if r["rsi_14"] is not None
                   and r["rsi_14"] < 70]),
}

# pre-registered rules, ALPHA+R5B population only (has labels/facts)
bull = [r for r in al if r["pm"] in BULL]
res["rules"] = {
    "BASELINE_all_bull": agg(bull),
    "R_FUND": agg([r for r in bull if r["fund_support"]]),
    "R_CONS": agg([r for r in bull if r["consensus"]]),
    "R_ACCEL": agg([r for r in bull if r["accel_label"]]),
    "R_FUND+CONS": agg([r for r in bull if r["fund_support"]
                        and r["consensus"]]),
}
res["rules"]["BASELINE_all_bull"]["tickers"] = [
    f'{r["ticker"]}@{r["session"]}' for r in bull]

# SHORT evaluation: Sell/Underweight-rated cohorts (separate, no
# entry-equivalence — these measure whether bearish ratings find
# underperformance, not that a short trade would have been authorized)
res["short_cohorts"] = {
    "ALPHA_R5B_sell_or_below": agg(
        [r for r in al if r["pm"] in BEAR or r["pm"] == "Hold"]),
    "C12_sell_underweight": agg(
        [r for r in recs if r["src"] == "C12" and r["pm"] in BEAR]),
}

# coverage/cost: per R5B session, deep_selected(production 10) vs rest
cov = {}
for sdir in sorted((A / "replays").glob("2026-*")):
    s = sdir.name
    pool = pools.get(s, {})
    order = list(pool)
    sel = {r["ticker"] for r in recs
           if r["src"] == "ALPHA" and r["session"] == s}
    top = [r for r in recs if r["session"] == s and r["ticker"] in sel]
    rest = [r for r in recs
            if r["session"] == s and r["src"] == "R5B"
            and r["ticker"] not in sel]
    cov[s] = {"top10_deep": agg(top), "ranks_11_28": agg(rest),
              "rest_rated_bull": sum(1 for r in rest if r["pm"] in BULL)}
res["coverage_by_session"] = cov
res["cost"] = {
    "mean_duration_s": round(
        sum(r["duration_s"] for r in recs if r["duration_s"])
        / max(1, sum(1 for r in recs if r["duration_s"])), 1),
    "deep_runs_total": sum(1 for r in recs if r["duration_s"])}

json.dump(res, open(OUT / "mission13.json", "w"), indent=1)
print(json.dumps(res, indent=1))
