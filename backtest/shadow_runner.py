#!/usr/bin/env python3
"""Forward shadow runner — three independent paper books.

Books: A=alphabetical, B=AI-rating priority, C=shuffle seed 42.
Identical mechanical retest rules, $100k/$5k/10-slot, 10bps/side.

Usage (manual, isolated):
    python3 backtest/shadow_runner.py --session 2026-10-23 --dry-run

Reads only published artifacts (frozen pools, publication intents,
case_artifacts) and market bars. Writes append-only records under
backtest/shadow/ — never the live watchlist, ledger, or positions.

Timing rules (enforced):
- A rating is eligible from the NEXT trading session after its pub date.
- A mechanical signal arms on the signal-day close; fills only on later
  bars.
- Daily OHLC never affects decisions before that day exists.

Deterministic/idempotent: rerunning the same session rewrites its book
snapshots and skips already-logged decision ids.
"""
import argparse
import json
import sys
from pathlib import Path

import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).parent))
import mechanics_multiyear as mm
from portfolio_sim import portfolio_run
from ai_priority_test import load_pools, load_ratings, rating_at, RATING_RANK

DEFAULT_DATA_DIR = Path.home() / "udi_provate" / "TradingAgents-shadow-data"
SEED = 42


def seen_sessions(ledger):
    if not ledger.exists():
        return set()
    return {json.loads(l)["session"] for l in ledger.open()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--session",
                    help="shadow session end date, e.g. 2026-10-23")
    ap.add_argument("--start", default="2026-10-01")
    ap.add_argument("--ev-dir",
                    default="/home/udi/udi_provate/TradingAgents/"
                            "evaluations/alpha_rnd_v1",
                    help="read-only research artifacts dir")
    ap.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR),
                    help="persistent shadow output dir (outside repo)")
    ap.add_argument("--prospective", action="store_true",
                    help="record into the PROSPECTIVE ledger; session must "
                         "be newer than the marker set by --init-prospective")
    ap.add_argument("--init-prospective", action="store_true",
                    help="write prospective_start marker = latest published "
                         "session; only sessions AFTER it may be prospective")
    ap.add_argument("--catchup", action="store_true",
                    help="process ALL published sessions after the marker "
                         "that are not yet logged (chronological)")
    ap.add_argument("--dry-run", action="store_true",
                    help="historical dry run; writes under <data-dir>/dry_run")
    args = ap.parse_args()
    period = (args.start, args.session)

    data_dir = Path(args.data_dir).expanduser()
    out_dir = data_dir / "dry_run" if args.dry_run else data_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    ledger = out_dir / "decisions.jsonl"
    books_file = out_dir / "books.json"
    marker = data_dir / "prospective_start"
    pools_tmp = load_pools()
    latest_pub = max(pools_tmp) if pools_tmp else None
    if args.init_prospective:
        marker.write_text(latest_pub + "\n")
        print("prospective_start set to latest published session:",
              latest_pub)
        return
    ev_dir = Path(args.ev_dir)
    import ai_priority_test as apt
    apt.EV = ev_dir

    def published_sessions():
        sess = {f.stem.rsplit("_", 1)[-1]
                for f in ev_dir.glob("candidate_pool_frozen_*.json")}
        sess |= {f.stem.rsplit("_", 1)[-1]
                 for f in ev_dir.glob("publication_intents_*.json")}
        return sorted(sess)

    if args.prospective:
        if not marker.exists():
            ap.error("--init-prospective first")
        mstart = marker.read_text().strip()
        today = str(__import__("datetime").date.today())
        pubs = [s_ for s_ in published_sessions()
                if s_ > mstart and s_ < today]
        # sessions strictly before today only: guarantees the session bar
        # is complete (no intraday data leak); a publication that lands
        # late is picked up automatically by the next run.
        if args.catchup:
            seen = seen_sessions(ledger)
            todo = [s_ for s_ in pubs if s_ not in seen]
            if todo:
                print("catching up sessions:", todo)
                for sess_ in todo:
                    _process_one(args, sess_, (args.start, sess_),
                                 ledger, books_file)
            elif seen:
                # no new publication: still mark/manage open positions
                # through the latest COMPLETED business-day bar.
                last_bar = str((pd.Timestamp(today)
                                - pd.offsets.BDay(1)).date())
                mark = "mark_" + last_bar
                if mark not in seen:
                    print("no new publication — marking open positions "
                          "through", last_bar)
                    _process_one(args, last_bar, (args.start, last_bar),
                                 ledger, books_file, rec_id=mark)
                else:
                    print("nothing to catch up — mark already logged")
            else:
                print("nothing to catch up — all published sessions logged")
            return
        if not args.session:
            ap.error("--session is required")
        if mstart >= args.session:
            ap.error(f"session {args.session} is not after marker "
                     f"{mstart} — not prospective")
        if args.session not in pubs:
            if args.session in published_sessions():
                print(f"{args.session}: bar may be incomplete "
                      "(session is today) — retryable skip")
            else:
                print(f"no published artifact for {args.session} — "
                      "skipping (retryable, not permanent)")
            return
    elif not args.session:
        ap.error("--session is required")

    _process_one(args, args.session, period, ledger, books_file)


