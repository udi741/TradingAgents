import json, tempfile, unittest, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
import pandas as pd
from alpha_rnd import decision_portfolio as dp


def bar(o, h, l, c):
    return pd.Series({"Open": o, "High": h, "Low": l, "Close": c})

def intent(t="SYN", direction="LONG", **kw):
    i = {"ticker": t, "stop_level": kw.get("stop", 55.0),
         "target": kw.get("tgt", 70.0), "horizon": "weeks",
         "size_frac": 0.5,
         "params": {"zone": kw.get("zone", [60, 62])},
         "invalidation": "close below stop",
         "decision": {"direction": direction,
                      "no_trade_reason": kw.get("reason")}}
    return i

class T(unittest.TestCase):
    def test_lifecycle_fill_stop_exit(self):
        d = Path(tempfile.mkdtemp())
        b = dp._new_book()
        dp.ingest_intent(b, intent(), "2025-01-01", d)   # LONG zone [60,62]
        self.assertEqual(len(b["pending"]), 1)
        # day after pub: dip into zone -> fill at top 62
        dp.step_day(b, "2025-01-02", {"SYN": bar(63, 64, 59, 63)}, d)
        self.assertIn("SYN", b["positions"])
        self.assertEqual(b["positions"]["SYN"]["entry_px"], 62.0)
        # day3: close below stop -> pending exit; day4: exit at open
        dp.step_day(b, "2025-01-03", {"SYN": bar(60, 61, 54, 54.5)}, d)
        dp.step_day(b, "2025-01-04", {"SYN": bar(54, 55, 53, 54)}, d)
        self.assertNotIn("SYN", b["positions"])
        self.assertLess(b["realized"], 0)  # exit below fill = loss
        self.assertLess(b["nav"], dp.START_CASH)

    def test_no_trade_rejected_not_opened(self):
        d = Path(tempfile.mkdtemp())
        b = dp._new_book()
        r = dp.ingest_intent(b, intent(direction="NO_TRADE",
                                       reason="no entry spec",
                                       zone=None), "2025-01-01", d)
        self.assertEqual(len(b["pending"]), 0)

    def test_short_paper_only(self):
        d = Path(tempfile.mkdtemp())
        b = dp._new_book()
        dp.ingest_intent(b, intent(direction="SHORT", zone=[60, 62],
                                   stop=65, tgt=50), "2025-01-01", d)
        dp.step_day(b, "2025-01-02", {"SYN": bar(61, 62.5, 60.5, 61)}, d)
        self.assertIn("SYN", b["positions"])
        self.assertEqual(b["positions"]["SYN"]["dir"], "SHORT")
        dp.step_day(b, "2025-01-03", {"SYN": bar(60, 61, 58, 59)}, d)
        # short at 60, mark 59 -> NAV gains; stop 65 untouched
        self.assertGreater(b["nav"], dp.START_CASH)

    def test_idempotent_ingest(self):
        d = Path(tempfile.mkdtemp())
        b = dp._new_book()
        i = intent()
        dp.ingest_intent(b, i, "2025-01-01", d)
        dp.ingest_intent(b, i, "2025-01-01", d)
        self.assertEqual(len(b["pending"]), 1)

    def test_no_fill_on_publication_day(self):
        # a decision published on day D must not fill on day D's bar even
        # if the low touched the zone — eligibility starts next session
        d = Path(tempfile.mkdtemp())
        b = dp._new_book()
        dp.ingest_intent(b, intent(), "2025-01-01", d)
        dp.step_day(b, "2025-01-01", {"SYN": bar(63, 64, 59, 63)}, d)
        self.assertNotIn("SYN", b["positions"])   # zone was touched; still no fill
        dp.step_day(b, "2025-01-02", {"SYN": bar(63, 64, 59, 63)}, d)
        self.assertIn("SYN", b["positions"])      # next session -> fill

    def test_late_publication_observed_on(self):
        # Monday pub appears Wednesday: eligibility starts AFTER observed
        # day, never retroactively from Monday. Prior marks stay intact.
        d = Path(tempfile.mkdtemp())
        b = dp._new_book()
        b["last_mark"] = "2025-01-08"  # Wed already marked
        dp.ingest_intent(b, intent(), "2025-01-06", d,
                         observed_on="2025-01-08")
        pe = b["pending"][0]
        self.assertEqual(pe["published_session"], "2025-01-06")
        self.assertEqual(pe["session"], "2025-01-08")  # observed date drives
        # Wednesday's own bar cannot fill it (needs next session)
        dp.step_day(b, "2025-01-08", {"SYN": bar(63, 64, 59, 63)}, d)
        self.assertNotIn("SYN", b["positions"])
        dp.step_day(b, "2025-01-09", {"SYN": bar(63, 64, 59, 63)}, d)
        self.assertIn("SYN", b["positions"])

    def test_writes_only_own_dir(self):
        # contract: engine only ever writes under data_dir; no prod files
        import inspect
        src = inspect.getsource(dp)
        for bad in ("live_watchlist", "alpha_paper_ledger", "monitor_state",
                    "positions.json", "publish("):
            self.assertNotIn(bad, src, bad)

if __name__ == "__main__":
    unittest.main()
