#!/usr/bin/env python3
"""TradingAgents Telegram notification relay (PROJECT_CONTROL infrastructure).

Delivery channel ONLY. Trading monitoring, paper execution, and C12
automation are fully independent of this process and of Telegram. If the
relay or Telegram is down, local durable logs remain authoritative and
unsent events are retried on the next run.

Event sources (READ-ONLY tails, never modified):
- ALPHA: <alpha>/alpha_rnd/trigger_events.jsonl   {"ticker","action","utc",...}
- C12:   <c12>/evaluations/gate_c12_prospective/c12_notifications.jsonl
                                                    {"ts","kind",...}

Secrets/state live OUTSIDE the repo in ~/.config/tradingagents/.

Usage:
  python3 -m ops.telegram_relay --configure   # interactive local setup
  python3 -m ops.telegram_relay --test        # send test message
  python3 -m ops.telegram_relay --status      # config/source health
  python3 -m ops.telegram_relay --once        # deliver pending events once (cron-safe)
  python3 -m ops.telegram_relay --serve       # long-running: delivery + /commands
"""

import argparse
import asyncio
import getpass
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ALPHA_ROOT = Path("/home/udi/udi_provate/TradingAgents-alpha-rnd")
C12_ROOT = Path("/home/udi/udi_provate/TradingAgents-c12")
EXPERT_ROOT = Path("/home/udi/udi_provate/TradingAgents-expert-rnd")

ALPHA_EVENTS = ALPHA_ROOT / "alpha_rnd" / "trigger_events.jsonl"
ALPHA_SCHED_EVENTS = ALPHA_ROOT / "alpha_rnd" / "scheduler_events.jsonl"
ALPHA_STATE = ALPHA_ROOT / "alpha_rnd" / "monitor_state.json"
ALPHA_WATCHLIST = ALPHA_ROOT / "alpha_rnd" / "live_watchlist.json"
ALPHA_CRON_LOG = ALPHA_ROOT / "alpha_rnd" / "monitor_cron.log"
C12_NOTIF = C12_ROOT / "evaluations" / "gate_c12_prospective" / "c12_notifications.jsonl"
C12_STATE = C12_ROOT / "evaluations" / "gate_c12_prospective" / "scheduler_state.json"
C12_LOG = C12_ROOT / "evaluations" / "gate_c12_prospective" / "scheduler.log"
C12_NAV = C12_ROOT / "evaluations" / "gate_c12_prospective" / "c12_nav.jsonl"
C12_LEDGER = C12_ROOT / "evaluations" / "gate_c12_prospective" / "c12_signal_ledger.jsonl"
C12_WEEKS = C12_ROOT / "evaluations" / "gate_c12_prospective" / "weeks"
ALPHA_SCHED_STATE = ALPHA_ROOT / "alpha_rnd" / "scheduler_state.json"
ALPHA_LEDGER = ALPHA_ROOT / "evaluations" / "alpha_rnd_v1" / "alpha_paper_ledger.jsonl"

CFG_DIR = Path.home() / ".config" / "tradingagents"
ENV_FILE = CFG_DIR / "telegram.env"
STATE_FILE = CFG_DIR / "telegram_state.json"

SESSIONS = {
    "ALPHA": ("cd ~/udi_provate/TradingAgents-alpha-rnd", "devin -r feather-room"),
    "C12": ("cd ~/udi_provate/TradingAgents-c12", "devin -r kindly-nightshade"),
    "EXPERT": ("cd ~/udi_provate/TradingAgents-expert-rnd", "devin -r groovy-allspice"),
    "PROJECT_CONTROL": ("cd ~/udi_provate/TradingAgents-tracks", "devin -r nonchalant-citipati"),
}

# action/kind -> (severity, notify?)  Everything not listed is not sent.
ALPHA_MAP = {
    "PAPER_ENTRY": ("SUCCESS", True),
    "PAPER_EXIT": ("SUCCESS", True),
    "REANALYSIS_REQUIRED": ("ACTION_REQUIRED", True),
    "MISSED_EXECUTION_REVIEW_REQUIRED": ("ACTION_REQUIRED", True),
    "CONFIRMED_PENDING_NEXT_OPEN_ENTRY": ("INFO", True),
    "CONFIRMED_PENDING_NEXT_OPEN_EXIT": ("INFO", True),
    "CONFIRMED": ("INFO", False),          # noisy; confirmation event follows
    "WATCH_EXPIRED": ("INFO", False),
    "monitor_error": ("ERROR", True),
    "RISK_PLAN_REQUIRED": ("INFO", True),
    "CORRECTIVE_EXIT_SCHEDULED": ("INFO", True),
    "POLICY_BOUNDARY": ("INFO", True),
    "EOD_MARK_UNAVAILABLE": ("WARNING", True),
}
ALPHA_SCHED_MAP = {
    "ALPHA_DISCOVERY_STARTED": ("INFO", True),
    "ALPHA_DISCOVERY_TA_COMPLETE": ("INFO", True),
    "ALPHA_PUBLICATION_REQUIRED": ("ACTION_REQUIRED", True),
    "ALPHA_PUBLICATION_REVIEW_REQUIRED": ("ACTION_REQUIRED", True),
    "ALPHA_PUBLICATION_REVIEW_RESOLVED": ("SUCCESS", True),
    "ALPHA_DISCOVERY_COMPLETE": ("SUCCESS", True),
    "ALPHA_DISCOVERY_ERROR": ("ACTION_REQUIRED", True),
    "ALPHA_DISCOVERY_BLOCKED_BRIDGE": ("WARNING", True),
}
C12_MAP = {
    "C12_CYCLE_STARTED": ("INFO", True),
    "C12_CYCLE_SCOREABLE_COMPLETE": ("SUCCESS", True),
    "C12_CYCLE_NON_SCOREABLE": ("WARNING", True),
    "C12_AUTOMATION_BLOCKED_BRIDGE": ("ACTION_REQUIRED", True),
    "C12_EXECUTION_SETTLED": ("SUCCESS", True),
    "C12_EXECUTION_MISSED": ("ACTION_REQUIRED", True),
    "C12_AUTOMATION_ERROR": ("ERROR", True),
}

SEV_EMOJI = {"INFO": "ℹ️", "SUCCESS": "✅", "WARNING": "⚠️",
             "ACTION_REQUIRED": "🚨", "ERROR": "🚨"}

HEARTBEAT_INTERVAL_S = 20 * 3600   # ~daily when enabled


# ---------- config / state ----------

