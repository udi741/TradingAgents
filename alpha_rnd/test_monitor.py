#!/usr/bin/env python3
"""Self-check for ALPHA_RND monitor logic — no network, synthetic data only."""

import sys
from pathlib import Path
from datetime import datetime, timezone

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from alpha_rnd import monitor as m  # noqa: E402

# keep synthetic test events out of the real ledger/notifications
m.EVENTS = Path("/tmp/alpha_test_events.jsonl")
m.NOTIFY = Path("/tmp/alpha_test_notify.log")
m.LEDGER = Path("/tmp/alpha_test_ledger.jsonl")
for p in (m.EVENTS, m.NOTIFY):
    if p.exists():
        p.unlink()


def mk_df(closes, vols, end="2026-10-10"):
    idx = pd.bdate_range(end=end, periods=len(closes))
    return pd.DataFrame({"Open": closes, "High": closes, "Low": closes,
                         "Close": closes, "Volume": vols}, index=idx)


def fresh_state():
    return {"last_check_utc": None, "processed_close_sessions": [], "confirm": {},
            "pending_open_fills": [], "pending_open_exits": [], "positions": {},
            "cash": 50000.0, "nav_last": 50000.0, "watch_status": {}}


def test_zone_fill_guards():
    st = fresh_state()
    wl = {"watches": [{"ticker": "XYZ", "cls": "AUTO_ENTRY", "invalidation": "s",
                       "horizon": "h", "size_frac": 1.0,
                       "trigger": "z", "params": {"zone": [8.0, 8.2]}}]}
    st["cash"] = 400.0  # below 500 min -> NO_ACTION
    m.do_fill(st, wl, "XYZ", 8.2, 1.0)
    assert "XYZ" not in st["positions"], "fill must respect min-notional guard"
    st["cash"] = 50000.0
    m.do_fill(st, wl, "XYZ", 8.2, 1.0)
    assert st["positions"]["XYZ"]["shares"] == int(5000 / 8.2)
    n = len(st["positions"])
    m.do_fill(st, wl, "XYZ", 8.2, 1.0)
    assert len(st["positions"]) == n, "no duplicate fills"


def test_close_breakout():
    st = fresh_state()
    closes = [10.0] * 30 + [26.0]
    vols = [1_000_000] * 30 + [3_000_000]
    df = mk_df(closes, vols)
    wl = {"watches": [{"ticker": "XN", "cls": "DETERMINISTIC_CONFIRMATION",
                       "trigger_type": "close_breakout_vol", "params": {"bo_level": 25.70, "vol_min": 2_000_000},
                       "size_frac": 1.0, "invalidation": "s", "horizon": "h", "trigger": "t"}],
          "open_positions": []}
    m.close_pass(st, wl, {"XN": df}, "2026-10-02")
    assert st["watch_status"]["XN"] == "TRIGGERED"
    assert st["pending_open_fills"][0]["ticker"] == "XN"


def test_no_close_breakout_on_touch():
    st = fresh_state()
    closes = [10.0] * 30 + [24.0]  # below level
    vols = [1_000_000] * 31
    df = mk_df(closes, vols)
    wl = {"watches": [{"ticker": "XN", "cls": "DETERMINISTIC_CONFIRMATION",
                       "trigger_type": "close_breakout_vol", "params": {"bo_level": 25.70, "vol_min": 2_000_000},
                       "size_frac": 1.0, "invalidation": "s", "horizon": "h", "trigger": "t"}],
          "open_positions": []}
    m.close_pass(st, wl, {"XN": df}, "2026-10-02")
    assert st["watch_status"].get("XN") != "TRIGGERED"


def test_reanalysis_emits_no_fill():
    st = fresh_state()
    df = mk_df([120.0] * 30 + [111.0], [1_000_000] * 31)
    wl = {"watches": [{"ticker": "SY", "cls": "REANALYZE_ON_TRIGGER",
                       "trigger_type": "price_level_or_event", "params": {"levels": [112.0]},
                       "size_frac": 1.0, "invalidation": "s", "horizon": "h", "trigger": "t"}],
          "open_positions": []}
    m.close_pass(st, wl, {"SY": df}, "2026-10-02")
    assert st["watch_status"]["SY"] == "REANALYSIS"
    assert "SY" not in st["positions"], "reanalysis must never auto-fill"


