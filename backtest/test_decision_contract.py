import unittest, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import decision_contract as dc

def base(**kw):
    c = {"direction": "LONG", "entry": {"type": "limit_zone",
         "zone": [60, 62]}, "stop": 55.0, "target": 70.0,
         "horizon": "weeks", "size_frac": 0.5, "provenance": {"t": "X"}}
    c.update(kw); return c

class T(unittest.TestCase):
    def test_valid_long(self):
        c = base(); self.assertEqual(dc.validate(c), [])
        self.assertAlmostEqual(c["reward_risk"], 8/7, places=2)
    def test_long_stop_above_entry_rejected(self):
        self.assertIn("STOP_NOT_BELOW_ENTRY",
                      dc.validate(base(stop=63.0)))
    def test_valid_short(self):
        c = base(direction="SHORT",
                 entry={"type": "limit_zone", "zone": [60, 62]},
                 stop=65.0, target=52.0)
        self.assertEqual(dc.validate(c), [])
    def test_short_stop_below_entry_rejected(self):
        self.assertIn("STOP_NOT_ABOVE_ENTRY",
                      dc.validate(base(direction="SHORT", stop=55.0,
                                       target=52.0,
                                       entry={"type": "limit_zone",
                                              "zone": [60, 62]})))
    def test_short_must_be_paper_only(self):
        c = base(direction="SHORT", entry={"type": "limit_level",
                 "level": 60}, stop=65.0, target=52.0, paper_only=False)
        self.assertIn("SHORT_MUST_BE_PAPER_ONLY", dc.validate(c))
    def test_no_trade_needs_reason(self):
        self.assertEqual(dc.validate({"direction": "NO_TRADE",
                                      "reason": "no entry spec"}), [])
        self.assertIn("NO_TRADE_WITHOUT_REASON",
                      dc.validate({"direction": "NO_TRADE"}))
    def test_missing_terms_rejected(self):
        for miss in ("stop", "target", "entry"):
            c = base(**{miss: None})
            self.assertTrue(dc.validate(c), miss)
    def test_synthetic_short_authored(self):
        # labeled synthetic fixture — NOT a profitable-opportunity claim
        i = {"ticker": "SYN", "classification": "WATCH_FOR_ENTRY",
             "params": {"short_zone": [50, 52]},
             "stop_level": 54.0, "target": 44.0, "horizon": "weeks",
             "size_frac": 0.3, "invalidation": "close above 54",
             "entry_convention": "short on bounce into 50-52"}
        c = dc.author(i, "Sell", True, "2025-01-01")
        self.assertEqual(c["direction"], "SHORT")
        self.assertTrue(c["paper_only"])
        self.assertEqual(c["exit_mode"], "buy_to_cover")
    def test_unspecified_short_falls_back_to_no_trade(self):
        i = {"ticker": "SYN2", "classification": "WATCH_FOR_ENTRY",
             "params": {}, "stop_level": None, "size_frac": 0.3,
             "entry_convention": "short if it breaks"}
        c = dc.author(i, "Sell", True, "2025-01-01")
        self.assertEqual(c["direction"], "NO_TRADE")
        self.assertIn("MISSING_", c["reason"])

if __name__ == "__main__":
    unittest.main()