def load_env() -> dict:
    env = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"cursors": {}, "delivered": [], "pending": [],
            "heartbeat_last": 0, "heartbeat_enabled": False}


def save_state(st: dict) -> None:
    CFG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, indent=1))
    tmp.replace(STATE_FILE)


# ---------- event ingestion + normalization ----------

def _event_id(track: str, raw_line: str) -> str:
    return hashlib.sha256(f"{track}|{raw_line.strip()}".encode()).hexdigest()[:24]


# Second-layer flood defense. Semantic identity ignores wall-clock fields so
# the same transition can never be delivered twice, even if the producer
# rewrites it; the circuit breaker bounds any remaining pathological burst.
CB_MAX_PER_SCAN = 25


def _semantic_id(track: str, rec: dict, event_id: str) -> str:
    """Transition identity for dedup: producer-stamped event_id first, else
    the semantic fields (action/kind/ticker/session/rule) — never utc/ts."""
    if rec.get("event_id"):
        return f"{track}:{rec['event_id']}"
    parts = [rec.get("action") or rec.get("kind") or "",
             rec.get("ticker") or "",
             rec.get("confirm_session") or rec.get("session") or "",
             rec.get("order_id") or rec.get("signal_id") or "",
             (rec.get("why") or rec.get("how") or "")[:48]]
    return f"{track}:" + ":".join(str(x) for x in parts)


