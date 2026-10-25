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
sys.path.insert(0, str(Path(__file__).parent.parent))
from alpha_rnd import decision_portfolio as dp

EV = Path("/home/udi/udi_provate/TradingAgents/evaluations/alpha_rnd_v1")
DATA = Path.home() / "udi_provate" / "TradingAgents-decision-portfolio"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--session")
    ap.add_argument("--catchup", action="store_true",
                    help="process every completed bar day after last_mark, "
                         "ingesting publications as they appear")
    ap.add_argument("--ev-dir", default=str(EV))
    ap.add_argument("--data-dir", default=str(DATA))
    args = ap.parse_args()
    d = Path(args.data_dir).expanduser()
    ev = Path(args.ev_dir)
    book = dp.load_book(d)
    import pandas as pd
    today = str(__import__("datetime").date.today())
    last_completed = str((pd.Timestamp(today)
                          - pd.offsets.BDay(1)).date())
    pubs = {}
    for f in sorted(ev.glob("publication_intents_*.json")):
        pubs[f.stem.rsplit("_", 1)[-1]] = f
    if args.catchup:
        # process each business day after last_mark through the latest
        # COMPLETED bar: ingest that day's publications (decisions become
        # fill-eligible next session) then advance the book one day.
        days = [str(x.date()) for x in
                pd.bdate_range(start=(book.get("last_mark") or "2026-01-01"),
                               end=last_completed)][1:]
        if not days:
            print("nothing to catch up")
            return
        tickers = sorted({i.get("ticker")
                          for f in pubs.values()
                          for i in (json.loads(f.read_text())
                                    .get("intents") or {}).values()
                          if i.get("ticker")})
        end = (pd.Timestamp(last_completed)
               + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        bars = yf.download(tickers + ["SPY"], start="2026-09-01", end=end,
                           group_by="ticker", progress=False,
                           auto_adjust=True, threads=True)
        # ingest EVERY published doc not yet ingested, with the
        # observation date = today: late publications are discovered
        # regardless of last_mark and become eligible only from the next
        # session after first observation (no retroactive eligibility).
        for sess_pub, f in sorted(pubs.items()):
            doc = json.loads(f.read_text())
            for t, i in (doc.get("intents") or {}).items():
                dp.ingest_intent(book, i, sess_pub, d, observed_on=today)
        for sess in days:
            day = {}
            for t in tickers:
                try:
                    df = bars[t].dropna()
                    row = df[df.index.strftime("%Y-%m-%d") == sess]
                    if len(row):
                        day[t] = row.iloc[0]
                except Exception:
                    pass
            if "SPY" not in day:
                # no index bar: genuine market holiday (not missing data) —
                # skip the day without stalling; a ticker-only gap still
                # marks remaining names.
                continue
            dp.step_day(book, sess, day, d)
            book["last_mark"] = sess
        dp.save_book(d, book)
        print(f"catchup -> last_mark={book.get('last_mark')} "
              f"nav={book['nav']:.2f} open={list(book['positions'])} "
              f"closed={len(book['closed'])}")
        return
    if not args.session:
        ap.error("--session or --catchup required")
    # ingest: every published intents doc up to session, new tickers only
    for s_, f in pubs.items():
        if s_ > args.session:
            continue
        doc = json.loads(f.read_text())
        for t, i in (doc.get("intents") or {}).items():
            dp.ingest_intent(book, i, s_, d, observed_on=args.session)
    tickers = {p["ticker"] for p in book["pending"]} | set(book["positions"])
    if not tickers:
        dp.save_book(d, book)
        print("no pending/open positions")
        return
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
    book["last_mark"] = args.session
    dp.save_book(d, book)
    print(f"session={args.session} nav={book['nav']:.2f} "
          f"cash={book['cash']:.2f} open={list(book['positions'])} "
          f"closed={len(book['closed'])}")


if __name__ == "__main__":
    main()
