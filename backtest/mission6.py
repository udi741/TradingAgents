#!/usr/bin/env python3
"""Improved historical evaluation: approximated PIT-ish S&P500 universe.

Source: free S&P500 constituent list (incl. 'Date added'). Membership
rule: ticker eligible on dates >= its date_added. KNOWN LIMITATIONS:
- index REMOVALS not captured: a removed member stays eligible until
  today (survivorship remains for removed names — direction is usually
  to overstate LONG results mildly).
- not an index-membership strategy proof; it's a tradability filter.

Run ORIG mechanical LONG + SHORT on this universe for the three periods.
"""
import io, json, urllib.request, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import pandas as pd, yfinance as yf
import mechanics_multiyear as mm
from portfolio_sim import portfolio_run

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
spy = bars['SPY']
sc = {str(x.date()): float(r) for x, r in spy['Close'].items()}
sm = {str(x.date()): float(r) for x, r in spy['Close'].rolling(20).mean().items()}

res = {}
for period, dates in mm.PERIODS.items():
    for direction in ('LONG', 'SHORT'):
        cand = []
        for t_ in tickers:
            df = bars.get(t_)
            if df is None:
                continue
            eligible = pd.Series(
                df.index.date.astype(str) >= addmap[t_],
                index=df.index)
            for tr in mm.sim_period(df, sc, sm, dates, direction, 'ORIG',
                                    elig=eligible):
                tr['ticker'] = t_; tr['direction'] = direction; cand.append(tr)
        r = portfolio_run(cand, bars, *dates)
        res[f'{direction}_{period}'] = r
        print(direction, period, 'sig', r['signals'], 'adm', r['admitted'],
              'nav%', r['net_pct'], 'pf', r['pf'], 'pnl', r['net_pnl'],
              'dd', r['max_dd'])
json.dump(res, open(Path(__file__).parent/'results/mission6.json','w'),
          indent=1)