def test_expiry():
    st = fresh_state()
    df = mk_df([10.0] * 31, [1_000_000] * 31)
    wl = {"watches": [{"ticker": "ZZ", "cls": "DETERMINISTIC_CONFIRMATION",
                       "trigger_type": "close_breakout_vol", "params": {"bo_level": 25.7, "vol_min": 1},
                       "size_frac": 1.0, "invalidation": "s", "horizon": "h", "trigger": "t"}],
          "open_positions": []}
    m.close_pass(st, wl, {"ZZ": df}, "2026-11-05")
    assert st["watch_status"]["ZZ"] == "EXPIRED"


def test_session_open():
    assert m.session_open(datetime(2026, 10, 5, 14, 0, tzinfo=timezone.utc))
    assert not m.session_open(datetime(2026, 10, 3, 14, 0, tzinfo=timezone.utc))  # Saturday
    assert not m.session_open(datetime(2026, 10, 5, 21, 0, tzinfo=timezone.utc))


def test_intraday_stop_exit():
    st = fresh_state()
    st["positions"]["PB"] = {"shares": 10, "fill": 80.0}
    wl = {"watches": [], "open_positions": [
        {"ticker": "PB", "invalidation": {"type": "intraday_stop", "level": 74.5, "label": "hard stop"},
         "exit_rules": []}]}
    import pandas as pd
    df = pd.DataFrame({"Low": [79.0, 74.0], "Open": [80, 79], "High": [80, 79],
                       "Close": [79.5, 74.2], "Volume": [1, 1]},
                      index=pd.date_range("2026-10-05 14:00", periods=2, freq="min", tz="UTC"))
    m.fetch_intraday = lambda tickers: {"PB": df}
    m.intraday_pass(st, wl, {})
    assert "PB" not in st["positions"], "stop must auto-exit"
    assert abs(st["cash"] - (50000 + 10 * 74.5 * (1 - m.COST_BPS))) < 0.01


def wl_pos(t, level):
    return {"watches": [], "open_positions": [
        {"ticker": t, "invalidation": {"type": "close_below", "level": level, "label": f"close<{level}"},
         "exit_rules": [{"type": "close_below", "level": level, "label": f"close<{level}"}]}]}


def test_close_exit_waits_for_next_open():
    st = fresh_state()
    st["positions"]["PB"] = {"shares": 10, "fill": 80.0}
    df = mk_df([80.0] * 30 + [77.0], [1_000_000] * 31)
    m.close_pass(st, wl_pos("PB", 78.0), {"PB": df}, "2026-10-05")
    assert "PB" in st["positions"], "close<78 must NOT sell at the confirming close"
    assert st["pending_open_exits"][0]["ticker"] == "PB"
    assert st["cash"] == 50000.0


def test_pending_exit_fills_at_next_open():
    st = fresh_state()
    st["positions"]["AC"] = {"shares": 5, "fill": 205.0}
    st["pending_open_exits"] = [{"ticker": "AC", "why": "close<194", "confirm_session": "2026-10-05"}]
    closes = [200.0] * 30 + [190.0, 180.0]
    df = mk_df(closes, [1_000_000] * 32, end="2026-10-06")
    df.iloc[-1, df.columns.get_loc("Open")] = 175.0  # next session gaps down
    m.resolve_pending(st, {"watches": []}, {"AC": df}, "2026-10-06", live=True)
    assert "AC" not in st["positions"]
    assert abs(st["cash"] - (50000 + 5 * 175.0 * (1 - m.COST_BPS))) < 0.01, "exit at ACTUAL next open"


def test_missed_open_marks_no_fill():
    st = fresh_state()
    st["pending_open_fills"] = [{"ticker": "ZZ", "frac": 1.0, "why": "x", "confirm_session": "2026-10-05"}]
    df = mk_df([10.0] * 30 + [11.0, 12.0], [1_000_000] * 32, end="2026-10-08")
    # current session is 2026-10-08; target was 2026-10-06 -> already passed
    m.resolve_pending(st, {"watches": []}, {"ZZ": df}, "2026-10-08", live=True)
    assert "ZZ" not in st["positions"], "missed open must not invent a retro fill"


