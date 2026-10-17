"""TradingAgents Command Center — FastAPI server. Read-only by default.

Run:  python3 -m dashboard.server   (binds 127.0.0.1:8420)
"""
from __future__ import annotations

import re
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config, paths
from .adapters import alpha, c12, capabilities, health, providers
from .truth_ledger import TRUTH_LEDGER

app = FastAPI(title="TradingAgents Command Center", version="1.0")
STATIC = Path(__file__).parent / "static"

_TICKER = re.compile(r"^[A-Z0-9.]{1,10}$")
_SESSION = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _ticker(t: str) -> str:
    t = t.upper()
    if not _TICKER.fullmatch(t):
        raise HTTPException(400, "invalid ticker")
    return t


def _session(s: str) -> str:
    if not _SESSION.fullmatch(s):
        raise HTTPException(400, "invalid session (YYYY-MM-DD)")
    return s


@app.get("/api/overview")
def api_overview():
    return alpha.overview()


@app.get("/api/funnel")
def api_funnel(session: str | None = None):
    if session:
        _session(session)
    data, meta = alpha.funnel(session)
    return {"meta": meta, "funnel": data,
            "sessions": alpha.funnel_sessions()}


@app.get("/api/candidates")
def api_candidates(session: str | None = None):
    if session:
        _session(session)
    data, meta = alpha.candidate_pool(session)
    pub, pub_meta = alpha.publication_intents(session)
    wl, _ = alpha.watchlist()
    return {"meta": meta, "pool": data, "sessions": alpha.candidate_pools(),
            "publication": pub, "publication_meta": pub_meta,
            "watchlist_generated_at": (wl or {}).get("generated_at"),
            "watch_count": len((wl or {}).get("watches") or [])}


@app.get("/api/research")
def api_research_index():
    return {"artifacts": alpha.case_artifacts(),
            "analysis_status": alpha.analysis_status()[0]}


@app.get("/api/research/{ticker}")
def api_research(ticker: str, session: str | None = None):
    ticker = _ticker(ticker)
    if session:
        _session(session)
    data, meta = alpha.case_artifact(ticker, session)
    if data is None:
        return JSONResponse({"meta": meta, "artifact": None,
                             "available": [a for a in alpha.case_artifacts()
                                           if a["ticker"] == ticker]})
    return {"meta": meta, "artifact": data,
            "available": [a for a in alpha.case_artifacts() if a["ticker"] == ticker]}


@app.get("/api/positions")
def api_positions():
    ms, meta = alpha.monitor()
    wl, _ = alpha.watchlist()
    snaps = {s.get("ticker"): s for s in alpha.entry_snapshots()}
    out = []
    for t, p in ((ms or {}).get("positions") or {}).items():
        out.append({"ticker": t, **p,
                    "has_phase_g_snapshot": t in snaps})
    # exited/legacy tickers known from watch status
    watch_status = (ms or {}).get("watch_status") or {}
    return {"meta": meta, "positions": out, "watch_status": watch_status,
            "snapshots_known": list(snaps.keys()),
            "open_position_rules": (wl or {}).get("open_positions") or []}


@app.get("/api/positions/{ticker}")
def api_position_detail(ticker: str):
    return alpha.position_detail(_ticker(ticker))


@app.get("/api/management")
def api_management():
    actions, a_meta = alpha.mgmt_actions()
    policy, p_meta = alpha.mgmt_policy()
    mstate, m_meta = alpha.mgmt_state()
    events, e_meta = alpha.mgmt_events(300)
    intents = alpha.mgmt_intents()
    ms, _ = alpha.monitor()
    return {
        "meta": {"actions": a_meta, "policy": p_meta, "state": m_meta,
                 "events": e_meta},
        "actions": actions or {},
        "policy": policy,
        "management_state": mstate,
        "events": events,
        "intents": intents[-50:],
        "analyses": alpha.mgmt_analyses()[-50:],
        "deterministic": {
            "pending_open_exits": (ms or {}).get("pending_open_exits") or [],
            "positions_invalidation": {t: p.get("invalidation") for t, p in
                                       ((ms or {}).get("positions") or {}).items()},
        },
    }


@app.get("/api/executions")
def api_executions():
    ms, meta = alpha.monitor()
    ledger_rows, l_meta = alpha.ledger(300)
    trig, t_meta = alpha.trigger_events(300)
    return {
        "meta": {"monitor": meta, "ledger": l_meta, "triggers": t_meta},
        "pending_entries": (ms or {}).get("pending_open_fills") or [],
        "pending_exits": (ms or {}).get("pending_open_exits") or [],
        "executed_ids": (ms or {}).get("executed") or [],
        "ledger_tail": ledger_rows,
        "trigger_events": trig,
        "authority_note": "monitor_state.executed[] + alpha_paper_ledger.jsonl are fill authority; pending/watched/recommended are not fills",
    }


