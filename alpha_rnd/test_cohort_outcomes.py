import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

import alpha_rnd.cohort_outcomes as co

SESS = "2026-10-09"  # Friday -> next session Monday 10-12
CAL = ["2026-10-09", "2026-10-12", "2026-10-13", "2026-10-14", "2026-10-15", "2026-10-16"]


def _df(prices_by_session, opens=None):
    idx = pd.to_datetime(list(prices_by_session))
    return pd.DataFrame({"Open": opens or list(prices_by_session.values()),
                         "Close": list(prices_by_session.values()),
                         "High": [p * 1.02 for p in prices_by_session.values()],
                         "Low": [p * 0.98 for p in prices_by_session.values()],
                         "Volume": [1e6] * len(prices_by_session)}, index=idx)


def fixture(root: Path):
    ev = root / "evaluations" / "alpha_rnd_v1"
    (ev / "opportunity_funnel").mkdir(parents=True)
    doc = {"session": SESS, "provenance": {"backfilled": False},
           "tickers": {
               "A": {"eligibility": {"eligible": True},
                     "screen": {"cohort": "TOP_1_10", "primary_rank": 3,
                                "lane_ranks": {"A": 3}, "pool_rank": 2,
                                "pool_selected": True},
                     "deep": {"selected": True}},
               "B": {"eligibility": {"eligible": True},
                     "screen": {"cohort": "RANK_11_25", "primary_rank": 14,
                                "lane_ranks": {"B": 14}, "pool_rank": 12},
                     "deep": {"selected": False}},
               "C": {"eligibility": {"eligible": True},
                     "screen": {"cohort": "RANK_51_100", "primary_rank": 80,
                                "lane_ranks": {"A": 80}, "pool_rank": None},
                     "deep": {"selected": False}},
               "GONE": {"eligibility": {"eligible": True},
                        "screen": {"cohort": "RANK_101_PLUS", "primary_rank": 500,
                                   "lane_ranks": {"C": 500}, "pool_rank": None},
                        "deep": {"selected": False}}}}
    (ev / "opportunity_funnel" / f"{SESS}.json").write_text(json.dumps(doc))


class CohortTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        root = Path(self.d.name)
        fixture(root)
        self.ev = co.EV; self.od = co.OUT_DIR
        co.EV = root / "evaluations" / "alpha_rnd_v1"
        co.OUT_DIR = co.EV / "rank_cohort_outcomes"
        self.md = {"SPY": _df({"2026-10-12": 100, "2026-10-13": 101, "2026-10-14": 102, "2026-10-15": 102, "2026-10-16": 103}),
                   "A": _df({"2026-10-12": 10, "2026-10-13": 10.5, "2026-10-14": 10.8, "2026-10-15": 10.9, "2026-10-16": 11}),
                   "B": _df({"2026-10-12": 20, "2026-10-13": 19, "2026-10-14": 18.5, "2026-10-15": 18.5, "2026-10-16": 18}),
                   "C": _df({"2026-10-12": 5, "2026-10-13": 5.1, "2026-10-14": 5.15, "2026-10-15": 5.15, "2026-10-16": 5.2})}
        self.patches = [
            mock.patch.object(co, "_sessions_index", return_value=CAL),
            mock.patch.object(co, "_fetch",
                              return_value=(self.md, []))]
        [p.start() for p in self.patches]

    def tearDown(self):
        [p.stop() for p in self.patches]
        co.EV, co.OUT_DIR = self.ev, self.od

    def test_next_open_entry_across_weekend_and_maturity(self):
        co.update()
        out = json.loads((co.OUT_DIR / f"{SESS}.json").read_text())
        a = out["tickers"]["A"]
        self.assertEqual(a["entry_session"], "2026-10-12")  # Monday, not Sat
        self.assertEqual(a["horizons"]["H1"]["target_session"], "2026-10-12")
        self.assertEqual(a["horizons"]["H5"]["target_session"], "2026-10-16")
        self.assertIsNone(a["horizons"]["H20"]["target_session"])

    def test_returns_and_excess(self):
        co.update()
        a = json.loads((co.OUT_DIR / f"{SESS}.json").read_text())["tickers"]["A"]
        h1 = a["horizons"]["H1"]
        self.assertEqual(h1["status"], "MATURED")
        self.assertAlmostEqual(h1["raw_return_pct"], 0.0)  # 10->10
        # SPY 100->101 = +1% on H5? no—H1: 100->100=0; H5 target 10-14=103
        h5 = a["horizons"]["H5"]
        self.assertAlmostEqual(h5["raw_return_pct"], 10.0)
        self.assertAlmostEqual(h5["benchmark_return_pct"], 3.0)
        self.assertAlmostEqual(h5["excess_return_pct"], 7.0)
        self.assertAlmostEqual(h5["MFE_pct"], 12.2, 1)  # 11*1.02/10 - 1
        self.assertLess(h5["MAE_pct"], 0)

    def test_pending_and_unavailable_and_idempotent(self):
        co.update()
        out = json.loads((co.OUT_DIR / f"{SESS}.json").read_text())
        self.assertEqual(out["tickers"]["A"]["horizons"]["H20"]["status"],
                         "PENDING")
        self.assertEqual(out["tickers"]["GONE"]["horizons"]["H1"]["status"],
                         "DATA_UNAVAILABLE")  # stays in denominator
        n0 = (co.OUT_DIR / f"{SESS}.json").read_text()
        co.update()  # idempotent: matured records never rewritten
        self.assertEqual((co.OUT_DIR / f"{SESS}.json").read_text(), n0)

    def test_stage_classification(self):
        co.update()
        out = json.loads((co.OUT_DIR / f"{SESS}.json").read_text())
        self.assertEqual(out["tickers"]["A"]["stage"], "DEEP_SELECTED")
        self.assertEqual(out["tickers"]["B"]["stage"], "POOL_SELECTED_NOT_DEEP")
        self.assertEqual(out["tickers"]["C"]["stage"],
                         "ELIGIBLE_NOT_POOL_SELECTED")
        # cohort semantics preserved: primary_rank, not fabricated global rank
        self.assertIsNone(out["tickers"]["A"].get("full_universe_rank"))
        self.assertEqual(out["tickers"]["B"]["primary_rank"], 14)


