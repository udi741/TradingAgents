import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from alpha_rnd import entry_gate as eg  # noqa: E402
from alpha_rnd import monitor as m  # noqa: E402


def _doc(d, session, disp=None, intent_cls="REANALYZE_ON_TRIGGER"):
    intents = {"ASST": {"ticker": "ASST", "classification": intent_cls,
                        "watch_mode": intent_cls}}
    dispositions = {} if disp is None else {"ASST": {"disposition": disp}}
    (d / f"publication_intents_{session}.json").write_text(json.dumps(
        {"session": session, "intents": intents, "dispositions": dispositions}))


def _watch(session="2026-10-02", **kw):
    w = {"ticker": "ASST", "cls": "DETERMINISTIC_CONFIRMATION",
         "trigger_type": "close_breakout_vol", "params": {"bo_level": 20.0},
         "size_frac": 0.25, "invalidation": "stop $19",
         "stop_rule": {"type": "intraday_stop", "level": 19.0},
         "horizon": "h", "trigger": "t",
         "artifact": f"ASST_{session}.json", "v": 2}
    w.update(kw)
    return w


class EntryGateUnit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.old = eg.PUB_DIR
        eg.PUB_DIR = self.d

    def tearDown(self):
        eg.PUB_DIR = self.old

    def test_legacy_watch_without_publication_evidence_is_blocked(self):
        self.assertFalse(eg.authorized(_watch()))

    def test_current_risk_plan_required_blocks_entry(self):
        _doc(self.d, "2026-10-02", "EXECUTABLE_WATCH", "DETERMINISTIC_CONFIRMATION")
        _doc(self.d, "2026-10-07", "RISK_PLAN_REQUIRED")
        self.assertFalse(eg.authorized(_watch("2026-10-02")))

    def test_newer_nonexecutable_supersedes_older_executable(self):
        _doc(self.d, "2026-10-02", "EXECUTABLE_WATCH", "DETERMINISTIC_CONFIRMATION")
        _doc(self.d, "2026-10-07", "PUBLISHED_NON_EXECUTABLE")
        self.assertFalse(eg.authorized(_watch("2026-10-02")))

    def test_newer_revision_without_disposition_fails_closed(self):
        _doc(self.d, "2026-10-02", "EXECUTABLE_WATCH", "DETERMINISTIC_CONFIRMATION")
        _doc(self.d, "2026-10-07", None)  # ASST 10-07 shape: intent but no disposition
        self.assertFalse(eg.authorized(_watch("2026-10-02")))

    def test_every_nonentry_class_blocks(self):
        for disp in ("PUBLISHED_NON_EXECUTABLE", "AMBIGUOUS_REJECTED",
                     "RESEARCH_ONLY", "NO_ACTION", "REANALYZE_ON_TRIGGER",
                     "RISK_PLAN_REQUIRED", "OPEN_POSITION_MANAGEMENT"):
            with self.subTest(disp=disp):
                for f in self.d.glob("publication_intents_*.json"):
                    f.unlink()
                _doc(self.d, "2026-10-02", disp)
                self.assertFalse(eg.authorized(_watch("2026-10-02")))

    def test_current_executable_watch_is_authorized(self):
        _doc(self.d, "2026-10-02", "EXECUTABLE_WATCH", "DETERMINISTIC_CONFIRMATION")
        self.assertTrue(eg.authorized(_watch("2026-10-02")))

    def test_executable_watch_from_older_session_is_not_authorized(self):
        _doc(self.d, "2026-10-02", "EXECUTABLE_WATCH", "DETERMINISTIC_CONFIRMATION")
        self.assertFalse(eg.authorized(_watch("2026-10-01")))


class EntryGateMonitor(unittest.TestCase):
    """ASST-shaped incident: legacy triggerable watch, newer non-executable
    revision, price satisfies the trigger on the open."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.old_pub = eg.PUB_DIR
        eg.PUB_DIR = self.d
        self.old_ev = m.EVENTS
        m.EVENTS = self.d / "events.jsonl"
        self.patch = mock.patch.object(m, "authorized", eg.authorized)
        self.patch.start()
        _doc(self.d, "2026-10-07", None)

    def tearDown(self):
        self.patch.stop()
        eg.PUB_DIR = self.old_pub
        m.EVENTS = self.old_ev

    def _state(self):
        return {"last_check_utc": None, "processed_close_sessions": [], "confirm": {},
                "pending_open_fills": [], "pending_open_exits": [], "positions": {},
                "cash": 50000.0, "nav_last": 50000.0, "watch_status": {}}

    def _events(self):
        m._flush_outbox(self.st) if hasattr(self, "st") else None
        if not m.EVENTS.exists():
            return []
        return [json.loads(l) for l in m.EVENTS.read_text().splitlines()]

    def _df(self):
        closes = [18.0] * 30 + [22.0]
        idx = pd.bdate_range(end="2026-10-07", periods=len(closes))
        return pd.DataFrame({"Open": closes, "High": closes, "Low": closes,
                             "Close": closes, "Volume": [2_000_000] * 31}, index=idx)

    def test_legacy_watch_never_reaches_risk_block_or_fill(self):
        self.st = self._state()
        wl = {"watches": [_watch()], "open_positions": []}
        for _ in range(3):
            m.close_pass(self.st, wl, {"ASST": self._df()}, "2026-10-07")
        evs = self._events()
        self.assertFalse([e for e in evs if e.get("action") == "RISK_PLAN_REQUIRED"])
        self.assertFalse([e for e in evs if e.get("action") == "CONFIRMED"])
        self.assertEqual(self.st["pending_open_fills"], [])
        self.assertEqual(self.st["positions"], {})
        blocked = [e for e in evs if "entry_not_authorized" in e.get("why", "")]
        self.assertEqual(len(blocked), 1, "fail-closed event emitted once")

    def test_restart_does_not_resurrect_or_duplicate(self):
        self.st = self._state()
        wl = {"watches": [_watch()], "open_positions": []}
        m.close_pass(self.st, wl, {"ASST": self._df()}, "2026-10-07")
        before = len(self._events())
        restored = json.loads(json.dumps(self.st))
        self.st = restored
        m.close_pass(self.st, wl, {"ASST": self._df()}, "2026-10-07")
        self.assertEqual(len(self._events()), before)
        self.assertEqual(self.st["pending_open_fills"], [])

    def test_do_fill_refuses_unauthorized_watch(self):
        self.st = self._state()
        wl = {"watches": [_watch()], "open_positions": []}
        m.do_fill(self.st, wl, "ASST", 20.0, 0.25)
        self.assertEqual(self.st["positions"], {})
        self.assertEqual(self.st["cash"], 50000.0)

    def test_authorized_executable_watch_still_queues_fill(self):
        _doc(self.d, "2026-10-07", "EXECUTABLE_WATCH", "DETERMINISTIC_CONFIRMATION")
        self.st = self._state()
        w = _watch("2026-10-07", artifact="ASST_2026-10-07.json")
        w["trigger_type"] = "close_breakout_vol"
        wl = {"watches": [w], "open_positions": []}
        m.close_pass(self.st, wl, {"ASST": self._df()}, "2026-10-07")
        self.assertEqual(self.st["pending_open_fills"][0]["ticker"], "ASST")


if __name__ == "__main__":
    unittest.main()
