"""API contract, safety, and edge-case tests for the dashboard."""
import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dashboard import config
from dashboard.server import app


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def test_all_endpoints_200(client):
    for ep in ["/api/meta", "/api/overview", "/api/funnel", "/api/candidates",
               "/api/research", "/api/positions", "/api/management",
               "/api/executions", "/api/performance", "/api/providers",
               "/api/health", "/api/capabilities", "/api/tracks",
               "/api/truth-ledger", "/api/controls", "/api/monitor-raw"]:
        r = client.get(ep)
        assert r.status_code == 200, f"{ep}: {r.status_code}"


def test_invalid_ticker_rejected(client):
    assert client.get("/api/research/..%2F..%2Fetc").status_code in (400, 404, 422)
    assert client.get("/api/positions/A;rm -rf").status_code in (400, 404, 422)
    assert client.get("/api/research/PBF/../../monitor_state").status_code in (400, 404, 422)


def test_invalid_session_rejected(client):
    assert client.get("/api/funnel?session=../../etc/passwd").status_code in (400, 422)
    # well-formed but nonexistent session -> graceful missing, not a traversal
    r = client.get("/api/funnel?session=2026-13-99")
    assert r.status_code == 200
    assert r.json()["meta"]["state"] in ("missing", "invalid")


def test_controls_require_confirmation(client):
    r = client.post("/api/controls/health-check")
    assert r.status_code == 428
    r = client.post("/api/controls/nonexistent?confirm=I_UNDERSTAND")
    assert r.status_code == 404


def test_no_secrets_in_api(client):
    """No API response may contain actual secret VALUES (key names are OK)."""
    import re
    secret_value = re.compile(
        r'("(?:api_?key|token|secret|password|passwd)"\s*:\s*"[^"]{3,}")|'
        r'(sk-[A-Za-z0-9]{8,})|([A-Z0-9_]*(?:KEY|TOKEN|SECRET)=\S{8,})',
        re.IGNORECASE)
    for ep in ["/api/overview", "/api/providers", "/api/health",
               "/api/capabilities", "/api/monitor-raw", "/api/tracks"]:
        body = client.get(ep).text
        m = secret_value.search(body)
        assert not m, f"secret-like value leaked via {ep}: {m.group(0)[:60]}"


def test_paper_flags(client):
    meta = client.get("/api/meta").json()
    assert meta["paper_only"] is True and meta["real_money"] is False
    ov = client.get("/api/overview").json()
    assert ov["real_money"] is False


def test_dashboard_does_not_mutate_state(tmp_path):
    """Reading every endpoint must not change any monitored state file."""
    before = {}
    files = [config.ALPHA_STATE / "monitor_state.json",
             config.ALPHA_STATE / "live_watchlist.json",
             config.ALPHA_EVAL / "management_actions.json",
             config.ALPHA_EVAL / "alpha_paper_ledger.jsonl",
             config.C12_EVAL / "c12_nav.jsonl"]
    for f in files:
        before[f] = (f.stat().st_mtime_ns, f.stat().st_size) if f.exists() else None
    c = TestClient(app)
    for ep in ["/api/overview", "/api/funnel", "/api/candidates", "/api/research",
               "/api/research/PBF", "/api/positions", "/api/positions/PBF",
               "/api/management", "/api/executions", "/api/performance",
               "/api/providers", "/api/capabilities", "/api/tracks"]:
        c.get(ep)
    for f in files:
        if before[f] is None:
            assert not f.exists()
        else:
            assert (f.stat().st_mtime_ns, f.stat().st_size) == before[f]


def test_missing_state_graceful(tmp_path, monkeypatch):
    """With roots pointed at empty dirs, API returns missing-state, never 500."""
    from importlib import reload
    import dashboard.config as cfg
    monkeypatch.setattr(cfg, "ALPHA_ROOT", tmp_path / "alpha")
    monkeypatch.setattr(cfg, "ALPHA_STATE", tmp_path / "alpha" / "alpha_rnd")
    monkeypatch.setattr(cfg, "ALPHA_EVAL", tmp_path / "alpha" / "evaluations" / "alpha_rnd_v1")
    monkeypatch.setattr(cfg, "C12_ROOT", tmp_path / "c12")
    monkeypatch.setattr(cfg, "C12_EVAL", tmp_path / "c12" / "evaluations" / "gate_c12_prospective")
    c = TestClient(app)
    for ep in ["/api/overview", "/api/funnel", "/api/candidates", "/api/positions",
               "/api/management", "/api/executions", "/api/performance", "/api/tracks"]:
        r = c.get(ep)
        assert r.status_code == 200, f"{ep} -> {r.status_code}"
        assert "0.0" not in str(r.json().get("portfolio", {}).get("cash")), "must not fabricate zero"
    ov = c.get("/api/overview").json()
    assert ov["portfolio"]["cash"] is None
    assert ov["meta"]["monitor_state"]["state"] == "missing"


def test_malformed_state_graceful(tmp_path, monkeypatch):
    import dashboard.config as cfg
    d = tmp_path / "alpha" / "alpha_rnd"
    d.mkdir(parents=True)
    (d / "monitor_state.json").write_text("{corrupt json")
    monkeypatch.setattr(cfg, "ALPHA_STATE", d)
    monkeypatch.setattr(cfg, "ALPHA_EVAL", tmp_path / "alpha" / "evaluations" / "alpha_rnd_v1")
    c = TestClient(app)
    r = c.get("/api/overview")
    assert r.status_code == 200
    assert r.json()["meta"]["monitor_state"]["state"] == "malformed"
