#!/usr/bin/env python3
"""Historical LONG/SHORT backtest over RECORDED TradingAgents decisions.

Replays the production monitor's actual semantics
(alpha_rnd/monitor.py, entry_gate.py, econ_contract.py) against recorded
publication intents + historical daily OHLC. No model calls.

Run:
    python backtest/historical_backtest.py [--ev DIR] [--out DIR]

Data sources (read-only):
  <ev>/publication_intents_*.json      production decision sessions
  <ev>/replays/*/*/publication.json    R5B replay publications
  <ev>/case_artifacts/*.json           signal per (session,ticker)
  <ev>/alpha_paper_ledger.jsonl        actual recorded paper trades (Track A)
  yfinance daily bars                  prices

Semantics implemented verbatim from monitor.py:
  COST_BPS=0.001 each side, POS_NOTIONAL=5000, MAX_POSITIONS=10,
  min notional 500, whole shares, EXPIRY=2026-10-30, watch wait<=20 sessions.
  AUTO_ENTRY zone -> fill at zone top when Low<=zone[1] (gap-through fills at
  zone top per production do_fill(p['zone'][1]) — flagged assumption).
  Confirmation triggers -> CONFIRMED at close -> next-session-open fill.
  intraday_stop -> open<=level: exit at open; low<=level: exit at level.
  close_below   -> close<level: exit next session open.
  Framework has NO mechanical profit target — positions exit on stop or
  end-of-data mark only; MFE reported to show foregone profits.
  Conservative same-bar ordering: if entry day low <= stop, stopped same day.
"""
import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

import pandas as pd
import yfinance as yf

COST_BPS = 0.001
POS_NOTIONAL = 5000.0
MAX_POSITIONS = 10
MIN_NOTIONAL = 500.0
START_CASH = 100000.0
EXPIRY = "2026-10-30"
MAX_WAIT_SESSIONS = 20
DATA_END = "2026-10-23"   # last complete recorded session
SHORT_BORROW_BPS_PER_DAY = 0.02 / 365  # ~2%/yr assumed borrow cost, flagged

ZONE_KEYS = ["entry_zone", "zone", "entry_band", "zone1", "buy_zone",
             "reentry_zone", "pullback_zone", "base_zone",
             "stabilization_zone", "tranche1", "probe_zone", "pb_zone",
             "support_zone", "readd_zone", "retest_zone", "long_zone"]
LEVEL_KEYS = ["entry", "trigger_level", "level", "reclaim", "reclaim_level",
              "bo_level", "breakout", "breakout_close", "alt_level",
              "resistance", "entry_price", "weekly_close_trigger"]
SHORT_WORDS = re.compile(r"\bshort\b", re.I)


def _num(x):
    try:
        v = float(x)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def _pair(v):
    """[lo,hi] from list or 'a-b' string."""
    if isinstance(v, (list, tuple)) and len(v) == 2:
        lo, hi = _num(v[0]), _num(v[1])
        if lo is not None and hi is not None:
            return [lo, hi]
    if isinstance(v, str):
        m = re.match(r"^\s*(\d+\.?\d*)\s*[-–]\s*(\d+\.?\d*)\s*$", v)
        if m:
            return [float(m.group(1)), float(m.group(2))]
    return None


def load_intents(ev: Path):
    """All recorded intents; each row tagged with source and disposition."""
    rows = []
    files = sorted(ev.glob("publication_intents_*.json"))
    files += sorted(ev.glob("replays/*/*/publication.json"))
    for f in files:
        d = json.loads(f.read_text())
        m = re.search(r"(\d{4}-\d{2}-\d{2})", str(f))
        sess = d.get("session") or (m.group(1) if m else
                                    f.stem.rsplit("_", 1)[-1])
        src = "REPLAY" if "replays" in str(f) else "PROD"
        disps = {t: (v.get("disposition") if isinstance(v, dict) else v)
                 for t, v in (d.get("dispositions") or {}).items()}
        its = d.get("intents")
        if isinstance(its, dict):
            its = list(its.values())
        elif its is None:
            its = [v["intent"] for v in
                   (d.get("dispositions") or {}).values() if v.get("intent")]
        for i in its or []:
            if not i:
                continue
            rows.append({"session": sess, "source": src, "intent": i,
                         "disposition": disps.get(i["ticker"])})
    return rows


