import json
import tempfile
import unittest
from pathlib import Path

import alpha_rnd.translator_gap as tg

S = "2026-10-12"


def _t(disp, exe=False, sig="Sell", deep=True, held=False):
    return {"eligibility": {"eligible": True},
            "screen": {"cohort": "TOP_1_10", "pool_rank": 1},
            "deep": {"selected": deep},
            "ta": {"final_signal": sig},
            "publication": {"disposition": disp, "executable": exe},
            "portfolio": {"existing_position": held}}


def fixture(root: Path):
    ev = root / "evaluations" / "alpha_rnd_v1"
    (ev / "opportunity_funnel").mkdir(parents=True)
    (ev / "rank_cohort_outcomes").mkdir(parents=True)
    fdoc = {"session": S, "provenance": {"backfilled": False},
            "tickers": {
                "ZNE": _t("PUBLISHED_NON_EXECUTABLE"),   # zone params
                "TXT": _t("PUBLISHED_NON_EXECUTABLE"),   # explicit text predicate
                "VAG": _t("PUBLISHED_NON_EXECUTABLE"),   # vague prose
                "RPK": _t("RISK_PLAN_REQUIRED"),
                "AMB": _t("AMBIGUOUS_REJECTED"),
                "EXE": _t("EXECUTABLE_WATCH", exe=True, sig="Buy"),
                "HELD": _t("OPEN_POSITION_MANAGEMENT", held=True)}}
    (ev / "opportunity_funnel" / f"{S}.json").write_text(json.dumps(fdoc))
    intents = {"intents": {
        "ZNE": {"params": {"starter_zone": [53, 54]}, "trigger": "into zone"},
        "TXT": {"params": {"primary_limit": 197.5},
                "trigger": "staged limit order at $197.50"},
        "VAG": {"params": {"note": "buy if sentiment improves"},
                "trigger": "buy if sentiment improves"}}}
    (ev / f"publication_intents_{S}.json").write_text(json.dumps(intents))
    (ev / "rank_cohort_outcomes" / f"{S}.json").write_text(json.dumps({
        "session": S, "tickers": {
            "ZNE": {"horizons": {"H1": {"status": "MATURED",
                                        "raw_return_pct": 5.0}}},
            "TXT": {"horizons": {"H1": {"status": "PENDING"}}}}}))


class GapTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.ev, self.fu, self.od = tg.EV, tg.FUNNEL, tg.OUT_DIR
        base = Path(self.d.name) / "evaluations" / "alpha_rnd_v1"
        tg.EV, tg.FUNNEL, tg.OUT_DIR = base, base / "opportunity_funnel", \
            base / "rank_cohort_outcomes"
        fixture(Path(self.d.name))

    def tearDown(self):
        tg.EV, tg.FUNNEL, tg.OUT_DIR = self.ev, self.fu, self.od

    def _obs(self):
        return {o["ticker"]: o for o in tg.observations()}

    def test_buckets(self):
        o = self._obs()
        self.assertEqual(o["ZNE"]["gap_layer"], "B_TRANSLATION")
        self.assertEqual(o["ZNE"]["matched_pattern"], "PARAM_ZONE_LIKE")
        self.assertTrue(o["ZNE"]["safe_translation_candidate"])
        self.assertEqual(o["TXT"]["gap_layer"], "B_TRANSLATION")
        self.assertEqual(o["TXT"]["matched_pattern"], "LIMIT_AT")
        self.assertEqual(o["VAG"]["gap_layer"], "A_INTENT_QUALITY")
        self.assertTrue(o["VAG"]["fundamentally_not_machine_actionable"])
        self.assertEqual(o["RPK"]["gap_layer"], "D_RISK_PLAN")
        self.assertEqual(o["AMB"]["gap_layer"], "A_INTENT_QUALITY")
        self.assertEqual(o["EXE"]["gap_layer"], "NONE")
        self.assertEqual(o["HELD"]["decision_context"], "OPEN_POSITION_MANAGEMENT")

    def test_r2_passthrough_and_capability_versioning(self):
        o = self._obs()
        self.assertEqual(o["ZNE"]["r2"]["horizons"]["H1"]["status"], "MATURED")
        self.assertEqual(o["TXT"]["r2"]["horizons"]["H1"]["status"], "PENDING")
        self.assertTrue(o["ZNE"]["capability_sha"])  # pinned to session's monitor

    def test_no_duplicate_and_clean(self):
        obs = tg.observations(clean_only=True)
        keys = [(o["session"], o["ticker"]) for o in obs]
        self.assertEqual(len(keys), len(set(keys)))
        st = tg.status()
        self.assertIn("B_TRANSLATION: 2", st)
        self.assertIn("LIMIT_AT", st)


if __name__ == "__main__":
    unittest.main()
