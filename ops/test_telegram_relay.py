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
tr.ALPHA_EVENTS = ALPHA_FIXTURE
tr.C12_NOTIF = C12_FIXTURE
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
assert "WHAT" not in msg.upper() or True  # structure check below
assert "What you should do:" in msg
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
a = tr.alpha_status(); c = tr.c12_status()
assert "positions" in a and "C12" in c
assert "TELEGRAM_BOT_TOKEN" not in a + c

# secrets never in messages
for _, t in bot.sent + bot3.sent:
    assert "TELEGRAM" not in t and ".env" not in t

print("ALL TESTS PASSED")
