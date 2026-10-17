"""ALPHA track adapters: read authoritative state, return API-shaped dicts.

Authority per docs/STATE_AND_DATA_AUTHORITY.md:
  economic: alpha_rnd/monitor_state.json + alpha_paper_ledger.jsonl
  operational: live_watchlist.json, scheduler_state.json, management_actions.json
  artifacts: case_artifacts/, entry_snapshots/, opportunity_funnel/,
             candidate_pool_frozen*.json, publication_intents_*.json
"""
from __future__ import annotations

import glob
import json
import re
from pathlib import Path

from .. import config
from ..readutil import read_json, read_jsonl, ts_of


def monitor() -> tuple[dict | None, dict]:
    return read_json(config.ALPHA_STATE / "monitor_state.json")


def watchlist() -> tuple[dict | None, dict]:
    return read_json(config.ALPHA_STATE / "live_watchlist.json")


def scheduler() -> tuple[dict | None, dict]:
    return read_json(config.ALPHA_STATE / "scheduler_state.json")


def mgmt_policy() -> tuple[dict | None, dict]:
    return read_json(config.ALPHA_STATE / "management_policy.json")


def mgmt_actions() -> tuple[dict | None, dict]:
    return read_json(config.ALPHA_EVAL / "management_actions.json")


def mgmt_state() -> tuple[dict | None, dict]:
    return read_json(config.ALPHA_EVAL / "management_state.json")


def mgmt_events(limit: int = 500) -> tuple[list, dict]:
    rows, meta = read_jsonl(config.ALPHA_STATE / "management_events.jsonl")
    meta["total_rows"] = len(rows)
    return rows[-limit:], meta


def trigger_events(limit: int = 500) -> tuple[list, dict]:
    rows, meta = read_jsonl(config.ALPHA_STATE / "trigger_events.jsonl")
    meta["total_rows"] = len(rows)
    return rows[-limit:], meta


def ledger(limit: int = 400) -> tuple[list, dict]:
    rows, meta = read_jsonl(config.ALPHA_EVAL / "alpha_paper_ledger.jsonl")
    meta["total_rows"] = len(rows)
    return rows[-limit:], meta


def ledger_full() -> tuple[list, dict]:
    return read_jsonl(config.ALPHA_EVAL / "alpha_paper_ledger.jsonl")


def _latest(globpat: str) -> Path | None:
    files = sorted(glob.glob(str(globpat)))
    return Path(files[-1]) if files else None


def funnel_sessions() -> list[str]:
    out = []
    for p in glob.glob(str(config.ALPHA_EVAL / "opportunity_funnel" / "*.json")):
        out.append(Path(p).stem)
    return sorted(out)


def funnel(session: str | None = None) -> tuple[dict | None, dict]:
    if session is None:
        p = _latest(config.ALPHA_EVAL / "opportunity_funnel" / "*.json")
    else:
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", session or ""):
            return None, {"state": "invalid", "path": None}
        p = config.ALPHA_EVAL / "opportunity_funnel" / f"{session}.json"
    if p is None:
        return None, {"state": "missing", "path": None}
    return read_json(p)


def candidate_pools() -> list[str]:
    out = []
    for p in glob.glob(str(config.ALPHA_EVAL / "candidate_pool_frozen_*.json")):
        out.append(Path(p).stem.replace("candidate_pool_frozen_", ""))
    return sorted(out)


def candidate_pool(session: str | None = None) -> tuple[dict | None, dict]:
    if session is None:
        # prefer the latest session-stamped pool; the un-suffixed file is the
        # oldest (2026-10-01) freeze kept for provenance
        p = _latest(config.ALPHA_EVAL / "candidate_pool_frozen_*.json")
        if p is None:
            p = config.ALPHA_EVAL / "candidate_pool_frozen.json"
    else:
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", session or ""):
            return None, {"state": "invalid", "path": None}
        p = config.ALPHA_EVAL / f"candidate_pool_frozen_{session}.json"
    if p is None:
        return None, {"state": "missing", "path": None}
    return read_json(p)


def publication_sessions() -> list[str]:
    return sorted(Path(p).stem.replace("publication_intents_", "")
                  for p in glob.glob(str(config.ALPHA_EVAL / "publication_intents_*.json")))


def publication_intents(session: str | None = None) -> tuple[dict | None, dict]:
    sessions = publication_sessions()
    if session is None:
        if not sessions:
            return None, {"state": "missing", "path": None}
        session = sessions[-1]
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", session):
        return None, {"state": "invalid", "path": None}
    return read_json(config.ALPHA_EVAL / f"publication_intents_{session}.json")


