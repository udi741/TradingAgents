#!/usr/bin/env python3
"""Mission9 — downtrend-gated SHORT retest.

Pre-registered hypothesis (frozen before run):
  Every prior short test (SHORT_ORIG, mission6 on both universes) was
  ungated and lost in all periods. Mission8 showed LONG entries against
  the stock's own trend fail. Mirror claim: SHORT entries should fail
  when the ticker is NOT already in a downtrend. Test: SHORT fill
  allowed only if ticker close < its own 200-SMA on the fill day.

Design: SHORT only. stop_mult=2.0 for BOTH arms (isolate the gate's
contribution against the already-rejected ungated baseline, not the
stop-width question). Universe: cached S&P500 snapshot + date-added
gate. 3 periods x {SHORT_ORIG, SHORT_T200} x seeds {a,1,7,13,42}, 10bps
+ 2%/yr borrow (as built into sim_period SHORT pnl).

Decision rule (frozen): RETAIN gate iff T200 seed-min > ORIG seed-min
in >=2 of 3 periods AND T200 seed-mean > ORIG seed-mean in >=2 of 3.
A positive-mean period would be notable but is NOT required for retain;
replication of improvement across regimes is.
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
            for tr in mm.sim_period(df, sc, sm, dates, 'SHORT', variant,
                                    elig=elig, stop_mult=2.0):
                tr['ticker'] = t_
                tr['direction'] = 'SHORT'
                out.append(tr)
        cands_cache[key] = out
    return cands_cache[key]

res = {}
for period, dates in mm.PERIODS.items():
    for tag, variant in (("SHORT_ORIG", "ORIG"), ("SHORT_T200", "TREND200")):
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
        print(tag, period, 'navs', navs, 'pf', runs[0]['pf'],
              'sig', runs[0]['signals'], 'adm', runs[0]['admitted'])

verdict = {
    'min_wins': sum(res[f'SHORT_T200_{p}']['seed_min']
                    > res[f'SHORT_ORIG_{p}']['seed_min']
                    for p in mm.PERIODS),
    'mean_wins': sum(res[f'SHORT_T200_{p}']['seed_mean']
                     > res[f'SHORT_ORIG_{p}']['seed_mean']
                     for p in mm.PERIODS),
    'gate_rejects': {p: res[f'SHORT_ORIG_{p}']['signals']
                     - res[f'SHORT_T200_{p}']['signals']
                     for p in mm.PERIODS}}
res['_verdict'] = verdict
print(json.dumps(verdict, indent=1))
json.dump(res, open(Path(__file__).parent / 'results/mission9.json', 'w'),
          indent=1)
