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
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import re
from contextlib import contextmanager
import fcntl
import hashlib

import pandas as pd
import yfinance as yf

from alpha_rnd.entry_gate import authorized

ROOT = Path(__file__).resolve().parents[1]
D = ROOT / "alpha_rnd"
WATCHLIST = D / "live_watchlist.json"
STATE = D / "monitor_state.json"
STATE_LOCK = D / "monitor_state.lock"
EVENTS = D / "trigger_events.jsonl"
LEDGER = ROOT / "evaluations" / "alpha_rnd_v1" / "alpha_paper_ledger.jsonl"
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
        st = json.loads(STATE.read_text())
        st.setdefault("pending_open_fills", [])
        st.setdefault("pending_open_exits", [])
        # migrate watch-fill positions: derive typed stop_rule from the
        # frozen invalidation text if missing (e.g. PGEN "stop $7.75")
        for pos in st.get("positions", {}).values():
            if "stop_rule" not in pos and isinstance(pos.get("invalidation"), str) \
                    and not pos.get("integrity_review") and not pos.get("stop_suspended"):
                mm = re.search(r"stop \$?(\d+\.?\d*)", pos["invalidation"])
                if mm:
                    pos["stop_rule"] = {"type": "intraday_stop",
                                        "level": float(mm.group(1)),
                                        "label": pos["invalidation"]}
        return st
    raise RuntimeError(
        "monitor_state.json MISSING — canonical book absent. FAIL CLOSED: "
        "no seeding, no trading. Manual review required.")


def save_state(st: dict) -> None:
    """Atomic replace: tmp file + os.replace — a crash cannot leave a
    truncated canonical state."""
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, indent=1, default=str))
    tmp.replace(STATE)


