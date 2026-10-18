"""Near-live refresh E2E: isolated synthetic state, browser left open,
files mutated as ALPHA would persist them, UI must update with NO reload.

Run: python3 dashboard/tests/e2e_autorefresh.py
"""
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "artifacts" / "dashboard_review"
PORT = 8423
BASE = f"http://127.0.0.1:{PORT}"


def build_state(tmp: Path) -> dict:
    alpha = tmp / "synth-alpha"
    (alpha / "alpha_rnd").mkdir(parents=True)
    ev = alpha / "evaluations" / "alpha_rnd_v1"
    for d in ("opportunity_funnel", "case_artifacts", "entry_snapshots",
              "management_intents", "management_analyses"):
        (ev / d).mkdir(parents=True)
    c12 = tmp / "synth-c12"
    (c12 / "evaluations" / "gate_c12_prospective").mkdir(parents=True)
    (c12 / "evaluations" / "gate_c12_prospective" / "c12_nav.jsonl").write_text(
        '{"ts":"2026-10-17T00:00:00Z","cash":85000,"nav":98000,"open_positions":0}\n')
    void = tmp / "void"  # prefix with no spec worktrees -> env roots used
    void.mkdir()

    ms = {
        "cash": 100000.0, "realized": 0.0, "nav_last": 100000.0,
        "positions": {}, "pending_open_fills": [], "pending_open_exits": [],
        "executed": [], "watch_status": {}, "risk_blocked": {},
        "book": {"nav": 100000.0, "market_value": 0, "unrealized": 0,
                 "exposure": 0, "cash": 100000.0, "realized": 0,
                 "mark_session": "2026-10-17", "marked_at": "2026-10-17T00:00:00Z"},
        "data_health": {"status": "ok", "daily_ok": 1, "daily_req": 1},
        "last_check_utc": "2026-10-17T00:00:00Z",
    }
    (alpha / "alpha_rnd" / "monitor_state.json").write_text(json.dumps(ms))
    (alpha / "alpha_rnd" / "live_watchlist.json").write_text(json.dumps(
        {"generated_at": "2026-10-17T00:00:00Z", "watches": [],
         "open_positions": [], "sizing": {}}))
    (alpha / "alpha_rnd" / "management_policy.json").write_text(
        json.dumps({"execution": {"enabled": False}, "triggers": {}}))
    (alpha / "alpha_rnd" / "scheduler_state.json").write_text(json.dumps(
        {"completed_sessions": ["2026-10-17"], "last_cycle": {}}))
    (ev / "management_actions.json").write_text("{}")
    (ev / "management_state.json").write_text("{}")
    (ev / "opportunity_funnel" / "2026-10-17.json").write_text(json.dumps({
        "session": "2026-10-17", "raw_universe_count": 100,
        "eligible_count": 50, "deep_quota": 10, "deep_selected_count": 1,
        "ta_completed_count": 1, "publication_disposition_counts": {},
        "summary": {"deep_selected": ["AAA"], "excluded": {},
                    "rank_cohorts": {}}, "tickers": {}}))
    (ev / "candidate_pool_frozen_2026-10-17.json").write_text(json.dumps({
        "session": "2026-10-17", "frozen_at": "2026-10-17T00:00:00Z",
        "universe_size_raw": 100, "universe_size_eligible": 50,
        "lane_counts": {}, "exclusion_counts": {},
        "candidates": [{"ticker": "AAA", "labels": ["MOMENTUM"],
                        "close": 10.0, "ret_5": 0.01, "ret_20": 0.02,
                        "rs_60": 1.0, "rsi_14": 55.0, "deep_score": 10}]}))
    (ev / "publication_intents_2026-10-17.json").write_text(json.dumps(
        {"session": "2026-10-17", "intents": {}, "dispositions": {}}))
    return {"alpha": alpha, "c12": c12, "void": void, "ev": ev}


