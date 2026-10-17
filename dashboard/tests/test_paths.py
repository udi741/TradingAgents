"""Path-resolution tests: prove the dashboard does not depend on the current
machine's worktree names or any user-specific directory.

Builds synthetic layouts in tmp dirs and monkeypatches the module-level
SELF_ROOT/WORKSPACE_SPEC so resolution is exercised end to end.
"""
import json
from pathlib import Path

import pytest

from dashboard import paths


@pytest.fixture()
def synth(tmp_path, monkeypatch):
    """Synthetic workspace: prefix/<role dirs>/..., dashboard checkout at
    prefix/'repo-dash' with its own ops/workspace.json + docs/."""
    prefix = tmp_path / "someprefix"
    dash = prefix / "repo-dash"
    (dash / "ops").mkdir(parents=True)
    (dash / "docs").mkdir(parents=True)
    (dash / "docs" / "TRADINGAGENTS_CAPABILITY_REGISTRY.yaml").write_text(
        "capabilities: []\n")
    # runtime worktrees with deliberately unrelated names
    alpha = prefix / "zzz-live"
    (alpha / "alpha_rnd").mkdir(parents=True)
    (alpha / "alpha_rnd" / "monitor_state.json").write_text("{}")
    (alpha / "evaluations" / "alpha_rnd_v1").mkdir(parents=True)
    c12 = prefix / "zzz-c12"
    (c12 / "evaluations" / "gate_c12_prospective").mkdir(parents=True)
    spec = {"roles": {
        "ALPHA": {"path": "zzz-live", "branch": "exp/x",
                  "required_for_production": True},
        "C12": {"path": "zzz-c12", "branch": "exp/y",
                "required_for_production": True},
        "TRACKS": {"path": "zzz-tracks", "branch": "project/tracks",
                   "required_for_production": True},
        "EXPERT": {"path": "zzz-expert", "branch": "exp/z",
                   "required_for_production": False},
    }}
    (dash / "ops" / "workspace.json").write_text(json.dumps(spec))
    monkeypatch.setattr(paths, "SELF_ROOT", dash)
    monkeypatch.setattr(paths, "WORKSPACE_SPEC",
                        dash / "ops" / "workspace.json")
    return {"prefix": prefix, "dash": dash, "alpha": alpha, "c12": c12}


def test_workspace_spec_resolution(synth):
    r = paths.resolve({"TA_DASH_PREFIX": str(synth["prefix"])})
    assert r["ALPHA"]["path"] == str(synth["alpha"])
    assert r["ALPHA"]["source"] == "workspace.json"
    assert r["C12"]["path"] == str(synth["c12"])
    # docs prefer this checkout (its own registry), not the sibling
    assert r["TRACKS"]["path"] == str(synth["dash"])
    assert r["TRACKS"]["source"] == "self-checkout"
    # EXPERT missing -> present False, not silently another dir
    assert r["EXPERT"]["present"] is False


def test_no_user_specific_paths_anywhere(synth):
    rep = paths.report({"TA_DASH_PREFIX": str(synth["prefix"])})
    blob = json.dumps(rep)
    assert "udi" not in blob.replace(str(synth["dash"].parents[1]), "")
    assert "TradingAgents-alpha-rnd" not in blob  # name comes from spec only


def test_env_override_wins(synth, tmp_path):
    other = tmp_path / "elsewhere"
    (other / "alpha_rnd").mkdir(parents=True)
    r = paths.resolve({"TA_DASH_ALPHA_ROOT": str(other)})
    assert r["ALPHA"]["path"] == str(other)
    assert r["ALPHA"]["source"] == "env:TA_DASH_ALPHA_ROOT"


def test_env_override_rejected_without_sentinel(synth, tmp_path):
    """An env path without alpha_rnd/ is rejected — no silent wrong root."""
    bad = tmp_path / "not-alpha"
    bad.mkdir()
    r = paths.resolve({"TA_DASH_ALPHA_ROOT": str(bad),
                       "TA_DASH_PREFIX": str(synth["prefix"])})
    assert r["ALPHA"]["path"] == str(synth["alpha"])  # fell back to spec
    assert any(bad.as_posix() == rej["path"]
               for rej in r["ALPHA"].get("rejected", []))


def test_single_checkout_layout(synth):
    """Spec absent worktrees + dashboard checkout containing alpha_rnd/ =>
    ALPHA resolves to the dashboard checkout itself."""
    (synth["dash"] / "alpha_rnd").mkdir()
    (synth["dash"] / "alpha_rnd" / "monitor_state.json").write_text("{}")
    # empty prefix: spec paths won't exist
    empty = synth["prefix"] / "elsewhere"
    empty.mkdir()
    r = paths.resolve({"TA_DASH_PREFIX": str(empty)})
    assert r["ALPHA"]["path"] == str(synth["dash"])
    assert r["ALPHA"]["source"] == "single-checkout"


def test_missing_everything_fails_clearly(synth):
    empty = synth["prefix"] / "void"
    empty.mkdir()
    r = paths.resolve({"TA_DASH_PREFIX": str(empty)})
    assert r["ALPHA"]["present"] is False
    assert r["ALPHA"]["required"] is True
    assert r["C12"]["present"] is False


def test_missing_root_yields_missing_meta_not_wrong_data(tmp_path, monkeypatch):
    """End-to-end: unresolvable ALPHA root -> meta.state missing, cash None.

    Real SELF_ROOT has no alpha_rnd/, so pointing PREFIX at an empty dir and
    ALPHA_ROOT at a sentinel-less dir leaves every candidate rejected.
    """
    from importlib import reload
    import dashboard.config as cfg
    void = tmp_path / "void"
    bad = tmp_path / "not-alpha"
    void.mkdir(); bad.mkdir()
    monkeypatch.setenv("TA_DASH_PREFIX", str(void))
    monkeypatch.setenv("TA_DASH_ALPHA_ROOT", str(bad))
    reload(cfg)  # re-resolve with broken env
    try:
        from fastapi.testclient import TestClient
        from dashboard.server import app
        c = TestClient(app)
        r = c.get("/api/overview")
        assert r.status_code == 200
        body = r.json()
        assert body["portfolio"]["cash"] is None
        assert body["meta"]["monitor_state"]["state"] == "missing"
        meta = c.get("/api/meta").json()
        assert meta["roots"]["roles"]["ALPHA"]["present"] is False
    finally:
        monkeypatch.undo()          # restore env BEFORE re-resolving
        reload(cfg)                 # back to real roots for other tests
