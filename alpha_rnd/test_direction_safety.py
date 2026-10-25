#!/usr/bin/env python3
"""Direction-safety regression tests (PCVX/HESM defect).

A legacy intent with no economic_authority contract must never become an
executable LONG watch when its geometry or params are SHORT-shaped.
Synthetic fixtures only — no model calls, no production state.
"""
import unittest

import alpha_rnd.synthesize as sz


def _intent(**kw):
    base = {"ticker": "X", "classification": "WATCH_FOR_ENTRY",
            "watch_mode": "DETERMINISTIC_CONFIRMATION",
            "trigger": "re-entry only on confirmed hold",
            "params": {"zone": [60.0, 62.0]},
            "entry_convention": "trigger-based re-entry",
            "invalidation": "close below 55", "stop_level": 55.0,
            "target": None, "horizon": "weeks", "reevaluation": "earnings",
            "size_frac": 0.5, "auto_execution_authorized": False,
            "ambiguity": None}
    base.update(kw)
    return base


class DirectionSafetyTest(unittest.TestCase):
    def test_pcvx_shape_blocked(self):
        # PCVX 2026-10-07: Sell signal, re-entry zone 62-64, the recorded
        # stop_level 73.8 belongs to a rejected short framing.
        i = _intent(params={"reentry_zone": [62, 64], "reclaim": 68.6,
                            "shelf": 59.5, "breakdown": 63.9},
                    stop_level=73.8)
        self.assertTrue(sz._bearish_geometry(i))
        self.assertFalse(sz._machine_executable(i))
        self.assertEqual(sz.disposition(i, [], set()),
                         "PUBLISHED_NON_EXECUTABLE")

    def test_hesm_shape_blocked(self):
        # HESM 2026-10-12: explicit short_zone params — short-only plan.
        i = _intent(params={"short_zone": [34, 35.3], "reclaim": 34,
                            "breakdown": 31.99}, stop_level=37.6)
        self.assertTrue(sz._bearish_geometry(i))
        self.assertFalse(sz._machine_executable(i))
        self.assertEqual(sz.disposition(i, [], set()),
                         "PUBLISHED_NON_EXECUTABLE")

    def test_valid_long_zone_passes(self):
        i = _intent()
        self.assertFalse(sz._bearish_geometry(i))
        self.assertTrue(sz._machine_executable(i))
        self.assertEqual(sz.disposition(i, [], set()), "EXECUTABLE_WATCH")

    def test_stop_at_zone_top_boundary_blocked(self):
        i = _intent(params={"zone": [60, 62]}, stop_level=62.0)
        self.assertTrue(sz._bearish_geometry(i))

    def test_missing_levels_fail_open_to_other_gates(self):
        # no parseable entry level -> geometry check abstains; the existing
        # param-key/risk-plan gates still decide (fail-closed elsewhere).
        i = _intent(params={}, stop_level=55.0)
        self.assertFalse(sz._bearish_geometry(i))
        self.assertFalse(sz._machine_executable(i))  # no executable param key

    def test_short_wording_alone_not_blocked(self):
        # "no short permitted" prose must not suppress a valid long watch.
        i = _intent(entry_convention="trigger-based re-entry; "
                                     "no short permitted")
        self.assertFalse(sz._bearish_geometry(i))

    def test_contract_path_unaffected(self):
        # a validated LONG contract still decides via project_execution
        i = _intent(economic_authority_resolved={
            "direction": "LONG",
            "entry": {"mode": "LIMIT_ZONE", "zone": [60.0, 62.0]},
            "sizing": {"initial_frac": 0.5},
            "stop": {"type": "close_below", "level": 55.0},
            "objective": {"target": 70.0}, "horizon": "weeks"})
        self.assertTrue(sz._machine_executable(i))


if __name__ == "__main__":
    unittest.main()
