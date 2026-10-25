#!/usr/bin/env python3
"""Mission11 — prospective scoring of AI-AUTHORED decisions.

The alpha_paper_ledger is a frozen prospective paper book: entry zones,
invalidations and triggers authored BEFORE outcomes (frozen_at stamps
precede the fills). This is the first causally-valid AI evidence: no
mechanical proxy — the recorded fills and exits are the AI's own.

As-recorded economics (canonical postmortems, 10bps costs):
  ACN  24@205.00 10/02 -> 10/07 @195.23 (close<194 rule)     -239.17
  APPS 442@11.30 10/02 -> 10/07 @10.30 (gap through 10.42)   -445.67
  PGEN 609@8.21  10/05 -> 10/06 @7.79  (hard stop 7.75)      -259.43
  SDGR 161@31.00 10/06 -> 100@27.81 + 61@~25.8 (mgmt stops)  -638.84
  TWST 11@209.55 10/06 -> 4@158.26 + 7@159.74 (mgmt stops)   -557.89
  PBF  62@80.00  10/02 -> OPEN; authored rules only
                           (close<78; hard 74.50; hold<=60 sess)

Controls (fair, non-AI):
  NAIVE_SAME_NAMES = same tickers/shares/fill dates, hold to end —
        isolates whether AI exits/invalidations added value vs holding.
  SPY_MATCHED      = each fill's notional into SPY on the same date.
  WATCHLIST_NAIVE  = all 10 V2 deep-research names, $5k each at the
        first open after the Oct-3 freeze, held — tests whether the
        AI's selective triggers beat just buying its whole watchlist.
  RULES_ONLY       = the 6 trades under authored invalidations alone
        (no discretionary mgmt exits; NOT_STATED -> hold to end).

Power: n=6 fills, ~3 weeks. Exploratory, not decisive — reported as
the first prospective datapoint, not proof.
"""
import json
import sys
from pathlib import Path

import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).parent))

COST = 0.001
END = "2026-10-23"
V2_TICKERS = ["PGEN", "SYNA", "ASST", "KOD", "TXG", "TWST", "PAYC",
              "XNCR", "AXGN", "HHH"]

# as-recorded canonical trades (postmortems): (ticker, fill_date, fill,
# shares, exits [(date, shares, px)]) — PBF handled separately (open).
RECORDED = {
    "ACN": ("2026-10-02", 205.00, 24, [("2026-10-07", 24, 195.22999572753906)]),
    "APPS": ("2026-10-02", 11.30, 442, [("2026-10-07", 442, 10.302000045776367)]),
    "PGEN": ("2026-10-05", 8.21, 609, [("2026-10-06", 609, 7.789999961853027)]),
    "SDGR": ("2026-10-06", 31.00, 161, [("2026-10-07", 100, 27.809999465942383),
                                        ("2026-10-13", 61, 25.90999984741211)]),
    "TWST": ("2026-10-06", 209.55, 11, [("2026-10-07", 4, 158.25999450683594),
                                        ("2026-10-12", 7, 159.74000549316406)]),
    "PBF": ("2026-10-02", 80.00, 62, []),
}
# authored invalidations for the rules-only replay
RULES = {"PBF": {"close_below": 78.0, "hard": 74.50},
         "ACN": {"close_below": 194.0},
         "APPS": {"hard": 10.42},
         "PGEN": {"hard": 7.75},
         "SDGR": {}, "TWST": {}}  # NOT_STATED -> hold

tickers = sorted(set(RECORDED) | set(V2_TICKERS) | {"SPY"})
d = yf.download(tickers, start="2026-09-25", end="2026-10-25",
                group_by="ticker", progress=False, auto_adjust=True,
                threads=True)
bars = {}
for t in tickers:
    try:
        df = d[t].dropna()
        if len(df):
            bars[t] = df
    except Exception:
        pass

def px(t, date, field="Close"):
    df = bars.get(t)
    if df is None:
        return None
    s = df.loc[:date]
    return float(s[field].iloc[-1]) if len(s) else None

def next_open(t, date):
    df = bars.get(t)
    if df is None:
        return None
    s = df.loc[df.index > date]
    return float(s["Open"].iloc[0]) if len(s) else None

end_px = {t: px(t, END) for t in tickers}

# --- book 1: AS-RECORDED ---
cash, deployed, positions = 100000.0, 0.0, {}
realized = 0.0
for t, (fd, f, sh, exits) in RECORDED.items():
    cost = sh * f * (1 + COST)
    cash -= cost
    deployed += cost
    realized += sum(s_ * (xp * (1 - COST) - f * (1 + COST))
                    for xd, s_, xp in exits)