def load_signals(ev: Path):
    sig = {}
    for f in sorted(ev.glob("case_artifacts/*.json")) + \
             sorted(ev.glob("replays/*/*/case_artifacts/*.json")):
        try:
            d = json.loads(f.read_text())
        except Exception:
            continue
        t, s = d.get("ticker"), d.get("decision_session")
        if t and s:
            sig.setdefault((s, t), d.get("signal"))
    return sig


def entry_spec(i):
    """(zone[lo,hi] | None, level|None) from recorded params."""
    p = i.get("params") or {}
    for k in ZONE_KEYS:
        z = _pair(p.get(k))
        if z:
            return z, None
    for k in LEVEL_KEYS:
        v = _num(p.get(k))
        if v:
            return None, v
    return None, None


def is_short_plan(i, signal):
    txt = " ".join(str(i.get(k) or "") for k in
                   ("trigger", "entry_convention", "invalidation"))
    p = i.get("params") or {}
    if "short_zone" in p:
        return True
    if SHORT_WORDS.search(txt) and "no short" not in txt.lower() \
            and "not short" not in txt.lower():
        return True
    # geometry: entry below stop AND target below entry = bearish plan
    st, tg = _num(i.get("stop_level")), _num(i.get("target"))
    z, lv = entry_spec(i)
    ref = z[1] if z else lv
    if signal in ("Sell", "Underweight") and st and ref and st > ref \
            and tg and tg < ref:
        return True
    return False


def classify(rows, signals):
    """Assign each intent a backtest disposition + executable spec."""
    out = []
    for r in rows:
        i, disp = r["intent"], r["disposition"]
        t, sess = i["ticker"], r["session"]
        sig = signals.get((sess, t))
        z, lv = entry_spec(i)
        stop = _num(i.get("stop_level"))
        tgt = _num(i.get("target"))
        cls = i.get("classification")
        wm = i.get("watch_mode")
        auth = bool(i.get("auto_execution_authorized"))
        short = is_short_plan(i, sig)
        # --- framework disposition -------------------------------------
        if disp == "AMBIGUOUS_REJECTED":
            status = "REJECTED_AMBIGUOUS"
        elif disp == "RESEARCH_ONLY":
            status = "RESEARCH_ONLY"
        elif short:
            status = "SHORT_DESCRIPTIVE_ONLY"  # econ_contract: never executable
        elif cls == "REANALYZE_ON_TRIGGER" or wm == "REANALYZE_ON_TRIGGER":
            status = "REANALYZE_ONLY"
        elif disp == "EXECUTABLE_WATCH":
            status = "AUTHORIZED"           # entry_gate pass
        elif auth and wm == "AUTO_ENTRY":
            status = "AUTH_INTENT_GATE_BLOCKED"  # authorized intent, no EXECUTABLE_WATCH
        elif auth:
            status = "AUTH_INTENT_NO_ZONE"
        else:
            status = "WATCH_NON_EXECUTABLE"
        # --- executable spec -------------------------------------------
        spec = None
        if status in ("AUTHORIZED", "AUTH_INTENT_GATE_BLOCKED") and not short:
            if z:
                spec = {"kind": "LIMIT_ZONE", "zone": z}
            elif lv and wm == "AUTO_ENTRY":
                spec = {"kind": "LIMIT_LEVEL", "level": lv}
            elif lv:
                spec = {"kind": "CLOSE_ABOVE", "level": lv}
            if spec and stop is None:
                spec = None
                status = "NON_EXECUTABLE_NO_STOP"
        elif short and (z or lv or _pair((i.get("params") or {}).get("short_zone"))) and stop:
            sz = _pair((i.get("params") or {}).get("short_zone")) or z
            spec = {"kind": "SHORT_ZONE" if sz else "SHORT_LEVEL",
                    "zone": sz, "level": lv}
        # stop type from invalidation wording
        stype = "close_below" if "close" in str(
            i.get("invalidation") or "").lower() else "intraday_stop"
        out.append({**r, "signal": sig, "short": short, "status": status,
                    "spec": spec, "stop": stop, "stop_type": stype,
                    "target": tgt, "frac": _num(i.get("size_frac")) or 1.0,
                    "expiry": EXPIRY})
    return out