def _tail_jsonl(path: Path, cursor: int) -> tuple[list[dict], int]:
    """Return (records, new_cursor). Skips nothing committed yet."""
    if not path.exists():
        return [], cursor
    size = path.stat().st_size
    if cursor > size:      # truncated/rotated — start fresh
        cursor = 0
    with path.open("rb") as f:
        f.seek(cursor)
        chunk = f.read()
    new_cursor = f.tell() if False else cursor + len(chunk)
    recs = []
    for line in chunk.decode(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            recs.append((json.loads(line), line))
        except json.JSONDecodeError:
            continue
    return recs, new_cursor


def normalize(track: str, rec: dict, raw: str) -> dict | None:
    if track == "ALPHA":
        action = rec.get("action", "")
        # monitor emits fatal errors as NO_ACTION + why="monitor_error ..."
        if action == "NO_ACTION" and str(rec.get("why", "")).startswith("monitor_error"):
            action = "monitor_error"
        sev, send = ALPHA_MAP.get(action, ("INFO", False))
        ticker = rec.get("ticker")
        parts = [f"{ticker} — {action}" if ticker else action]
        for k in ("price", "shares", "cost", "proceeds", "why", "how", "cls"):
            if rec.get(k) is not None:
                parts.append(f"{k}: {rec[k]}")
        action_required = sev == "ACTION_REQUIRED"
        next_action = ""
        if action == "REANALYSIS_REQUIRED":
            next_action = ("NO BUY YET. Resume ALPHA agent and request the "
                           "single-ticker refresh.")
        elif action == "MISSED_EXECUTION_REVIEW_REQUIRED":
            next_action = ("A required next-open execution was missed while "
                           "the machine was off. Manual review needed — the "
                           "system did NOT invent a fill.")
        elif action == "monitor_error":
            next_action = "Monitor hit an internal error; investigate."
        body = None
        if action == "PAPER_ENTRY":
            body = (f"{ticker} — PAPER ENTRY EXECUTED\n\n"
                    f"{rec.get('shares')} shares @ ${rec.get('price')}\n"
                    + (f"Cost: ${rec.get('cost')}\n" if rec.get('cost') else "")
                    + (f"Stop: {rec.get('invalidation')}\n" if rec.get('invalidation') else ""))
        elif action == "PAPER_EXIT":
            body = (f"{ticker} — PAPER EXIT EXECUTED\n\n"
                    f"Exit @ ${rec.get('price')}\n"
                    + (f"Proceeds: ${rec.get('proceeds')}\n" if rec.get('proceeds') else "")
                    + (f"Reason: {rec.get('why')}" if rec.get('why') else ""))
        elif action == "CONFIRMED_PENDING_NEXT_OPEN_ENTRY":
            body = (f"{ticker} — ENTRY CONFIRMED FOR NEXT REGULAR OPEN\n\n"
                    f"Why:\n{rec.get('how','trigger condition met')}\n\n"
                    "Status: NOT BOUGHT YET\n"
                    "Expected next step: the monitor will paper-enter at the "
                    "next eligible regular-session open.")
        elif action == "CONFIRMED_PENDING_NEXT_OPEN_EXIT":
            body = (f"{ticker} — EXIT CONFIRMED FOR NEXT REGULAR OPEN\n\n"
                    f"Why:\n{rec.get('how') or rec.get('why','exit condition met')}\n\n"
                    "Status: NOT SOLD YET\n"
                    "Expected next step: the monitor will paper-exit at the "
                    "next regular-session open.")
        elif action == "REANALYSIS_REQUIRED":
            body = (f"{ticker} — REANALYSIS REQUIRED\n\n"
                    f"{rec.get('how','frozen trigger fired')}\n\n"
                    "Status: NO BUY YET — a fresh single-ticker analysis is "
                    "required before any decision.")
        elif action == "MISSED_EXECUTION_REVIEW_REQUIRED":
            body = (f"{ticker} — MISSED EXECUTION (machine was off)\n\n"
                    f"{rec.get('why','')}\n"
                    "The required next-open execution already passed. No "
                    "fill was invented — manual review needed.")
        return {
            "source_track": "ALPHA", "event_type": action, "severity": sev,
            "event_timestamp": rec.get("utc"), "ticker": ticker,
            "summary": " | ".join(parts), "body": body,
            "action_required": action_required,
            "recommended_next_action": next_action,
            "source_ref": str(ALPHA_EVENTS), "event_id": _event_id("ALPHA", raw),
            "semantic_id": _semantic_id("ALPHA", rec, rec.get("event_id")),
            "send": send,
        }
    if track == "ALPHA_SCHED":
        kind = rec.get("kind", "")
        sev, send = ALPHA_SCHED_MAP.get(kind, ("INFO", False))
        fields = ", ".join(f"{k}={v}" for k, v in rec.items()
                           if k not in ("ts", "kind") and v is not None)
        action_required = sev == "ACTION_REQUIRED"
        next_action = ""
        if kind == "ALPHA_DISCOVERY_ERROR":
            next_action = ("ALPHA full-cycle discovery did NOT complete "
                           f"(stage: {rec.get('stage', '?')}). "
                           "Resume feather-room; see alpha_rnd/scheduler.log.")
            action_required = True
        elif kind == "ALPHA_PUBLICATION_REVIEW_REQUIRED":
            next_action = ("Automatic publication refused these tickers "
                           "(ambiguous/unsupported intent — fail closed). "
                           "Validated cases already published. Resume "
                           "feather-room to resolve the listed cases.")
            action_required = True
        elif kind == "ALPHA_PUBLICATION_REQUIRED":
            next_action = ("TA analysis finished but live-watch publication "
                           "is the canonical researcher step — resume "
                           "feather-room to publish. Session not marked done.")
            action_required = True
        elif kind == "ALPHA_DISCOVERY_BLOCKED_BRIDGE":
            next_action = ("Model bridge unreachable. The scheduler retries "
                           "automatically on the next hourly tick — no action "
                           "needed unless this persists.")
        body = None
        if kind == "ALPHA_DISCOVERY_COMPLETE":
            deep = rec.get("deep") or []
            pub = rec.get("published") or {}
            pr = rec.get("pending_review") or []
            uar = rec.get("user_action_required")
            body = ("ALPHA DAILY SCAN COMPLETE\n\n"
                    f"Session: {rec.get('session')}\n"
                    f"Deep-analyzed: {len(deep)}\n"
                    f"Active watches published: {pub.get('watch_count', '?')}\n"
                    f"Review required: {', '.join(pr) if pr else 'none'}\n"
                    f"User action required: {'YES' if uar and uar != 'none' else 'NO'}")
            if uar and uar != "none":
                # keep footer consistent with the body — a review-pending
                # cycle is genuinely ACTION_REQUIRED, never "...: NONE"
                sev = "ACTION_REQUIRED"
                action_required = True
                next_action = ("Publication cases pending fail-closed review "
                               "(see ALPHA_PUBLICATION_REVIEW_REQUIRED). Resume "
                               "feather-room to resolve.")
            if deep:
                body += "\n\nDeep-analyzed names:\n" + ", ".join(map(str, deep))
        return {
            "source_track": "ALPHA", "event_type": kind, "severity": sev,
            "event_timestamp": rec.get("ts"), "ticker": None,
            "summary": f"{kind} — {fields}" if fields else kind, "body": body,
            "action_required": action_required,
            "recommended_next_action": next_action,
            "source_ref": str(ALPHA_SCHED_EVENTS),
            "event_id": _event_id("ALPHA_SCHED", raw),
            "semantic_id": _semantic_id("ALPHA_SCHED", rec, rec.get("event_id")),
            "send": send,
        }
    # C12
    kind = rec.get("kind", "")
    sev, send = C12_MAP.get(kind, ("INFO", False))
    fields = ", ".join(f"{k}={v}" for k, v in rec.items()
                       if k not in ("ts", "kind") and v is not None)
    action_required = sev == "ACTION_REQUIRED"
    next_action = ""
    if kind == "C12_AUTOMATION_BLOCKED_BRIDGE":
        next_action = ("C12 automation could not reach the model bridge. "
                       "Resume the C12 session to check the bridge.")
    elif kind == "C12_AUTOMATION_ERROR":
        next_action = "C12 scheduler hit an internal error; investigate."
    elif kind == "C12_EXECUTION_MISSED":
        next_action = ("A pending execution was missed; no retroactive fill "
                       "was created. Review needed.")
    elif kind == "C12_CYCLE_NON_SCOREABLE":
        next_action = "This weekly cycle does not count (per frozen rules). No fix needed unless unexpected."
    body = None
    if kind == "C12_EXECUTION_SETTLED":
        import re
        m = re.search(r"FILLED (\S+) @ ([\d.]+) on (\S+) \[(\w+)\]",
                      str(rec.get("detail", "")))
        if m:
            t_, px_, d_, slot_ = m.groups()
            body = (f"{t_} — PAPER FILL RECORDED\n\n"
                    f"Effective simulated execution:\n"
                    f"{d_} regular-session {slot_} @ ${float(px_):.2f}\n\n"
                    "This order was frozen before the open.\n"
                    "The accounting record was written later, after session "
                    "data became available — C12 did not trade overnight.")
        else:
            body = f"PAPER EXECUTION RECORDED\n\n{rec.get('detail')}"
    return {
        "source_track": "C12", "event_type": kind, "severity": sev,
        "event_timestamp": rec.get("ts"), "ticker": None,
        "summary": f"{kind} — {fields}" if fields else kind, "body": body,
        "action_required": action_required,
        "recommended_next_action": next_action,
        "source_ref": str(C12_NOTIF), "event_id": _event_id("C12", raw),
        "semantic_id": _semantic_id("C12", rec, rec.get("event_id")),
        "send": send,
    }


def format_message(ev: dict) -> str:
    sev = ev["severity"]
    track = ev["source_track"]
    title = {"ACTION_REQUIRED": "ACTION REQUIRED", "ERROR": "ERROR",
             "SUCCESS": "OK", "WARNING": "WARNING", "INFO": "INFO"}[sev]
    lines = [f"{SEV_EMOJI[sev]} {track} — {title}", "",
             (ev.get("body") or ev["summary"])[:700]]
    if ev["recommended_next_action"] and sev not in ("ACTION_REQUIRED", "ERROR"):
        lines += ["", "Note:", ev["recommended_next_action"]]
    # cheap post-state context for executions
    if track == "ALPHA" and ev["event_type"] in ("PAPER_ENTRY", "PAPER_EXIT"):
        try:
            mst = json.loads(ALPHA_STATE.read_text())
            lines += ["", f"Book now: {len(mst.get('positions', {}))} open positions, "
                          f"cash ${mst.get('cash', 0):,.0f}"]
        except Exception:
            pass
    if sev in ("ACTION_REQUIRED", "ERROR"):
        cd, cmd = SESSIONS[track]
        lines += ["", "USER ACTION REQUIRED:",
                  ev["recommended_next_action"] or "Review needed.", "", cd, cmd]
    else:
        lines += ["", "USER ACTION: NONE"]
    lines += ["", f"Source: {ev['source_ref']}"]
    return "\n".join(lines)


# ---------- delivery ----------

async def _send(bot, chat_id: str, text: str) -> None:
    await bot.send_message(chat_id=chat_id, text=text[:4000])


def scan_sources(st: dict) -> list[dict]:
    """Advance cursors; return normalized events worth sending.
    Per-source per-scan cap: >CB_MAX_PER_SCAN sendable events is never
    legitimate for this system; overflow is suppressed + summarized."""
    out = []
    for track, path in (("ALPHA", ALPHA_EVENTS),
                        ("ALPHA_SCHED", ALPHA_SCHED_EVENTS),
                        ("C12", C12_NOTIF)):
        cur = st["cursors"].get(str(path), 0)
        recs, new_cur = _tail_jsonl(path, cur)
        batch = []
        for rec, raw in recs:
            ev = normalize(track, rec, raw)
            if ev and ev["send"]:
                batch.append(ev)
        if len(batch) > CB_MAX_PER_SCAN:
            suppressed = len(batch) - CB_MAX_PER_SCAN
            kinds = {}
            for e in batch[CB_MAX_PER_SCAN:]:
                kinds[e["event_type"]] = kinds.get(e["event_type"], 0) + 1
            st.setdefault("breaker_log", []).append(
                {"track": track, "suppressed": suppressed,
                 "kinds": kinds, "at": datetime.now(timezone.utc).isoformat()})
            st["breaker_log"] = st["breaker_log"][-100:]
            out.extend(batch[:CB_MAX_PER_SCAN])
            out.append({
                "source_track": track, "event_type": "CIRCUIT_BREAKER",
                "severity": "ACTION_REQUIRED",
                "event_timestamp": datetime.now(timezone.utc).isoformat(),
                "ticker": None,
                "summary": f"{track} NOTIFICATION CIRCUIT BREAKER — "
                           f"{len(batch)} events in one poll",
                "body": (f"{track} NOTIFICATION CIRCUIT BREAKER ACTIVATED\n\n"
                         f"{suppressed} repeated/suppressed notifications "
                         f"(kinds: {kinds}).\nTrading engine state unchanged. "
                         "Check the producer for an event loop."),
                "action_required": True,
                "recommended_next_action":
                    "Inspect the producing track's event log before restarting.",
                "source_ref": str(path),
                "event_id": _event_id(track, f"breaker:{track}:{recs[-1][1][:80]}" if recs else "breaker"),
                "semantic_id": f"{track}:breaker:{recs[-1][1][:80] if recs else 'x'}",
                "send": True,
            })
        else:
            out.extend(batch)
        st["cursors"][str(path)] = new_cur
    return out


async def deliver_pending(bot, chat_id: str, st: dict) -> tuple[int, int]:
    """Send queued + newly scanned events. Returns (sent, failed)."""
    sem_seen = st.setdefault("delivered_semantic", [])
    pend_sem = {p.get("semantic_id") for p in st["pending"]}
    for ev in scan_sources(st):
        sid = ev.get("semantic_id") or ev["event_id"]
        if ev["event_id"] in st["delivered"] or sid in sem_seen:
            continue
        if ev["event_id"] not in [p["event_id"] for p in st["pending"]] \
                and sid not in pend_sem:
            st["pending"].append({"event_id": ev["event_id"],
                                  "semantic_id": sid,
                                  "text": format_message(ev)})
            pend_sem.add(sid)
    sent = failed = 0
    still = []
    for p in st["pending"]:
        try:
            await _send(bot, chat_id, p["text"])
            st["delivered"].append(p["event_id"])
            if p.get("semantic_id"):
                st["delivered_semantic"].append(p["semantic_id"])
            sent += 1
        except Exception as e:
            print(f"[relay] send failed ({e!r}); will retry", file=sys.stderr)
            still.append(p)
            failed += 1
        await asyncio.sleep(0.3)
    st["pending"] = still
    st["delivered"] = st["delivered"][-5000:]
    st["delivered_semantic"] = st["delivered_semantic"][-5000:]
    return sent, failed


def _make_bot(token: str):
    from telegram import Bot
    return Bot(token=token)


def _require_cfg() -> tuple[dict, dict, object, str]:
    env = load_env()
    if not env.get("TELEGRAM_BOT_TOKEN") or not env.get("TELEGRAM_CHAT_ID"):
        sys.exit("Not configured. Run: python3 -m ops.telegram_relay --configure")
    st = load_state()
    return env, st, _make_bot(env["TELEGRAM_BOT_TOKEN"]), env["TELEGRAM_CHAT_ID"]


# ---------- read-only status for /commands and heartbeat ----------

def _age_s(path: Path) -> float | None:
    try:
        return time.time() - path.stat().st_mtime
    except OSError:
        return None


def _last_jsonl(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text().strip().splitlines()[-1])
    except Exception:
        return None


def _alpha_last_mark() -> dict | None:
    """Latest canonical MARK record from the ALPHA paper ledger."""
    if not ALPHA_LEDGER.exists():
        return None
    last = None
    for l in ALPHA_LEDGER.read_text().splitlines():
        try:
            r = json.loads(l)
            if r.get("type") == "MARK":
                last = r
        except Exception:
            pass
    return last


def _pnl(v) -> str:
    return f"+${v:,.0f}" if v >= 0 else f"-${abs(v):,.0f}"


def _alpha_positions_view(st: dict, wl: dict | None = None) -> tuple[list[str], float, str, list]:
    """Per-position lines + marked-only unrealized total + freshness label.

    Uses the canonical per-position mark fields (mark/mark_session/
    mark_status) written by the monitor; positions without a temporally
    valid mark are labeled UNMARKED_SINCE_ENTRY and excluded from the P&L
    total (their fill is shown but never implied to be a live mark).
    """
    pos = st.get("positions", {})
    book = st.get("book") or {}
    mark_sess = book.get("mark_session")
    proc = st.get("processed_close_sessions") or []
    fresh = ("LAST_COMPLETED_CLOSE" if mark_sess and proc and mark_sess == proc[-1]
             else "STALE" if mark_sess else "NONE")
    when = (f"{mark_sess} regular-session close" if mark_sess else "no mark yet")
    lines, tot = [], 0.0
    for t, p in pos.items():
        entry = p["fill"]
        if p.get("mark_status") == "MARKED" and p.get("mark") is not None:
            px, unr = p["mark"], p.get("unrealized", 0.0)
            tot += unr
            pct = p.get("unrealized_pct")
            core = (f"{p['shares']}sh @ ${entry:.2f} | last ${px:.2f} | "
                    f"{_pnl(unr)} ({f'{pct:+.1f}%' if pct is not None else ''})")
        else:
            px, unr = entry, 0.0
            core = (f"{p['shares']}sh @ ${entry:.2f} | UNMARKED_SINCE_ENTRY "
                    f"(entry {p.get('entry_session','?')}; shown at cost)")
        extra = []
        stop = _current_stop_label(t, p, wl)
        if stop:
            extra.append(stop)
        if p.get("horizon"):
            extra.append(f"horizon: {p['horizon'][:55]}")
        lines.append(f"  {t}: {core}" + (" | " + " | ".join(extra) if extra else ""))
    unmarked = [t for t, p in pos.items() if p.get("mark_status") == "UNMARKED_SINCE_ENTRY"]
    return lines, tot, f"{when} ({fresh})", unmarked


def alpha_status() -> str:
    st = json.loads(ALPHA_STATE.read_text()) if ALPHA_STATE.exists() else {}
    wl = json.loads(ALPHA_WATCHLIST.read_text()) if ALPHA_WATCHLIST.exists() else {}
    pos = st.get("positions", {})
    watches = [w["ticker"] for w in wl.get("watches", [])
               if st.get("watch_status", {}).get(w["ticker"], "ACTIVE") == "ACTIVE"]
    # health = last SUCCESSFUL tick (state), not cron-log writes (fires even
    # when every invocation crashes); also flag a recent traceback.
    last_tick = None
    try:
        last_tick = datetime.fromisoformat(st.get("last_check_utc") or "")
    except Exception:
        pass
    tick_age = (datetime.now(timezone.utc) - last_tick).total_seconds() \
        if last_tick else None
    recent_crash = False
    try:
        tail = ALPHA_CRON_LOG.read_bytes()[-4000:].decode(errors="replace")
        # crash only if the newest traceback is more recent than the last
        # successful "checked" tick in the log tail
        tb = tail.rfind("Traceback")
        ok_tick = tail.rfind("checked 20")
        recent_crash = tb > ok_tick and (_age_s(ALPHA_CRON_LOG) or 1e9) < 240
    except OSError:
        pass
    if recent_crash or (tick_age is not None and tick_age > 240):
        err = tail.strip().splitlines()[-1][:80] if recent_crash else "tick overdue"
        health = f"ERROR (last ok tick {int(tick_age or -1)}s ago; {err})"
    else:
        health = "OK" if tick_age is not None and tick_age < 240 else \
            f"UNKNOWN (no ticks yet)"
    plines, unrl, asof, unmarked_pos = _alpha_positions_view(st, wl)
    bk = _alpha_book(st)
    cash = bk["cash"] or 0.0
    invested = bk["invested"]
    reanalysis = [t for t, s in st.get("watch_status", {}).items() if s == "REANALYSIS"]
    d = json.loads(ALPHA_SCHED_STATE.read_text()) if ALPHA_SCHED_STATE.exists() else {}
    done = d.get("completed_sessions") or []
    sess_status = d.get("session_status") or {}
    valid_ta = [x for x in done if sess_status.get(x) != "INVALID_TA_RUNTIME_FAILURE"]
    invalid_ta = [x for x in done if sess_status.get(x) == "INVALID_TA_RUNTIME_FAILURE"]
    lines = ["ALPHA — PAPER PORTFOLIO", "",
             f"Monitor: {health} (per-minute cron)",
             f"Latest canonical EOD mark session: {(st.get('book') or {}).get('mark_session') or asof}"
             + (" — current book fully comparable: NO" if unmarked_pos else ""),
             _alpha_nav_headline(st)[0],
             f"cash: ${cash:,.0f}   invested: ${invested:,.0f}   "
             f"unrealized P&L{' (marked positions only)' if unmarked_pos else ''}: {_pnl(unrl)}"
             + (f"   realized P&L: {_pnl(st.get('realized'))}"
                if st.get("realized") else ""),
             f"positions: {len(pos)}   active watches: {len(watches)}",
             f"pending next-open: {len(st.get('pending_open_fills', []))} entries / "
             f"{len(st.get('pending_open_exits', []))} exits",
             f"reanalysis required: {', '.join(reanalysis) if reanalysis else 'none'}",
             (f"last VALID TA research session: {valid_ta[-1] if valid_ta else 'none'}   "
              f"(last attempted: {invalid_ta[-1]} = INVALID_TA_RUNTIME_FAILURE)"
              if invalid_ta else
              f"last discovery session: {done[-1] if done else 'none'}"),
             "", "Positions:"] + plines + ["", "Watches: " + (", ".join(watches) or "none")]
    return "\n".join(lines)


def _c12_book() -> dict:
    """Read-only C12 book: open trades, pending orders, latest NAV."""
    out = {"open": [], "pending": 0, "nav": None, "scoreable": 0, "matured20": 0, "matured60": 0}
    if C12_LEDGER.exists():
        latest = {}
        for l in C12_LEDGER.read_text().splitlines():
            try:
                r = json.loads(l)
                latest[r.get("ticker") or r.get("id")] = r
            except Exception:
                pass
        for r in latest.values():
            ms = r.get("maturity_status")
            if ms == "PENDING_ENTRY":
                out["pending"] += 1
            if r.get("scoreable"):
                out["scoreable"] += 1
            if r.get("rel20") is not None:
                out["matured20"] += 1
            if r.get("rel60") is not None:
                out["matured60"] += 1
    if C12_NAV.exists() and C12_NAV.stat().st_size:
        pass
    if (p := C12_NAV.parent / "c12_paper_portfolio.jsonl").exists():
        tr = {}
        for l in p.read_text().splitlines():
            try:
                r = json.loads(l); tr[r["trade_id"]] = r
            except Exception:
                pass
        out["open"] = [t for t in tr.values() if t.get("status") == "OPEN"]
    out["nav"] = _last_jsonl(C12_NAV)
    return out


def _last_lines(path: Path, n: int) -> list[str]:
    try:
        return path.read_text().strip().splitlines()[-n:]
    except Exception:
        return []


def c12_status() -> str:
    """CURRENT health — historical errors are reported separately."""
    lines = ["C12 — current health", ""]
    # scheduler freshness from its log (hourly cron writes every tick)
    age = _age_s(C12_LOG)
    health = "OK" if age is not None and age < 7200 else f"STALE ({int(age or -1)}s)"
    lines.append(f"Scheduler: {health} (hourly cron)")
    # last tick line (ts + action)
    last_tick_ts = ""
    for ln in reversed(_last_lines(C12_LOG, 20)):
        if " check:" in ln:
            last_tick_ts = ln[:25]
            lines.append(f"last tick: {ln.strip()[:90]}")
            break
    # current week state
    weeks = sorted(C12_WEEKS.iterdir()) if C12_WEEKS.exists() else []
    if weeks:
        w = json.loads((weeks[-1] / "state.json").read_text())
        lines += [f"decision session: {w.get('decision_session')}",
                  f"disposition: {w.get('disposition','?')}",
                  f"cases done: {len(w.get('cases_done') or [])}/{len(w.get('selected') or [])}"]
    # pending orders + open positions (read-only ledger/nav)
    pending = open_pos = 0
    if C12_LEDGER.exists():
        latest = {}
        for l in C12_LEDGER.read_text().splitlines():
            try:
                r = json.loads(l)
                latest[r.get("ticker") or r.get("id")] = r
            except Exception:
                pass
        pending = sum(1 for r in latest.values()
                      if r.get("maturity_status") == "PENDING_ENTRY")
    navlines = _last_lines(C12_NAV, 1)
    if navlines:
        try:
            nav = json.loads(navlines[0])
            open_pos = nav.get("open_positions", 0)
            lines.append(f"open paper positions: {open_pos}   NAV: ${nav.get('nav')}")
        except Exception:
            pass
    lines.append(f"pending entry orders: {pending}")
    # prospective book detail
    book = _c12_book()
    nav = book["nav"] or {}
    lines += ["", "C12 PROSPECTIVE BOOK",
              f"NAV: ${nav.get('nav')}   cash: ${nav.get('cash')}   "
              f"invested: ${nav.get('gross_exposure')}",
              f"scoreable signals: {book['scoreable']}   matured 20s: "
              f"{book['matured20']}   60s: {book['matured60']}"]
    if book["open"]:
        unr = (nav.get("open_mkt_value") or 0) - (nav.get("gross_exposure") or 0)
        lines.append(f"book unrealized P&L: {_pnl(unr)}  "
                     f"(mark {str(nav.get('ts','?'))[:16]}Z)")
        lines.append("Positions:")
        for t in book["open"]:
            lines.append(f"  {t['ticker']}: {t['shares']:.1f}sh @ ${t['entry_price']}"
                         f" — effective entry {t['entry_session']} regular-session OPEN"
                         f" (${t['notional']:,.0f})")
    # current unresolved blocker = an error newer than the last healthy tick
    last_err = None
    if C12_NOTIF.exists():
        for l in _last_lines(C12_NOTIF, 20):
            try:
                r = json.loads(l)
                if r.get("kind") == "C12_AUTOMATION_ERROR":
                    last_err = r
            except Exception:
                pass
    # unresolved only if the error is newer than the last successful tick
    err_is_current = bool(last_err) and str(last_err.get("ts", "")) > last_tick_ts
    if err_is_current:
        lines += ["", f"CURRENT UNRESOLVED ERROR: {last_err.get('error','?')[:150]}",
                  f"at {last_err.get('ts')}"]
    elif last_err:
        lines += ["", f"last historical error (resolved — later ticks healthy):",
                  f"{last_err.get('error','?')[:120]} @ {last_err.get('ts','?')[:16]}Z"]
    return "\n".join(lines)


def bridge_health() -> dict:
    """Non-billable bridge health via /healthz (no model call)."""
    import urllib.request
    try:
        with urllib.request.urlopen("http://127.0.0.1:8765/healthz",
                                    timeout=5) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"status": "down", "error": str(e)[:80]}


