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
assert "kindly-nightshade" in msg and str(tr.C12_ROOT) in msg
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

# --- read-only status (real files of the resolved roots, read only) ---
tr.C12_STATE = tr.C12_ROOT / "evaluations/gate_c12_prospective/scheduler_state.json"
tr.C12_NOTIF = C12_FIXTURE
tr.C12_LOG = tr.C12_ROOT / "evaluations/gate_c12_prospective/scheduler.log"
tr.C12_NAV = tr.C12_ROOT / "evaluations/gate_c12_prospective/c12_nav.jsonl"
tr.C12_LEDGER = tr.C12_ROOT / "evaluations/gate_c12_prospective/c12_signal_ledger.jsonl"
tr.C12_WEEKS = tr.C12_ROOT / "evaluations/gate_c12_prospective/weeks"
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
assert "NAV: $" not in nav_unm  # no normal NAV headline while unmarked
assert "UNAVAILABLE" in nav_unm and "marked subtotal $5,000.00" in nav_unm
assert "provisional book $6,000.00" in nav_unm and "SDGR" in nav_unm
# unmarked position excluded from P&L but shown at cost
view, _, _, _ = tr._alpha_positions_view(st_unm)
assert "UNMARKED_SINCE_ENTRY" in view[1]
# restore: everything marked -> normal NAV returns
nav_back = tr._alpha_nav_line(st_all, [])
assert nav_back.startswith("NAV:")

# --- canonical book-view: stale/corrupted nav_last cannot override ---
import copy as _copy
st_corrupt = {"positions": {"A": mk_pos("A", True)}, "cash": 90203.02,
              "nav_last": 960935.02, "realized": -1485.68,
              "processed_close_sessions": ["S1"],
              "book": {"mark_session": "S1", "cash": 90203.02,
                       "market_value": 8070.25, "realized": -1485.68,
                       "unmarked_positions": []}}
bk = tr._alpha_book(st_corrupt)
assert bk["valuation"] == 98273.27  # canonical book wins over corrupt nav_last
assert tr._alpha_nav_headline(st_corrupt)[0] == "NAV: $98,273.27"
# stale ledger MARK can't override either (alpha_status ignores it) — headline
# comes solely from the book helper, which never reads the ledger.

# --- mixed-time: no normal EOD NAV ---
st_mixed = _copy.deepcopy(st_corrupt)
st_mixed["book"]["note"] = "MIXED-TIME valuation: cash incl. today's fills"
h, flags = tr._alpha_nav_headline(st_mixed)
assert "Mixed-time book value: $98,273.27" in h and "NAV: $" not in h.split("$98")[0]
assert "marks as of S1 close" in h
# after EOD marks land (note cleared) -> normal NAV restored
del st_mixed["book"]["note"]
assert tr._alpha_nav_headline(st_mixed)[0] == "NAV: $98,273.27"

# --- current typed stops displayed; pre-entry veto not shown as stop ---
wl_p = {"open_positions": [{"ticker": "PBF",
        "invalidation": {"type": "intraday_stop", "level": 74.5}}], "watches": []}
pos_mixed = {"positions": {
    "PBF": {"shares": 62, "fill": 80.0, "invalidation": "hard stop",
            "mark_status": "MARKED", "mark": 82.88, "unrealized": 178.56},
    "SDGR": {"shares": 61, "fill": 31.0, "invalidation": "NOT_STATED",
             "stop_rule": {"type": "close_below", "level": 27.29},
             "mark_status": "MARKED", "mark": 28.9, "unrealized": -128.1},
    "TWST": {"shares": 7, "fill": 209.55,
             "invalidation": "stay out if $183.39 breaks on heavy volume",
             "stop_rule": {"type": "close_below", "level": 164.0},
             "mark_status": "MARKED", "mark": 166.97, "unrealized": -298.06}}}
