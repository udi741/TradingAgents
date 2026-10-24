#!/usr/bin/env python3
"""do_fill robustness: structured/string/missing invalidation must not
crash the fill path or alter order economics."""
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

if "fcntl" not in sys.modules:  # Windows: monitor's state locking unused here
    fcntl = types.ModuleType("fcntl")
    fcntl.flock = lambda *a, **k: None
    fcntl.LOCK_EX = fcntl.LOCK_SH = fcntl.LOCK_UN = fcntl.LOCK_NB = 0
    sys.modules["fcntl"] = fcntl

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from alpha_rnd import monitor as m  # noqa: E402


def _st():
    return {"last_check_utc": None, "processed_close_sessions": [],
            "confirm": {}, "pending_open_fills": [], "pending_open_exits": [],
            "positions": {}, "cash": 50000.0, "nav_last": 50000.0,
            "watch_status": {}, "executed": [], "emitted_ids": [],
            "event_outbox": [], "risk_blocked": {}}


def _watch(invalidation):
    return {"ticker": "XYZ", "cls": "AUTO_ENTRY",
            "trigger_type": "intraday_zone_touch", "v": "auto",
            "params": {"zone": [100.0, 105.0], "entry_price": 105.0,
                       "success_criteria": "x",
                       "profit_realization_plan": "y"},
            "size_frac": 0.4, "invalidation": invalidation,
            "stop_rule": {"type": "intraday_stop", "level": 95.0},
            "target": 130.0, "trigger": "zone", "horizon": "3m",
            "artifact": "case_artifacts/XYZ_2026-10-12.json",
            "session": "2026-10-12"}


class RenderInvalidation(unittest.TestCase):
    def test_string_passthrough(self):
        s = "hard stop at $41.75 on heavy volume"
        self.assertEqual(m._render_invalidation(s), s)

    def test_dict_renders(self):
        inv = {"type": "close_below", "level": 108.0, "label": "hard stop"}
        self.assertEqual(m._render_invalidation(inv),
                         "close_below 108.0 (hard stop)")

    def test_none(self):
        self.assertEqual(m._render_invalidation(None), "none")


class DoFillRobust(unittest.TestCase):
    def _fill(self, invalidation):
        st, w = _st(), _watch(invalidation)
        wl = {"watches": [w], "open_positions": []}
        with mock.patch.object(m, "authorized", lambda *a, **k: True), \
                mock.patch.object(m, "NOTIFY",
                                  Path(self._tmp.name) / "n.log"), \
                mock.patch.object(m, "desktop_notify", lambda *a, **k: None):
            m.do_fill(st, wl, "XYZ", 105.0, 0.4)
        return st, w

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()

    def test_dict_invalidation_fills(self):
        st, w = self._fill({"type": "intraday_stop", "level": 95.0,
                            "label": "hard stop"})
        self.assertIn("XYZ", st["positions"])
        pos = st["positions"]["XYZ"]
        self.assertEqual(pos["fill"], 105.0)
        self.assertEqual(pos["frac"], 0.4)
        self.assertEqual(pos["stop_rule"]["level"], 95.0)
        self.assertEqual(pos["invalidation"]["type"], "intraday_stop")

    def test_string_invalidation_fills(self):
        st, _ = self._fill("stop at $95 hard")
        self.assertIn("XYZ", st["positions"])
        self.assertEqual(st["positions"]["XYZ"]["invalidation"],
                         "stop at $95 hard")

    def test_economics_unchanged_by_render(self):
        st1, _ = self._fill({"type": "intraday_stop", "level": 95.0})
        st2, _ = self._fill("stop at $95 hard")
        p1, p2 = st1["positions"]["XYZ"], st2["positions"]["XYZ"]
        self.assertEqual(p1["shares"], p2["shares"])
        self.assertEqual(p1["cost"], p2["cost"])


if __name__ == "__main__":
    unittest.main()
