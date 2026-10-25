#!/usr/bin/env python3
"""Daily driver for the AI-decision paper portfolio.

Reads publication_intents_<date>.json + daily bars; ingests NEW authored
decisions (next-session eligibility), advances the book one completed
session, appends events. Idempotent per session.

Manual: python3 backtest/decision_portfolio_runner.py --session 2026-10-24
"""
import argparse
import json
import sys
from pathlib import Path

import yfinance as yf

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, "/home/udi/udi_provate/TradingAgents-contract")
from alpha_rnd import decision_portfolio as dp

EV = Path("/home/udi/udi_provate/TradingAgents/evaluations/alpha_rnd_v1")
DATA = Path.home() / "udi_provate" / "TradingAgents-decision-portfolio"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", required=True)
    ap.add_argument("--data-dir", default=str(DATA))
    args = ap.parse_args()
    d = Path(args.data_dir).expanduser()
    book = dp.load_book(d)
    # ingest: every published intents doc up to session, new tickers only
    for f in sorted(EV.glob("publication_intents_*.json")):
        s = f.stem.rsplit("_", 1)[-1]
        if s > args.session:
            continue
        doc = json.loads(f.read_text())
        for t, i in (doc.get("intents") or {}).items():
            dp.ingest_intent(book, i, s, d)
    # bars: through session (inclusive, completed bars only)
    tickers = {p["ticker"] for p in book["pending"]} | set(book["positions"])
    if not tickers:
        dp.save_book(d, book)
        print("no pending/open positions")
        return
    import pandas as pd
    end = (pd.Timestamp(args.session) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    bars = yf.download(sorted(tickers), start="2026-09-01", end=end,
                       group_by="ticker", progress=False, auto_adjust=True)
    day = {}
    for t in tickers:
        try:
            df = bars[t].dropna() if len(tickers) > 1 else bars.dropna()
            row = df[df.index.strftime("%Y-%m-%d") <= args.session]
            if len(row):
                day[t] = row.iloc[-1]
        except Exception:
            pass
    dp.step_day(book, args.session, day, d)
    dp.save_book(d, book)
    print(f"session={args.session} nav={book['nav']:.2f} "
          f"cash={book['cash']:.2f} open={list(book['positions'])} "
          f"closed={len(book['closed'])}")


if __name__ == "__main__":
    main()