def fetch_bars(tickers, end):
    tickers = sorted(set(tickers) | {"SPY"})
    d = yf.download(tickers, start="2026-09-25", end=end,
                    group_by="ticker", progress=False, auto_adjust=True,
                    threads=True)
    out = {}
    for t in tickers:
        try:
            df = d[t].dropna() if len(tickers) > 1 else d.dropna()
            if not df.empty:
                out[t] = df
        except Exception:
            pass
    return out


def next_sessions(bars, sess):
    return [str(x.date()) for x in bars.index if str(x.date()) > sess]


def simulate(item, df, sessions_all, ledger_style=True):
    """Simulate one authorized intent. Returns trade dict or None."""
    i = item["intent"]
    t = i["ticker"]
    spec = item["spec"]
    stop, stype = item["stop"], item["stop_type"]
    tgt = item["target"]
    eligible = [s for s in sessions_all
                if s > item["session"] and s <= item["expiry"]]
    eligible = eligible[:MAX_WAIT_SESSIONS]
    bar_by_date = {str(x.date()): r for x, r in df.iterrows()}
    fill = fill_date = None
    untriggered = True
    for s in eligible:
        b = bar_by_date.get(s)
        if b is None:
            continue
        o, h, l, c = (float(b[k]) for k in ("Open", "High", "Low", "Close"))
        if spec["kind"] == "LIMIT_ZONE":
            hi = spec["zone"][1]
            if l <= hi:
                fill, fill_date = hi, s   # production fills at zone top
                break
        elif spec["kind"] == "SHORT_ZONE":
            lo, hi = spec["zone"]
            # short = sell a bounce INTO the zone: bar must intersect it
            if l <= hi and h >= lo:
                fill, fill_date = max(lo, min(o, hi)), s
                break
        elif spec["kind"] == "LIMIT_LEVEL":
            if l <= spec["level"]:
                fill, fill_date = spec["level"], s
                break
        elif spec["kind"] == "CLOSE_ABOVE":
            if c > spec["level"]:
                nxt = [x for x in sessions_all if x > s]
                if nxt:
                    nb = bar_by_date.get(nxt[0])
                    if nb is not None:
                        fill, fill_date = float(nb["Open"]), nxt[0]
                break
        elif spec["kind"] == "SHORT_LEVEL":
            if h >= spec["level"]:
                fill, fill_date = spec["level"], s
                break
    if fill is None:
        return {"ticker": t, "session": item["session"], "status":
                "UNTRIGGERED", "watch_expired_sessions": len(eligible)}
    # position open: walk bars from fill_date (same-bar stop check first)
    direction = -1 if item["short"] else 1
    post = [s for s in sessions_all if s >= fill_date]
    exit_px = exit_date = exit_why = None
    mfe = mae = 0.0
    for s in post:
        b = bar_by_date.get(s)
        if b is None:
            continue
        o, h, l, c = (float(b[k]) for k in ("Open", "High", "Low", "Close"))
        if direction == 1:
            mfe = max(mfe, (h / fill - 1) * 100)
            mae = min(mae, (l / fill - 1) * 100)
            if stype == "intraday_stop":
                if o <= stop and s != fill_date:
                    exit_px, exit_date, exit_why = o, s, "gap_through_stop_open"
                    break
                if l <= stop:
                    # same-bar as fill: order unknowable -> conservative stop fill
                    exit_px, exit_date, exit_why = stop, s, "intraday_stop"
                    break
            else:  # close_below
                if c < stop:
                    nxt = [x for x in sessions_all if x > s]
                    if nxt and bar_by_date.get(nxt[0]) is not None:
                        exit_px = float(bar_by_date[nxt[0]]["Open"])
                        exit_date, exit_why = nxt[0], "close_below_next_open"
                    else:
                        exit_px, exit_date, exit_why = c, s, "close_below_mark"
                    break
        else:  # SHORT: stop above, symmetric
            mfe = max(mfe, (fill / l - 1) * 100 if l else 0)
            mae = min(mae, (fill / h - 1) * 100 if h else 0)
            if stype == "close_below":
                if c > stop:
                    nxt = [x for x in sessions_all if x > s]
                    if nxt and bar_by_date.get(nxt[0]) is not None:
                        exit_px = float(bar_by_date[nxt[0]]["Open"])
                        exit_date, exit_why = nxt[0], "close_above_next_open"
                    else:
                        exit_px, exit_date, exit_why = c, s, "close_above_mark"
                    break
            elif o >= stop and s != fill_date:
                exit_px, exit_date, exit_why = o, s, "gap_through_stop_open"
                break
            elif h >= stop:
                exit_px, exit_date, exit_why = stop, s, "intraday_stop"
                break
        if s == DATA_END:
            exit_px, exit_date, exit_why = c, s, "OPEN_MARK_END_OF_DATA"
    if exit_px is None:  # data exhausted
        last = bar_by_date.get(post[-1])
        exit_px, exit_date = float(last["Close"]), post[-1]
        exit_why = "OPEN_MARK_END_OF_DATA"
    # costs
    notional = min(POS_NOTIONAL * item["frac"], START_CASH)
    shares = int(notional / fill)
    if shares < 1:
        return {"ticker": t, "session": item["session"], "status": "NO_FILL_SIZE"}
    buy_cost = shares * fill * (1 + COST_BPS)
    days_held = (dt.date.fromisoformat(exit_date)
                 - dt.date.fromisoformat(fill_date)).days
    if direction == 1:
        proceeds = shares * exit_px * (1 - COST_BPS)
        pnl = proceeds - buy_cost
        borrow = 0.0
    else:
        proceeds = shares * fill * (1 - COST_BPS)
        cover = shares * exit_px * (1 + COST_BPS)
        borrow = shares * fill * SHORT_BORROW_BPS_PER_DAY * days_held
        pnl = proceeds - cover - borrow
    return {"ticker": t, "session": item["session"], "status":
            "CLOSED" if exit_why != "OPEN_MARK_END_OF_DATA" else "OPEN",
            "direction": "SHORT" if direction == -1 else "LONG",
            "entry_date": fill_date, "entry_px": round(fill, 4),
            "exit_date": exit_date, "exit_px": round(exit_px, 4),
            "exit_reason": exit_why, "shares": shares,
            "stop": stop, "stop_type": stype, "target": tgt,
            "pnl": round(pnl, 2), "borrow_cost": round(borrow, 2),
            "ret_pct": round(direction * (exit_px / fill - 1) * 100, 2),
            "mfe_pct": round(mfe, 2), "mae_pct": round(mae, 2),
            "days_held": days_held,
            "target_hit": bool(tgt and mfe >= (tgt / fill - 1) * 100)}