pl, _, _, _ = tr._alpha_positions_view(pos_mixed, wl_p)
assert "intraday <= $74.50" in pl[0]                      # PBF hard stop
assert "close < $27.29" in pl[1]                          # SDGR typed residual
assert "close < $164.00" in pl[2]                         # TWST typed residual
assert "183.39" not in pl[2]                              # pre-entry veto hidden

# --- invalid TA session not called valid research ---
d_inv = {"completed_sessions": ["2026-10-02", "2026-10-06"],
         "session_status": {"2026-10-06": "INVALID_TA_RUNTIME_FAILURE"}}
lbl = tr._alpha_research_label(d_inv)
assert "last valid 2026-10-02" in lbl and "INVALID_TA_RUNTIME_FAILURE" in lbl
assert tr._alpha_research_label({"completed_sessions": ["S1"]}) == "last session S1"

# --- last attempted must track the NEWEST attempt, not a stale invalid marker ---
# 10-05/10-06 are permanently INVALID in history; a later failed attempt must
# replace "last attempted" instead of pinning it to 10-06.
d_new = {"completed_sessions": ["2026-10-02", "2026-10-06", "2026-10-13"],
         "session_status": {"2026-10-05": "INVALID_TA_RUNTIME_FAILURE",
                            "2026-10-06": "INVALID_TA_RUNTIME_FAILURE",
                            "2026-10-13": "COMPLETE",
                            "2026-10-14": "ERROR"}}
lbl = tr._alpha_research_label(d_new)
assert "last valid 2026-10-13" in lbl
assert "last attempted 2026-10-14 = ERROR" in lbl
assert "10-06" not in lbl.split("attempted")[-1]
# recovered session: attempt == last valid -> plain label, no stale error
d_ok = {"completed_sessions": ["2026-10-13", "2026-10-14"],
        "session_status": {"2026-10-13": "COMPLETE", "2026-10-14": "COMPLETE"}}
assert tr._alpha_research_label(d_ok) == "last session 2026-10-14"
# no attempts recorded at all
assert tr._alpha_research_label({}) == "last session none"

# --- rendering performs no state mutation ---
snap = _copy.deepcopy(st_mixed)
tr._alpha_nav_headline(st_mixed); tr._alpha_positions_view(pos_mixed, wl_p)
assert st_mixed == snap

print("ALL TESTS PASSED")


# --- flood defense: semantic dedup + circuit breaker ---

F2 = TMP / "flood_events.jsonl"
tr.ALPHA_EVENTS = F2

# A/B: 500 records, same semantic transition, different timestamps -> 1 delivery
st = tr.load_state()
st["cursors"] = {}
for i in range(500):
    w(F2, {"ticker": "SDGR", "action": "MISSED_EXECUTION_REVIEW_REQUIRED",
           "kind": "exit", "why": "rule", "confirm_session": "2026-10-09",
           "missed_session": "2026-10-12", "utc": f"2026-10-13T04:{i:02d}Z"})
bot = FakeBot()
sent, _ = asyncio.run(tr.deliver_pending(bot, "CHAT", st))
assert sent <= tr.CB_MAX_PER_SCAN + 1, sent
sdgr_msgs = [t for _, t in bot.sent if "SDGR" in t and "MISSED" in t]
assert len(sdgr_msgs) == 1, f"expected 1 SDGR missed msg, got {len(sdgr_msgs)}"
# breaker summary exists
assert any("CIRCUIT BREAKER" in t for _, t in bot.sent), "breaker msg missing"
# restart persistence: same source again -> only suppressed residual, no dup
bot2 = FakeBot()
sent2, _ = asyncio.run(tr.deliver_pending(bot2, "CHAT", st))
assert not any("MISSED" in t for _, t in bot2.sent), "restart replayed semantic dup"

# C: a few genuinely different events below volume -> all delivered
F3 = TMP / "varied.jsonl"
tr.ALPHA_EVENTS = F3
st3 = tr.load_state(); st3["cursors"] = {}
for i, t in enumerate(["AAA", "BBB", "CCC"]):
    w(F3, {"ticker": t, "action": "PAPER_EXIT", "why": f"rule{i}",
           "price": 1.0, "shares": 1, "proceeds": 1.0, "utc": f"2026-10-13T05:0{i}Z"})
