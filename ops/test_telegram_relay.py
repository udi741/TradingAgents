#!/usr/bin/env python3
"""Self-check for ops.telegram_relay — synthetic fixtures only.

Creates NO paper trades, touches NO track state, calls NO network.
Run: python3 ops/test_telegram_relay.py
"""

import asyncio
import importlib
import json
import sys
import tempfile
from pathlib import Path

import ops.telegram_relay as tr

TMP = Path(tempfile.mkdtemp(prefix="relay_test_"))

ALPHA_FIXTURE = TMP / "trigger_events.jsonl"
C12_FIXTURE = TMP / "c12_notifications.jsonl"
SCHED_FIXTURE = TMP / "scheduler_events.jsonl"
tr.ALPHA_EVENTS = ALPHA_FIXTURE
tr.C12_NOTIF = C12_FIXTURE
tr.ALPHA_SCHED_EVENTS = SCHED_FIXTURE
tr.STATE_FILE = TMP / "state.json"


class FakeBot:
    def __init__(self, fail_n=0):
        self.sent = []
        self.fail_n = fail_n

    async def send_message(self, chat_id, text):
        if self.fail_n:
            self.fail_n -= 1
            raise RuntimeError("telegram down")
        self.sent.append((chat_id, text))


def w(path, rec):
    with path.open("a") as f:
        f.write(json.dumps(rec) + "\n")


# --- normalization ---

ev = tr.normalize("ALPHA", {"ticker": "KOD", "action": "REANALYSIS_REQUIRED",
                            "how": "priced offering", "utc": "2026-10-03T10:00Z"}, 'x')
assert ev["severity"] == "ACTION_REQUIRED" and ev["send"]
assert "NO BUY YET" in ev["recommended_next_action"]
assert ev["ticker"] == "KOD" and ev["event_id"]

ev = tr.normalize("ALPHA", {"ticker": "PBF", "action": "PAPER_ENTRY",
                            "price": 80.0, "shares": 62, "utc": "t"}, 'x')
assert ev["severity"] == "SUCCESS" and "80.0" in ev["summary"]

ev = tr.normalize("ALPHA", {"action": "NO_ACTION", "why": "already_open"}, 'x')
assert ev["send"] is False
ev = tr.normalize("ALPHA", {"action": "NO_ACTION", "why": "monitor_error X"}, 'x')
assert ev["severity"] == "ERROR" and ev["send"]

ev = tr.normalize("C12", {"ts": "t1", "kind": "C12_CYCLE_SCOREABLE_COMPLETE",
                          "session": "2026-10-02", "entries": "HPE,NTAP"}, 'x')
assert ev["severity"] == "SUCCESS"
ev = tr.normalize("C12", {"ts": "t1", "kind": "C12_AUTOMATION_BLOCKED_BRIDGE"}, 'x')
assert ev["severity"] == "ACTION_REQUIRED" and "kindly-nightshade" not in ev["recommended_next_action"]
msg = tr.format_message(ev)
assert "kindly-nightshade" in msg and "TradingAgents-c12" in msg
assert "USER ACTION REQUIRED:" in msg
ev_ok = tr.normalize("C12", {"ts": "t", "kind": "C12_CYCLE_STARTED"}, "x")
assert "USER ACTION: NONE" in tr.format_message(ev_ok)
ev2 = tr.normalize("C12", {"ts": "t1", "kind": "C12_CYCLE_STARTED"}, 'x')
assert ev2["send"] and ev2["severity"] == "INFO"

# --- scan + dedup + retry + restart ---

w(ALPHA_FIXTURE, {"ticker": "PGEN", "action": "PAPER_ENTRY", "price": 8.2,
                  "shares": 600, "utc": "u1"})
w(ALPHA_FIXTURE, {"ticker": "IOVA", "action": "NO_ACTION", "why": "x"})
w(C12_FIXTURE, {"ts": "c1", "kind": "C12_CYCLE_STARTED", "session": "s"})
w(C12_FIXTURE, {"ts": "c2", "kind": "C12_AUTOMATION_ERROR", "error": "boom"})

st = tr.load_state()
bot = FakeBot()
sent, failed = asyncio.run(tr.deliver_pending(bot, "CHAT", st))
assert sent == 3 and failed == 0, (sent, failed)
assert any("PGEN" in t for _, t in bot.sent)
assert any("C12_CYCLE_STARTED" in t for _, t in bot.sent)
assert any("C12_AUTOMATION_ERROR" in t for _, t in bot.sent)
assert not any("IOVA" in t for _, t in bot.sent)