if __name__ == "__main__":
    unittest.main()


class SchedulerTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        root = Path(self.d.name)
        fixture(root)
        self.ev, self.od = co.EV, co.OUT_DIR
        self.log, self.lk, self.hf = co.LOG, co.LOCK, co.HEALTH
        co.EV = root / "evaluations" / "alpha_rnd_v1"
        co.OUT_DIR = co.EV / "rank_cohort_outcomes"
        co.LOG = root / "alpha_rnd" / "co.log"
        co.LOCK = root / "alpha_rnd" / "co.lock"
        co.HEALTH = root / "alpha_rnd" / "co_state.json"
        self.md = {"SPY": _df({d: 100 + i for i, d in enumerate(CAL[1:])}),
                   "A": _df({d: 10 + i * 0.1 for i, d in enumerate(CAL[1:])}),
                   "B": _df({d: 20 for d in CAL[1:]}),
                   "C": _df({d: 5 for d in CAL[1:]})}

    def tearDown(self):
        co.EV, co.OUT_DIR = self.ev, self.od
        co.LOG, co.LOCK, co.HEALTH = self.log, self.lk, self.hf

    def test_lock_excludes_overlap(self):
        with mock.patch.object(co, "_sessions_index", return_value=CAL), \
             mock.patch.object(co, "_fetch", return_value=(self.md, [])):
            import fcntl as _f
            co.LOCK.parent.mkdir(parents=True, exist_ok=True)
            with open(co.LOCK, "w") as lf:
                _f.flock(lf, _f.LOCK_EX)
                r = co.run_locked()
                self.assertEqual(r, {"skipped": "locked"})

    def test_catchup_and_health(self):
        with mock.patch.object(co, "_sessions_index", return_value=CAL), \
             mock.patch.object(co, "_fetch", return_value=(self.md, [])):
            r = co.run_locked()
            self.assertEqual(r["sessions_touched"], [SESS])
            out = json.loads((co.OUT_DIR / f"{SESS}.json").read_text())
            self.assertEqual(out["tickers"]["A"]["horizons"]["H5"]["status"],
                             "MATURED")
            h = json.loads(co.HEALTH.read_text())
            self.assertEqual(h["status"], "OK")
            r2 = co.run_locked()  # idempotent second run
            self.assertEqual(r2["sessions_touched"], [])

    def test_transient_failure_stays_pending(self):
        with mock.patch.object(co, "_sessions_index", return_value=CAL), \
             mock.patch.object(co, "_fetch",
                               return_value=({"SPY": self.md["SPY"]},
                                             ["A", "B", "C", "GONE"])):
            co.run_locked()
            out = json.loads((co.OUT_DIR / f"{SESS}.json").read_text())
            self.assertEqual(out["tickers"]["A"]["horizons"]["H1"]["status"],
                             "PENDING")  # retryable, not burned
        # retry succeeds later
        with mock.patch.object(co, "_sessions_index", return_value=CAL), \
             mock.patch.object(co, "_fetch", return_value=(self.md, [])):
            co.run_locked()
            out = json.loads((co.OUT_DIR / f"{SESS}.json").read_text())
            self.assertEqual(out["tickers"]["A"]["horizons"]["H1"]["status"],
                             "MATURED")