def case_artifacts() -> list[dict]:
    """Index of TA case artifacts: ticker, session, kind (ok/error/replay)."""
    out = []
    for p in sorted(glob.glob(str(config.ALPHA_EVAL / "case_artifacts" / "*.json"))):
        stem = Path(p).stem
        kind = "ok"
        if stem.endswith(".error"):
            stem = stem[:-6]; kind = "error"
        elif stem.endswith("_REPLAY"):
            kind = "replay"; stem = stem[:-7]
        m = re.match(r"(.+)_(\d{4}-\d{2}-\d{2})$", stem)
        if not m:
            continue
        rec = {"ticker": m.group(1), "session": m.group(2), "kind": kind, "file": Path(p).name}
        try:
            st = Path(p).stat()
            import time as _t
            rec["mtime_utc"] = _t.strftime("%Y-%m-%dT%H:%M:%SZ", _t.gmtime(st.st_mtime))
        except OSError:
            pass
        out.append(rec)
    return out


_CASE_NAME = re.compile(r"^[A-Z0-9.]+_\d{4}-\d{2}-\d{2}(_REPLAY|\.error)?\.json$")


def case_artifact(ticker: str, session: str | None = None) -> tuple[dict | None, dict]:
    ticker = ticker.upper()
    if not re.fullmatch(r"[A-Z0-9.]{1,10}", ticker):
        return None, {"state": "invalid", "path": None}
    cands = []
    for p in glob.glob(str(config.ALPHA_EVAL / "case_artifacts" / f"{ticker}_*.json")):
        name = Path(p).name
        if not _CASE_NAME.match(name):
            continue
        if session and session not in name:
            continue
        if ".error." in name or name.endswith("_REPLAY.json"):
            continue
        cands.append(p)
    if not cands:
        return None, {"state": "missing", "path": None}
    return read_json(Path(sorted(cands)[-1]))


def entry_snapshots() -> list[dict]:
    out = []
    for p in sorted(glob.glob(str(config.ALPHA_EVAL / "entry_snapshots" / "*.json"))):
        d, meta = read_json(Path(p))
        if isinstance(d, dict):
            d["_file"] = Path(p).name
            d["_meta"] = meta
            out.append(d)
    return out


def entry_snapshot(ticker: str) -> dict | None:
    ticker = ticker.upper()
    best = None
    for s in entry_snapshots():
        if s.get("ticker") == ticker and "_REPLAY" not in s.get("_file", ""):
            if best is None or s.get("created_at", "") > best.get("created_at", ""):
                best = s
    return best


def mgmt_intents(ticker: str | None = None) -> list[dict]:
    base = config.ALPHA_EVAL / "management_intents"
    out = []
    for p in sorted(base.glob("*/*.json")) if base.exists() else []:
        if ticker and p.parent.name != ticker.upper():
            continue
        d, meta = read_json(p)
        if isinstance(d, dict):
            d["_file"] = p.name
            d["_dir"] = p.parent.name
            out.append(d)
    return out


def mgmt_analyses(ticker: str | None = None) -> list[dict]:
    """Shadow reassessment artifacts: management_analyses/<T>/reassess_*.json"""
    base = config.ALPHA_EVAL / "management_analyses"
    out = []
    for p in sorted(base.glob("*/*.json")) if base.exists() else []:
        if ticker and p.parent.name != ticker.upper():
            continue
        d, meta = read_json(p)
        if isinstance(d, dict):
            d["_file"] = p.name
            d["_dir"] = p.parent.name
            d["_meta"] = meta
            out.append(d)
    return out


def analysis_status(session: str | None = None) -> tuple[dict | None, dict]:
    if session is None:
        p = _latest(config.ALPHA_EVAL / "analysis_status_*.json")
    else:
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", session):
            return None, {"state": "invalid", "path": None}
        p = config.ALPHA_EVAL / f"analysis_status_{session}.json"
    if p is None:
        return None, {"state": "missing", "path": None}
    return read_json(p)


def cohort_state() -> tuple[dict | None, dict]:
    return read_json(config.ALPHA_STATE / "cohort_outcomes_state.json")


# ---------- composed views ----------