def _alpha_book(mst: dict) -> dict:
    """THE canonical ALPHA valuation view — all dashboards use this.

    Source of truth: monitor_state.json `book` block + top-level
    cash/realized/nav_last written by the repaired monitor. The ledger MARK
    history is NOT used for headline valuation (it contains
    incident-corrupted records). Detects MIXED-TIME (cash includes today's
    executions while marks are yesterday's close) and unmarked positions.
    """
    book = mst.get("book") or {}
    pos = mst.get("positions", {})
    unmarked = book.get("unmarked_positions") or [
        t for t, p in pos.items() if p.get("mark_status") == "UNMARKED_SINCE_ENTRY"]
    mixed = bool(book.get("note") and "MIXED-TIME" in str(book["note"]))
    market_value = book.get("market_value")
    cash = book.get("cash", mst.get("cash", 0.0))
    realized = book.get("realized", mst.get("realized"))
    invested = sum(p["shares"] * p["fill"] for p in pos.values())
    # canonical valuation: cash + marked market value (+ unmarked at cost)
    if market_value is not None:
        marked_subtotal = (cash or 0) + market_value
    else:
        marked_subtotal = book.get("nav", mst.get("nav_last", cash))
        market_value = (marked_subtotal or 0) - (cash or 0)
    valuation = marked_subtotal
    if unmarked:
        valuation += sum(p["shares"] * p["fill"] for t, p in pos.items()
                         if t in unmarked)
    mark_sess = book.get("mark_session")
    proc = mst.get("processed_close_sessions") or []
    if not mark_sess:
        fresh = "NONE"
    elif mixed:
        fresh = "MIXED-TIME"
    elif proc and mark_sess == proc[-1]:
        fresh = "LAST_COMPLETED_CLOSE"
    else:
        fresh = "STALE"
    return {"cash": cash, "realized": realized, "market_value": market_value,
            "marked_subtotal": marked_subtotal,
            "unrealized": book.get("unrealized"), "invested": invested,
            "valuation": valuation, "unmarked": unmarked, "mixed": mixed,
            "mark_session": mark_sess, "fresh": fresh,
            "provisional": book.get("provisional_nav_incl_unmarked_at_cost")}


