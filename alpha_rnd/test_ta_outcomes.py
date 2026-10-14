import json
import tempfile
import unittest
from pathlib import Path

import alpha_rnd.ta_outcomes as ta

S = "2026-10-12"
S2 = "2026-10-13"


def _t(elig=True, deep=True, cohort="TOP_1_10", pool_rank=1, sig="Buy",
       disp="EXECUTABLE_WATCH", exe=True, held=False):
    return {"eligibility": {"eligible": elig},
            "screen": {"cohort": cohort, "primary_rank": 1,
                       "pool_rank": pool_rank, "pool_selected": pool_rank is not None},
            "deep": {"selected": deep},
            "ta": {"attempted": True, "final_signal": sig,
                   "artifact": f"case_artifacts/x_{S}.json"},
            "publication": {"disposition": disp, "executable": exe},
            "portfolio": {"existing_position": held}}


def _h(status, ret=None):
    r = {"status": status}
    if status == "MATURED":
        r.update({"raw_return_pct": ret, "excess_return_pct": ret - 1.0,
                  "MFE_pct": ret + 2, "MAE_pct": -2.0})
    return r


def fixture(root: Path):
    ev = root / "evaluations" / "alpha_rnd_v1"
    (ev / "opportunity_funnel").mkdir(parents=True)
    (ev / "rank_cohort_outcomes").mkdir(parents=True)
    # clean session
    (ev / "opportunity_funnel" / f"{S}.json").write_text(json.dumps({
        "session": S, "provenance": {"backfilled": False},
        "tickers": {
            "BUY": _t(sig="Buy", disp="EXECUTABLE_WATCH", exe=True),
            "SELL": _t(sig="Sell", disp="AMBIGUOUS_REJECTED", exe=False),
            "HLD": _t(sig="Hold", disp="RESEARCH_ONLY", exe=False, held=True),
            "NOTDEEP": _t(deep=False, sig=None)}}))
    (ev / "rank_cohort_outcomes" / f"{S}.json").write_text(json.dumps({
        "session": S, "funnel_backfilled": False,
        "tickers": {
            "BUY": {"horizons": {"H1": _h("MATURED", 3.0), "H5": _h("PENDING")}},
            "SELL": {"horizons": {"H1": _h("MATURED", -1.0), "H5": _h("PENDING")}},
            "HLD": {"horizons": {"H1": _h("DATA_UNAVAILABLE"), "H5": _h("PENDING")}}}}))
    # diagnostic session (backfilled)
    (ev / "opportunity_funnel" / f"{S2}.json").write_text(json.dumps({
        "session": S2, "provenance": {"backfilled": True},
        "tickers": {"OLD": _t(sig="Sell", disp="AMBIGUOUS_REJECTED")}}))


class TaOutcomesTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.ev, self.fu, self.od = ta.EV, ta.FUNNEL, ta.OUT_DIR
        ta.EV = ta.FUNNEL = ta.OUT_DIR = Path(self.d.name) / "evaluations" / "alpha_rnd_v1"
        ta.FUNNEL = ta.EV / "opportunity_funnel"
        ta.OUT_DIR = ta.EV / "rank_cohort_outcomes"
        fixture(Path(self.d.name))

    def tearDown(self):
        ta.EV, ta.FUNNEL, ta.OUT_DIR = self.ev, self.fu, self.od

    def test_frozen_labels_and_normalization(self):
        obs = {o["ticker"]: o for o in ta.observations()}
        self.assertEqual(obs["BUY"]["raw_ta_signal"], "Buy")
        self.assertEqual(obs["BUY"]["normalized_ta_group"], "POSITIVE")
        self.assertEqual(obs["SELL"]["normalized_ta_group"], "NEGATIVE")
        self.assertEqual(obs["HLD"]["normalized_ta_group"], "NEUTRAL")
        self.assertEqual(ta.norm_group("weird"), "UNKNOWN")

    def test_disposition_separate_and_context(self):
        obs = {o["ticker"]: o for o in ta.observations()}
        self.assertEqual(obs["SELL"]["disposition"], "AMBIGUOUS_REJECTED")
        self.assertEqual(obs["HLD"]["decision_context"], "OPEN_POSITION_MANAGEMENT")
        self.assertEqual(obs["BUY"]["decision_context"], "NEW_ENTRY")
        self.assertNotIn("NOTDEEP", obs)  # never TA-analyzed

    def test_r2_passthrough_and_denominator(self):
        obs = {o["ticker"]: o for o in ta.observations()}
        self.assertEqual(obs["BUY"]["r2"]["horizons"]["H5"]["status"], "PENDING")
        self.assertEqual(obs["BUY"]["r2"]["horizons"]["H1"]["raw_return_pct"], 3.0)
        self.assertEqual(obs["HLD"]["r2"]["horizons"]["H1"]["status"],
                         "DATA_UNAVAILABLE")

    def test_clean_vs_diagnostic_and_one_obs_per_ticker(self):
        obs = ta.observations(clean_only=True)
        self.assertEqual(sorted(o["ticker"] for o in obs),
                         ["BUY", "HLD", "SELL"])
        all_obs = ta.observations(clean_only=False)
        # session+ticker unique
        keys = [(o["session"], o["ticker"]) for o in all_obs]
        self.assertEqual(len(keys), len(set(keys)))
        st = ta.status()
        self.assertIn("Clean prospective deep-analyzed: 3", st)
        self.assertIn("TA POSITIVE: N=1 matured=1", st)
        self.assertIn("diagnostic", st)  # backfilled excluded from headline


if __name__ == "__main__":
    unittest.main()