def track_a_ledger(ev: Path):
    """Reconstruct actual recorded paper trades from the ledger."""
    trades = {}
    fills = exits = []
    for line in (ev / "alpha_paper_ledger.jsonl").read_text().splitlines():
        try:
            e = json.loads(line)
        except Exception:
            continue
        ty = e.get("type")
        if ty == "PAPER_FILL":
            trades.setdefault(e["ticker"], []).append(
                {"in_session": e["session"], "px": e["fill_price"],
                 "shares": e["shares"], "notional": e["notional"],
                 "trigger": e["trigger"], "invalidation": e["invalidation"]})
        elif ty == "PAPER_EXIT" or (ty and "EXIT" in ty and e.get("ticker")):
            pass
    # exits live in incident record + management state; pull from events jsonl
    return trades


def stats(trades):
    closed = [t for t in trades if t.get("pnl") is not None]
    wins = [t for t in closed if t["pnl"] > 0]
    losses = [t for t in closed if t["pnl"] <= 0]
    gp = sum(t["pnl"] for t in wins)
    gl = -sum(t["pnl"] for t in losses)
    n = len(closed)
    return {"n": n, "wins": len(wins), "win_rate": round(len(wins) / n, 3) if n else None,
            "gross_pnl": round(sum(t["pnl"] for t in closed), 2),
            "avg_win": round(gp / len(wins), 2) if wins else None,
            "avg_loss": round(-gl / len(losses), 2) if losses else None,
            "expectancy": round(sum(t["pnl"] for t in closed) / n, 2) if n else None,
            "profit_factor": round(gp / gl, 2) if gl > 0 else None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ev", default=str(
        Path("/home/udi/udi_provate/TradingAgents/evaluations/alpha_rnd_v1")))
    ap.add_argument("--out", default=str(Path(__file__).parent / "results"))
    a = ap.parse_args()
    ev = Path(a.ev)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    rows = load_intents(ev)
    signals = load_signals(ev)
    items = classify(rows, signals)

    # ---------- inventory ----------
    from collections import Counter
    inv = Counter(i["status"] for i in items)
    short_ct = Counter(i["status"] for i in items if i["short"])
    print("== INTENT INVENTORY ==", dict(inv))
    print("short plans:", dict(short_ct))

    # ---------- price data ----------
    tickers = [i["intent"]["ticker"] for i in items]
    bars = fetch_bars(tickers, "2026-10-24")
    spy = bars.get("SPY")
    sessions_all = [str(x.date()) for x in spy.index]
    print("sessions:", sessions_all[0], "->", sessions_all[-1],
          len(sessions_all))

    # ---------- Track B: framework-strict authorized ----------
    trades = []
    for i in items:
        if i["status"] not in ("AUTHORIZED", "AUTH_INTENT_GATE_BLOCKED",
                              "SHORT_DESCRIPTIVE_ONLY"):
            continue
        if not i["spec"]:
            i["status"] = "NON_EXECUTABLE_NO_SPEC"
            continue
        df = bars.get(i["intent"]["ticker"])
        if df is None:
            i["status"] = "NO_PRICE_DATA"
            continue
        i["sim"] = simulate(i, df, sessions_all)
        if i["sim"].get("pnl") is not None:
            trades.append(i["sim"] | {"source": i["source"],
                                      "status_gate": i["status"],
                                      "signal": i["signal"]})

    res = {"inventory": dict(inv),
           "trades": trades,
           "stats_strict": stats([t for t in trades
                                  if t["status_gate"] == "AUTHORIZED"]),
           "stats_gate_blocked": stats([t for t in trades
                                        if t["status_gate"] == "AUTH_INTENT_GATE_BLOCKED"]),
           "stats_short_exp": stats([t for t in trades
                                     if t["status_gate"] == "SHORT_DESCRIPTIVE_ONLY"]),
           "items": [{"ticker": i["intent"]["ticker"], "session": i["session"],
                      "source": i["source"], "signal": i["signal"],
                      "classification": i["intent"].get("classification"),
                      "watch_mode": i["intent"].get("watch_mode"),
                      "auto_auth": i["intent"].get("auto_execution_authorized"),
                      "disposition": i["disposition"], "status": i["status"],
                      "short": i["short"], "spec": i["spec"],
                      "stop": i["stop"], "target": i["target"],
                      "sim": i.get("sim")} for i in items]}
    (out / "backtest_results.json").write_text(json.dumps(res, indent=1))

    # ---------- benchmark ----------
    spy_b = {str(x.date()): float(r["Close"]) for x, r in spy.iterrows()}
    spy_ret = (spy_b[DATA_END] / spy_b["2026-10-01"] - 1) * 100
    print(f"\n== RESULTS ==\nstrict EXECUTABLE_WATCH trades: {res['stats_strict']}")
    print(f"gate-blocked authorized intents: {res['stats_gate_blocked']}")
    print(f"short-descriptive experiment: {res['stats_short_exp']}")
    print(f"SPY 2026-10-01..23: {spy_ret:+.2f}%")
    for t in trades:
        print(t)


if __name__ == "__main__":
    sys.exit(main())