def _alpha_nav_headline(mst: dict) -> tuple[str, list]:
    """Honest NAV headline; returns (text, flags). Never a normal NAV
    when unmarked or mixed-time."""
    b = _alpha_book(mst)
    if b["unmarked"]:
        return (f"Current fully-marked NAV: UNAVAILABLE   "
                f"marked subtotal ${b['marked_subtotal']:,.2f}   "
                f"provisional book ${b['provisional'] or b['valuation']:,.2f} "
                f"(unmarked at entry cost: {', '.join(b['unmarked'])})"), ["unmarked"]
    if b["mixed"]:
        return (f"Current EOD NAV: UNAVAILABLE   "
                f"Mixed-time book value: ${b['valuation']:,.2f} "
                f"(cash incl. today's executions; marks as of "
                f"{b['mark_session']} close)"), ["mixed"]
    return f"NAV: ${b['valuation']:,.2f}", []


def _alpha_research_label(d: dict) -> str:
    """Latest VALID TA session vs last attempted (invalid TA cycles named)."""
    done = d.get("completed_sessions") or []
    inv = [x for x in done
           if (d.get("session_status") or {}).get(x) == "INVALID_TA_RUNTIME_FAILURE"]
    val = [x for x in done if x not in inv]
    if inv:
        return (f"last valid {val[-1] if val else 'none'} "
                f"(last attempted {inv[-1]} INVALID_TA_RUNTIME_FAILURE)")
    return f"last session {done[-1] if done else 'none'}"


