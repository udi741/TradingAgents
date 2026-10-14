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
    (ev / "universe_raw.json").write_text(json.dumps({"session": S}))


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
                         ["A", "B", "C", "D", "E", "F"])  # count is an output

    def test_identical_upstream_across_policies(self):
        pool = rp._frozen_pool(S)
        for pol in rp.POLICIES:
            r = rp.run(rp.ReplayContext.make(S, pol), max_ta=0,
                       ta_fn=lambda t, s: {"signal": "Buy"})
        m1 = json.loads((rp.REPLAYS / S / "CURRENT_PRODUCTION" /
                         "manifest.json").read_text())
        m2 = json.loads((rp.REPLAYS / S / "ANALYZE_ALL_CANDIDATES" /
                         "manifest.json").read_text())
        self.assertEqual(m1["candidate_pool_members"], m2["candidate_pool_members"])
        self.assertNotEqual(m1["ta_selected"], m2["ta_selected"])

    def test_manifest_cache_resume_and_audit(self):
        calls = []
        def fake(t, s):
            calls.append(t)
            return {"ticker": t, "signal": "Hold"}
        rp.run(rp.ReplayContext.make(S, "ANALYZE_ALL_CANDIDATES"), ta_fn=fake)
        r2 = rp.run(rp.ReplayContext.make(S, "ANALYZE_ALL_CANDIDATES"),
                    ta_fn=fake)
        self.assertEqual(len(calls), 6)          # ran once only
        self.assertEqual(r2["ta_cached"], ["A", "B", "C", "D", "E", "F"])
        self.assertIn("SAFE_TO_RUN_REPLAY", rp.audit(S))

    def test_no_production_writes(self):
        rp.run(rp.ReplayContext.make(S, "CURRENT_PRODUCTION"), max_ta=1,
               ta_fn=lambda t, s: {"signal": "Buy"})
        written = {str(p) for p in Path(self.d.name).rglob("*") if p.is_file()}
        self.assertFalse(any("watchlist" in w or "monitor_state" in w
                             or "ledger" in w for w in written))
        self.assertTrue(all("replays" in w or "candidate_pool" in w
                            or "market_cache" in w or "fundamental" in w
                            or "opportunity_funnel" in w or "universe" in w
                            for w in written))


if __name__ == "__main__":
    unittest.main()