# PBF open under authored rules: did close<78 or low<=74.5 trigger?
pbf_exit = None
df = bars["PBF"].loc["2026-10-02":END]
for dt, r in df.iterrows():
    if float(r["Low"]) <= 74.50:
        pbf_exit = (str(dt.date()), 74.50); break
    if float(r["Close"]) < 78.0:
        pbf_exit = (str(df.index[df.index > dt][0].date())
                    if (df.index > dt).any() else str(dt.date()),
                    float(bars["PBF"].loc[df.index > dt, "Open"].iloc[0])
                    if (df.index > dt).any() else float(r["Close"]))
        break
pbf_legs = [(62, pbf_exit[1], "auth_rule", pbf_exit[0])] if pbf_exit \
    else [(62, end_px["PBF"], "open_mark", END)]
pbf_pnl = sum(s_ * (xp * (1 - COST) - 80.0 * (1 + COST))
              for s_, xp, *_ in pbf_legs)
nav_recorded = cash + realized + (0 if pbf_exit else
                                  62 * end_px["PBF"] * (1 - COST)
                                  + 62 * 80 * COST)  # mark, net of exit cost
# simpler: nav = start + realized + pbf_pnl
nav_recorded = 100000 + realized + pbf_pnl

# --- book 2: RULES-ONLY (authored invalidations, no mgmt exits) ---
ro_pnl = 0.0
ro_detail = {}
for t, (fd, f, sh, _) in RECORDED.items():
    df = bars[t].loc[fd:END]
    legs, rem, done = [], sh, False
    rule = RULES[t]
    for dt, r in df.iterrows():
        if str(dt.date()) <= fd:
            continue
        if rule.get("hard") and float(r["Low"]) <= rule["hard"]:
            legs.append((rem, rule["hard"], "hard", str(dt.date())))
            done = True; break
        if rule.get("close_below") and float(r["Close"]) < rule["close_below"]:
            nxt = df.loc[df.index > dt]
            xp = float(nxt["Open"].iloc[0]) if len(nxt) else float(r["Close"])
            xd = str(nxt.index[0].date()) if len(nxt) else str(dt.date())
            legs.append((rem, xp, "close_below", xd))
            done = True; break
    if not done:
        legs.append((rem, float(df["Close"].iloc[-1]), "end", END))
    ro_pnl += sum(s_ * (xp * (1 - COST) - f * (1 + COST))
                  for s_, xp, *_ in legs)
    ro_detail[t] = legs
nav_rules = 100000 + ro_pnl

# --- control 1: NAIVE_SAME_NAMES ---
nv_pnl = sum(sh * (end_px[t] * (1 - COST) - f * (1 + COST))
             for t, (fd, f, sh, _) in RECORDED.items())
nav_naive = 100000 + nv_pnl

# --- control 2: SPY_MATCHED ---
spy_pnl = 0.0
for t, (fd, f, sh, _) in RECORDED.items():
    s0 = px("SPY", fd)
    if s0:
        spy_pnl += sh * f * (end_px["SPY"] / s0 - 1)
nav_spy = 100000 + spy_pnl

# --- control 3: WATCHLIST_NAIVE (first open after Oct-3 freeze = 10/05) ---
wl_pnl, wl_detail = 0.0, {}
for t in V2_TICKERS:
    o = px(t, "2026-10-05", "Open")
    if o and end_px[t]:
        wl_detail[t] = round(100 * (end_px[t] / o - 1), 2)
        wl_pnl += 5000 * (end_px[t] * (1 - COST) / (o * (1 + COST)) - 1)
nav_wl = 100000 + wl_pnl

out = {
    "window": ["2026-10-02", END],
    "as_recorded": {"nav": round(nav_recorded, 2),
                    "net_pct": round(nav_recorded / 1000 - 100, 2),
                    "realized_closed": round(realized, 2),
                    "pbf": {"exit": pbf_exit, "pnl": round(pbf_pnl, 2)}},
    "rules_only": {"nav": round(nav_rules, 2),
                   "net_pct": round(nav_rules / 1000 - 100, 2),
                   "legs": ro_detail},
    "naive_same_names": {"nav": round(nav_naive, 2),
                         "net_pct": round(nav_naive / 1000 - 100, 2)},
    "spy_matched": {"nav": round(nav_spy, 2),
                    "net_pct": round(nav_spy / 1000 - 100, 2)},
    "watchlist_naive": {"nav": round(nav_wl, 2),
                        "net_pct": round(nav_wl / 1000 - 100, 2),
                        "per_ticker": wl_detail},
    "end_marks": {t: round(v, 2) for t, v in end_px.items() if v}}
print(json.dumps(out, indent=1))
json.dump(out, open(Path(__file__).parent / "results/mission11.json", "w"),
          indent=1)