def test_close_entry_waits_for_next_open():
    st = fresh_state()
    closes = [10.0] * 30 + [26.0]
    vols = [1_000_000] * 30 + [3_000_000]
    df = mk_df(closes, vols)
    wl = {"watches": [{"ticker": "XN", "cls": "DETERMINISTIC_CONFIRMATION",
                       "trigger_type": "close_breakout_vol", "params": {"bo_level": 25.70, "vol_min": 2_000_000},
                       "size_frac": 1.0, "invalidation": "s", "horizon": "h", "trigger": "t"}],
          "open_positions": []}
    m.close_pass(st, wl, {"XN": df}, "2026-10-05")
    assert "XN" not in st["positions"] and st["pending_open_fills"][0]["ticker"] == "XN"


def test_gap_through_stop_exits_at_open():
    st = fresh_state()
    st["positions"]["AP"] = {"shares": 100, "fill": 11.30}
    wl = {"watches": [], "open_positions": [
        {"ticker": "AP", "invalidation": {"type": "intraday_stop", "level": 10.42, "label": "stop"},
         "exit_rules": []}]}
    df = pd.DataFrame({"Open": [10.10, 10.2], "Low": [10.05, 10.15], "High": [10.3, 10.3],
                       "Close": [10.2, 10.25], "Volume": [1, 1]},
                      index=pd.date_range("2026-10-06 14:00", periods=2, freq="min", tz="UTC"))
    m.fetch_intraday = lambda tickers: {"AP": df}
    orig_rp = m.resolve_pending
    m.resolve_pending = lambda *a, **k: None
    try:
        m.intraday_pass(st, wl, {})
    finally:
        m.resolve_pending = orig_rp
    assert "AP" not in st["positions"]
    assert abs(st["cash"] - (50000 + 100 * 10.10 * (1 - m.COST_BPS))) < 0.01, "gap -> exit at actual open"


if __name__ == "__main__":
    for f in [test_zone_fill_guards, test_close_breakout, test_no_close_breakout_on_touch,
              test_reanalysis_emits_no_fill, test_expiry, test_session_open,
              test_intraday_stop_exit, test_close_exit_waits_for_next_open,
              test_pending_exit_fills_at_next_open, test_missed_open_marks_no_fill,
              test_close_entry_waits_for_next_open, test_gap_through_stop_exits_at_open]:
        f()
        print(f"PASS {f.__name__}")
    print("ALL TESTS PASS")


def test_eod_marks():
    st = fresh_state()
    st["positions"] = {
        "AAA": {"shares": 10, "fill": 100.0},
        "NEW": {"shares": 5, "fill": 50.0},   # entered same day
        "NOPX": {"shares": 7, "fill": 10.0},  # no data
    }
    st["pending_open_fills"] = [{"ticker": "PEND", "frac": 1.0,
                                 "confirm_session": "2026-10-09"}]
    daily = {
        "AAA": mk_df([110.0, 120.0], [1, 1]),
        "NEW": mk_df([55.0, 60.0], [1, 1]),
        # NOPX absent -> stale, no invented price
        "PEND": mk_df([999.0], [1]),
    }
    m.eod_marks(st, daily, "2026-10-09")
    assert st["positions"]["AAA"]["mark"] == 120.0
    assert st["positions"]["AAA"]["mark_session"] == "2026-10-09"
    assert st["positions"]["AAA"]["unrealized"] == 200.0
    assert st["positions"]["NEW"]["unrealized"] == 50.0      # same-day entry marked at close
    assert st["positions"]["NOPX"].get("mark_stale") is True  # no invented price
    assert "PEND" not in st["positions"]                      # pending excluded
    assert st["cash"] == 50000.0                              # cash untouched
    nav = st["nav_last"]
    assert nav == 50000.0 + 120.0 * 10 + 60.0 * 5
    assert st["book"]["mark_session"] == "2026-10-09"
    # idempotent: re-run same session -> identical
    st2 = json.loads(json.dumps(st))
    m.eod_marks(st2, daily, "2026-10-09")
    assert st2["book"]["nav"] == st["book"]["nav"]
    assert st2["positions"] == st["positions"]
    print("eod_marks ok")