bot3 = FakeBot()
sent3, _ = asyncio.run(tr.deliver_pending(bot3, "CHAT", st3))
assert sent3 == 3, sent3

# D: pathological burst of UNIQUE events -> capped + one breaker message
F4 = TMP / "burst.jsonl"
tr.ALPHA_EVENTS = F4
st4 = tr.load_state(); st4["cursors"] = {}
for i in range(100):
    w(F4, {"ticker": f"T{i:03d}", "action": "PAPER_EXIT", "why": f"r{i}",
           "price": 1.0, "shares": 1, "proceeds": 1.0, "utc": f"2026-10-13T06:{i:02d}Z"})
bot4 = FakeBot()
sent4, _ = asyncio.run(tr.deliver_pending(bot4, "CHAT", st4))
assert sent4 <= tr.CB_MAX_PER_SCAN + 1, sent4
assert sum("CIRCUIT BREAKER" in t for _, t in bot4.sent) == 1
assert st4["breaker_log"], "breaker not persisted"

tr.ALPHA_EVENTS = ALPHA_FIXTURE
print("relay flood defense ok")
for act, want in (("RISK_PLAN_REQUIRED", False), ("PAPER_EXIT", True), ("monitor_error", True)):
    rec = {"ticker": "ASST", "action": act if act != "monitor_error" else "NO_ACTION",
           "why": "monitor_error x" if act == "monitor_error" else "r", "utc": "2026-10-14T13:31Z",
           "event_id": f"e:{act}"}
    ev = tr.normalize("ALPHA", rec, json.dumps(rec))
    assert ev["send"] is want, (act, ev["send"])
print("relay policy ok")
def _sched(rec):
    raw = json.dumps(rec)
    return tr.normalize("ALPHA_SCHED", rec, raw)

deg = {"ts": "2026-10-14T14:50:00+00:00", "kind": "ALPHA_ANALYSIS_DEGRADED", "session": "2026-10-12",
       "stage": "ta", "reason_code": "MODEL_RATE_LIMITED", "ta_requested": 10, "ta_succeeded": 7,
       "ta_failed": 3, "failed_tickers": ["H", "I", "J"], "user_action_required": "NONE"}
ev = _sched(deg)
assert ev["send"] is True and ev["severity"] == "WARNING", ev
assert "ANALYSIS DEGRADED" in ev["body"] and "Successful: 7/10" in ev["body"]
assert "Failed: 3/10" in ev["body"] and "USER ACTION: NONE" in ev["body"]
assert "treated as an investment rejection" in ev["body"]
assert _sched(dict(deg, ts="2026-10-14T15:50:00+00:00"))["semantic_id"] == ev["semantic_id"], "repeat must dedup"
q = dict(deg, kind="ALPHA_ANALYSIS_INFRASTRUCTURE_FAILED", reason_code="MODEL_QUOTA_EXHAUSTED",
         ta_succeeded=0, ta_failed=10, user_action_required="REQUIRED")
qe = _sched(q)
assert "USER ACTION: REQUIRED" in qe["body"] and "Successful: 0/10" in qe["body"]
done = {"ts": "x", "kind": "ALPHA_DISCOVERY_COMPLETE", "session": "2026-10-12", "deep": list("ABC"),
        "published": {"watch_count": 1}, "analysis_complete": False, "ta_requested": 10,
        "ta_succeeded": 7, "user_action_required": "none"}
assert "ANALYSIS INCOMPLETE" in _sched(done)["body"]
term = dict(done, session_terminal=True)
assert "ANALYSIS INCOMPLETE — TERMINAL FAILURES" in _sched(term)["body"]
assert "ANALYSIS INCOMPLETE — TERMINAL FAILURES" not in _sched(done)["body"]
print("relay analysis messages ok")


