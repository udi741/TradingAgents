#!/usr/bin/env python3
"""Mission7 — H3 cross-universe validation.

Pre-registered hypothesis (frozen before run):
  H3 (2.5*ATR stop) beat ORIG (2.0*ATR) on the 1824-name survivor-biased
  universe (exp6/7, all 3 periods) but was seed-fragile in 2025. If that
  edge is real and not a universe artifact, ATR25 should also beat ORIG
  on the mission6 universe (S&P500 snapshot + date-added gate, ~503
  names — added-later bias removed, removed-member bias remains).

Design: LONG only (short rule already rejected on both universes).
3 periods x {ORIG 2.0, ATR25 2.5} x order {alphabetical + seeds 1,7,13,42}
at 10bps costs, portfolio-constrained (portfolio_run defaults).

Decision rule (frozen): RETAIN-VALIDATED iff ATR25 net_pct > ORIG net_pct
in all 3 periods on alphabetical ordering AND ATR25 seed-min > ORIG
seed-min in >=2 of 3 periods. Else REJECT-H3.
"""
import io
import json
import pickle
import sys
import urllib.request
from pathlib import Path

import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).parent))
import mechanics_multiyear as mm
import portfolio_sim as ps
from portfolio_sim import portfolio_run

ARC = Path.home() / "udi_provate/research-results-archive"
BARS_PKL = ARC / "sp500_snapshot_bars.pkl"
ADDMAP = ARC / "sp500_snapshot_addmap.json"
SEEDS = (None, 1, 7, 13, 42)

if BARS_PKL.exists() and ADDMAP.exists():
    bars = pickle.load(open(BARS_PKL, "rb"))
    addmap = json.loads(ADDMAP.read_text())
    print("cached bars:", len(bars))
else:
    req = urllib.request.Request(
        'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies',
        headers={'User-Agent': 'research/1.0'})
    html = urllib.request.urlopen(req, timeout=30).read().decode()
    t = pd.read_html(io.StringIO(html))[0]
    t['added'] = pd.to_datetime(t['Date added'], errors='coerce')
    members = t[['Symbol', 'added']].dropna()
    members['Symbol'] = members['Symbol'].str.replace('.', '-', regex=False)
    print('members', len(members))
    tickers = members['Symbol'].tolist()
    d = yf.download(tickers + ['SPY'], start='2023-01-01', end='2026-10-24',
                    group_by='ticker', progress=False, auto_adjust=True,
                    threads=True)
    bars = {}
    for s_ in tickers + ['SPY']:
        try:
            df = d[s_].dropna()
            if len(df) > 70:
                bars[s_] = df
        except Exception:
            pass
    print('priced', len(bars))
    addmap = dict(zip(members['Symbol'], members['added'].dt.date.astype(str)))
    pickle.dump(bars, open(BARS_PKL, "wb"))
    ADDMAP.write_text(json.dumps(addmap))

spy = bars['SPY']
sc = {str(x.date()): float(r) for x, r in spy['Close'].items()}
sm = {str(x.date()): float(r) for x, r in spy['Close'].rolling(20).mean().items()}
tickers = sorted(t for t in bars if t != 'SPY' and t in addmap)

ps.COST = 0.001
cands_cache = {}
def cands(dates, mult):
    key = (dates, mult)
    if key not in cands_cache:
        out = []
        for t_ in tickers:
            df = bars[t_]
            elig = pd.Series(
                [str(x.date()) >= addmap[t_] for x in df.index],
                index=df.index)
            for tr in mm.sim_period(df, sc, sm, dates, 'LONG', 'ORIG',
                                    elig=elig, stop_mult=mult):
                tr['ticker'] = t_
                tr['direction'] = 'LONG'
                out.append(tr)
        cands_cache[key] = out
    return cands_cache[key]

res = {}
for period, dates in mm.PERIODS.items():
    for tag, mult in (("ORIG", 2.0), ("ATR25", 2.5)):
        cand = cands(dates, mult)
        runs = [portfolio_run(cand, bars, *dates, order_seed=s)
                for s in SEEDS]
        navs = [r['net_pct'] for r in runs]
        res[f'{tag}_{period}'] = {
            'nav_pct_by_seed': dict(zip(
                [str(s) for s in SEEDS], navs)),
            'seed_min': min(navs), 'seed_max': max(navs),
            'seed_mean': round(sum(navs) / len(navs), 2),
            'signals': runs[0]['signals'], 'admitted': runs[0]['admitted'],
            'pf_alpha': runs[0]['pf'], 'max_dd_alpha': runs[0]['max_dd'],
        }
        print(tag, period, 'navs', navs, 'pf', runs[0]['pf'])

# frozen decision rule
verdict = {'all_periods_atr25_better_alpha': all(
        res[f'ATR25_{p}']['nav_pct_by_seed']['None']
        > res[f'ORIG_{p}']['nav_pct_by_seed']['None']
        for p in mm.PERIODS),
    'seed_min_wins': sum(
        res[f'ATR25_{p}']['seed_min'] > res[f'ORIG_{p}']['seed_min']
        for p in mm.PERIODS)}
res['_verdict'] = verdict
print(json.dumps(verdict, indent=1))
json.dump(res, open(Path(__file__).parent / 'results/mission7.json', 'w'),
          indent=1)
