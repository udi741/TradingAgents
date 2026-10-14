import json
import tempfile
import unittest
from pathlib import Path

import alpha_rnd.funnel as F

S = "2026-10-13"


def fixture(root: Path):
    ev = root / "evaluations" / "alpha_rnd_v1"
    (ev / "case_artifacts").mkdir(parents=True)
    (root / "alpha_rnd").mkdir(parents=True)
    pool = {
        "session": S, "universe_size_raw": 5, "universe_size_eligible": 3,
        "filters": {"min_history": 252, "min_price": 5.0,
                    "min_median_dv20": 20000000},
        "exclusion_counts": {"price_below_5": 2},
        "exclusions": {"price_below_5": ["AAA", "BBB"]},
        "eligible_features": {
            "A1": {"close": 12.0, "rs_60": 1.0,
                   "lanes": {"A": [0.9, 1]}, "primary_rank": 1},
            "A2": {"close": 20.0, "rs_60": 1.5,
                   "lanes": {"A": [0.8, 2], "RS": [2.4, 1]}, "primary_rank": 1},
            "A3": {"close": 9.0, "rs_60": 0.5,
                   "lanes": {"B": [0.7, 3]}, "primary_rank": 3},
            **{f"X{i:03d}": {"close": 10.0 + i * 0.01, "rs_60": 0.1,
                             "lanes": {"A": [0.5 - i * 0.001, 10 + i]},
                             "primary_rank": 10 + i}
               for i in range(1, 201)}},
        "deep_quota": 2,
        "candidates": [
            {"ticker": "A1", "labels": ["MOMENTUM"], "close": 12.0,
             "rs_60": 1.0, "ret_5": 0.01, "vol_ratio_5_20": 1.0},
            {"ticker": "A2", "labels": ["MOMENTUM", "CATALYST"],
             "close": 20.0, "rs_60": 1.5, "ret_5": 0.02,
             "vol_ratio_5_20": 1.2},
            {"ticker": "A3", "labels": ["QUALITY_PULLBACK"], "close": 9.0,
             "rs_60": 0.5, "ret_5": -0.01, "vol_ratio_5_20": 0.9}],
        "artifact_sha256": "abc"}
    (ev / f"candidate_pool_frozen_{S}.json").write_text(json.dumps(pool))
    for t, sig in (("A1", "Sell"), ("A2", "Buy")):
        (ev / "case_artifacts" / f"{t}_{S}.json").write_text(
            json.dumps({"ticker": t, "signal": sig}))
    intents = {"session": S, "dispositions": {
        "A1": {"disposition": "PUBLISHED_NON_EXECUTABLE", "violations": [],
               "executable": False, "artifact": f"case_artifacts/A1_{S}.json"},
        "A2": {"disposition": "EXECUTABLE_WATCH", "violations": [],
               "executable": True, "artifact": f"case_artifacts/A2_{S}.json"}}}
    (ev / f"publication_intents_{S}.json").write_text(json.dumps(intents))
    (root / "alpha_rnd" / "live_watchlist.json").write_text(json.dumps({
        "watches": [{"ticker": "A2", "trigger_type": "close_in_zone",
                     "params": {"zone": [19, 20]}}]}))
    (root / "alpha_rnd" / "monitor_state.json").write_text(json.dumps({
        "positions": {"A3": {"shares": 5}}, "emitted_ids": [],
        "risk_blocked": {}}))
    return pool


class FunnelTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.root = Path(self.d.name)
        self.pool = fixture(self.root)
        self.doc = F.build(S, root=self.root)

    def test_exclusion_recorded_with_threshold(self):
        t = self.doc["tickers"]["AAA"]
        self.assertFalse(t["eligibility"]["eligible"])
        self.assertEqual(t["eligibility"]["exclusion_reason"], "PRICE_BELOW_MIN")
        self.assertEqual(t["eligibility"]["threshold"]["min_price"], 5.0)

    def test_rank_cohorts_and_deep_selection(self):
        tk = self.doc["tickers"]
        self.assertEqual(tk["A2"]["screen"]["cohort"], "TOP_1_10")
        self.assertTrue(tk["A2"]["deep"]["selected"])
        # A3 ranks 3rd (score 11) with quota 2 -> cohort TOP_1_10 but not deep
        self.assertEqual(tk["A3"]["screen"]["cohort"], "TOP_1_10")
        self.assertFalse(tk["A3"]["deep"]["selected"])
        self.assertIn("quota", tk["A3"]["deep"]["selection_reason"])
        self.assertEqual(self.doc["deep_selected_count"], 2)

    def test_sell_disposition_not_executable(self):
        p = self.doc["tickers"]["A1"]["publication"]
        self.assertEqual(p["disposition"], "PUBLISHED_NON_EXECUTABLE")
        self.assertFalse(p["executable"])
        self.assertEqual(self.doc["tickers"]["A1"]["ta"]["final_signal"], "Sell")

    def test_executable_and_held_distinct(self):
        p2 = self.doc["tickers"]["A2"]["publication"]
        self.assertEqual(p2["disposition"], "EXECUTABLE_WATCH")
        self.assertTrue(p2["executable"])
        self.assertEqual(self.doc["tickers"]["A2"]["monitor"]["trigger_type"],
                         "close_in_zone")
        self.assertTrue(self.doc["tickers"]["A3"]["portfolio"]["existing_position"])
        self.assertEqual(self.doc["executable_watch_count"], 1)

    def test_idempotent_byte_stable(self):
        p = self.root / "evaluations/alpha_rnd_v1/opportunity_funnel" / f"{S}.json"
        before = p.read_text()
        again = F.build(S, root=self.root)
        self.assertEqual(p.read_text(), before)
        self.assertEqual(again["created_at"], self.doc["created_at"])

    def test_full_universe_cohort_coverage(self):
        # >150 eligible; every eligible gets authentic provenance or a cohort
        tk = self.doc["tickers"]
        self.assertEqual(tk["X004"]["screen"]["cohort"], "RANK_11_25")   # pr 14
        self.assertEqual(tk["X030"]["screen"]["cohort"], "RANK_26_50")   # pr 40
        self.assertEqual(tk["X065"]["screen"]["cohort"], "RANK_51_100")  # pr 75
        self.assertEqual(tk["X140"]["screen"]["cohort"], "RANK_101_PLUS")# pr 150
        self.assertFalse(tk["X004"]["screen"]["pool_selected"])
        self.assertEqual(tk["X004"]["screen"]["lane_ranks"], {"A": 14})
        self.assertIsNone(tk["X004"]["screen"]["full_universe_rank"])
        c = self.doc["summary"]["rank_cohorts"]
        self.assertGreater(c["RANK_101_PLUS"], 0)

    def test_inputs_unchanged(self):
        after = json.loads((self.root / "evaluations" / "alpha_rnd_v1" /
                            f"candidate_pool_frozen_{S}.json").read_text())
        self.assertEqual(after, self.pool)  # read-only: artifact untouched


if __name__ == "__main__":
    unittest.main()