def main():
    tmp = Path(tempfile.mkdtemp(prefix="ta_dash_live_"))
    st = build_state(tmp)
    env = dict(os.environ,
               TA_DASH_ALPHA_ROOT=str(st["alpha"]),
               TA_DASH_C12_ROOT=str(st["c12"]),
               TA_DASH_PREFIX=str(st["void"]),
               TA_DASH_PORT=str(PORT))
    srv = subprocess.Popen([sys.executable, "-m", "dashboard.server"],
                           cwd=str(ROOT), env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(60):
            try:
                import urllib.request
                urllib.request.urlopen(f"{BASE}/api/meta", timeout=1)
                break
            except Exception:
                time.sleep(0.5)
        results = {}
        console_errors = []
        api5xx = []
        with sync_playwright() as pw:
            b = pw.chromium.launch()
            page = b.new_page(viewport={"width": 1440, "height": 900})
            page.on("console", lambda m: console_errors.append(m.text)
                    if m.type == "error" else None)
            page.on("response", lambda r: api5xx.append(r.url)
                    if "/api/" in r.url and r.status >= 500 else None)

            def wait_text(route, needle, mutate, label, timeout=15):
                page.goto(f"{BASE}/?refresh_ms=2000{route}",
                          wait_until="networkidle")
                page.wait_for_timeout(500)
                t0 = time.time()
                mutate()
                try:
                    page.wait_for_function(
                        f"document.body.innerText.includes({json.dumps(needle)})",
                        timeout=timeout * 1000)
                    results[label] = round(time.time() - t0, 1)
                    page.screenshot(path=str(OUT / f"autorefresh_{label}.png"))
                except Exception:
                    results[label] = None

            ev = st["ev"]
            alpha = st["alpha"]

            # 1. funnel/candidate change
            def mut_funnel():
                p = json.loads((ev / "candidate_pool_frozen_2026-10-17.json").read_text())
                p["candidates"].append({"ticker": "ZZNEW", "labels": ["CATALYST"],
                                        "close": 5.5, "deep_score": 99})
                (ev / "candidate_pool_frozen_2026-10-17.json").write_text(json.dumps(p))
            wait_text("#/funnel", "ZZNEW", mut_funnel, "funnel_candidate")

            # 2. TA result appears
            def mut_ta():
                (ev / "case_artifacts" / "NEWTA_2026-10-17.json").write_text(json.dumps(
                    {"ticker": "NEWTA", "decision_session": "2026-10-17",
                     "signal": "Buy", "pm_rating": "Buy",
                     "final_trade_decision": "test"}))
            wait_text("#/research", "NEWTA", mut_ta, "ta_result")

            # 3. publication disposition appears
            def mut_pub():
                p = json.loads((ev / "publication_intents_2026-10-17.json").read_text())
                p["intents"]["AAA"] = {"ticker": "AAA",
                                       "classification": "WATCH_FOR_ENTRY",
                                       "watch_mode": "AUTO_ENTRY",
                                       "trigger": "test trig"}
                (ev / "publication_intents_2026-10-17.json").write_text(json.dumps(p))
            wait_text("#/funnel", "WATCH_FOR_ENTRY", mut_pub, "publication")

            # 3b. rejection + persisted violation reason appears without reload
            def mut_rej():
                p = json.loads((ev / "publication_intents_2026-10-17.json").read_text())
                p["dispositions"]["AAA"] = {
                    "disposition": "AMBIGUOUS_REJECTED",
                    "violations": ["ambiguous: e2e persisted violation marker"],
                    "executable": False, "user_action_required": False}
                (ev / "publication_intents_2026-10-17.json").write_text(json.dumps(p))
            wait_text("#/funnel", "e2e persisted violation marker",
                      mut_rej, "rejection_reason")

            # 4. watch appears (monitor_state.watch_status)
            def mut_watch():
                m = json.loads((alpha / "alpha_rnd" / "monitor_state.json").read_text())
                m["watch_status"] = {"WLX": "TRIGGERED"}
                (alpha / "alpha_rnd" / "monitor_state.json").write_text(json.dumps(m))
            wait_text("#/overview", "WLX", mut_watch, "watch")

            # 5. position/fill appears
            def mut_pos():
                m = json.loads((alpha / "alpha_rnd" / "monitor_state.json").read_text())
                m["positions"]["NEWPOS"] = {"shares": 10, "fill": 20.0,
                                            "mark": 21.0, "unrealized": 10.0,
                                            "mark_status": "MARKED"}
                (alpha / "alpha_rnd" / "monitor_state.json").write_text(json.dumps(m))
            wait_text("#/positions", "NEWPOS", mut_pos, "position")

            # 6. management action appears
            def mut_mgmt():
                (ev / "management_actions.json").write_text(json.dumps(
                    {"mgmact_test99": {"action_id": "mgmact_test99",
                                       "ticker": "NEWPOS",
                                       "action": "PARTIAL_EXIT", "qty": 5,
                                       "status": "ENQUEUED",
                                       "remainder_status": "PENDING_FILL",
                                       "remainder_rule": {"type": "close_below",
                                                          "level": 19.0}}}))
            wait_text("#/management", "mgmact_test99", mut_mgmt, "management")

            b.close()

        print(json.dumps({"latency_seconds": results,
                          "console_errors": console_errors,
                          "api_5xx": api5xx}, indent=1))
        ok = all(v is not None for v in results.values())
        print("ALL_STAGES_AUTO_UPDATED:", ok)
        sys.exit(0 if ok and not console_errors and not api5xx else 1)
    finally:
        srv.terminate()


if __name__ == "__main__":
    main()