import json  # noqa: E402
from unittest import mock  # noqa: E402
test_eod_marks()


def mk_intraday(prices, day="2026-10-05"):
    idx = pd.date_range(f"{day} 10:30", periods=len(prices), freq="1min",
                        tz="US/Eastern")
    return pd.DataFrame({"Open": prices, "High": prices, "Low": prices,
                         "Close": prices, "Volume": 1}, index=idx)


def test_watch_fill_stop_enforcement():
    """AUTO_ENTRY fill -> same-session stop breach -> exactly one PAPER_EXIT."""
    wl = {"open_positions": [], "watches": [
        {"ticker": "ZZZ", "cls": "AUTO_ENTRY", "size_frac": 1.0,
         "trigger_type": "intraday_zone_touch",
         "params": {"zone": [8.0, 8.2]}, "invalidation": "stop $7.75",
         "horizon": "x", "trigger": "zone touch"}]}
    st = fresh_state()
    # tick 1: price enters zone -> fill; stop armed immediately
    with mock.patch.object(
            m, "fetch_intraday",
            return_value={"ZZZ": mk_intraday([8.1, 8.2])}), \
         mock.patch.object(m, "session_open",
                                                  return_value=True):
        m.intraday_pass(st, wl, {})
    assert st["positions"]["ZZZ"]["shares"] > 0
    assert st["positions"]["ZZZ"]["stop_rule"]["level"] == 7.75
    # tick 2 same session: trade through the stop -> exit at stop level
    evs_before = len(m.EVENTS.read_text().splitlines()) if m.EVENTS.exists() else 0
    with mock.patch.object(
            m, "fetch_intraday",
            return_value={"ZZZ": mk_intraday([8.2, 7.6])}), \
         mock.patch.object(m, "session_open",
                                                  return_value=True):
        m.intraday_pass(st, wl, {})
    assert "ZZZ" not in st["positions"]
    evs = [json.loads(l) for l in m.EVENTS.read_text().splitlines()[evs_before:]]
    exits = [e for e in evs if e.get("action") == "PAPER_EXIT" and e.get("ticker") == "ZZZ"]
    assert len(exits) == 1 and exits[0]["price"] == 7.75
    # tick 3: no duplicate exit; no position to re-evaluate
    with mock.patch.object(
            m, "fetch_intraday",
            return_value={"ZZZ": mk_intraday([7.5])}), \
         mock.patch.object(m, "session_open",
                                                  return_value=True):
        m.intraday_pass(st, wl, {})
    evs = m.EVENTS.read_text().splitlines()
    assert len([l for l in evs if '"PAPER_EXIT"' in l and "ZZZ" in l]) == 1
    print("watch_fill_stop_enforcement ok")


test_watch_fill_stop_enforcement()


def test_corrective_exit_and_blocked():
    st = fresh_state()
    st["positions"]["PGEN"] = {"shares": 10, "fill": 8.2, "stop_suspended": "x"}
    st["pending_open_exits"] = [{"ticker": "PGEN", "confirm_session": "2026-10-05",
                                 "why": "INTEGRITY_CORRECTIVE_EXIT_AFTER_MISSED_HARD_STOP"}]
    st["pending_open_fills"] = [{"ticker": "BLK", "confirm_session": "2026-10-05",
                                 "frac": 1.0, "blocked": True}]
    # session 2026-10-06 live: PGEN exits at ACTUAL open (not $7.75)
    daily = {"PGEN": mk_df([9.0], [1], end="2026-10-06"),
             "BLK": mk_df([5.0], [1], end="2026-10-06")}
    m.resolve_pending(st, {"watches": [{"ticker": "BLK"}]}, daily, "2026-10-06", live=True)
    assert "PGEN" not in st["positions"]
    ev = [json.loads(l) for l in m.EVENTS.read_text().splitlines()
          if json.loads(l).get("ticker") == "PGEN"][-1]
    assert ev["action"] == "PAPER_EXIT" and ev["price"] == 9.0  # actual open, not 7.75
    assert "MISSED_HARD_STOP" in ev["why"]
    # blocked entry stays queued, no fill
    assert len(st["pending_open_fills"]) == 1 and st["pending_open_fills"][0]["blocked"]
    # repeat -> no duplicate exit
    n = len(m.EVENTS.read_text().splitlines())
    m.resolve_pending(st, {"watches": []}, daily, "2026-10-06", live=True)
    assert len(m.EVENTS.read_text().splitlines()) == n
    print("corrective_exit_and_blocked ok")