# restart: same state, nothing new -> no duplicates
tr.save_state(st)
st2 = tr.load_state()
bot2 = FakeBot()
sent, _ = asyncio.run(tr.deliver_pending(bot2, "CHAT", st2))
assert sent == 0 and len(bot2.sent) == 0

# transient failure -> stays pending, retries next run
w(ALPHA_FIXTURE, {"ticker": "PBF", "action": "PAPER_EXIT", "price": 79.0,
                  "proceeds": 4900, "utc": "u2"})
bot3 = FakeBot(fail_n=1)
sent, failed = asyncio.run(tr.deliver_pending(bot3, "CHAT", st2))
assert sent == 0 and failed == 1 and len(st2["pending"]) == 1
sent, failed = asyncio.run(tr.deliver_pending(bot3, "CHAT", st2))
assert sent == 1 and failed == 0 and "PBF" in bot3.sent[0][1]

# missing source file tolerated
tr.ALPHA_EVENTS = TMP / "does_not_exist.jsonl"
sent, failed = asyncio.run(tr.deliver_pending(FakeBot(), "CHAT", st2))
assert sent == 0

# --- auth ---
class U: pass
u = U(); u.effective_chat = U(); u.effective_chat.id = "123"
assert tr._authorized({"TELEGRAM_CHAT_ID": "123"}, u)
u.effective_chat.id = "999"
assert not tr._authorized({"TELEGRAM_CHAT_ID": "123"}, u)

# --- read-only status (real files, read only) ---
tr.ALPHA_STATE = Path("/home/udi/udi_provate/TradingAgents-alpha-rnd/alpha_rnd/monitor_state.json")
tr.ALPHA_WATCHLIST = Path("/home/udi/udi_provate/TradingAgents-alpha-rnd/alpha_rnd/live_watchlist.json")
tr.ALPHA_CRON_LOG = Path("/home/udi/udi_provate/TradingAgents-alpha-rnd/alpha_rnd/monitor_cron.log")
tr.C12_STATE = Path("/home/udi/udi_provate/TradingAgents-c12/evaluations/gate_c12_prospective/scheduler_state.json")
tr.C12_NOTIF = C12_FIXTURE
tr.C12_LOG = Path("/home/udi/udi_provate/TradingAgents-c12/evaluations/gate_c12_prospective/scheduler.log")
tr.C12_NAV = Path("/home/udi/udi_provate/TradingAgents-c12/evaluations/gate_c12_prospective/c12_nav.jsonl")
tr.C12_LEDGER = Path("/home/udi/udi_provate/TradingAgents-c12/evaluations/gate_c12_prospective/c12_signal_ledger.jsonl")
tr.C12_WEEKS = Path("/home/udi/udi_provate/TradingAgents-c12/evaluations/gate_c12_prospective/weeks")
a = tr.alpha_status(); c = tr.c12_status()
assert "Positions" in a and "C12" in c and "disposition" in c
assert "TELEGRAM_BOT_TOKEN" not in a + c

# secrets never in messages
for _, t in bot.sent + bot3.sent:
    assert "TELEGRAM" not in t and ".env" not in t

# --- UX: C12 delayed accounting fill ---
ev = tr.normalize("C12", {"ts": "2026-10-06T01:00:00Z", "kind": "C12_EXECUTION_SETTLED",
                          "detail": "FILLED NTAP @ 216.4300 on 2026-10-05 [OPEN]"}, 'x')
m = tr.format_message(ev)
assert "PAPER FILL RECORDED" in m and "NTAP" in m
assert "2026-10-05 regular-session OPEN @ $216.43" in m
assert "frozen before the open" in m and "did not trade overnight" in m
assert "USER ACTION: NONE" in m

# --- UX: discovery-complete hides internals ---
ev = tr.normalize("ALPHA_SCHED", {"ts": "t", "kind": "ALPHA_DISCOVERY_COMPLETE",
    "session": "2026-10-05", "deep": ["IOVA","SYNA"], "ta_signals": {},
    "published": {"published_at": "t", "watch_count": 13, "sha256": "abc"},
    "pending_review": [], "user_action_required": "none"}, 'x')
