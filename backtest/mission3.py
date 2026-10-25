#!/usr/bin/env python3
"""H2: entries only when SPY close > its 20-SMA (fixed rule, no tuning).
H3: 2.5*ATR stop vs the frozen 2.0*ATR (single alternative, pre-registered).
Universe: archived eligible_bars (survivor-biased; results labeled).
"""
import json, pickle, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import mechanics_multiyear as mm
from portfolio_sim import portfolio_run
from universe_pt import elig_mask

ARC = Path.home() / "udi_provate/research-results-archive/eligible_bars.pkl"
bars_all = pickle.load(open(ARC, "rb"))
tickers = sorted(t for t in bars_all if t != "SPY")
spy = bars_all["SPY"].dropna()
sc = {str(x.date()): float(r) for x, r in spy["Close"].items()}
sm = {str(x.date()): float(r) for x, r in spy["Close"].rolling(20).mean().items()}



res = {}
for period, dates in mm.PERIODS.items():
    for tag, kw in (("H2_spygate", dict(variant="SPYGATE")),
                    ("H3_atr25", dict(stop_mult=2.5))):
        cand = []
        for t in tickers:
            df = bars_all[t]
            kw2 = dict(elig=elig_mask(df)) if len(df) >= 70 else dict(elig=None)
            for tr in mm.sim_period(df, sc, sm, dates, "LONG",
                                    kw.get("variant", "ORIG"),
                                    **kw2, stop_mult=kw.get("stop_mult", 2.0)):
                tr["ticker"] = t; tr["direction"] = "LONG"
                cand.append(tr)
        r = portfolio_run(cand, bars_all, *dates)
        res[f"{tag}_{period}"] = r
        print(tag, period, "sig", r["signals"], "adm", r["admitted"],
              "nav%", r["net_pct"], "pf", r["pf"], "pnl", r["net_pnl"])
json.dump(res, open(Path(__file__).parent/"results/mission3.json", "w"),
          indent=1)
