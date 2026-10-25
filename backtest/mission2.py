#!/usr/bin/env python3
"""Mission experiments A/B/C on cached 1,824-ticker PIT universe.
A: LONG horizon discipline (60-session vs 20-session cap).
B: corrected-timing SHORT on full eligible universe.
C: quota economics — mechanical retest on deep-rank 1-10 vs 11-28 pools.
"""
import json, pickle, sys, collections
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import mechanics_multiyear as mm
from portfolio_sim import portfolio_run
from universe_pt import elig_mask

bars_all = pickle.load(open(Path(__file__).parent/'results/eligible_bars.pkl','rb'))
tickers = sorted(t for t in bars_all if t != 'SPY')
spy = bars_all['SPY'].dropna()
sc = {str(x.date()): float(r) for x,r in spy['Close'].items()}
sm = {str(x.date()): float(r) for x,r in spy['Close'].rolling(20).mean().items()}

def cands(dates, direction, cap=None, elig=True, pool=None):
    out=[]
    ts = pool or tickers
    for t in ts:
        df = bars_all.get(t)
        if df is None or len(df)<70: continue
        old = mm.MAX_HOLD
        if cap: mm.MAX_HOLD = cap
        try:
            for tr in mm.sim_period(df, sc, sm, dates, direction, 'ORIG',
                                    elig=elig_mask(df) if elig else None):
                tr['ticker']=t; tr['direction']=direction; out.append(tr)
        finally: mm.MAX_HOLD = old
    return out

res={}
# A: horizon variants
for cap in (60,20):
    for period,dates in mm.PERIODS.items():
        r=portfolio_run(cands(dates,'LONG',cap),bars_all,*dates)
        res[f'A_hold{cap}_{period}']=r
        print('A',cap,period,'n',r['admitted'],'nav%',r['net_pct'],'pf',r['pf'])
# B: shorts full universe
for period,dates in mm.PERIODS.items():
    r=portfolio_run(cands(dates,'SHORT'),bars_all,*dates)
    res[f'B_short_{period}']=r
    print('B',period,'n',r['admitted'],'nav%',r['net_pct'],'pf',r['pf'],'pnl',r['net_pnl'])
# C: quota — frozen pool sessions in Oct, deep-rank split
EV=Path('/home/udi/udi_provate/TradingAgents/evaluations/alpha_rnd_v1')
def score(c):
    labs=set(c.get('labels') or [])
    return 10*len(labs)+2*min(max(c.get('rs_60') or 0,0),2)+(1 if 'CATALYST' in labs else 0)
top10, rest = set(), set()
for f in sorted(EV.glob('candidate_pool_frozen_*.json')):
    d=json.loads(f.read_text())
    cs=sorted(d.get('candidates',[]),key=lambda x:(-score(x),x['ticker']))
    for i,c in enumerate(cs): (top10 if i<10 else rest).add(c['ticker'])
dates=('2026-10-01','2026-10-23')
for name,pool in (('C_top10',top10),('C_rest',rest),('C_all',top10|rest)):
    r=portfolio_run(cands(dates,'LONG',elig=False,pool=pool),bars_all,*dates)
    res[name]=r
    print(name,'pool',len(pool),'admit',r['admitted'],'pnl',r['net_pnl'],'pf',r['pf'])
json.dump(res,open(Path(__file__).parent/'results/mission2.json','w'),indent=1)