@app.get("/api/performance")
def api_performance():
    ms, _ = alpha.monitor()
    ledger_rows, l_meta = alpha.ledger_full()
    cohort, c_meta = alpha.cohort_state()

    fills = [r for r in ledger_rows if r.get("type") == "PAPER_FILL"]
    marks = [r for r in ledger_rows if r.get("type") == "MARK"]
    # mark series: sum of unrealized across positions per session
    mark_series = []
    for m in marks:
        tot = sum(float(p.get("unrealized") or 0) for p in m.get("positions") or [])
        mark_series.append({"session": m.get("session"),
                            "unrealized": round(tot, 2),
                            "n_positions": len(m.get("positions") or [])})
    n_closed = len([e for e in ((ms or {}).get("executed") or [])
                    if str(e).split(":")[0] in ("exit", "intraday_stop", "close_below")])
    n_fills = len(fills)
    sample_ok = n_closed >= 20  # honest threshold for any rate claims
    return {
        "meta": {"ledger": l_meta, "cohort": c_meta},
        "fills": fills,
        "fill_count": n_fills,
        "closed_exit_events": n_closed,
        "realized": (ms or {}).get("realized"),
        "unrealized": (ms or {}).get("book", {}).get("unrealized"),
        "nav": (ms or {}).get("book", {}).get("nav", (ms or {}).get("nav_last")),
        "mark_series": mark_series,
        "cohort_outcomes": cohort,
        "sample": {
            "closed_trades": n_closed,
            "sufficient": sample_ok,
            "label": "INSUFFICIENT_SAMPLE" if not sample_ok else "OK",
            "note": "rate/expectancy statistics are withheld below 20 closed trades; "
                    "raw per-trade records shown instead",
        },
    }


@app.get("/api/providers")
def api_providers():
    return providers.providers()


@app.get("/api/health")
def api_health():
    return {"ops_health": health.health(),
            "ops_status": health.status(),
            "bridge": health.bridge(),
            "units": health.systemd_units()}


@app.get("/api/capabilities")
def api_capabilities():
    return capabilities.summary()


@app.get("/api/tracks")
def api_tracks():
    reg = capabilities.summary()
    return {
        "alpha": {"name": "ALPHA_RND", "type": "Active R&D / paper trading",
                  "authoritative_root": str(config.ALPHA_ROOT),
                  "overview": alpha.overview()},
        "c12": {"name": "C12_PROSPECTIVE", "type": "Frozen prospective control",
                "authoritative_root": str(config.C12_ROOT),
                **c12.summary()},
        "expert": {"name": "EXPERT_RND", "type": "Parked challenger (analysis R&D)",
                   "note": "historical mimic closed; prospective signal capture only; never mixed with ALPHA economics"},
        "research": {"name": "Time-machine / lifecycle research",
                     "note": "simulations only — not live economic truth"},
        "boundaries": reg.get("track_boundaries"),
    }


@app.get("/api/truth-ledger")
def api_truth_ledger():
    return {"ledger": TRUTH_LEDGER}


@app.get("/api/monitor-raw")
def api_monitor_raw():
    """Escape hatch for auditability: raw monitor_state.json, secrets-free."""
    ms, meta = alpha.monitor()
    return {"meta": meta, "state": ms}


# ---------- safe controls (allowlist only) ----------

SAFE_CONTROLS = {
    "health-check": {"desc": "Run ops.ta health (read-only deep check)", "mutates": False},
    "status": {"desc": "Run ops.ta status (read-only summary)", "mutates": False},
    "backup": {"desc": "Create consistent state backup archive (takes flocks briefly; writes only the archive file under artifacts/backups/)", "mutates": False},
}

_CONFIRM = "I_UNDERSTAND"


@app.get("/api/controls")
def api_controls():
    return {"controls": [{"id": k, **v} for k, v in SAFE_CONTROLS.items()],
            "confirm_token": _CONFIRM,
            "note": "allowlist only; no raw shell; no economic actions exposed"}


@app.post("/api/controls/{control_id}")
def api_run_control(control_id: str, confirm: str | None = None):
    if control_id not in SAFE_CONTROLS:
        raise HTTPException(404, "unknown control")
    if confirm != _CONFIRM:
        raise HTTPException(428, f"confirmation required: pass confirm={_CONFIRM}")
    if control_id == "health-check":
        return {"control": control_id, "result": health.health()}
    if control_id == "status":
        return {"control": control_id, "result": health.status()}
    if control_id == "backup":
        ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        out = config.SELF_ROOT / "artifacts" / "backups" / f"dashboard-backup-{ts}.tar.gz"
        out.parent.mkdir(parents=True, exist_ok=True)
        import subprocess
        p = subprocess.run(
            ["python3", "-m", "ops.ta", "backup", "--output", str(out),
             "--prefix", str(config.WORKSPACE_PREFIX)],
            cwd=str(config.SELF_ROOT), capture_output=True, text=True, timeout=300)
        return {"control": control_id, "rc": p.returncode,
                "stdout": p.stdout[-3000:], "stderr": p.stderr[-2000:],
                "archive": str(out)}
    raise HTTPException(500, "unreachable")


@app.get("/api/meta")
def api_meta():
    return {
        "name": "TradingAgents Command Center",
        "paper_only": True, "real_money": False,
        "roots": paths.report(),
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


# static SPA
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/{full_path:path}")
def spa(full_path: str):
    if full_path.startswith("api/"):
        raise HTTPException(404)
    return FileResponse(STATIC / "index.html")


def main():
    import uvicorn
    uvicorn.run(app, host=config.HOST, port=config.PORT, log_level="warning")


if __name__ == "__main__":
    main()
