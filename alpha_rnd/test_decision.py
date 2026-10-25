import unittest, sys
sys.path.insert(0, "backtest")
sys.path.insert(0, ".")
import pandas as pd
from alpha_rnd import decision as dec
import historical_backtest as hb
import decision_contract as ldc  # legacy adapter


EA_LONG = {"direction": "LONG",
           "entry": {"mode": "LIMIT_ZONE", "zone": [60.0, 62.0]},
           "sizing": {"initial_frac": 0.5, "max_frac": 0.75, "tranches": []},
           "stop": {"type": "close_below", "level": 55.0},
           "objective": {"target": 70.0}, "horizon": "weeks",
           "success_criteria": "x", "no_entry_conditions": []}

EA_SHORT = {"direction": "SHORT",
            "entry": {"mode": "LIMIT_ZONE", "zone": [60.0, 62.0]},
            "sizing": {"initial_frac": 0.5, "max_frac": 0.5, "tranches": []},
            "stop": {"type": "close_above", "level": 65.0},
            "objective": {"target": 50.0}, "horizon": "weeks",
            "success_criteria": "x", "no_entry_conditions": []}


class T(unittest.TestCase):
    def test_contract_long(self):
        c = dec.from_economic_authority(EA_LONG, "2026-10-23", "X")
        self.assertEqual(c["direction"], "LONG")
        self.assertEqual(c["entry"]["zone"], [60.0, 62.0])
        self.assertGreater(c["reward_risk"], 0)

    def test_contract_short_paper_only(self):
        c = dec.from_economic_authority(EA_SHORT, "2026-10-23", "X")
        self.assertEqual(c["direction"], "SHORT")
        self.assertTrue(c["paper_only"])
        self.assertEqual(c["exit_mode"], "buy_to_cover")

    def test_short_bad_geometry_rejected(self):
        bad = dict(EA_SHORT, stop={"type": "close_above", "level": 55.0})
        c = dec.from_economic_authority(bad, "s", "X")
        self.assertEqual(c["direction"], "NO_TRADE")
        self.assertIn("STOP_NOT_ABOVE_ENTRY", c["reason"])

    def test_missing_terms_no_trade(self):
        bad = dict(EA_LONG, sizing={})
        c = dec.from_economic_authority(bad, "s", "X")
        self.assertEqual(c["direction"], "NO_TRADE")
        self.assertIn("MISSING_", c["reason"])

    def test_from_intent_prefers_contract(self):
        i = {"ticker": "X", "economic_authority_resolved": EA_LONG}
        c = dec.from_intent(i, "Buy", False, "s")
        self.assertEqual(c["direction"], "LONG")

    def test_end_to_end_sim(self):
        # authored LONG contract -> spec -> sim on synthetic bars
        c = dec.from_economic_authority(EA_LONG, "2025-06-01", "SYN")
        idx = pd.date_range("2025-06-02", periods=30, freq="B")
        rows = []
        for i in range(30):
            lo = 59.0 if i >= 5 else 62.5   # day-6 dip fills zone
            c_ = 54.0 if i >= 12 else 63.0  # day-13 close below stop
            o_ = 53.0 if i >= 13 else 63.0  # next open after breach
            rows.append({"Open": o_, "High": 63.5, "Low": lo,
                         "Close": c_, "Volume": 1e7})
        df = pd.DataFrame(rows, index=idx)
        item = {"intent": {"ticker": "SYN"}, "session": "2025-06-01",
                "short": False,
                "spec": {"kind": "LIMIT_ZONE",
                         "zone": c["entry"]["zone"], "level": None},
                "stop": c["stop"], "target": c["target"],
                "stop_type": "close_below", "frac": c["size_frac"],
                "expiry": "2025-12-31"}
        sim = hb.simulate(item, df, [str(x.date()) for x in idx])
        self.assertEqual(sim["exit_reason"], "close_below_next_open")
        self.assertLess(sim["pnl"], 0)


if __name__ == "__main__":
    unittest.main()