@contextmanager
def locked_state():
    """Single canonical mutation path: kernel flock serializes every
    read-modify-write of monitor_state.json (cron ticks, pending-order
    resolution, EOD marks, AND manual ops utilities). Yield the state; the
    (possibly mutated) dict is atomically written back on clean exit.
    Event records are queued in a durable outbox INSIDE the state, so a
    crash between transition and log-write cannot replay duplicates."""
    with STATE_LOCK.open("w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        st = load_state()
        yield st
        save_state(st)
        if _flush_outbox(st):
            save_state(st)


def _ev_hash(ev: dict) -> str:
    return "sha:" + hashlib.sha256(
        json.dumps(ev, sort_keys=True, default=str).encode()).hexdigest()[:24]


def _flush_outbox(st: dict) -> bool:
    """Append queued event records to the immutable JSONL — idempotent.
    A crash between JSONL append and outbox-clear re-attempts the same
    records; the tail dedup (bounded scan, guard only) prevents any
    duplicate durable line. Returns True if the outbox was consumed."""
    ob = st.get("event_outbox") or []
    if not ob:
        return False
    known_ids, known_hashes = set(), set()
    if EVENTS.exists():
        for line in EVENTS.read_text().splitlines()[-500:]:
            try:
                e = json.loads(line)
            except Exception:
                continue
            if e.get("event_id"):
                known_ids.add(e["event_id"])
            known_hashes.add(_ev_hash(e))
    with open(EVENTS, "a") as f:
        for ev in ob:
            if (ev.get("event_id") and ev["event_id"] in known_ids) \
                    or _ev_hash(ev) in known_hashes:
                continue
            f.write(json.dumps(ev, default=str) + "\n")
    st["event_outbox"] = []
    return True


def emit(st: dict, ev: dict) -> None:
    ev["utc"] = now_utc().isoformat()
    st.setdefault("event_outbox", []).append(ev)


def emit_once(st: dict, ev: dict, event_id: str) -> bool:
    """Global exactly-once for user-visible transitions: same semantic
    transition + same immutable provenance = at most one durable event.
    Dedup registry lives in canonical state (bounded); the stamped event_id
    also lets the relay suppress any residual duplicate."""
    if event_id in st.setdefault("emitted_ids", []):
        return False
    ev["event_id"] = event_id
    emit(st, ev)
    ids = st["emitted_ids"]
    ids.append(event_id)
    st["emitted_ids"] = ids[-5000:]
    return True


def _queue_executed_notification(st: dict, text: str) -> None:
    """Execution claims are queued on the state being mutated and emitted
    only by _drain_notifications AFTER that state is durably saved. If the
    save never happens (exception/crash/discarded tick), the notification
    never fires — a fill claim can never precede its durable authority."""
    st.setdefault("deferred_notifications", []).append(text)


def _drain_notifications(st: dict) -> None:
    """Pop queued execution notifications, persist the consumed queue,
    then emit. A crash between save and emit can lose a real notification
    (fail-safe) but can never create a false one."""
    msgs = st.pop("deferred_notifications", None)
    if not msgs:
        return
    save_state(st)
    for m in msgs:
        notify(m)


def notify(text: str) -> None:
    stamp = now_utc().strftime("%Y-%m-%d %H:%MZ")
    block = f"\n===== {stamp} =====\n{text}\n"
    with open(NOTIFY, "a") as f:
        f.write(block)
    print(block)
    desktop_notify("ALPHA_RND", text.split("\n", 1)[0] + " — " +
                   " ".join(text.split())[:180])


def desktop_notify(title: str, body: str) -> None:
    """Best-effort visible local notification (libnotify). Works from cron
    because DISPLAY/DBUS are set explicitly; silently no-ops if unavailable."""
    import shutil
    import subprocess
    if not shutil.which("notify-send"):
        return
    env = dict(os.environ)
    env.setdefault("DISPLAY", ":1")
    env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path=/run/user/{os.getuid()}/bus")
    try:
        subprocess.run(["notify-send", "-u", "critical", "-t", "0",
                        title, body], env=env, timeout=10,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


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


RISK_GUARDRAIL_FROM = "2026-10-07"  # policy-version boundary (prospective only)


def entry_success_plan(watch: dict) -> tuple[bool, str]:
    """Executable long entry must define SUCCESS, not only failure.
    Plan derived from the watch's own fields (target/params/horizon) —
    legacy prose is used, never invented. Fail-closed."""
    from alpha_rnd.success_plan import extract, validate, _hi
    p = watch.get("params") or {}
    plan = extract({"target": watch.get("target"),
                    "success_criteria": watch.get("invalidation") and
                    (p.get("success_criteria") or watch.get("horizon")),
                    "profit_realization_plan": watch.get("target") or
                    p.get("profit_realization_plan")})
    stop = post_entry_risk_plan(watch)
    entry = p.get("entry_price") or p.get("primary_limit")
    v, errs = validate(plan, entry or 0, (stop or {}).get("level"),
                       None)
    return (v is not None), ("; ".join(errs) if errs else "ok")


def post_entry_risk_plan(watch: dict) -> dict | None:
    """Machine-actionable POST-ENTRY risk rule, or None.
    Qualifying: typed intraday stop; typed close/exit rule; explicit typed
    stop_rule on the spec; legacy numeric 'stop $X' still parseable (existing
    migration fallback, marked). A horizon alone, NOT_STATED, or a pre-entry
    veto does NOT qualify."""
    inv = watch.get("invalidation")
    if isinstance(inv, dict) and inv.get("type") in (
            "intraday_stop", "close_below", "price_below"):
        return inv
    sr = watch.get("stop_rule")
    if isinstance(sr, dict) and sr.get("type") == "intraday_stop":
        return sr
    for r in watch.get("exit_rules") or []:
        if r.get("type") in ("intraday_stop", "close_below"):
            return r
    mm = re.search(r"stop \$?(\d+\.?\d*)", str(inv or ""))
    if mm:
        return {"type": "intraday_stop", "level": float(mm.group(1)),
                "legacy_parsed": True}
    return None


def _render_invalidation(inv) -> str:
    """Render watch/position invalidation for logs/notifications. Strings
    pass through unchanged; structured dict rules render as
    '<type> <level> (<label>)'; None renders 'none'. Display only — never
    changes economics, authorization, or stop behavior."""
    if inv is None:
        return "none"
    if isinstance(inv, dict):
        base = " ".join(str(x) for x in (inv.get("type"), inv.get("level"))
                        if x is not None) or str(inv)
        lbl = inv.get("label")
        return f"{base} ({lbl})" if lbl else base
    return str(inv)


def _watch_rev(w: dict) -> str:
    """Immutable watch-revision identity for risk-block idempotency: tied to
    the frozen publication artifact + revision, not the wall clock."""
    return f"{w.get('artifact')}#{w.get('v', '')}"


TERMINAL_WATCH = {"TRIGGERED", "EXPIRED", "KILLED", "RISK_PLAN_REQUIRED",
                  "RETIRED"}


def _set_watch_status(st: dict, w: dict, status: str) -> None:
    """Single watch-status write path. Terminal transitions also record a
    durable lifecycle entry {status, rev, session} keyed to the watch
    revision — publish() uses it to block resurrection of a retired/superseded
    revision while still allowing a genuinely NEWER one."""
    t = w["ticker"]
    st["watch_status"][t] = status
    if status in TERMINAL_WATCH:
        rev = _watch_rev(w)
        sess = rev.split("#", 1)[0].rsplit("_", 1)[-1].split(".")[0]
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", sess or ""):
            sess = None  # unknown revision session -> publish fails closed
        st.setdefault("watch_lifecycle", {})[t] = {
            "status": status, "rev": rev, "session": sess,
            "at": now_utc().isoformat()}


def _risk_blocked(st: dict, w: dict) -> bool:
    """True while the SAME watch revision stays blocked. A new published
    revision (different artifact/v) is evaluated again."""
    return st.get("watch_status", {}).get(w["ticker"]) == "RISK_PLAN_REQUIRED" \
        and st.get("risk_blocked", {}).get(w["ticker"]) == _watch_rev(w)


def _exec_check(st: dict, exec_id: str) -> bool:
    """Exactly-once guard, phase 1: True if fresh (not yet recorded)."""
    if exec_id in st.setdefault("executed", []):
        emit(st, {"action": "NO_ACTION", "why": f"duplicate_suppressed {exec_id}"})
        return False
    return True


def _exec_commit(st: dict, exec_id: str) -> None:
    """Phase 2: record AFTER the book mutation succeeded."""
    done = st.setdefault("executed", [])
    if exec_id not in done:
        done.append(exec_id)
    st["executed"] = done[-2000:]


def do_fill(st: dict, wl: dict, ticker: str, price: float, frac: float, ev_type="PAPER_ENTRY", exec_id: str | None = None) -> None:
    watch = next(w for w in wl["watches"] if w["ticker"] == ticker)
    if watch["cls"] != "REANALYZE_ON_TRIGGER" and not authorized(watch):
        emit_once(st, {"ticker": ticker, "action": "NO_ACTION",
                  "why": "entry_not_authorized: fill refused"},
                  f"entry_gate_fill:{ticker}:{_watch_rev(watch)}")
        return
    if ticker in st["positions"]:
        emit(st, {"ticker": ticker, "action": "NO_ACTION", "why": "already_open"})
        return
    if not post_entry_risk_plan(watch):
        _set_watch_status(st, watch, "RISK_PLAN_REQUIRED")
        st.setdefault("risk_blocked", {})[ticker] = _watch_rev(watch)
        emit_once(st, {"ticker": ticker, "action": "RISK_PLAN_REQUIRED",
                  "why": "entry triggered but frozen plan has no explicit "
                         "machine-actionable post-entry risk/exit rule; "
                         "interesting stock, incomplete risk plan — NOT BOUGHT"},
                  f"risk_block:{ticker}:{_watch_rev(watch)}")
        notify(f"ALPHA_RND RISK PLAN REQUIRED — NOT AUTO-EXECUTABLE\n\n{ticker}\n"
               "TA identified an entry opportunity but provided no explicit "
               "post-entry risk/exit rule.\nStatus: NOT BOUGHT.\nUSER ACTION: NONE")
        return
    ok_sp, why_sp = entry_success_plan(watch)
    if not ok_sp:
        emit_once(st, {"ticker": ticker, "action": "NO_ACTION",
                  "why": "success_plan_required: no valid upside/profit "
                         f"objective ({why_sp}) — NOT BOUGHT"},
                  f"success_plan_block:{ticker}:{_watch_rev(watch)}")
        return
    if len(st["positions"]) >= MAX_POSITIONS:
        emit(st, {"ticker": ticker, "action": "NO_ACTION", "why": "no_slots"})
        return
    if exec_id and not _exec_check(st, exec_id):
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
    # canonical typed stop from the watch spec; prose parse = legacy fallback only
    stop = dict(watch.get("stop_rule") or {})
    if not stop:
        mm = re.search(r"stop \$?(\d+\.?\d*)", str(watch["invalidation"]))
        if mm:
            stop = {"type": "intraday_stop", "level": float(mm.group(1)),
                    "label": watch["invalidation"], "legacy_parsed": True}
    _exec_commit(st, exec_id) if exec_id else None
    st["positions"][ticker] = {"shares": shares, "fill": price, "frac": frac,
                              "cost": cost,
                              "invalidation": watch["invalidation"],
                              "horizon": watch["horizon"], "stop_rule": stop,
                              "entry_session": now_utc().strftime("%Y-%m-%d")}
    try:  # shadow management snapshot — failure must never block a fill
        from alpha_rnd import mgmt as _mgmt
        _mgmt.create_snapshot(ticker, st["positions"][ticker]["entry_session"],
                              watch=watch, pos=st["positions"][ticker],
                              intent=_mgmt._latest_intent(ticker),
                              artifact_ref=watch.get("artifact"))
    except Exception:
        pass
    _set_watch_status(st, watch, "TRIGGERED")
    emit_once(st, {"ticker": ticker, "action": ev_type, "price": price,
              "shares": shares,
              "cost": round(cost, 2), "cls": watch["cls"], "invalidation": watch["invalidation"]},
              f"paper_entry:{exec_id or ticker + ':' + now_utc().strftime('%Y-%m-%d')}")
    _queue_executed_notification(st, f"""ALPHA_RND PAPER ENTRY EXECUTED

{ticker}
Price: ${price:.2f}
Frozen entry: {watch['trigger'][:120]}
Class: {watch['cls']}

Shares: {shares}
Price: ${price:.2f}
Stop: {_render_invalidation(watch['invalidation'])[:80]}
Expected horizon: {watch['horizon']}""")


def do_exit(st: dict, ticker: str, price: float, why: str, how: str = "",
            shares: int | None = None, exec_id: str | None = None) -> None:
    pos = st["positions"].get(ticker)
    if pos is None:
        return
    if exec_id and not _exec_check(st, exec_id):
        return
    sell = min(shares or pos["shares"], pos["shares"])
    proceeds = sell * price * (1 - COST_BPS)
    st["cash"] += proceeds
    pos["shares"] -= sell
    _exec_commit(st, exec_id) if exec_id else None
    if pos["shares"] <= 0:
        st["positions"].pop(ticker)
        if pos.get("seeded"):
            st.setdefault("retired_seeds", []).append(ticker)
        # consume any competing pending exits for this ticker: one position
        # => one authoritative exit intent; no orphan orders after close
        st["pending_open_exits"] = [
            o for o in st["pending_open_exits"] if o["ticker"] != ticker]
    # alloc = pro-rata cost of the shares being sold. For cost-less positions
    # (seeded/legacy) the default must be ORIGINAL shares x fill, else a
    # negative basis gets written back and realized P&L inflates on the next
    # exit (SDGR incident 2026-10-13).
    orig = pos.get("cost", pos["fill"] * (pos["shares"] + sell))
    alloc = orig * (sell / (pos["shares"] + sell))
    st["realized"] = round(st.get("realized", 0.0) + proceeds - alloc, 2)
    if pos["shares"] > 0:
        pos["cost"] = round(orig - alloc, 2)
    emit_once(st, {"ticker": ticker, "action": "PAPER_EXIT", "why": why,
              "price": price, "shares": sell, "proceeds": round(proceeds, 2)},
              f"paper_exit:{exec_id or ticker + ':' + why}")
    _queue_executed_notification(
        st, f"ALPHA_RND PAPER EXIT EXECUTED\n\n{ticker}\n{why}\n"
            f"Exit @ ${price:.2f}\nProceeds ${proceeds:,.2f}")


def resolve_pending(st: dict, wl: dict, daily: dict[str, pd.DataFrame],
                    current_session_date: str, live: bool = True,
                    intraday: dict[str, pd.DataFrame] | None = None) -> None:
    """Execute pending next-open orders at the ACTUAL open of the first
    session after confirm_session — only while that session is live.
    If its open is already fully in the past (live=False close-pass counts the
    just-closed session as past too), mark MISSED — no retroactive fill."""
    for kind, queue, is_exit in (("entry", st["pending_open_fills"], False),
                                 ("exit", st["pending_open_exits"], True)):
        keep = []
        for od in queue:
            t = od["ticker"]
            od.setdefault("order_id", f"{kind}:{t}:{od['confirm_session']}:{str(od.get('why'))[:24]}")
            if od["order_id"] in st.setdefault("executed", []):
                continue  # already executed exactly once
            if od.get("blocked"):
                keep.append(od)
                continue
            df = daily.get(t)
            if df is None:
                keep.append(od)
                continue
            dates = sorted(str(d.date()) for d in df.index)
            after = [d for d in dates if d > od["confirm_session"]]
            if not after:
                # the daily frame excludes the still-open session (end is
                # exclusive) — during the live target session, the intraday
                # frame IS today's bar set
                idf = (intraday or {}).get(t)
                if live and idf is not None and len(idf) and \
                        str(idf.index[0].date()) == current_session_date \
                        and current_session_date > od["confirm_session"]:
                    px = float(idf["Open"].iloc[0])
                    if _exec_check(st, od["order_id"]):
                        if is_exit:
                            do_exit(st, t, px, od["why"], shares=od.get("shares"))
                        else:
                            do_fill(st, wl, t, px, od.get("frac", 1.0))
                        _exec_commit(st, od["order_id"])
                    continue
                keep.append(od)
                continue
            target = after[0]
            missed = target < current_session_date or (not live and target <= current_session_date)
            if missed:
                if emit_once(st, {"ticker": t, "action": "MISSED_EXECUTION_REVIEW_REQUIRED",
                          "kind": kind, "why": od.get("why"), "confirm_session": od["confirm_session"],
                          "missed_session": target},
                          f"missed:{kind}:{t}:{od['confirm_session']}:{target}"):
                    notify(f"ALPHA_RND MISSED EXECUTION\n\n{t}\nTarget open {target} already passed (machine off at open?).\nManual review required — no retroactive fill.")
                continue
            px = float(df[df.index.strftime("%Y-%m-%d") == target]["Open"].iloc[0])
            if _exec_check(st, od["order_id"]):
                if is_exit:
                    do_exit(st, t, px, od["why"], shares=od.get("shares"))
                else:
                    do_fill(st, wl, t, px, od.get("frac", 1.0))
                _exec_commit(st, od["order_id"])
        queue[:] = keep


def close_pass(st: dict, wl: dict, daily: dict[str, pd.DataFrame], session: str) -> None:
    avgv = {t: df["Volume"].rolling(20).mean() for t, df in daily.items()}
    ret = {t: df["Close"].pct_change() for t, df in daily.items()}

    # typed close-below stop_rule on ANY open position (e.g. post-entry
    # management rules from a fresh review) -> PENDING_NEXT_OPEN exit
    for t, p in list(st["positions"].items()):
        sr = p.get("stop_rule") or {}
        if sr.get("type") == "close_below" and t in daily and t not in {
                o["ticker"] for o in st["pending_open_exits"]}:
            c = float(daily[t]["Close"].iloc[-1])
            if c < sr["level"]:
                st["pending_open_exits"].append(
                    {"ticker": t, "why": sr.get("label", f"close<{sr['level']}"),
                     "confirm_session": session,
                     "order_id": f"close_below:{t}:{session}"})
                if emit_once(st, {"ticker": t, "action": "CONFIRMED_PENDING_NEXT_OPEN_EXIT",
                          "why": sr.get("label"), "confirm_close": c, "session": session},
                          f"exit_confirmed:close_below:{t}:{session}"):
                    notify(f"ALPHA_RND EXIT CONFIRMED — PENDING NEXT OPEN\n\n{t}\n"
                       f"{sr.get('label')}\nConfirming close ${c:.2f}")

    # ── position exits: close-confirmed rules -> PENDING_NEXT_OPEN exit ──
    for pos in wl["open_positions"]:
        t = pos["ticker"]
        if t not in st["positions"] or t not in daily:
            continue
        if any(o["ticker"] == t for o in st["pending_open_exits"]):
            continue
        c = float(daily[t]["Close"].iloc[-1])
        for rule in pos["exit_rules"]:
            if rule["type"] == "close_below" and c < rule["level"]:
                lbl = rule.get("label", f"close<{rule['level']}")
                st["pending_open_exits"].append({"ticker": t, "why": lbl,
                                                 "confirm_session": session})
                if emit_once(st, {"ticker": t, "action": "CONFIRMED_PENDING_NEXT_OPEN_EXIT",
                          "why": lbl, "confirm_close": c, "session": session},
                          f"exit_confirmed:close_below:{t}:{session}"):
                    notify(f"ALPHA_RND EXIT CONFIRMED — PENDING NEXT OPEN\n\n{t}\n{lbl}\nConfirming close ${c:.2f}\nExits at next regular-session open.")

    for w in wl["watches"]:
        t = w["ticker"]
        if st["watch_status"].get(t) in ("TRIGGERED", "EXPIRED", "KILLED", "REANALYSIS") \
                or _risk_blocked(st, w):
            continue
        if w["cls"] != "REANALYZE_ON_TRIGGER" and not authorized(w):
            emit_once(st, {"ticker": t, "action": "NO_ACTION",
                      "why": "entry_not_authorized: watch revision is not the latest EXECUTABLE_WATCH decision"},
                      f"entry_gate:{t}:{_watch_rev(w)}")
            continue
        if session > EXPIRY:
            _set_watch_status(st, w, "EXPIRED")
            emit_once(st, {"ticker": t, "action": "WATCH_EXPIRED", "session": session},
                      f"expired:{t}:{session}")
            continue
        df = daily.get(t)
        if df is None or len(df) < 25:
            continue
        c = float(df["Close"].iloc[-1]); v = float(df["Volume"].iloc[-1])
        v20 = float(avgv[t].iloc[-1]) if not pd.isna(avgv[t].iloc[-1]) else 0
        p = w["params"]; tt = w.get("trigger_type") or ""
        prog = st["confirm"].setdefault(t, {})

        # malformed watch: evaluator named in trigger_type needs these params;
        # missing params => skip the watch fail-closed, never crash the pass
        _REQ = {"multi_close_in_zone": ("zone",),
                "close_breakout_vol": ("bo_level",),
                "close_breakout_retest": ("bo_level",),
                "orderly_pullback_close": ("pb_zone",),
                "reclaim_2step": ("reclaim", "hold"),
                "gapfill_probe": ("kill", "probe_zone"),
                "event_gated_multi_close": ("gate_date", "level")}
        _missing = [f"{tt_}:{k}" for tt_, ks in _REQ.items() if tt_ in tt
                    for k in ks if k not in p]
        if _missing:
            emit_once(st, {"ticker": t, "action": "NO_ACTION",
                      "why": f"missing_trigger_params {_missing}"},
                      f"schema:{t}:{_watch_rev(w)}:{','.join(_missing)}"[:100])
            continue

        def triggered(how):
            _set_watch_status(st, w, "TRIGGERED")
            emit_once(st, {"ticker": t, "action": "CONFIRMED", "how": how,
                      "session": session, "close": c, "vol": v},
                      f"confirmed:{t}:{_watch_rev(w)}")
            if w["cls"] == "REANALYZE_ON_TRIGGER":
                _set_watch_status(st, w, "REANALYSIS")
                emit_once(st, {"ticker": t, "action": "REANALYSIS_REQUIRED",
                          "why": how, "session": session},
                          f"reanalysis:{t}:{_watch_rev(w)}")
                notify(f"{t} TRIGGER\n\n{how}\n\nClass: REANALYZE_ON_TRIGGER\n\nAction: NO BUY YET — single-ticker refresh required.")
            else:
                # Fill-time guardrail belongs at confirmation too: never
                # announce "ENTRY CONFIRMED" for a plan that cannot execute.
                if not post_entry_risk_plan(w):
                    _set_watch_status(st, w, "RISK_PLAN_REQUIRED")
                    st.setdefault("risk_blocked", {})[t] = _watch_rev(w)
                    emit_once(st, {"ticker": t, "action": "RISK_PLAN_REQUIRED",
                              "how": how, "session": session,
                              "why": "trigger confirmed but no machine-actionable "
                                     "post-entry risk plan — NOT AUTO-EXECUTABLE"},
                              f"risk_block:{t}:{_watch_rev(w)}")
                    notify(f"ALPHA_RND TRIGGER — NOT AUTO-EXECUTABLE\n\n{t}\n{how}\n"
                           "No machine-actionable post-entry risk plan.\n"
                           "Status: NOT BOUGHT. USER ACTION: NONE")
                else:
                    st["pending_open_fills"].append({"ticker": t, "frac": w["size_frac"],
                                                     "why": how, "confirm_session": session})
                    emit_once(st, {"ticker": t, "action": "CONFIRMED_PENDING_NEXT_OPEN_ENTRY",
                              "how": how, "session": session},
                              f"entry_confirmed:{t}:{session}:{how[:24]}")
                    notify(f"ALPHA_RND ENTRY CONFIRMED — PENDING NEXT OPEN\n\n{t}\n{how}\nClass: {w['cls']}\nEnters at next regular-session open.")

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
                _set_watch_status(st, w, "KILLED")
                emit_once(st, {"ticker": t, "action": "NO_ACTION", "why": f"close<{p['kill']} kills triggers"},
                          f"killed:{t}:{_watch_rev(w)}")
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
            _set_watch_status(st, w, "KILLED")
            emit_once(st, {"ticker": t, "action": "NO_ACTION", "why": f"veto: close {c}<{p['veto_level']} heavy vol"},
                          f"veto:{t}:{_watch_rev(w)}")


def intraday_pass(st: dict, wl: dict, daily: dict[str, pd.DataFrame]) -> int:
    tickers = [w["ticker"] for w in wl["watches"]
               if st["watch_status"].get(w["ticker"]) not in ("TRIGGERED", "EXPIRED", "KILLED", "REANALYSIS")
               and not _risk_blocked(st, w)]
    wl_pos = {p["ticker"]: p for p in wl["open_positions"]}
    pos_tickers = list(st["positions"])  # ALL open positions, incl. watch fills
    pend = {o["ticker"] for o in st["pending_open_fills"]} | {o["ticker"] for o in st["pending_open_exits"]}
    wanted = list(set(tickers + pos_tickers + list(pend)))
    data = fetch_intraday(wanted)
    st.setdefault("data_health", {})["intraday_ok"] = len(data)
    st["data_health"]["intraday_req"] = len(wanted)
    today_sess = None
    for df in data.values():
        d = str(df.index[-1].tz_convert("US/Eastern").date())
        today_sess = d if today_sess is None else min(today_sess, d)
    if today_sess:
        resolve_pending(st, wl, daily, today_sess, intraday=data)

    for t in pos_tickers:
        try:
            if t not in st["positions"]:
                continue  # exited earlier in this same pass
            inv = ((wl_pos.get(t) or {}).get("invalidation")
                   or st["positions"][t].get("stop_rule") or {})
            df = data.get(t)
            if df is None:
                continue
            it = inv.get("type") if isinstance(inv, dict) else None
            if it == "intraday_stop" and any(
                    o["ticker"] == t for o in st["pending_open_exits"]):
                continue  # close-confirmed next-open order is authoritative
            if it != "intraday_stop":
                if it is None and isinstance(inv, dict) and inv.get("level") is not None:
                    emit_once(st, {"ticker": t, "action": "NO_ACTION",
                              "why": "unsupported_rule_schema (has level, no type)"},
                              f"schema:{t}:{inv.get('level')}")
                continue  # {} / close-based / veto rules -> not intraday stops
            low = float(df["Low"].min())
            first_open = float(df["Open"].iloc[0])
            if first_open <= inv["level"]:
                # gapped through the stop at the open -> exit at ACTUAL open
                do_exit(st, t, first_open, f"gap-through open below stop {inv['level']}",
                        exec_id=f"intraday_stop:{t}:{today_sess}")
            elif low <= inv["level"]:
                do_exit(st, t, inv["level"], f"intraday stop {inv['level']}",
                        exec_id=f"intraday_stop:{t}:{today_sess}")
        except Exception as e:
            emit_once(st, {"ticker": t, "action": "NO_ACTION",
                      "why": f"rule_eval_error {e!r}"},
                      f"evalerr:{t}:{e!r}"[:80])

    for w in wl["watches"]:
        t = w["ticker"]
        if st["watch_status"].get(t) in ("TRIGGERED", "EXPIRED", "KILLED", "REANALYSIS") \
                or _risk_blocked(st, w):
            continue
        if now_utc().strftime("%Y-%m-%d") > EXPIRY:
            continue
        if w["cls"] != "REANALYZE_ON_TRIGGER" and not authorized(w):
            continue
        df = data.get(t)
        if df is None:
            continue
        low = float(df["Low"].min()); p = w["params"]
        # AUTO_ENTRY zone touch -> immediate fill at zone top
        if w["cls"] == "AUTO_ENTRY" and p.get("zone") and low <= p["zone"][1]:
            do_fill(st, wl, t, p["zone"][1], w["size_frac"])
            continue
        # deterministic intraday legs
        if "intraday_zone_touch" in (w.get("trigger_type") or "") and w["cls"] == "DETERMINISTIC_CONFIRMATION":
            if p.get("pb_zone") and low <= p["pb_zone"][1]:
                do_fill(st, wl, t, p["pb_zone"][1], w["size_frac"])
                continue
        prog = st["confirm"].get(t, {})
        if prog.get("breakout_armed") and "retest_zone" in p and low <= p["retest_zone"][1]:
            do_fill(st, wl, t, p["retest_zone"][1], w["size_frac"])
            continue
    return len(data)


def settle_pending(st: dict, wl: dict, daily: dict[str, pd.DataFrame], session: str) -> None:
    """Close-pass pending check: any pending order whose target session has
    already fully passed is MISSED (no retroactive fill). Live-session fills
    happen in intraday_pass via resolve_pending."""
    resolve_pending(st, wl, daily, session, live=False)


def eod_marks(st: dict, daily: dict[str, pd.DataFrame], session: str) -> None:
    """End-of-session mark-to-market. Deterministic recompute: every open
    position marked at the regular-session CLOSE for `session`. Idempotent —
    re-running for the same session replaces identical values; cash, shares
    and fills are never touched. Pending next-open orders are not positions.
    """
    mv = upnl = unmarked_cost = 0.0
    unmarked = []
    stale = []
    for t, pos in st["positions"].items():
        if pos.get("entry_session") and pos["entry_session"] > session:
            # mark predates entry — temporally invalid; do not stamp
            for k in ("mark", "mark_session", "mark_source", "unrealized",
                      "unrealized_pct"):
                pos.pop(k, None)
            pos["mark_status"] = "UNMARKED_SINCE_ENTRY"
            unmarked.append(t)
            unmarked_cost += pos.get("cost", pos["shares"] * pos["fill"])
            continue
        df = daily.get(t)
        c = None
        if df is not None and len(df):
            row = df[df.index.date == pd.Timestamp(session).date()]
            if len(row):
                c = float(row["Close"].iloc[-1])
        if c is None:
            pos["mark_session"] = pos.get("mark_session")  # keep prior
            pos["mark_stale"] = True
            stale.append(t)
            continue
        pos["mark"] = round(c, 4)
        pos["mark_session"] = session
        pos["mark_source"] = "regular_session_close"
        pos.pop("mark_stale", None)
        pos["mark_status"] = "MARKED"
        pos["unrealized"] = round((c - pos["fill"]) * pos["shares"], 2)
        pos["unrealized_pct"] = round((c / pos["fill"] - 1) * 100, 2)
        mv += c * pos["shares"]
        upnl += pos["unrealized"]
    st["nav_last"] = round(st["cash"] + mv, 2)
    st["book"] = {
        "mark_session": session,
        "market_value": round(mv, 2),
        "unrealized": round(upnl, 2),
        "exposure": round(mv, 2),
        "nav": st["nav_last"],
        "provisional_nav_incl_unmarked_at_cost":
            round(st["cash"] + mv + unmarked_cost, 2),
        "unmarked_positions": unmarked,
        "cash": st["cash"],
        "realized": st.get("realized", 0.0),
        "marked_at": now_utc().isoformat(),
    }
    if stale:
        emit_once(st, {"action": "EOD_MARK_UNAVAILABLE", "tickers": stale,
                  "session": session}, f"mark_unavail:{session}")
        notify(f"ALPHA_RND EOD MARK UNAVAILABLE\n{', '.join(stale)} — left STALE, no price invented.")
    # Canonical ledger MARK record (append-only; dedup by session+content so
    # repeated ticks never duplicate, but a later same-session fill re-marks).
    ledger = LEDGER
    rec = {"type": "MARK",
           "frozen_at": now_utc().isoformat(),
           "session": session,
           "positions": [{"ticker": t, "fill": p["fill"], "close": p["mark"],
                          "unrealized": p["unrealized"]}
                         for t, p in sorted(st["positions"].items())
                         if p.get("mark_session") == session],
           "cash": st["cash"], "nav": st["nav_last"],
           "open_slots": MAX_POSITIONS - len(st["positions"])}
    body = {k: v for k, v in rec.items() if k != "frozen_at"}
    last_mark = None
    if ledger.exists():
        for l in ledger.read_text().splitlines():
            try:
                r = json.loads(l)
                if r.get("type") == "MARK":
                    last_mark = r
            except Exception:
                pass
    prev = {k: v for k, v in (last_mark or {}).items() if k != "frozen_at"}
    if prev != body:
        with ledger.open("a") as f:
            f.write(json.dumps(rec, default=str) + "\n")


def run_once(wl: dict) -> None:
    with locked_state() as st:
        _run_once_locked(st, wl)


def _run_once_locked(st: dict, wl: dict) -> None:
    wanted = ([w["ticker"] for w in wl["watches"]] +
              [p["ticker"] for p in wl["open_positions"]] +
              list(st["positions"]))
    daily = fetch_daily(wanted)
    # PROCESS_ALIVE != MARKET_DATA_HEALTHY: a tick that got zero usable
    # bars is a successful process but a failed data pass — say so durably.
    st["data_health"] = {"at": now_utc().isoformat(),
                         "daily_ok": len(daily), "daily_req": len(wanted),
                         "status": "ok" if daily else "down"}
    sess = last_close_session(daily)
    MIN_EVAL_SESSION = "2026-10-03"  # triggers frozen 10-02/10-03: no retro eval
    if sess and sess > MIN_EVAL_SESSION and sess not in st["processed_close_sessions"]:
        st["processed_close_sessions"].append(sess)  # mark seen, evaluate below
    elif sess and sess <= MIN_EVAL_SESSION and sess not in st["processed_close_sessions"]:
        st["processed_close_sessions"].append(sess)  # skip pre-freeze sessions entirely
        sess = None
    if sess:
        # pending orders whose target open already passed -> MISSED
        settle_pending(st, wl, daily, sess)
        close_pass(st, wl, daily, sess)
    if sess:
        # Canonical EOD valuation for the latest completed session —
        # idempotent, safe to recompute every tick.
        if st.get("book", {}).get("mark_session") != sess or \
                any(p.get("mark_session") != sess for p in st["positions"].values()):
            eod_marks(st, daily, sess)
    if session_open(now_utc()):
        intraday_pass(st, wl, daily)
        if st["data_health"]["status"] == "ok" and not st["data_health"].get("intraday_ok"):
            st["data_health"]["status"] = "degraded_intraday"
    try:  # post-entry shadow triggers — observational only, never economics
        from alpha_rnd import mgmt as _mgmt
        obs = _mgmt.observe(st, wl, daily,
                            last_close_session(daily) or sess or "", None)
        st["last_mgmt_observe"] = obs
    except Exception:
        pass
    try:  # adaptive execution pass — currently a pure no-op (kill switch off)
        from alpha_rnd import mgmt_exec as _mx
        _mx.run_exec_pass(st, wl)
    except Exception:
        pass
    st["last_check_utc"] = now_utc().isoformat()
    save_state(st)
    _drain_notifications(st)


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
    h = st.get("data_health") or {}
    lines += [f"data: {h.get('status', 'unknown')} "
              f"(daily {h.get('daily_ok', '?')}/{h.get('daily_req', '?')} at {h.get('at', '?')})", ""]
    return "\n".join(lines)


def _seed_once(st: dict, wl: dict) -> None:
    """One-time explicit initialization. After it, absence of a previously
    closed position means CLOSED — never re-seeded (retired_seeds is
    defense-in-depth only)."""
    if st.get("initialized"):
        return
    for p in wl["open_positions"]:
        if p["ticker"] in st.get("retired_seeds", []):
            continue
        if p["ticker"] not in st["positions"]:
            st["positions"][p["ticker"]] = {
                "shares": p["shares"], "fill": p["fill"],
                "invalidation": p["invalidation"]["label"],
                "horizon": p["horizon"], "seeded": True}
    st["initialized"] = True


def main() -> None:
    wl = json.loads(WATCHLIST.read_text())
    # one-time explicit seeding; afterwards absence = CLOSED (never re-seeded)
    with locked_state() as st:
        _seed_once(st, wl)
    if "--status" in sys.argv:
        print(status(wl, st))
        return
    if "--loop" in sys.argv:
        while True:
            try:
                run_once(wl)
            except Exception as e:
                with locked_state() as sx:
                    emit_once(sx, {"action": "NO_ACTION", "why": f"monitor_error {e!r}"},
                              f"monitor_error:{e!r}"[:80])
            time.sleep(60)
    else:
        run_once(wl)
        st = load_state()
        h = st.get("data_health") or {}
        print(f"checked {st['last_check_utc']} data={h.get('status', 'unknown')}")


if __name__ == "__main__":
    main()