m = tr.format_message(ev)
assert "ALPHA DAILY SCAN COMPLETE" in m and "Session: 2026-10-05" in m
assert "Active watches published: 13" in m and "User action required: NO" in m
assert "sha256" not in m and "ta_signals" not in m and "IOVA" in m

# --- UX: pending-next-open says NOT BOUGHT YET ---
ev = tr.normalize("ALPHA", {"ticker": "TWST", "action": "CONFIRMED_PENDING_NEXT_OPEN_ENTRY",
                            "how": "close 205.0>200.31 on vol 3205000>=2421390", "utc": "u"}, 'x')
m = tr.format_message(ev)
assert "ENTRY CONFIRMED FOR NEXT REGULAR OPEN" in m and "NOT BOUGHT YET" in m
assert "USER ACTION: NONE" in m

# --- current health vs historical error (synthetic) ---
import time as _t
C12LOG = TMP/"sched.log"; C12LOG.write_text("2026-01-01T00:00:00Z check: session=x action=done\n")
WK = TMP/"weeks"; (WK/"2026-01-01").mkdir(parents=True)
(WK/"2026-01-01"/"state.json").write_text(json.dumps({"decision_session":"2026-01-01","disposition":"SCOREABLE","cases_done":["A"],"selected":["A"]}))
old_c12 = (tr.C12_LOG, tr.C12_WEEKS, tr.C12_NAV, tr.C12_LEDGER, tr.C12_NOTIF)
tr.C12_LOG, tr.C12_WEEKS = C12LOG, WK
tr.C12_NAV = TMP/"no_nav.jsonl"; tr.C12_LEDGER = TMP/"no_led.jsonl"
ERRF = TMP/"errs.jsonl"
ERRF.write_text(json.dumps({"ts":"2026-01-01T01:00:00Z","kind":"C12_AUTOMATION_ERROR","error":"boom"})+"\n")
tr.C12_NOTIF = ERRF
c = tr.c12_status()  # error 01:00 is NEWER than last tick 00:00 -> current
assert "CURRENT UNRESOLVED ERROR" in c
# resolved case: a healthy tick after the error
C12LOG.write_text("2026-01-01T00:00:00Z check: x\n2026-01-02T00:00:00Z check: session=y action=done\n")
c = tr.c12_status()
assert "resolved" in c and "CURRENT UNRESOLVED" not in c
tr.C12_LOG, tr.C12_WEEKS, tr.C12_NAV, tr.C12_LEDGER, tr.C12_NOTIF = old_c12

# --- partial-mark NAV labeling ---
mk_pos = lambda t, marked: {"shares": 10, "fill": 100.0, "mark_status": "MARKED" if marked else "UNMARKED_SINCE_ENTRY",
                           "mark": 110.0 if marked else None, "unrealized": 100.0 if marked else 0.0}
st_all = {"positions": {"A": mk_pos("A", True), "B": mk_pos("B", True)},
          "processed_close_sessions": ["S1"], "cash": 0,
          "book": {"mark_session": "S1", "nav": 5000.0, "unmarked_positions": []}}
st_unm = {"positions": {"A": mk_pos("A", True), "SDGR": mk_pos("SDGR", False)},
          "processed_close_sessions": ["S1"], "cash": 0,
          "book": {"mark_session": "S1", "nav": 5000.0,
                   "provisional_nav_incl_unmarked_at_cost": 6000.0,
                   "unmarked_positions": ["SDGR"]}}
assert _t and True
nav_all = tr._alpha_nav_line(st_all, [])
assert nav_all.startswith("NAV:") and "5,000" in nav_all
_, tot, _, unm = tr._alpha_positions_view(st_unm)
assert unm == ["SDGR"] and tot == 100.0
nav_unm = tr._alpha_nav_line(st_unm, unm)
assert "NAV:" not in nav_unm
assert "UNAVAILABLE" in nav_unm and "marked subtotal $5,000.00" in nav_unm
assert "provisional book $6,000.00" in nav_unm and "SDGR" in nav_unm
# unmarked position excluded from P&L but shown at cost
view, _, _, _ = tr._alpha_positions_view(st_unm)
assert "UNMARKED_SINCE_ENTRY" in view[1]
# restore: everything marked -> normal NAV returns
nav_back = tr._alpha_nav_line(st_all, [])
assert nav_back.startswith("NAV:")

print("ALL TESTS PASSED")