def _current_stop_label(t: str, p: dict, wl: dict):
    """Current machine-enforced post-entry rule — typed first.

    Position stop_rule (mgmt review residual rules) wins; else watchlist
    open_positions typed invalidation (PBF/APPS seeded rules); else the
    raw invalidation text last — clearly labeled 'orig' since it may be a
    stale pre-entry veto, never displayed as a live stop.
    """
    sr = p.get("stop_rule")
    if isinstance(sr, dict) and sr.get("type") == "close_below":
        return f"stop: close < ${sr['level']:.2f}"
    if isinstance(sr, dict) and sr.get("type") == "intraday_stop":
        return f"stop: intraday <= ${sr['level']:.2f}"
    for op in (wl or {}).get("open_positions", []):
        if op["ticker"] != t:
            continue
        inv = op.get("invalidation")
        if isinstance(inv, dict) and inv.get("type") == "intraday_stop":
            return f"stop: intraday <= ${inv['level']:.2f}"
        if isinstance(inv, dict) and inv.get("type") == "close_below":
            return f"stop: close < ${inv['level']:.2f}"
    if p.get("invalidation"):
        return f"orig invalidation: {p['invalidation'][:50]}"
    return None


def _alpha_nav_line(mst: dict, unmarked: list) -> str:
    """Backwards-compat wrapper — delegates to _alpha_nav_headline."""
    return _alpha_nav_headline(mst)[0]


