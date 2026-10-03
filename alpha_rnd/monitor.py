#!/usr/bin/env python3
"""ALPHA_RND fast trigger monitor V1.

Watches frozen ALPHA_RND triggers only — no LLM, no TA inference.

Modes:
  --once     one evaluation pass (intraday if session open; close-pass if a
             new completed session exists). Suitable for cron.
  --loop     persistent daemon: ~60s intraday polling during US regular
             session + one close-pass per completed session.
  --status   human-readable book view (own / waiting / triggered / reanalysis).

Data: yfinance 1m bars (intraday) and daily bars (close conditions).
State: alpha_rnd/monitor_state.json  Events: alpha_rnd/trigger_events.jsonl
Notifications: alpha_rnd/NOTIFICATIONS.log (+ stdout)
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
D = ROOT / "alpha_rnd"
WATCHLIST = D / "live_watchlist.json"
STATE = D / "monitor_state.json"
EVENTS = D / "trigger_events.jsonl"
NOTIFY = D / "NOTIFICATIONS.log"

OPEN_HHMM = (13, 30)   # 13:30 UTC regular open (no DST/holiday table — see README)
CLOSE_HHMM = (20, 0)   # 20:00 UTC close
EXPIRY = "2026-10-30"
POS_NOTIONAL = 5000.0
MAX_POSITIONS = 10
COST_BPS = 0.001


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def session_open(dt: datetime) -> bool:
    return dt.weekday() < 5 and (dt.hour, dt.minute) >= OPEN_HHMM and (dt.hour, dt.minute) < CLOSE_HHMM


def load_state() -> dict:
    if STATE.exists():
        return json.loads(STATE.read_text())
    return {
        "last_check_utc": None,
        "processed_close_sessions": [],
        "confirm": {},          # ticker -> progress dict
        "pending_open_fills": [],  # fills waiting next-session open
        "positions": {},        # ticker -> {shares, fill, source}
        "cash": 85125.40,       # seeded from ledger 2026-10-02 mark
        "nav_last": 99844.50,
        "watch_status": {},     # ticker -> ACTIVE|TRIGGERED|EXPIRED|KILLED|REANALYSIS
    }


def save_state(st: dict) -> None:
    STATE.write_text(json.dumps(st, indent=1, default=str))


def emit(st: dict, ev: dict) -> None:
    ev["utc"] = now_utc().isoformat()
    with open(EVENTS, "a") as f:
        f.write(json.dumps(ev, default=str) + "\n")


def notify(text: str) -> None:
    stamp = now_utc().strftime("%Y-%m-%d %H:%MZ")
    block = f"\n===== {stamp} =====\n{text}\n"
    with open(NOTIFY, "a") as f:
        f.write(block)
    print(block)


def fetch_intraday(tickers: list[str]) -> dict[str, pd.DataFrame]:
    try:
        d = yf.download(tickers, period="1d", interval="1m", group_by="ticker",
                        progress=False, auto_adjust=True)
    except Exception:
        return {}
    out = {}
    for t in tickers:
        try:
            df = d[t].dropna() if len(tickers) > 1 else d.dropna()
            if not df.empty:
                out[t] = df
        except Exception:
            continue
    return out


def fetch_daily(tickers: list[str], days: int = 60) -> dict[str, pd.DataFrame]:
    end = now_utc().strftime("%Y-%m-%d")
    start = (now_utc() - timedelta(days=days * 2)).strftime("%Y-%m-%d")
    d = yf.download(tickers, start=start, end=end, group_by="ticker",
                    progress=False, auto_adjust=True)
    out = {}
    for t in tickers:
        try:
            df = d[t].dropna() if len(tickers) > 1 else d.dropna()
            if not df.empty:
                out[t] = df
        except Exception:
            continue
    return out


def last_close_session(daily: dict[str, pd.DataFrame]) -> str | None:
    dates = [df.index[-1] for df in daily.values() if len(df)]
    if not dates:
        return None
    return str(min(dates).date())


def do_fill(st: dict, wl: dict, ticker: str, price: float, frac: float, ev_type="PAPER_ENTRY") -> None:
    watch = next(w for w in wl["watches"] if w["ticker"] == ticker)
    if ticker in st["positions"]:
        emit(st, {"ticker": ticker, "action": "NO_ACTION", "why": "already_open"})
        return
    if len(st["positions"]) >= MAX_POSITIONS:
        emit(st, {"ticker": ticker, "action": "NO_ACTION", "why": "no_slots"})
        return
    notional = min(POS_NOTIONAL * frac, st["cash"] / (1 + COST_BPS))
    if notional < 500:
        emit(st, {"ticker": ticker, "action": "NO_ACTION", "why": "insufficient_cash"})
        return
    shares = int(notional / price)
    if shares <= 0:
        return
    cost = shares * price * (1 + COST_BPS)
    st["cash"] -= cost
    st["positions"][ticker] = {"shares": shares, "fill": price, "frac": frac,
                              "invalidation": watch["invalidation"], "horizon": watch["horizon"]}
    st["watch_status"][ticker] = "TRIGGERED"
    emit(st, {"ticker": ticker, "action": ev_type, "price": price, "shares": shares,
              "cost": round(cost, 2), "cls": watch["cls"], "invalidation": watch["invalidation"]})
    notify(f"""ALPHA_RND TRIGGER

