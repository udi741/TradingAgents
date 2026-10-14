import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import alpha_rnd.replay as rp

S = "2026-10-13"


def fixture(root: Path):
    ev = root / "evaluations" / "alpha_rnd_v1"
    (ev / "opportunity_funnel").mkdir(parents=True)
    cands = [{"ticker": t} for t in ("A", "B", "C", "D", "E", "F")]
    (ev / f"candidate_pool_frozen_{S}.json").write_text(json.dumps({
        "session": S, "candidates": cands}))
    (ev / "opportunity_funnel" / f"{S}.json").write_text(json.dumps({
        "session": S,
        "tickers": {t: {"deep": {"selected": t in ("A", "B", "C")}}
                    for t in "ABCDEF"}}))
    (ev / "market_cache_2026-10-13.pkl").write_bytes(b"fake")
    (ev / f"fundamental_facts_{S}.json").write_text("{}")
    (ev / "universe_raw.json").write_text(json.dumps({
        "session": S, "constituents": [{"ticker": t}
                                       for t in "ABCDEF"]}))


class ReplayTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.ev, self.rp_dir = rp.EV, rp.REPLAYS
        rp.EV = Path(self.d.name) / "evaluations" / "alpha_rnd_v1"
        rp.REPLAYS = rp.EV / "replays"
        fixture(Path(self.d.name))

    def tearDown(self):
        rp.EV, rp.REPLAYS = self.ev, self.rp_dir

    def test_policy_selection(self):
        pool = rp._frozen_pool(S)
        cur = rp.ReplayContext.make(S, "CURRENT_PRODUCTION")
        allp = rp.ReplayContext.make(S, "ANALYZE_ALL_CANDIDATES")
        self.assertEqual(rp.select_for_ta(cur, pool), ["A", "B", "C"])
        self.assertEqual(rp.select_for_ta(allp, pool),
                         ["A", "B", "C", "D", "E", "F"])

    def test_cutoff_and_not_run_and_incomplete(self):
        calls = []
        def fake(t, s):
            calls.append(t)
            return {"ticker": t, "signal": "Hold"}
        r = rp.run(rp.ReplayContext.make(S, "ANALYZE_ALL_CANDIDATES"),
                   max_ta=2, ta_fn=fake, upstream="frozen")
        self.assertEqual(r["decision_cutoff"], f"{S}T20:00:00Z")
        self.assertEqual(r["ta_not_run"], ["C", "D", "E", "F"])
        self.assertFalse(r["replay_complete"])
        pub = json.loads((rp.REPLAYS / S / "ANALYZE_ALL_CANDIDATES" /
                          "publication.json").read_text())
        self.assertEqual(pub["dispositions"]["F"]["disposition"], "NOT_RUN")

    def test_identical_pool_across_policies_and_resume(self):
        for pol in rp.POLICIES:
            rp.run(rp.ReplayContext.make(S, pol), max_ta=0,
                   ta_fn=lambda t, s: {}, upstream="frozen")
        m1 = json.loads((rp.REPLAYS / S / "CURRENT_PRODUCTION" /
                         "manifest.json").read_text())
        m2 = json.loads((rp.REPLAYS / S / "ANALYZE_ALL_CANDIDATES" /
                         "manifest.json").read_text())
        self.assertEqual(m1["candidate_pool_members"],
                         m2["candidate_pool_members"])
        self.assertNotEqual(m1["ta_selected"], m2["ta_selected"])
        self.assertIn("SAFE_TO_RUN_REPLAY", rp.audit(S))

    def test_pit_gate_hard_fails_future_bar(self):
        import pandas as pd
        bad = {"SPY": pd.DataFrame({"Close": [1]},
               index=pd.DatetimeIndex(["2026-10-20"]))}
        with mock.patch("pickle.loads", return_value=(bad, [])), \
             mock.patch.object(rp, "EV", rp.EV):
            with self.assertRaises(RuntimeError) as c:
                rp.recompute_upstream(S)
            self.assertIn("PIT violation", str(c.exception))


if __name__ == "__main__":
    unittest.main()