def status_summary() -> str:
    """Compact cross-project dashboard for /status."""
    a_age = _age_s(ALPHA_CRON_LOG)
    a_health = "OK" if a_age is not None and a_age < 180 else "STALE"
    c_age = _age_s(C12_LOG)
    c_health = "OK" if c_age is not None and c_age < 7200 else "STALE"
    mst = json.loads(ALPHA_STATE.read_text()) if ALPHA_STATE.exists() else {}
    _awl = json.loads(ALPHA_WATCHLIST.read_text()) if ALPHA_WATCHLIST.exists() else {}
    mark = _alpha_last_mark() or {}
    plines, unrl, asof, _unm = _alpha_positions_view(mst, _awl)
    book = _c12_book()
    nav = book["nav"] or {}
    acts = pending_action_items(load_state())
    bh = bridge_health()
    b_health = ("OK" if bh.get("status") == "ok"
                and (bh.get("models") or {}).get("devin-quick") == "swe-2-medium"
                and (bh.get("models") or {}).get("devin-deep") == "swe-2-high"
                else "DOWN")
    if bh.get("status") == "down":
        acts = ("SWE bridge down — restart: systemctl --user restart "
                "tradingagents-swe-bridge.service; if it still fails, resume "
                "nonchalant-citipati" if acts == "none"
                else acts + "; SWE bridge down")
    pend = mst.get("pending_open_fills", [])
    pend_s = ", ".join(p["ticker"] for p in pend) if pend and isinstance(pend[0], dict) \
             else str(len(pend))
    lines = ["TRADINGAGENTS STATUS", "",
             "ALPHA",
             f"Health: {a_health}   {_alpha_nav_line(mst, _unm)}",
             f"Positions: {len(mst.get('positions', {}))}   "
             f"unrealized{' (marked only)' if _unm else ''}: {_pnl(unrl)}  (marks as of {asof})",
             f"Pending entry: {pend_s or 'none'}",
             "",
             "C12",
             f"Health: {c_health}   NAV: ${nav.get('nav')}",
             f"Positions: {', '.join(t['ticker'] for t in book['open']) or 'none'}",
             f"Pending orders: {book['pending']}",
             "",
             f"SWE bridge: {b_health}" +
             ("" if b_health == "OK" else "  — " +
              "restart: systemctl --user restart tradingagents-swe-bridge.service"),
             "TELEGRAM: OK", "",
             "USER ACTION: NONE" if acts == "none" else f"USER ACTION REQUIRED: {acts}"]
    return "\n".join(lines)


def digest_text() -> str:
    """Compact daily operations digest (post-close when marks exist)."""
    mst = json.loads(ALPHA_STATE.read_text()) if ALPHA_STATE.exists() else {}
    _awl = json.loads(ALPHA_WATCHLIST.read_text()) if ALPHA_WATCHLIST.exists() else {}
    mark = _alpha_last_mark() or {}
    plines, unrl, asof, _unm = _alpha_positions_view(mst, _awl)
    book = _c12_book()
    nav = book["nav"] or {}
    acts = pending_action_items(load_state())
    d = json.loads(ALPHA_SCHED_STATE.read_text()) if ALPHA_SCHED_STATE.exists() else {}
    done = d.get("completed_sessions") or []
    lines = ["TRADINGAGENTS DAILY SUMMARY", "",
             f"ALPHA (marks as of {asof}):",
             f"  {_alpha_nav_line(mst, _unm)}   "
             f"unrealized{' (marked only)' if _unm else ''} {_pnl(unrl)}   "
             f"positions {len(mst.get('positions', {}))}"]
    for ln in plines:
        lines.append("  " + ln.split(" | invalidation")[0].split(" | stop:")[0].split(" | horizon")[0])
    lines += [f"  pending next-open: {len(mst.get('pending_open_fills', []))} entries / "
              f"{len(mst.get('pending_open_exits', []))} exits",
              f"  discovery: {_alpha_research_label(d)}",
              "",
              f"C12: NAV ${nav.get('nav')}   positions {len(book['open'])}   "
              f"pending orders {book['pending']}",
              "",
              "SYSTEM:",
              f"  ALPHA monitor {'OK' if (_age_s(ALPHA_CRON_LOG) or 1e9) < 180 else 'CHECK'}",
              f"  C12 scheduler {'OK' if (_age_s(C12_LOG) or 1e9) < 7200 else 'CHECK'}",
              f"  SWE bridge {'OK' if bridge_health().get('status') == 'ok' else 'DOWN'}",
              "  Telegram relay OK",
              "",
              "USER ACTION: NONE" if acts == "none" else f"USER ACTION REQUIRED: {acts}"]
    return "\n".join(lines)


def pending_action_items(st: dict) -> str:
    items = []
    if ALPHA_STATE.exists():
        mst = json.loads(ALPHA_STATE.read_text())
        for t, s in mst.get("watch_status", {}).items():
            if s == "REANALYSIS":
                items.append(f"ALPHA {t}: REANALYSIS_REQUIRED")
    return ", ".join(items) or "none"