{ticker}
Price: ${price:.2f}
Frozen entry: {watch['trigger'][:120]}
Class: {watch['cls']}

Action:
PAPER ENTRY recorded

Shares: {shares}
Price: ${price:.2f}
Stop: {watch['invalidation'][:80]}
Expected horizon: {watch['horizon']}""")


def close_pass(st: dict, wl: dict, daily: dict[str, pd.DataFrame], session: str) -> None:
    avgv = {t: df["Volume"].rolling(20).mean() for t, df in daily.items()}
    ret = {t: df["Close"].pct_change() for t, df in daily.items()}

    # ── position exits (close-based only; intraday stops handled live) ──
    for pos in wl["open_positions"]:
        t = pos["ticker"]
        if t not in st["positions"] or t not in daily:
            continue
        c = float(daily[t]["Close"].iloc[-1])
        for rule in pos["exit_rules"]:
            if rule["type"] == "close_below" and c < rule["level"]:
                px = c
                st["cash"] += st["positions"][t]["shares"] * px * (1 - COST_BPS)
                emit(st, {"ticker": t, "action": "PAPER_EXIT", "why": rule["label"],
                          "price": px, "session": session})
                notify(f"ALPHA_RND EXIT\n\n{t}\nInvalidation hit: {rule['label']}\nExit @ ${px:.2f} (close)")
                del st["positions"][t]

    for w in wl["watches"]:
        t = w["ticker"]
        if st["watch_status"].get(t) in ("TRIGGERED", "EXPIRED", "KILLED", "REANALYSIS"):
            continue
        if session > EXPIRY:
            st["watch_status"][t] = "EXPIRED"
            emit(st, {"ticker": t, "action": "WATCH_EXPIRED", "session": session})
            continue
        df = daily.get(t)
        if df is None or len(df) < 25:
            continue
        c = float(df["Close"].iloc[-1]); v = float(df["Volume"].iloc[-1])
        v20 = float(avgv[t].iloc[-1]) if not pd.isna(avgv[t].iloc[-1]) else 0
        p = w["params"]; tt = w["trigger_type"]
        prog = st["confirm"].setdefault(t, {})

        def triggered(how):
            st["watch_status"][t] = "TRIGGERED"
            emit(st, {"ticker": t, "action": "CONFIRMED", "how": how, "session": session,
                      "close": c, "vol": v})
            if w["cls"] == "REANALYZE_ON_TRIGGER":
                st["watch_status"][t] = "REANALYSIS"
                emit(st, {"ticker": t, "action": "REANALYSIS_REQUIRED",
                          "why": how, "session": session})
                notify(f"{t} TRIGGER\n\n{how}\n\nClass: REANALYZE_ON_TRIGGER\n\nAction: NO BUY YET — single-ticker refresh required.")
            else:
                st["pending_open_fills"].append({"ticker": t, "frac": w["size_frac"],
                                                 "why": how, "confirm_session": session})
                emit(st, {"ticker": t, "action": "PENDING_NEXT_OPEN", "session": session})

        # mechanical evaluators
        if "multi_close_in_zone" in tt:
            z = p["zone"]; n = p.get("closes_required", 2)
            in_zone = ((df["Close"] >= z[0]) & (df["Close"] <= z[1]))
            consec = int(in_zone.iloc[::-1].cumprod().sum())
            prog["consec_in_zone"] = consec
            if consec >= n:
                triggered(f"{n} consecutive closes inside {z}")
        if "close_in_zone_low_vol" in tt:
            for zk in ("zone", "zone1"):
                if zk in p:
                    z = p[zk]
                    if z[0] <= c <= z[1] and v < v20:
                        triggered(f"close {c} in {z} on declining volume ({v:.0f}<{v20:.0f})")
        if "close_in_zone" in tt and "zone2" in p:
            z = p["zone2"]
            if z[0] <= c <= z[1]:
                triggered(f"close {c} inside shelf zone {z}")
        if "close_breakout_vol" in tt:
            lvl = p["bo_level"]; vmin = max(p.get("vol_min", 0), v20 if "vol_min" not in p else 0)
            if c > lvl and v >= vmin:
                triggered(f"close {c}>{lvl} on vol {v:.0f}>={vmin:.0f}")
            elif c > lvl and "vol_min" not in p and v > v20:
                triggered(f"close {c}>{lvl} on vol {v:.0f}>{v20:.0f}")
        if "close_breakout_retest" in tt:
            if c > p["bo_level"] and v > v20:
                prog["breakout_armed"] = True
        if "orderly_pullback_close" in tt:
            z = p["pb_zone"]
            if z[0] <= c <= z[1]:
                mx = float(ret[t].iloc[-5:].abs().max())
                if mx < p.get("gap_guard", 0.08):
                    triggered(f"orderly pullback close {c} in {z}, max|ret|={mx:.3f}")
        if "weekly_close_breakout" in tt and df.index[-1].weekday() == 4 and len(df) >= 10:
            wk_close = float(df["Close"].iloc[-1])
            wk_vol = float(df["Volume"].iloc[-5:].sum())
            prev_vol = float(df["Volume"].iloc[-10:-5].sum())
            if wk_close > p["alt_level"] and wk_vol > prev_vol:
                triggered(f"weekly close {wk_close}>{p['alt_level']} on re-expanding volume")
        if "reclaim_2step" in tt:
            if not prog.get("reclaim") and c > p["reclaim"]:
                prog["reclaim"] = session
            elif prog.get("reclaim") and prog["reclaim"] != session and c > p["hold"]:
                triggered(f"reclaim {p['reclaim']} + hold >{p['hold']} confirmed")
        if "gapfill_probe" in tt:
            if c < p["kill"]:
                st["watch_status"][t] = "KILLED"
                emit(st, {"ticker": t, "action": "NO_ACTION", "why": f"close<{p['kill']} kills triggers"})
                continue
            z = p["probe_zone"]
            if z[0] <= c <= z[1] and c < float(df["Close"].iloc[-2]) and v < float(df["Volume"].iloc[-2]):
                triggered(f"gap-fill probe close {c} in {z} after down day on lighter volume")
        if "event_gated_multi_close" in tt:
            if session >= p["gate_date"]:
                above = (df["Close"] > p["level"])
                consec = int(above.iloc[::-1].cumprod().sum())
                if consec >= p.get("closes_required", 3):
                    triggered(f"{consec} closes >{p['level']} post-{p['gate_date']}")
        if "close_breakout" in tt and "bo_level" in p and tt.endswith("close_breakout"):
            if c > p["bo_level"] and v > v20:
                triggered(f"close {c}>{p['bo_level']} expanding vol")
        # REANALYZE price legs
        if w["cls"] == "REANALYZE_ON_TRIGGER":
            for lv in p.get("levels", []):
                if float(df["Low"].iloc[-1]) <= lv:
                    triggered(f"price touched {lv}")
                    break
            z = p.get("zone")
            if z and float(df["Low"].iloc[-1]) <= z[1]:
                triggered(f"price into zone {z}")
            if p.get("bo_level") and c > p["bo_level"] and v > v20:
                triggered(f"close {c}>{p['bo_level']} expanding vol")

        # TWST-style veto handled by 'veto_level'
        if p.get("veto_level") and c < p["veto_level"] and v > v20 and st["watch_status"].get(t) != "TRIGGERED":
            st["watch_status"][t] = "KILLED"
            emit(st, {"ticker": t, "action": "NO_ACTION", "why": f"veto: close {c}<{p['veto_level']} heavy vol"})


def intraday_pass(st: dict, wl: dict) -> None:
    tickers = [w["ticker"] for w in wl["watches"]
               if st["watch_status"].get(w["ticker"]) not in ("TRIGGERED", "EXPIRED", "KILLED", "REANALYSIS")]
    pos_tickers = [p["ticker"] for p in wl["open_positions"] if p["ticker"] in st["positions"]]
    data = fetch_intraday(list(set(tickers + pos_tickers)))
    for t in pos_tickers:
        pos = next(p for p in wl["open_positions"] if p["ticker"] == t)
        inv = pos["invalidation"]
        df = data.get(t)
        if df is None:
            continue
        low = float(df["Low"].min())
        if inv["type"] == "intraday_stop" and low <= inv["level"]:
            px = inv["level"]
            st["cash"] += st["positions"][t]["shares"] * px * (1 - COST_BPS)
            emit(st, {"ticker": t, "action": "PAPER_EXIT", "why": "intraday stop",
                      "price": px})
            notify(f"ALPHA_RND EXIT\n\n{t}\nHard stop {px} hit intraday\nExit @ ${px:.2f}")
            del st["positions"][t]

    for w in wl["watches"]:
        t = w["ticker"]
        if st["watch_status"].get(t) in ("TRIGGERED", "EXPIRED", "KILLED", "REANALYSIS"):
            continue
        if now_utc().strftime("%Y-%m-%d") > EXPIRY:
            continue
        df = data.get(t)
        if df is None:
            continue
        low = float(df["Low"].min()); p = w["params"]
        # AUTO_ENTRY zone touch -> immediate fill at zone top
        if w["cls"] == "AUTO_ENTRY" and low <= p["zone"][1]:
            do_fill(st, wl, t, p["zone"][1], w["size_frac"])
            continue
        # deterministic intraday legs
        if "intraday_zone_touch" in w["trigger_type"] and w["cls"] == "DETERMINISTIC_CONFIRMATION":
            if low <= p["pb_zone"][1]:
                do_fill(st, wl, t, p["pb_zone"][1], w["size_frac"])
                continue
        prog = st["confirm"].get(t, {})
        if prog.get("breakout_armed") and "retest_zone" in p and low <= p["retest_zone"][1]:
            do_fill(st, wl, t, p["retest_zone"][1], w["size_frac"])
            continue


def settle_pending(st: dict, wl: dict, daily: dict[str, pd.DataFrame], session: str) -> None:
    """Fill PENDING_NEXT_OPEN orders at the first open of a session AFTER the
    confirmation session. Called when a new completed session appears."""
    still = []
    for od in st["pending_open_fills"]:
        t = od["ticker"]
        df = daily.get(t)
        if df is None:
            still.append(od)
            continue
        newer = df[df.index > pd.Timestamp(od["confirm_session"])]
        if newer.empty:
            still.append(od)
            continue
        px = float(newer.iloc[0]["Open"])  # open of first session after confirmation
        do_fill(st, wl, t, px, od.get("frac", 1.0))
    st["pending_open_fills"] = [od for od in still if od["ticker"] not in st["positions"]]


def run_once(st: dict, wl: dict) -> None:
    daily = fetch_daily([w["ticker"] for w in wl["watches"]] +
                        [p["ticker"] for p in wl["open_positions"]])
    sess = last_close_session(daily)
    MIN_EVAL_SESSION = "2026-10-03"  # triggers frozen 10-02/10-03: no retro eval
    if sess and sess > MIN_EVAL_SESSION and sess not in st["processed_close_sessions"]:
        st["processed_close_sessions"].append(sess)  # mark seen, evaluate below
    elif sess and sess <= MIN_EVAL_SESSION and sess not in st["processed_close_sessions"]:
        st["processed_close_sessions"].append(sess)  # skip pre-freeze sessions entirely
        sess = None
    if sess:
        # fill next-open orders using the NEW session's open
        settle_pending(st, wl, daily, sess)
        close_pass(st, wl, daily, sess)
    if session_open(now_utc()):
        intraday_pass(st, wl)
    st["last_check_utc"] = now_utc().isoformat()
    save_state(st)


def status(wl: dict, st: dict) -> str:
    lines = ["OPEN", ""]
    for p in wl["open_positions"]:
        t = p["ticker"]
        pos = st["positions"].get(t)
        if pos:
            lines += [f"{t}", f"entry ${pos['fill']}", p["style"].lower().replace("_", " "),
                      f"next review {p['reeval']}", f"stop {p['invalidation']['label']} @{p['invalidation']['level']}", ""]
    lines += ["WATCHING", ""]
    for w in wl["watches"]:
        s = st["watch_status"].get(w["ticker"], "ACTIVE")
        if s in ("TRIGGERED",):
            continue
        lines += [f"{w['ticker']}  [{s}]", f"waiting for {w['trigger'][:110]}",
                  f"{w['horizon']} | class {w['cls']}", ""]
    lines += ["TRIGGERED / POSITIONS", ""]
    for t, pos in st["positions"].items():
        src = "watch fill" if t not in [p["ticker"] for p in wl["open_positions"]] else "V1 fill"
        lines += [f"{t}  {pos['shares']}sh @{pos['fill']} ({src})"]
    lines += ["", f"cash ${st['cash']:,.2f}", ""]
    return "\n".join(lines)


def main() -> None:
    wl = json.loads(WATCHLIST.read_text())
    st = load_state()
    # seed V1 positions once
    for p in wl["open_positions"]:
        if p["ticker"] not in st["positions"]:
            st["positions"][p["ticker"]] = {"shares": p["shares"], "fill": p["fill"],
                                           "invalidation": p["invalidation"]["label"],
                                           "horizon": p["horizon"], "seeded": True}
    if "--status" in sys.argv:
        print(status(wl, st))
        return
    if "--loop" in sys.argv:
        while True:
            try:
                run_once(st, wl)
            except Exception as e:
                emit(st, {"action": "NO_ACTION", "why": f"monitor_error {e!r}"})
            time.sleep(60)
    else:
        run_once(st, wl)
        print(f"checked {st['last_check_utc']}")


if __name__ == "__main__":
    main()
