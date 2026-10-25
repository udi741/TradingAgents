#!/usr/bin/env python3
"""Independent AI-decision paper portfolio.

Consumes authored `decision` objects (or validated contracts from
`decision.from_intent`) and maintains a persistent paper book:
pending entries -> fills -> stop/target management -> exits -> NAV.

Isolated by construction: reads only published research artifacts +
market bars; writes ONLY under its own data dir. No watchlist, ledger,
order, or monitor contact.

Paper-only: SHORT positions are simulated with borrow cost and margin
accounting; nothing is ever authorized for execution.

Ledger/state schema (append-only JSONL + book snapshot JSON):
  events: INGEST|FILL|EXIT|MARK per session
  book: cash, positions, realized_pnl, nav
"""
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backtest"))
from alpha_rnd import decision as dec

COST_BPS = 0.001
START_CASH = 100_000.0
MAX_POS = 10
POS_NOTIONAL = 5_000.0
RISK_BUDGET_FRAC = 0.01
SHORT_BORROW_BPS_PER_DAY = 0.02 / 365
MAX_WAIT_SESSIONS = 20


def _new_book():
    return {"cash": START_CASH, "realized": 0.0, "borrow_costs": 0.0,
            "fees": 0.0, "positions": {}, "pending": [], "nav": START_CASH,
            "peak_nav": START_CASH, "max_dd": 0.0, "closed": [],
            "ingested_decisions": []}


def load_book(d: Path):
    f = d / "book.json"
    return json.loads(f.read_text()) if f.exists() else _new_book()


def save_book(d: Path, book):
    d.mkdir(parents=True, exist_ok=True)
    (d / "book.json").write_text(json.dumps(book, indent=1))


def seen_sessions(d: Path):
    led = d / "events.jsonl"
    return {json.loads(l)["session"] for l in led.open()} \
        if led.exists() else set()


def _emit(d, session, type_, **kw):
    with (d / "events.jsonl").open("a") as f:
        f.write(json.dumps({"session": session, "type": type_, **kw})
                + "\n")


def ingest_intent(book, intent, session, data_dir):
    """Record a validated decision; register pending entry when valid."""
    authored = intent.get("decision")
    c = dec.from_intent(
        intent, (intent.get("provenance") or {}).get("signal"),
        bool(authored and authored.get("direction") == "SHORT"),
        session)
    did = f"{session}|{intent.get('ticker')}"
    if did in book["ingested_decisions"]:
        return None
    book["ingested_decisions"].append(did)
    if c["direction"] == "NO_TRADE":
        _emit(data_dir, session, "INGEST", ticker=intent.get("ticker"),
              decision="NO_TRADE", reason=c["reason"],
              authored=bool(authored))
        return c["reason"]
    size = c.get("size_frac") or c.get("permissible_size_frac") or 0.0
    notional = min(POS_NOTIONAL * size if size <= 1 else POS_NOTIONAL,
                   POS_NOTIONAL)  # frac scales the standard slot
    book["pending"].append(
        {"ticker": intent.get("ticker"), "dir": c["direction"],
         "entry": c["entry"], "stop": c["stop"], "target": c["target"],
         "horizon": c.get("horizon"), "rr": c.get("reward_risk"),
         "notional": notional, "session": session,
         "deadline_sessions": MAX_WAIT_SESSIONS, "waited": 0})
    _emit(data_dir, session, "INGEST", ticker=intent.get("ticker"),
          decision=c["direction"], entry=c["entry"], stop=c["stop"],
          target=c["target"], notional=round(notional, 2),
          rr=c.get("reward_risk"), authored=bool(authored))
    return None