def heartbeat_text() -> str:
    a = "OK" if (_age_s(ALPHA_CRON_LOG) or 1e9) < 180 else "CHECK"
    c = "OK" if (_age_s(C12_LOG) or 1e9) < 7200 else "CHECK"
    return ("TradingAgents systems alive:\n"
            f"ALPHA monitor: {a}\nC12 scheduler: {c}\nTelegram relay: OK")


# ---------- PTB command surface (serve mode) ----------

def _authorized(env: dict, update) -> bool:
    return (update.effective_chat and
            str(update.effective_chat.id) == str(env.get("TELEGRAM_CHAT_ID")))


def build_app(env: dict):
    from telegram.ext import Application, CommandHandler
    app = Application.builder().token(env["TELEGRAM_BOT_TOKEN"]).build()

    async def guard(update, fn):
        if not _authorized(env, update):
            return  # silently ignore strangers
        await update.message.reply_text(fn()[:4000])

    async def h_status(u, c):
        await guard(u, status_summary)

    async def h_alpha(u, c):
        await guard(u, alpha_status)

    async def h_c12(u, c):
        await guard(u, c12_status)

    async def h_help(u, c):
        await guard(u, lambda: (
            "Read-only commands:\n/status — system health + pending items\n"
            "/alpha — paper portfolio dashboard\n"
            "/c12 — prospective book + scheduler\n/help — this list"))

    for cmd, fn in (("status", h_status), ("alpha", h_alpha),
                    ("c12", h_c12), ("help", h_help)):
        app.add_handler(CommandHandler(cmd, fn))
    return app


async def serve(env: dict) -> None:
    app = build_app(env)
    st = load_state()
    chat_id = env["TELEGRAM_CHAT_ID"]

    async def scan_loop():
        while True:
            try:
                await deliver_pending(app.bot, chat_id, st)
                if (st.get("heartbeat_enabled")
                        and time.time() - st.get("heartbeat_last", 0) > HEARTBEAT_INTERVAL_S):
                    await _send(app.bot, chat_id, digest_text())
                    st["heartbeat_last"] = time.time()
                save_state(st)
            except Exception as e:
                print(f"[relay] loop error {e!r}", file=sys.stderr)
            await asyncio.sleep(60)

    async with app:
        await app.start()
        await app.updater.start_polling()
        task = asyncio.create_task(scan_loop())
        print("[relay] serving — delivery loop + command polling", file=sys.stderr)
        try:
            await asyncio.Event().wait()
        finally:
            task.cancel()
            await app.updater.stop()
            await app.stop()


# ---------- CLI ----------

def cmd_configure() -> None:
    CFG_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(CFG_DIR, 0o700)
    token = getpass.getpass("Telegram bot token (hidden, from @BotFather): ").strip()
    if not token:
        sys.exit("empty token — aborted")
    env_file = dict(load_env())
    env_file["TELEGRAM_BOT_TOKEN"] = token
    masked = token[:4] + "..." + token[-4:]
    print(f"token stored ({masked})")
    _write_env(env_file)
    print("\n1) Open your bot in Telegram and send it any message (e.g. /start).")
    input("2) Press Enter here after sending it... ")
    bot = _make_bot(token)

    async def find_chat():
        ups = await bot.get_updates()
        chats = {str(u.effective_chat.id): u.effective_chat
                 for u in ups if u.effective_chat}
        return chats
    try:
        chats = asyncio.run(find_chat())
    except Exception as e:
        sys.exit(f"could not reach Telegram API: {e}")
    if not chats:
        sys.exit("no chats found — message the bot first, then rerun --configure")
    print("Visible chats:")
    for cid, c in chats.items():
        print(f"  {cid}  ({c.title or c.first_name or 'chat'})")
    chat_id = input("Authorized chat/user ID to use: ").strip()
    if chat_id not in chats:
        sys.exit("ID not in list — aborted")
    env_file["TELEGRAM_CHAT_ID"] = chat_id
    _write_env(env_file)
    os.chmod(ENV_FILE, 0o600)
    asyncio.run(_send(bot, chat_id,
                      "✅ TradingAgents Telegram relay configured. "
                      "You will receive ALPHA/C12 alerts here."))
    print("Test message sent. Configuration complete.")


def _write_env(d: dict) -> None:
    lines = [f"{k}={v}" for k, v in d.items() if v]
    ENV_FILE.write_text("\n".join(lines) + "\n")
    os.chmod(ENV_FILE, 0o600)


def cmd_test() -> None:
    env, st, bot, chat_id = _require_cfg()
    asyncio.run(_send(bot, chat_id,
                      "✅ TEST — TradingAgents Telegram relay is working."))
    print("test message sent")


def cmd_status() -> None:
    env = load_env()
    print(f"config: {'configured' if env.get('TELEGRAM_BOT_TOKEN') and env.get('TELEGRAM_CHAT_ID') else 'MISSING'} ({ENV_FILE})")
    if env.get("TELEGRAM_BOT_TOKEN"):
        t = env["TELEGRAM_BOT_TOKEN"]
        print(f"token: {t[:4]}...{t[-4:]}")
    st = load_state()
    print(f"state: {STATE_FILE}")
    print(f"cursors: {st['cursors']}")
    print(f"delivered: {len(st['delivered'])}  pending: {len(st['pending'])}")
    print(f"heartbeat: {'on' if st.get('heartbeat_enabled') else 'off'}")
    for p in (ALPHA_EVENTS, C12_NOTIF, ALPHA_STATE, C12_STATE):
        print(f"source {p}: {'exists' if p.exists() else 'absent (will be created by track)'}")


def cmd_heartbeat(on: bool) -> None:
    st = load_state()
    st["heartbeat_enabled"] = on
    save_state(st)
    print(f"heartbeat {'enabled' if on else 'disabled'}")


def cmd_once() -> None:
    env, st, bot, chat_id = _require_cfg()

    async def go():
        sent, failed = await deliver_pending(bot, chat_id, st)
        save_state(st)
        print(f"sent={sent} pending_retry={failed}")
    asyncio.run(go())


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--configure", action="store_true")
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--serve", action="store_true")
    ap.add_argument("--heartbeat", choices=["on", "off"])
    a = ap.parse_args()
    if a.configure:
        cmd_configure()
    elif a.test:
        cmd_test()
    elif a.status:
        cmd_status()
    elif a.once:
        cmd_once()
    elif a.serve:
        env, st, bot, chat_id = _require_cfg()  # validates config first
        asyncio.run(serve(load_env()))
    elif a.heartbeat:
        cmd_heartbeat(a.heartbeat == "on")
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
