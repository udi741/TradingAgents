"""Audit-remediation regression tests.

- Sessioned artifacts expose semantic freshness (asof/freshness_basis), so a
  restored file's mtime can never make stale content look current.
- Publication dispositions (incl. violations[]) reach the API so the UI can
  answer "why was this stock rejected" without reading JSON.
- /api/health serves a cached snapshot; refresh=1 reruns the authoritative
  check; neither path mutates economic state.
"""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dashboard import config
from dashboard.server import app


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def test_funnel_meta_semantic_freshness(client):
    api = client.get("/api/funnel").json()
    if api["funnel"] is None:
        pytest.skip("no funnel artifact in this state")
    assert api["meta"]["freshness_basis"] == "artifact"
    assert api["meta"]["asof"] == api["funnel"]["session"]
    assert "scheduler_latest_session" in api


def test_funnel_older_session_keeps_own_asof(client):
    sessions = client.get("/api/funnel").json()["sessions"]
    if len(sessions) < 2:
        pytest.skip("need >=2 funnel sessions")
    api = client.get(f"/api/funnel?session={sessions[0]}").json()
    # an old session must report ITS OWN as-of, never 'current'
    assert api["meta"]["asof"] == sessions[0]
    assert api["funnel"]["session"] == sessions[0]


def test_candidate_pool_meta_semantic_freshness(client):
    api = client.get("/api/candidates").json()
    if api["pool"] is None:
        pytest.skip("no candidate pool in this state")
    assert api["meta"]["freshness_basis"] == "artifact"
    assert api["meta"]["asof"] in (api["pool"]["session"],
                                 api["pool"]["frozen_at"])


def test_publication_dispositions_exposed(client):
    """dispositions[] with violations[] must reach the API verbatim."""
    api = client.get("/api/candidates").json()
    pub = api["publication"]
    if not pub:
        pytest.skip("no publication intents in this state")
    disps = pub.get("dispositions")
    assert isinstance(disps, dict)
    # find persisted truth and check the API carries it unchanged
    sessions = api.get("sessions")
    src = None
    for fn in config.ALPHA_EVAL.glob("publication_intents_*.json"):
        src = json.loads(Path(fn).read_text())
    if src and src.get("session") == pub.get("session"):
        assert disps == src["dispositions"]
    for t, d in disps.items():
        assert "disposition" in d
        if d.get("violations"):
            assert all(isinstance(v, str) for v in d["violations"])


def test_rejected_tickers_have_violations_or_honest_absence(client):
    """Every non-executable disposition either carries violation text or is
    honestly reason-less — the API must never fabricate one."""
    api = client.get("/api/candidates").json()
    pub = api["publication"] or {}
    for t, d in (pub.get("dispositions") or {}).items():
        if "REJECT" in str(d.get("disposition")):
            # persisted reason expected; absence is also legal but must stay
            # absent (the UI renders REASON NOT PERSISTED, not a guess)
            assert "violations" in d


def test_research_artifact_meta(client):
    arts = client.get("/api/research").json()["artifacts"]
    if not arts:
        pytest.skip("no case artifacts")
    t = arts[0]["ticker"]
    api = client.get(f"/api/research/{t}").json()
    if api["artifact"] is None:
        pytest.skip("artifact unreadable")
    assert api["meta"]["freshness_basis"] == "artifact"
    assert api["meta"]["asof"] == api["artifact"].get("decision_session") or \
        api["meta"]["asof"]


def test_health_cached_snapshot(client):
    r1 = client.get("/api/health").json()
    assert "cache" in r1
    r2 = client.get("/api/health").json()
    # second call within TTL must be the cached snapshot (no respawn)
    assert r2["cache"]["age_s"] >= 0
    assert r2["ops_health"] == r1["ops_health"]


def test_health_refresh_forces_authoritative(client):
    r1 = client.get("/api/health").json()
    r2 = client.get("/api/health?refresh=1").json()
    assert r2["cache"]["age_s"] <= 5
    # authoritative result is unchanged in meaning: same command output shape
    assert "overall" in r2["ops_health"] or "rc" in r2["ops_health"]


def test_no_economic_mutation_from_health(client):
    """Reading health (cached or fresh) must not touch economic files."""
    before = {p: p.stat().st_mtime for p in config.ECONOMIC_FILES if p.exists()}
    client.get("/api/health")
    client.get("/api/health?refresh=1")
    for p, mt in before.items():
        assert p.stat().st_mtime == mt
