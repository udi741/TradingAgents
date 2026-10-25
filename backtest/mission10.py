#!/usr/bin/env python3
"""Mission10 — PROFIT exit variant on the validated ATR25 stop.

Pre-registered hypothesis (frozen before run):
  All retained variants so far hold to stop-or-horizon. Test whether
  trimming 50% at first close >= +8% and trailing the rest at
  peak_close-8pp improves portfolio economics vs plain ATR25.
  Single fixed exit alternative; entry/stop identical (2.5xATR).

Design: LONG, stop_mult=2.5 both arms, cached S&P500 snapshot universe
+ date-added gate, 3 periods x {ATR25, PROFIT} x seeds {a,1,7,13,42},
10bps, portfolio-constrained.

Decision rule (frozen): RETAIN iff PROFIT seed-mean > ATR25 seed-mean
in >=2 of 3 periods AND PROFIT seed-min > ATR25 seed-min in >=2 of 3.
Else REJECT.
"""
import json
import pickle
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import mechanics_multiyear as mm
import portfolio_sim as ps
from portfolio_sim import portfolio_run

ARC = Path.home() / "udi_provate/research-results-archive"
bars = pickle.load(open(ARC / "sp500_snapshot_bars.pkl", "rb"))
addmap = json.loads((ARC / "sp500_snapshot_addmap.json").read_text())
SEEDS = (None, 1, 7, 13, 42)

spy = bars['SPY']
sc = {str(x.date()): float(r) for x, r in spy['Close'].items()}
sm = {str(x.date()): float(r) for x, r in spy['Close'].rolling(20).mean().items()}
tickers = sorted(t for t in bars if t != 'SPY' and t in addmap)

ps.COST = 0.001
cands_cache = {}
def cands(dates, variant):
    key = (dates, variant)
    if key not in cands_cache:
        out = []
        for t_ in tickers:
            df = bars[t_]
            elig = pd.Series(
                [str(x.date()) >= addmap[t_] for x in df.index],
                index=df.index)
            for tr in mm.sim_period(df, sc, sm, dates, 'LONG', variant,
                                    elig=elig, stop_mult=2.5):
                tr['ticker'] = t_
                tr['direction'] = 'LONG'
                out.append(tr)
        cands_cache[key] = out
    return cands_cache[key]

res = {}
for period, dates in mm.PERIODS.items():
    for tag, variant in (("ATR25", "ORIG"), ("PROFIT", "PROFIT")):
        cand = cands(dates, variant)
        runs = [portfolio_run(cand, bars, *dates, order_seed=s)
                for s in SEEDS]
        navs = [r['net_pct'] for r in runs]
        res[f'{tag}_{period}'] = {
            'nav_pct_by_seed': dict(zip([str(s) for s in SEEDS], navs)),
            'seed_min': min(navs), 'seed_max': max(navs),
            'seed_mean': round(sum(navs) / len(navs), 2),
            'signals': runs[0]['signals'], 'admitted': runs[0]['admitted'],
            'pf_alpha': runs[0]['pf'], 'max_dd_alpha': runs[0]['max_dd']}
        print(tag, period, 'navs', navs, 'pf', runs[0]['pf'])

verdict = {
    'mean_wins': sum(res[f'PROFIT_{p}']['seed_mean']
                     > res[f'ATR25_{p}']['seed_mean'] for p in mm.PERIODS),
    'min_wins': sum(res[f'PROFIT_{p}']['seed_min']
                    > res[f'ATR25_{p}']['seed_min'] for p in mm.PERIODS)}
res['_verdict'] = verdict
print(json.dumps(verdict, indent=1))
json.dump(res, open(Path(__file__).parent / 'results/mission10.json', 'w'),
          indent=1)