test_corrective_exit_and_blocked()


def test_locked_state_serialization_and_atomicity():
    import tempfile, os
    td = Path(tempfile.mkdtemp())
    m.STATE = td / "state.json"; m.STATE_LOCK = td / "state.lock"
    # writer A mutates under lock
    with m.locked_state() as st:
        st["pending_open_exits"] = [{"ticker": "PGEN", "why": "X"}]
    # writer B adds pending entry under lock — A's update must persist
    with m.locked_state() as st:
        st["pending_open_fills"] = [{"ticker": "TWST", "frac": 0.5}]
        assert st["pending_open_exits"][0]["ticker"] == "PGEN"
    st = json.loads(m.STATE.read_text())
    assert st["pending_open_exits"] and st["pending_open_fills"]
    # corrupt tmp left by a crash does not corrupt canonical state
    (td / "state.tmp").write_text("{garbage")
    with m.locked_state() as st:
        assert st["pending_open_exits"][0]["ticker"] == "PGEN"
    print("locked_state_serialization ok")


test_locked_state_serialization_and_atomicity()


def test_schema_safe_dispatch_and_pending_via_intraday_open():
    st = fresh_state()
    # position with NO stop_rule and NOT in open_positions -> inv={} must not crash
    st["positions"]["PGEN"] = {"shares": 10, "fill": 8.2, "stop_suspended": "x"}
    st["pending_open_exits"] = [{"ticker": "PGEN", "confirm_session": "2026-10-05",
                                 "why": "INTEGRITY_CORRECTIVE_EXIT"}]
    st["pending_open_fills"] = [{"ticker": "TWST", "confirm_session": "2026-10-05",
                                 "frac": 0.5}]
    # daily frame lacks today's bar (end-exclusive) -> intraday frame supplies open
    daily = {"PGEN": mk_df([8.0], [1], end="2026-10-05"),
             "TWST": mk_df([200.0], [1], end="2026-10-05")}
    intra = {"PGEN": mk_intraday([7.79], "2026-10-06"), "TWST": mk_intraday([209.55], "2026-10-06")}
    m.resolve_pending(st, {"watches": [{"ticker": "TWST", "cls": "DETERMINISTIC_CONFIRMATION",
                                        "invalidation": "x", "horizon": "y",
                                        "trigger": "t", "size_frac": 0.5}]},
                      daily, "2026-10-06", live=True, intraday=intra)
    assert "PGEN" not in st["positions"] and "TWST" in st["positions"]
    evs = [json.loads(l) for l in m.EVENTS.read_text().splitlines()]
    assert any(e.get("action") == "PAPER_EXIT" and e.get("ticker") == "PGEN"
               and e.get("price") == 7.79 for e in evs)
    # same-session inv={} dispatch: intraday_pass must not crash on PGEN-less state
    st2 = fresh_state()
    st2["positions"]["Z"] = {"shares": 1, "fill": 9.0}  # no stop_rule, not in wl
    with mock.patch.object(m, "fetch_intraday",
                           return_value={"Z": mk_intraday([9.5])}), \
         mock.patch.object(m, "session_open", return_value=True):
        m.intraday_pass(st2, {"watches": [], "open_positions": []}, {})
    assert "Z" in st2["positions"]  # untouched, no crash
    print("schema_safe_dispatch ok")


test_schema_safe_dispatch_and_pending_via_intraday_open()
