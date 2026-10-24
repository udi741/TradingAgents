#!/usr/bin/env python3
"""Scenario-replay tests: caps, isolation, determinism — synthetic fixtures
only, no production artifacts or live calls."""
import json
import pickle
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from alpha_rnd import scenario_replay as sr  # noqa: E402


def _mk_ev(tmp: Path, ticker="ZZT", session="2026-10-15"):
    """Fabricated ev_dir: artifact + 60-bar market cache + intents doc."""
    ev = tmp / "ev"; (ev / "case_artifacts").mkdir(parents=True)
    art = {"ticker": ticker, "signal": "Overweight",
           "decision_session": session,
           "final_trade_decision":
               "zone 10.0-10.5, stop 9.0, target 12.0, 50% deploy, 4 weeks",
           "trader_investment_plan": "", "risk_judge_decision": "",
           "investment_plan": ""}
    (ev / "case_artifacts" / f"{ticker}_{session}.json").write_text(
        json.dumps(art))
    idx = pd.bdate_range("2026-08-01", periods=60)
    df = pd.DataFrame({"Open": 9.0, "High": 10.4, "Low": 8.9,
                       "Close": [9.0] * 20 + [10.2] * 40,  # in-zone closes
                       "Volume": 1e6}, index=idx)
    # keep >10 sessions after 10-15 inside the cap
    df.index.name = "Date"
    pickle.dump(({ticker: df}, {}), open(ev / f"market_cache_2026-10-30.pkl",
                                        "wb"))
    return ev


def _scenario(ticker="ZZT", session="2026-10-15", cls="POSITIVE_PATH",
              expected=None, grant=True, extra_intent=None, watch=None):
    i = {"classification": "ACTIONABLE_NOW", "watch_mode": "AUTO_ENTRY",
         "auto_execution_authorized": True, "trigger": "zone 10.0-10.5",
         "ambiguity": None,
         "ambiguities": [{"type": "SIZING_CONFLICT", "detail": "x"}],
         "params": {"zone": [10.0, 10.5]},
         "stop_level": 9.0, "target": 12.0, "size_frac": 0.5,
         "economic_authority": {
             "schema_version": 1, "ticker": ticker, "session": session,
             "direction": "LONG",
             "entry": {"mode": "LIMIT_ZONE", "zone": [10.0, 10.5]},
             "sizing": {"initial_frac": 0.5, "max_frac": 0.5, "tranches": []},
             "stop": {"type": "close_below", "level": 9.0},
             "objective": {"target": 12.0},
             "success_criteria": "x", "profit_realization_plan": "x",
             "horizon": "4 weeks", "event_constraints": [],
             "no_entry_conditions": [], "resolves": ["SIZING_CONFLICT"]}}
    if extra_intent:
        i.update(extra_intent)
    return {"id": f"{ticker}_{session}", "class": cls, "ticker": ticker,
            "session": session, "reason": "t", "intent": i,
            "watch": watch if watch is not None else {
                "trigger_type": "multi_close_in_zone",
                "params": {"zone": [10.0, 10.5]},
                "stop_rule": {"type": "intraday_stop", "level": 9.0}},
            "grant_authorization": grant,
            "expected": expected or {"disposition": "EXECUTABLE_WATCH",
                                     "trigger": "reached",
                                     "order": "created"}}


class ScenarioReplay(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.ev = _mk_ev(self.tmp)

    def _run(self, scenarios):
        mp = self.tmp / "m.json"
        mp.write_text(json.dumps({"scenarios": scenarios}))
        return sr.run_manifest(str(mp), self.ev)

    def test_scenario_cap(self):
        with self.assertRaises(RuntimeError):
            self._run([_scenario() for _ in range(13)])

    def test_positive_path_full_chain(self):
        r = self._run([_scenario()])["scenarios"][0]
        self.assertEqual(r["result"], "PASS")
        self.assertEqual(r["disposition"], "EXECUTABLE_WATCH")
        self.assertEqual(r["contract"], "VALID")
        self.assertTrue(r["replay"]["order_created"])

    def test_negative_nonresolvable(self):
        s = _scenario(extra_intent={
            "ambiguities": [{"type": "CATALYST_UNRESOLVED", "detail": "x"}]},
            expected={"disposition": "AMBIGUOUS_REJECTED", "order": "none"})
        r = self._run([s])["scenarios"][0]
        self.assertEqual(r["result"], "PASS")

    def test_stale_watch_not_authorized_no_order(self):
        s = _scenario(grant=False,
                      expected={"disposition": "EXECUTABLE_WATCH",
                                "not_authorized": True, "order": "none"})
        r = self._run([s])["scenarios"][0]
        self.assertEqual(r["result"], "PASS")
        self.assertTrue(r["replay"]["not_authorized"])
        self.assertFalse(r["replay"]["order_created"])

    def test_trigger_not_reached_passes(self):
        s = _scenario(extra_intent={"economic_authority": None,
                                    "ambiguities": None},
                      watch={"trigger_type": "close_breakout_vol",
                             "params": {"bo_level": 99.0},
                             "stop_rule": {"type": "intraday_stop",
                                           "level": 9.0}},
                      expected={"disposition": "EXECUTABLE_WATCH",
                                "trigger": "not_reached", "order": "none"})
        r = self._run([s])["scenarios"][0]
        self.assertEqual(r["result"], "PASS")
        self.assertIsNone(r["replay"]["triggered_at"])

    def test_forbidden_order_detected(self):
        s = _scenario(grant=False,
                      expected={"order": "created"})  # deliberately wrong
        r = self._run([s])["scenarios"][0]
        self.assertEqual(r["result"], "FAIL")

    def test_deterministic_rerun(self):
        a = self._run([_scenario()])
        b = self._run([_scenario()])
        self.assertEqual(a["scenarios"][0]["replay"],
                         b["scenarios"][0]["replay"])

    def test_no_production_mutation(self):
        before = sorted((self.ev / "case_artifacts").iterdir())
        self._run([_scenario()])
        self.assertEqual(before, sorted((self.ev / "case_artifacts").iterdir()))
        self.assertFalse((self.ev / "monitor_state.json").exists())
        self.assertFalse((self.ev / "live_watchlist.json").exists())


if __name__ == "__main__":
    unittest.main()
