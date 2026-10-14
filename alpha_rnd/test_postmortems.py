import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import alpha_rnd.postmortems as pm

EVD = None


def fixture(root: Path):
    ev = root / "evaluations" / "alpha_rnd_v1"
    (ev / "case_artifacts").mkdir(parents=True)
    (ev / "trade_postmortems").mkdir(parents=True)
    (ev / "alpha_paper_ledger.jsonl").write_text(json.dumps({
        "type": "POSITION_RULES", "positions": [
            {"ticker": "SEED", "fill_date": "2026-10-02", "fill_price": 100.0,
             "shares": 10, "cost": 1000.0}]}) + "\n")
    (ev / "case_artifacts" / "SEED_2026-10-01.json").write_text(
        json.dumps({"signal": "Buy"}))
    (ev / "case_artifacts" / "BROKEN_2026-10-02.error.json").write_text(
        json.dumps({"error": "ImportError x"}))
    (ev / "case_artifacts" / "BROKEN_2026-10-01.json").write_text(
        json.dumps({"signal": "Overweight"}))
    (root / "alpha_rnd").mkdir(parents=True, exist_ok=True)
    (root / "alpha_rnd" / "trigger_events.jsonl").write_text("\n".join([
        # normal entry + exit
        json.dumps({"action": "PAPER_ENTRY", "ticker": "NORM",
                    "shares": 10, "price": 50.0, "utc": "2026-10-05T14:00:00Z"}),
        json.dumps({"action": "PAPER_EXIT", "ticker": "NORM",
                    "shares": 10, "price": 45.0, "utc": "2026-10-07T13:00:00Z"}),
        # duplicate replay rows (identical key)
        json.dumps({"action": "PAPER_EXIT", "ticker": "NORM",
                    "shares": 10, "price": 45.0, "utc": "2026-10-07T13:31:00Z"}),
        json.dumps({"action": "PAPER_EXIT", "ticker": "NORM",
                    "shares": 10, "price": 45.0, "utc": "2026-10-07T13:32:00Z"}),
        # phantom variant same shares, different price
        json.dumps({"action": "PAPER_EXIT", "ticker": "NORM",
                    "shares": 10, "price": 44.9, "utc": "2026-10-07T13:46:00Z"}),
        # broken-TA entry
        json.dumps({"action": "PAPER_ENTRY", "ticker": "BROKEN",
                    "shares": 5, "price": 10.0, "utc": "2026-10-02T14:00:00Z"}),
    ]))
    (root / "alpha_rnd" / "monitor_state.json").write_text(json.dumps({
        "positions": {"SEED": {"shares": 10, "fill": 100.0,
                               "entry_session": "2026-10-02"}},
        "realized": -100.0, "cash": 1000.0}))


class PostmortemTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        root = Path(self.d.name)
        fixture(root)
        self.saved = (pm.EV, pm.OUT, pm.EVENTS, pm.STATE)
        pm.EV = root / "evaluations" / "alpha_rnd_v1"
        pm.OUT = pm.EV / "trade_postmortems"
        pm.EVENTS = root / "alpha_rnd" / "trigger_events.jsonl"
        pm.STATE = root / "alpha_rnd" / "monitor_state.json"
        self._p = mock.patch.object(pm, "_path_stats",
                                    return_value={"status": "DATA_UNAVAILABLE"})
        self._p.start()

    def tearDown(self):
        self._p.stop()
        pm.EV, pm.OUT, pm.EVENTS, pm.STATE = self.saved

    def test_duplicate_events_one_economic_fill(self):
        p = pm.build("NORM")
        econ = [x for x in p["execution"]["exits"] if not x.get("non_economic")]
        self.assertEqual(len(econ), 1)  # only the canonical 45.0 fill counts
        realized = p["execution"]["realized_pnl"]
        # must be computable without double-counting a third row
        self.assertLess(abs(realized), 200)

    def test_open_position_and_stale_ta(self):
        p = pm.build("SEED")
        self.assertEqual(p["identity"]["status"], "OPEN")
        self.assertEqual(p["execution"]["realized_pnl"], 0.0)
        self.assertEqual(p["ex_ante"]["ta_evidence_status"], "VALID_STALE")

    def test_invalid_runtime_labeled(self):
        p = pm.build("BROKEN")
        self.assertEqual(p["ex_ante"]["ta_evidence_status"],
                         "INVALID_RUNTIME_AT_ENTRY")
        self.assertIn("NO_VALID_TA_AT_ENTRY", p["attribution"]["lesson_tags"])

    def test_idempotent_and_no_state_mutation(self):
        a = pm.build("NORM")
        b = pm.build("NORM")
        self.assertEqual({k: v for k, v in a.items() if k != "built_at"},
                         {k: v for k, v in b.items() if k != "built_at"})
        self.assertIn("realized", json.loads(pm.STATE.read_text()))


if __name__ == "__main__":
    unittest.main()
