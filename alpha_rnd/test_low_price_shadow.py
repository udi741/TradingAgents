import json
import pickle
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

import alpha_rnd.low_price_shadow as lp

S = "2026-10-13"


def mk_bars(close, vol, n=300, trend=False):
    idx = pd.bdate_range(end=S, periods=n)
    px = np.linspace(close * 0.6, close, n) if trend else np.full(n, close)
    return pd.DataFrame({"Open": px, "High": px * 1.01,
                         "Close": px, "Low": px * 0.99,
                         "Volume": vol}, index=idx)


def fixture(root: Path):
    ev = root / "evaluations" / "alpha_rnd_v1"
    ev.mkdir(parents=True)
    (ev / "universe_raw.json").write_text(json.dumps({
        "session": S, "constituents": [
            {"ticker": t, "indices": ["nasdaq_listed"]}
            for t in ("LP_OK", "LP_ILLIQ", "LP_NEW", "LP_SUB1", "MAIN",
                      "NOFETCH")]}))
    spy = mk_bars(100.0, 5e7)
    md = {"SPY": spy,
          "LP_OK": mk_bars(3.5, 3e6),      # $3.50, ~$10.5M dv20? -> tune below
          "LP_ILLIQ": mk_bars(3.0, 1e4),   # $3.00, tiny volume
          "LP_NEW": mk_bars(4.0, 5e6, n=60),  # short history
          "LP_SUB1": mk_bars(0.7, 5e6),
          "MAIN": mk_bars(12.0, 5e6)}
    # LP_OK needs median_dv20 >= 20M: 3.5 * 6e6 = 21M
    md["LP_OK"] = mk_bars(3.5, 6.2e6, trend=True)  # uptrend -> lane A eligible
    (ev / f"market_cache_{S}.pkl").write_bytes(pickle.dumps((md, ["NOFETCH"])))


class LowPriceShadowTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.ev = lp.EV
        lp.EV = Path(self.d.name) / "evaluations" / "alpha_rnd_v1"
        lp.LP_DIR = lp.EV / "low_price_shadow"
        fixture(Path(self.d.name))
        self.doc = lp.build(S)

    def tearDown(self):
        lp.EV = self.ev
        lp.LP_DIR = lp.EV / "low_price_shadow"

    def test_cohort_membership(self):
        tk = self.doc["tickers"]
        self.assertIn("LP_OK", tk)
        self.assertNotIn("MAIN", tk)            # $12 not in shadow
        self.assertNotIn("LP_SUB1", tk)         # <$1 excluded from cohort
        self.assertNotIn("NOFETCH", tk)         # no data -> absent
        self.assertEqual(self.doc["counts"]["below_1"], 1)

    def test_counterfactual_classification(self):
        tk = self.doc["tickers"]
        self.assertTrue(tk["LP_OK"]["counterfactual"]
                        ["would_be_main_eligible_if_price_floor_removed"])
        self.assertIn("LIQUIDITY", tk["LP_ILLIQ"]["counterfactual"]
                      ["nonprice_exclusion_reasons"])
        self.assertEqual(tk["LP_ILLIQ"]["cohort"], "LP_LIQUIDITY")
        self.assertIn("INSUFFICIENT_HISTORY",
                      tk["LP_NEW"]["counterfactual"]
                      ["nonprice_exclusion_reasons"])
        self.assertEqual(self.doc["counts"]["passes_nonprice_main_filters"], 1)

    def test_shadow_rank_and_bands(self):
        tk = self.doc["tickers"]
        self.assertEqual(tk["LP_OK"]["price_band"], "$3.00-3.99")
        self.assertIsNotNone(tk["LP_OK"]["screen"]["primary_rank"])
        self.assertTrue(all(r["screen"]["cohort"] for r in tk.values()))

    def test_idempotent(self):
        p = lp.LP_DIR / f"{S}.json"
        before = p.read_text()
        again = lp.build(S)
        self.assertEqual(p.read_text(), before)
        self.assertEqual(again["created_at"], self.doc["created_at"])

    def test_no_trading_writes(self):
        # LP build wrote only its own artifact dir
        self.assertFalse((Path(self.d.name) / "alpha_rnd").exists())


if __name__ == "__main__":
    unittest.main()
