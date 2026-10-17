"""Reconciliation tests: dashboard API values must match authoritative state.

Reads the same files directly and asserts the API reports identical values.
Also covers the PBF canary field-by-field and C12 track isolation.
"""
import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dashboard import config
from dashboard.server import app

ALPHA = config.ALPHA_ROOT
C12 = config.C12_ROOT


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture(scope="module")
def monitor_state():
    return json.loads((ALPHA / "alpha_rnd" / "monitor_state.json").read_text())


@pytest.fixture(scope="module")
def mgmt_actions():
    p = ALPHA / "evaluations" / "alpha_rnd_v1" / "management_actions.json"
    return json.loads(p.read_text()) if p.exists() else {}


def test_cash_matches(client, monitor_state):
    api = client.get("/api/overview").json()
    assert api["portfolio"]["cash"] == pytest.approx(monitor_state["cash"], abs=1e-6)


def test_realized_matches(client, monitor_state):
    api = client.get("/api/overview").json()
    assert api["portfolio"]["realized"] == pytest.approx(monitor_state["realized"], abs=1e-6)


def test_nav_matches(client, monitor_state):
    api = client.get("/api/overview").json()
    expected = monitor_state["book"]["nav"]
    assert api["portfolio"]["nav"] == pytest.approx(expected, abs=1e-6)


def test_positions_match(client, monitor_state):
    api = client.get("/api/positions").json()
    src = monitor_state["positions"]
    assert {p["ticker"] for p in api["positions"]} == set(src.keys())
    for p in api["positions"]:
        s = src[p["ticker"]]
        assert p["shares"] == s["shares"]
        assert p["fill"] == pytest.approx(s["fill"])
        assert p["mark"] == pytest.approx(s["mark"])
        assert p["unrealized"] == pytest.approx(s["unrealized"], abs=0.01)


def test_pending_exits_match(client, monitor_state):
    api = client.get("/api/executions").json()
    assert api["pending_exits"] == monitor_state["pending_open_exits"]
    assert api["pending_entries"] == monitor_state["pending_open_fills"]


def test_executed_ids_match(client, monitor_state):
    api = client.get("/api/executions").json()
    assert api["executed_ids"] == monitor_state["executed"]


def test_pbf_canary(client, monitor_state, mgmt_actions):
    """PBF field-by-field against authoritative sources."""
    src = monitor_state["positions"]["PBF"]
    detail = client.get("/api/positions/PBF").json()

    assert detail["position"]["shares"] == src["shares"]            # 62
    assert detail["position"]["fill"] == pytest.approx(src["fill"])  # 80.00
    assert detail["position"]["mark"] == pytest.approx(src["mark"])  # 84.52
    assert detail["position"]["unrealized"] == pytest.approx(src["unrealized"], abs=0.01)

    # pending adaptive partial exit
    pex = [o for o in monitor_state["pending_open_exits"] if o["ticker"] == "PBF"]
    assert len(pex) == 1
    act_id = pex[0]["mgmt_action"]
    assert act_id in detail["management_actions"]
    act = mgmt_actions[act_id]
    assert act["qty"] == pex[0]["shares"]                    # 31
    assert act["remainder_rule"]["level"] == pytest.approx(83.5)
    assert act["remainder_rule"]["type"] == "close_below"
    assert act["remainder_status"] == "PENDING_FILL"

    # entry snapshot (Phase G)
    snap = detail["entry_snapshot"]
    assert snap is not None
    assert snap["entry_price"] == pytest.approx(80.0)
    assert snap["risk_plan"]["stop_level"] == pytest.approx(74.5)
    assert "cost_basis (legacy/seeded)" in snap["missing_context"]


def test_c12_isolation(client):
    """C12 tickers/pnl must never leak into ALPHA endpoints."""
    api = client.get("/api/overview").json()
    alpha_tickers = {p["ticker"] for p in api["positions"]}
    c12_pf = [json.loads(l) for l in
              (C12 / "evaluations/gate_c12_prospective/c12_paper_portfolio.jsonl")
              .read_text().splitlines() if l.strip()]
    c12_tickers = {r["ticker"] for r in c12_pf}
    # C12 nav/cash must not appear as ALPHA figures
    nav = [json.loads(l) for l in
           (C12 / "evaluations/gate_c12_prospective/c12_nav.jsonl")
           .read_text().splitlines() if l.strip()][-1]
    assert api["portfolio"]["nav"] != nav["nav"]
    assert api["portfolio"]["cash"] != nav["cash"]


def test_c12_track_page(client):
    api = client.get("/api/tracks").json()
    nav_rows = (C12 / "evaluations/gate_c12_prospective/c12_nav.jsonl").read_text().splitlines()
    latest = json.loads(nav_rows[-1])
    assert api["c12"]["latest_nav"]["nav"] == pytest.approx(latest["nav"])
    assert api["c12"]["frozen_control"] is True


def test_capability_registry_count(client):
    import yaml
    reg = yaml.safe_load((config.SELF_ROOT /
                          "docs/TRADINGAGENTS_CAPABILITY_REGISTRY.yaml").read_text())
    api = client.get("/api/capabilities").json()
    assert api["count"] == len(reg["capabilities"])
    assert api["count"] >= 60
    assert api["registry_version"] == reg["registry_version"]


def test_funnel_matches_file(client):
    import glob
    latest = sorted(glob.glob(str(config.ALPHA_EVAL / "opportunity_funnel/*.json")))[-1]
    src = json.loads(Path(latest).read_text())
    api = client.get("/api/funnel").json()
    assert api["funnel"]["session"] == src["session"]
    assert api["funnel"]["raw_universe_count"] == src["raw_universe_count"]
    assert api["funnel"]["eligible_count"] == src["eligible_count"]
    assert api["funnel"]["deep_selected_count"] == src["deep_selected_count"]


def test_provider_health_present(client):
    api = client.get("/api/providers").json()
    assert api["infra"]["bridge_process"] in ("HEALTHY", "DOWN")
    assert api["infra"]["upstream"]["status"] in (
        "AVAILABLE", "RATE_LIMITED", "QUOTA_EXHAUSTED", "UNAVAILABLE", "UNKNOWN")
    assert len(api["provider_semantics"]) >= 8  # registry provider_semantics entries