def _process_one(args, session, period, ledger, books_file,
                 rec_id=None):
    pools = load_pools()
    ratings = load_ratings()
    covered = sorted({t for ts in pools.values() for t in ts})
    import datetime as _dt
    end_d = (pd.Timestamp(session) + pd.Timedelta(days=1)).strftime(
        "%Y-%m-%d")  # yf end is exclusive -> include the session bar
    data = yf.download(covered + ["SPY"], start="2025-10-01",
                       end=end_d, group_by="ticker", progress=False,
                       auto_adjust=True, threads=True)
    spy = data["SPY"].dropna()
    sc = {str(x.date()): float(r) for x, r in spy["Close"].items()}
    sm = {str(x.date()): float(r) for x, r in
          spy["Close"].rolling(20).mean().items()}
    cand = []
    for t in covered:
        df = data[t].dropna()
        if len(df) < 40:
            continue
        for tr in mm.sim_period(df, sc, sm, period, "LONG", "ORIG"):
            tr["ticker"] = t
            tr["direction"] = "LONG"
            tr["rating"] = rating_at(ratings, t, tr["fill_date"])
            tr["rating_eligible_from"] = "next_session_after_pub"
            cand.append(tr)
    bars = {t: data[t].dropna() for t in covered}
    books = {
        "A_alpha": portfolio_run(cand, bars, *period),
        "B_ai_rating": portfolio_run(
            cand, bars, *period,
            priority_fn=lambda c: -RATING_RANK.get(c["rating"], 0)),
        "C_shuffle_42": portfolio_run(cand, bars, *period, order_seed=SEED),
    }
    contested = {}
    for c in cand:
        contested.setdefault(c["fill_date"], []).append(c["ticker"])
    rec = {"session": rec_id or session, "period": period,
           "candidates": len(cand),
           "contested_days": {k: v for k, v in contested.items()
                              if len(v) > 1},
           "books": {k: {"nav": r["end_nav"], "net_pct": r["net_pct"],
                         "admitted": r["admitted"],
                         "net_pnl": r["net_pnl"], "pf": r["pf"],
                         "max_dd": r["max_dd"],
                         "trades": r["admitted_trades"]}
                     for k, r in books.items()}}
    if args.session in seen_sessions(ledger):
        print("session already logged — idempotent skip of ledger append")
    else:
        with ledger.open("a") as f:
            f.write(json.dumps(rec) + "\n")
    books_file.write_text(json.dumps({args.session: rec["books"]}, indent=1))
    for k, r in rec["books"].items():
        print(f"{k:14s} admit={r['admitted']} nav%={r['net_pct']} "
              f"pnl={r['net_pnl']} pf={r['pf']} dd={r['max_dd']}")
    print("contested days:", len(rec["contested_days"]))
    print("written:", ledger, books_file)


if __name__ == "__main__":
    main()
