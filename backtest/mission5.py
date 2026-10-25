#!/usr/bin/env python3
"""AI-selection value test (Oct window, corrected timing).

Q: do the names TradingAgents RESEARCHED (AI research coverage) produce
better mechanical-trade outcomes than (a) the full discovered pool and
(b) random same-size subsets? Identical ORIG rules/costs/caps.
Also: AI-priority admission vs random (existing ai_priority result).
"""
import json, random, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import mechanics_multiyear as mm
from portfolio_sim import portfolio_run

EV = Path("/home/udi/udi_provate/TradingAgents/evaluations/alpha_rnd_v1")
import yfinance as yf

researched, pool_all = set(), set()
for f in sorted(EV.glob("publication_intents_*.json")):
    doc = json.loads(f.read_text())
    for t in (doc.get("intents") or {}):
        researched.add(t)
for f in sorted(EV.glob("candidate_pool_frozen_*.json")):
    for c in json.loads(f.read_text()).get("candidates", []):
        pool_all.add(c["ticker"])
R5B = Path("/home/udi/udi_provate/TradingAgents/r5b_history")
if R5B.exists():
    for f in R5B.rglob("publication.json"):
        d = json.loads(f.read_text())
        for t in (d.get("intents") or {}):
            researched.add(t)
print("researched", len(researched), "pool", len(pool_all))

tickers = sorted((researched | pool_all) | {"SPY"})
d = yf.download(tickers, start="2026-01-01", end="2026-10-24",
                group_by="ticker", progress=False, auto_adjust=True,
                threads=True)
bars = {t: d[t].dropna() for t in tickers}
spy = bars["SPY"]
sc = {str(x.date()): float(r) for x, r in spy["Close"].items()}
sm = {str(x.date()): float(r) for x, r in spy["Close"].rolling(20).mean().items()}
dates = ("2026-10-01", "2026-10-23")

def cand_for(ts):
    out = []
    for t in ts:
        df = bars.get(t)
        if df is None or len(df) < 70:
            continue
        for tr in mm.sim_period(df, sc, sm, dates, "LONG", "ORIG"):
            tr["ticker"] = t; tr["direction"] = "LONG"; out.append(tr)
    return out

res = {}
for name, uni in (("researched", researched), ("full_pool", pool_all),
                  ("union", researched | pool_all)):
    r = portfolio_run(cand_for(uni), bars, *dates)
    res[name] = r
    print(name, "universe", len(uni), "sig", r["signals"],
          "adm", r["admitted"], "pnl", r["net_pnl"], "nav%", r["net_pct"],
          "pf", r["pf"])
# random same-size subsets of pool as control
rng_results = []
full = sorted(pool_all)
for seed in (1, 7, 13, 42, 99):
    rnd = set(random.Random(seed).sample(full, min(len(researched), len(full))))
    r = portfolio_run(cand_for(rnd), bars, *dates)
    rng_results.append({"seed": seed, "net_pnl": r["net_pnl"],
                        "net_pct": r["net_pct"], "admitted": r["admitted"],
                        "pf": r["pf"]})
    print("random", seed, r["net_pnl"], r["pf"])
res["random_subsets"] = rng_results
res["universe_sizes"] = {"researched": len(researched),
                        "pool": len(pool_all)}
json.dump(res, open(Path(__file__).parent/"results/mission5.json","w"),
          indent=1)
