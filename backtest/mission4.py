#!/usr/bin/env python3
"""H3 robustness: 2.5xATR vs 2.0xATR baseline.
- 3 periods x {ORIG, ATR25} x seeds{alpha,1,7} x costs{10,15}bps
- diagnostics: winner concentration, exposure, expectancy, size decay.
"""
import json, pickle, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import mechanics_multiyear as mm
import portfolio_sim as ps
from portfolio_sim import portfolio_run
from universe_pt import elig_mask

ARC = Path.home() / "udi_provate/research-results-archive/eligible_bars.pkl"
bars_all = pickle.load(open(ARC, "rb"))
tickers = sorted(t for t in bars_all if t != "SPY")
spy = bars_all["SPY"].dropna()
sc = {str(x.date()): float(r) for x, r in spy["Close"].items()}
sm = {str(x.date()): float(r) for x, r in spy["Close"].rolling(20).mean().items()}

cands_cache = {}
def cands(dates, mult):
    key = (dates, mult)
    if key in cands_cache:
        return cands_cache[key]
    out = []
    for t in tickers:
        df = bars_all[t]
        if len(df) < 70:
            continue
        for tr in mm.sim_period(df, sc, sm, dates, "LONG", "ORIG",
                                elig=elig_mask(df), stop_mult=mult):
            tr["ticker"] = t; tr["direction"] = "LONG"; out.append(tr)
    cands_cache[key] = out
    return out

def stats_from_runs(runs):
    navs = [r["net_pct"] for r in runs]
    return {"nav_pct": navs,
            "min": min(navs), "max": max(navs),
            "mean": round(sum(navs)/len(navs),2)}

res = {}
for period, dates in mm.PERIODS.items():
    for tag, mult in (("ORIG", 2.0), ("ATR25", 2.5)):
        cand = cands(dates, mult)
        for cost in (0.001, 0.0015):
            ps.COST = cost
            seed_runs = [portfolio_run(cand, bars_all, *dates,
                                     order_seed=None)]
            for seed in (1, 7):
                seed_runs.append(portfolio_run(cand, bars_all, *dates,
                                               order_seed=seed))
            key = f"{tag}_c{int(cost*1e4)}_{period}"
            r0 = seed_runs[0]
            # winner concentration on alphabetical run
            closed = r0.get("closed") or []
            wins = sorted((t2["pnl"] for t2 in closed if t2["pnl"] > 0),
                          reverse=True)
            tot_w = sum(wins) or 1
            top3 = round(sum(wins[:3]) / tot_w * 100, 1) if wins else None
            res[key] = {
                "variant": tag, "stop_mult": mult,
                "cost_bps_side": cost * 1e4,
                "nav_pct_seeds": stats_from_runs(seed_runs),
                "alphabetical": {k: r0[k] for k in
                    ("signals","admitted","net_pct","pf","net_pnl",
                     "max_dd","expectancy","winrate","days_invested",
                     "end_nav") if k in r0},
                "top3_winners_pct_of_gains": top3,
                "n_winners": len(wins), "n_closed": len(closed)}
            print(key, res[key]["alphabetical"].get("net_pct"),
                  "seed-range", res[key]["nav_pct_seeds"])
ps.COST = 0.001
json.dump(res, open(Path(__file__).parent/"results/mission4.json","w"),
          indent=1, default=str)