def step_day(book, session, bars_by_ticker, data_dir):
    """Advance one completed session: fills (from arm-day+1 semantics are
    inherent: pending was ingested on its pub date and only evaluated on
    later sessions), exits on stops, NAV mark."""
    bar = {t: b for t, b in bars_by_ticker.items()}
    # 1) pending close-based exits fill at today's open (yesterday's
    # confirmed breach executes first — cannot be re-armed same day)
    for t, p in list(book["positions"].items()):
        pe = p.get("pending_exit")
        if not pe or pe["day"] == session:
            continue
        b = bar.get(t)
        if b is not None:
            _close(book, session, t, float(b["Open"]),
                   pe["type"] + "_next_open", data_dir)
            continue
        p.pop("pending_exit", None)
    # 2) exits: today's bar stop checks (may arm a pending exit)
    for t, p in list(book["positions"].items()):
        b = bar.get(t)
        if b is None:
            continue
        o, h, l, c = (float(b[k]) for k in ("Open", "High", "Low", "Close"))
        stop, stype = p["stop"], p["stop_type"]
        exit_px = why = None
        if p["dir"] == "LONG":
            if stype == "intraday_stop":
                if o <= stop and session != p["entry_date"]:
                    exit_px, why = o, "gap_through_stop_open"
                elif l <= stop:
                    exit_px, why = stop, "intraday_stop"
            else:
                if c < stop:
                    exit_px, why = None, "close_below_pending_next_open"
                    p["pending_exit"] = {"type": "close_below", "day": session}
        else:
            if stype == "intraday_stop":
                if o >= stop and session != p["entry_date"]:
                    exit_px, why = o, "gap_through_stop_open"
                elif h >= stop:
                    exit_px, why = stop, "intraday_stop"
            else:
                if c > stop:
                    p["pending_exit"] = {"type": "close_above",
                                         "day": session}
        if exit_px is not None:
            _close(book, session, t, exit_px, why, data_dir)
    # 3) pending entries fill on today's bar
    for pe in list(book["pending"]):
        t = pe["ticker"]
        if t in book["positions"]:
            book["pending"].remove(pe)
            continue
        b = bar.get(t)
        pe["waited"] += 1
        if pe["waited"] > pe["deadline_sessions"]:
            book["pending"].remove(pe)
            _emit(data_dir, session, "EXPIRE", ticker=t, dir=pe["dir"])
            continue
        if session <= pe["session"]:
            continue  # decision not yet eligible: needs next session
        if b is None or len(book["positions"]) >= MAX_POS:
            continue
        o, h, l, c = (float(b[k]) for k in ("Open", "High", "Low", "Close"))
        e = pe["entry"]
        fill = None
        z = dec._zone(e.get("zone"))
        if z and pe["dir"] == "LONG" and l <= z[1]:
            fill = z[1]
        elif z and pe["dir"] == "SHORT" and l <= z[1] and h >= z[0]:
            fill = z[0]
        elif not z:
            lv = dec._f(e.get("level") or e.get("trigger_level"))
            if lv and pe["dir"] == "LONG" and l <= lv:
                fill = lv
            elif lv and pe["dir"] == "SHORT" and h >= lv:
                fill = lv
        if fill is None:
            continue
        shares = math.floor(pe["notional"] / fill)
        if shares < 1:
            continue
        cost = shares * fill * COST_BPS
        need = shares * fill + cost
        if need > book["cash"]:
            continue
        book["cash"] -= need
        book["fees"] += cost
        book["positions"][t] = {
            "dir": pe["dir"], "shares": shares, "entry_px": fill,
            "entry_date": session, "stop": pe["stop"],
            "target": pe["target"], "horizon": pe.get("horizon"),
            "stop_type": "close_below",
            "session_published": pe["session"]}
        book["pending"].remove(pe)
        _emit(data_dir, session, "FILL", ticker=t, dir=pe["dir"],
              px=fill, shares=shares, notional=round(shares * fill, 2),
              stop=pe["stop"], target=pe["target"])
    # 4) mark NAV
    def _mv(t, p):
        c = float(bar[t]["Close"])
        return p["shares"] * (c if p["dir"] == "LONG"
                              else 2 * p["entry_px"] - c)
    mv = sum(_mv(t, p) for t, p in book["positions"].items() if t in bar)
    book["nav"] = book["cash"] + mv
    book["peak_nav"] = max(book["peak_nav"], book["nav"])
    book["max_dd"] = max(book["max_dd"], book["peak_nav"] - book["nav"])
    _emit(data_dir, session, "MARK", nav=round(book["nav"], 2),
          cash=round(book["cash"], 2),
          positions={t: p["shares"] for t, p in book["positions"].items()})


def _close(book, session, t, px, why, data_dir):
    p = book["positions"].pop(t)
    shares, fill = p["shares"], p["entry_px"]
    days = (session[:10] == p["entry_date"][:10])
    held = 0 if days else None
    if p["dir"] == "LONG":
        proceeds = shares * px * (1 - COST_BPS)
        pnl = proceeds - shares * fill * (1 + COST_BPS)
        fee = shares * px * COST_BPS
    else:
        held_days = sum(1 for _ in ()) or 0
        held_days = _daydiff(p["entry_date"], session)
        borrow = shares * fill * SHORT_BORROW_BPS_PER_DAY * held_days
        pnl = shares * (fill * (1 - COST_BPS) - px * (1 + COST_BPS)) - borrow
        proceeds = 0
        fee = shares * (fill + px) * COST_BPS + borrow
        book["borrow_costs"] += borrow
        book["cash"] += pnl  # margin was debited at entry; P&L settles
        book["realized"] += pnl
        book["fees"] += fee
        book["closed"].append({"ticker": t, "dir": "SHORT",
                               "in": [p["entry_date"], fill],
                               "out": [session, px], "why": why,
                               "pnl": round(pnl, 2)})
        _emit(data_dir, session, "EXIT", ticker=t, dir="SHORT", px=px,
              why=why, pnl=round(pnl, 2), borrow=round(borrow, 2))
        return
    book["cash"] += proceeds
    book["fees"] += shares * px * COST_BPS
    book["realized"] += pnl
    book["closed"].append({"ticker": t, "dir": "LONG",
                           "in": [p["entry_date"], fill],
                           "out": [session, px], "why": why,
                           "pnl": round(pnl, 2)})
    _emit(data_dir, session, "EXIT", ticker=t, dir="LONG", px=px, why=why,
          pnl=round(pnl, 2))


def _daydiff(a, b):
    return (pd.Timestamp(b) - pd.Timestamp(a)).days


import pandas as pd  # noqa: E402