def overview() -> dict:
    ms, ms_meta = monitor()
    wl, wl_meta = watchlist()
    sched, sched_meta = scheduler()
    ma, _ = mgmt_actions()
    pol, _ = mgmt_policy()
    fun, fun_meta = funnel()

    positions = []
    if ms:
        for t, p in (ms.get("positions") or {}).items():
            positions.append({
                "ticker": t, "shares": p.get("shares"), "fill": p.get("fill"),
                "mark": p.get("mark"), "mark_status": p.get("mark_status"),
                "mark_session": p.get("mark_session"),
                "unrealized": p.get("unrealized"),
                "unrealized_pct": p.get("unrealized_pct"),
                "seeded": p.get("seeded", False),
                "invalidation": p.get("invalidation"),
                "horizon": p.get("horizon"),
            })
    book = (ms or {}).get("book") or {}
    pending_in = (ms or {}).get("pending_open_fills") or []
    pending_out = (ms or {}).get("pending_open_exits") or []

    attention = []
    if pending_out:
        for o in pending_out:
            attention.append({"kind": "PENDING_EXIT", "ticker": o.get("ticker"),
                              "detail": f"{o.get('shares','?')} sh {o.get('type','')} — {o.get('reason','')}"})
    for t, st in ((ms or {}).get("watch_status") or {}).items():
        if st == "RISK_PLAN_REQUIRED":
            attention.append({"kind": "RISK_PLAN_REQUIRED", "ticker": t,
                              "detail": f"watch blocked: {(ms.get('risk_blocked') or {}).get(t)}"})
    if pol and (pol.get("execution") or {}).get("enabled"):
        attention.append({"kind": "ADAPTIVE_EXECUTION_ENABLED", "ticker": None,
                          "detail": "adaptive paper execution is ENABLED (kill switch on)"})
    if ma:
        for aid, a in ma.items():
            attention.append({"kind": "MGMT_ACTION", "ticker": a.get("ticker"),
                              "detail": f"{a.get('action')} {a.get('qty','')}sh status={a.get('status')} remainder={a.get('remainder_status')}"})
    if fun is None:
        attention.append({"kind": "FUNNEL_MISSING", "ticker": None, "detail": "no opportunity_funnel artifact"})
    if ms is None:
        attention.append({"kind": "STATE_MISSING", "ticker": None, "detail": "monitor_state.json unreadable"})

    return {
        "generated_utc": __import__("time").strftime("%Y-%m-%dT%H:%M:%SZ", __import__("time").gmtime()),
        "meta": {"monitor_state": ms_meta, "watchlist": wl_meta, "scheduler": sched_meta},
        "portfolio": {
            "cash": (ms or {}).get("cash"),
            "nav": book.get("nav", (ms or {}).get("nav_last")),
            "market_value": book.get("market_value"),
            "exposure": book.get("exposure"),
            "unrealized": book.get("unrealized"),
            "realized": (ms or {}).get("realized"),
            "mark_session": book.get("mark_session"),
            "marked_at": book.get("marked_at"),
            "unmarked_positions": book.get("unmarked_positions"),
        },
        "positions": positions,
        "pending_entries": pending_in,
        "pending_exits": pending_out,
        "watch_status": (ms or {}).get("watch_status") or {},
        "risk_blocked": (ms or {}).get("risk_blocked") or {},
        "executed_count": len((ms or {}).get("executed") or []),
        "scheduler": {
            "completed_sessions": (sched or {}).get("completed_sessions"),
            "last_cycle": (sched or {}).get("last_cycle"),
            "published_sessions": (sched or {}).get("published_sessions"),
        },
        "adaptive_execution": (pol or {}).get("execution"),
        "management_actions": ma or {},
        "latest_funnel_session": (fun or {}).get("session"),
        "attention": attention,
        "paper_only": True,
        "real_money": False,
    }


def position_detail(ticker: str) -> dict:
    ticker = ticker.upper()
    ms, _ = monitor()
    wl, _ = watchlist()
    snap = entry_snapshot(ticker)
    intents = mgmt_intents(ticker)
    ma = mgmt_actions()[0] or {}
    ma_t = {k: v for k, v in ma.items() if v.get("ticker") == ticker}
    pos = ((ms or {}).get("positions") or {}).get(ticker)
    watch = None
    for w in (wl or {}).get("watches") or []:
        if w.get("ticker") == ticker:
            watch = w
    open_pos = None
    for w in (wl or {}).get("open_positions") or []:
        if w.get("ticker") == ticker:
            open_pos = w
    # ledger history for this ticker
    hist = []
    rows, _ = ledger_full()
    for r in rows:
        s = json.dumps(r)
        if f'"ticker": "{ticker}"' in s or f'"ticker":"{ticker}"' in s:
            hist.append(r)
    # mgmt + trigger events
    mev = [r for r in (mgmt_events(2000)[0] or []) if r.get("ticker") == ticker]
    tev = [r for r in (trigger_events(2000)[0] or []) if r.get("ticker") == ticker]
    art = case_artifact(ticker)
    return {
        "ticker": ticker,
        "position": pos,
        "watch": watch,
        "open_position_rules": open_pos,
        "entry_snapshot": snap,
        "has_phase_g_snapshot": bool(snap and snap.get("schema")),
        "management_actions": ma_t,
        "management_intents": intents[-10:],
        "management_analyses": mgmt_analyses(ticker)[-10:],
        "management_events": mev[-50:],
        "trigger_events": tev[-50:],
        "ledger_records": hist[-50:],
        "case_artifact": art[0],
        "case_artifact_meta": art[1],
        "watch_status": ((ms or {}).get("watch_status") or {}).get(ticker),
        "risk_blocked": ((ms or {}).get("risk_blocked") or {}).get(ticker),
    }
