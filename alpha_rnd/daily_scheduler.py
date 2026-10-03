#!/usr/bin/env python3
"""ALPHA_RND daily-cycle scheduler — orchestration only.

Deterministic due-cycle checker. Contains NO strategy logic: it decides whether
the existing frozen ALPHA discovery/operating cycle should run for the latest
completed US market session, then invokes the existing entrypoints
(discovery.py -> run_ta.py) and emits durable events.

Usage:
  python3 -m alpha_rnd.daily_scheduler --check   # cron entry (hourly)
  python3 -m alpha_rnd.daily_scheduler --status
  python3 -m alpha_rnd.daily_scheduler --run-session YYYY-MM-DD  # internal
"""

from __future__ import annotations

import fcntl
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AR = ROOT / "alpha_rnd"
EV_DIR = ROOT / "evaluations" / "alpha_rnd_v1"
SCHED_LOCK = AR / "alpha_scheduler.lock"
CYCLE_LOCK = AR / "alpha_cycle.lock"
SCHED_STATE = AR / "scheduler_state.json"
EVENTS = AR / "scheduler_events.jsonl"
LOG = AR / "scheduler.log"

BRIDGE_MODELS_URL = "http://127.0.0.1:8765/v1/models"
BRIDGE_DIR = Path("/home/udi/udi_provate/TradingAgents")
BRIDGE_ARGS = [
    "python3", "-m", "devin_bridge",
    "--quick-model", "swe-2-medium", "--deep-model", "swe-2-high",
    "--timeout", "1200",
]
BRIDGE_LOG = Path("/tmp/devin_bridge_alpha.log")
BRIDGE_ACTIVITY_WINDOW_S = 900  # busy if log touched within 15 min

DEEP_QUOTA = 10
PY = sys.executable


def _j(path: Path, default=None):
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def _log(msg: str) -> None:
    line = f"{datetime.now(timezone.utc).isoformat()} {msg}"
    with LOG.open("a") as f:
        f.write(line + "\n")
    print(line)


def event(kind: str, **fields) -> None:
    rec = {"ts": datetime.now(timezone.utc).isoformat(), "kind": kind, **fields}
    with EVENTS.open("a") as f:
        f.write(json.dumps(rec) + "\n")
    _log(f"EVENT {kind} {fields}")
    if shutil.which("notify-send"):
        env = dict(os.environ, DISPLAY=":1",
                   DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/1000/bus")
        subprocess.run(["notify-send", "-u", "critical", f"ALPHA {kind}",
                        json.dumps(fields)[:180]],
                       check=False, capture_output=True, env=env)


def _load_discovery():
    spec = importlib.util.spec_from_file_location(
        "alpha_discovery", EV_DIR / "discovery.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def last_completed_session() -> str:
    return _load_discovery().last_completed_session()


def cycle_done(session: str) -> bool:
    st = _j(SCHED_STATE, {}) or {}
    return session in (st.get("completed_sessions") or [])


def mark_done(session: str, summary: dict) -> None:
    st = _j(SCHED_STATE, {}) or {}
    done = st.get("completed_sessions") or []
    if session not in done:
        done.append(session)
    st["completed_sessions"] = done
    st["last_cycle"] = {"session": session,
                        "finished_at": datetime.now(timezone.utc).isoformat(),
                        "summary": summary}
    SCHED_STATE.write_text(json.dumps(st, indent=1))


def deep_allocation(session: str) -> list[str]:
    """Frozen deep-score ranking applied to the frozen pool artifact:
    10*labels + 2*clip(rs_60,0,2) + (1 if CATALYST). Read-only derivation."""
    pool = (_j(EV_DIR / f"candidate_pool_frozen_{session}.json", {}) or {}) \
        .get("candidates") or []
    scored = []
    for c in pool:
        labs = c.get("labels") or []
        base = [x for x in labs if x != "MULTI_SIGNAL"]
        sc = (10 * len(base) + 2 * min(max(c.get("rs_60") or 0, 0), 2)
              + (1 if "CATALYST" in labs else 0))
        scored.append((c["ticker"], sc))
    scored.sort(key=lambda x: (-x[1], x[0]))
    return [t for t, _ in scored[:DEEP_QUOTA]]


def bridge_status() -> str:
    """'ok' | 'down' | 'foreign_busy' — never disturb another track's bridge."""
    try:
        d = json.loads(urllib.request.urlopen(BRIDGE_MODELS_URL, timeout=5).read())
        models = {m.get("id") for m in d.get("data", [])}
        if {"devin-quick", "devin-deep"} <= models:
            return "ok"
        return "foreign_busy"  # up but wrong models — not ours to restart
    except Exception:
        return "down"


def ensure_bridge() -> bool:
    st = bridge_status()
    if st == "ok":
        return True
    if st == "foreign_busy":
        return False
    # down: safe to launch our accepted config
    _log("bridge down; launching accepted config")
    with BRIDGE_LOG.open("ab") as f:
        subprocess.Popen(BRIDGE_ARGS, cwd=BRIDGE_DIR, stdout=f,
                         stderr=subprocess.STDOUT, start_new_session=True)
    for _ in range(30):
        if bridge_status() == "ok":
            return True
        time.sleep(2)
    return False


def run_cycle(session: str) -> None:
    """One full normal cycle for `session` (internal, holds cycle lock)."""
    with CYCLE_LOCK.open("w") as lf:
        try:
            fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            _log(f"cycle {session} already running elsewhere; exiting")
            return
        event("ALPHA_DISCOVERY_STARTED", session=session)

        # 1. Existing book first — per-minute monitor bookkeeping pass.
        subprocess.run([PY, "-m", "alpha_rnd.monitor", "--once"],
                       cwd=ROOT, env={**os.environ, "PYTHONPATH": str(ROOT)},
                       capture_output=True, timeout=600)

        # 2. Frozen discovery pipeline.
        r = subprocess.run([PY, str(EV_DIR / "discovery.py"), session],
                           cwd=ROOT,
                           env={**os.environ, "PYTHONPATH": str(ROOT)},
                           capture_output=True, text=True, timeout=7200)
        if r.returncode != 0 or not (EV_DIR / f"candidate_pool_frozen_{session}.json").exists():
            event("ALPHA_DISCOVERY_ERROR", session=session,
                  stage="discovery", tail=(r.stderr or r.stdout)[-400:])
            return
        deep = deep_allocation(session)

        # 3. Bridge, then frozen TA pass on the deep allocation.
        if not ensure_bridge():
            event("ALPHA_DISCOVERY_BLOCKED_BRIDGE", session=session,
                  deep=deep, status=bridge_status())
            return  # retried on next tick (not marked done)
        r = subprocess.run([PY, str(EV_DIR / "run_ta.py"), session, *deep],
                           cwd=ROOT,
                           env={**os.environ, "PYTHONPATH": str(ROOT)},
                           capture_output=True, text=True, timeout=14400)
        arts = sorted((EV_DIR / "case_artifacts").glob(f"*_{session}.json"))
        signals = {}
        for p in arts:
            a = _j(p, {}) or {}
            signals[a.get("ticker") or p.stem.split("_")[0]] = a.get("signal")
        if r.returncode != 0 and not signals:
            event("ALPHA_DISCOVERY_ERROR", session=session,
                  stage="ta", tail=(r.stderr or r.stdout)[-400:])
            return
        summary = {"deep": deep, "ta_signals": signals}
        mark_done(session, summary)
        event("ALPHA_DISCOVERY_COMPLETE", session=session,
              deep=deep, ta_signals=signals,
              user_action_required="watch_merge_pending"
              if signals else "none")


def check() -> None:
    """Cheap due-cycle check; exits fast when nothing is due."""
    with SCHED_LOCK.open("w") as lf:
        try:
            fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return  # another checker tick in flight
        session = last_completed_session()
        st = _j(SCHED_STATE, {}) or {}
        if cycle_done(session):
            if st.get("uptodate_reported") != session:
                st["uptodate_reported"] = session
                SCHED_STATE.write_text(json.dumps(st, indent=1))
                _log(f"ALPHA_DISCOVERY_UP_TO_DATE session={session}")
            else:
                _log(f"up to date session={session}")
            return
        if CYCLE_LOCK.exists():
            try:
                with CYCLE_LOCK.open("r") as cf:
                    fcntl.flock(cf, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    fcntl.flock(cf, fcntl.LOCK_UN)
            except BlockingIOError:
                _log(f"cycle {session} already running")
                return
        _log(f"session {session} due; launching cycle")
        subprocess.Popen(
            [PY, "-m", "alpha_rnd.daily_scheduler", "--run-session", session],
            cwd=ROOT, env={**os.environ, "PYTHONPATH": str(ROOT)},
            stdout=LOG.open("a"), stderr=subprocess.STDOUT,
            start_new_session=True)


def status() -> None:
    st = _j(SCHED_STATE, {}) or {}
    print("ALPHA SCHEDULER STATUS")
    print("completed_sessions:", st.get("completed_sessions"))
    print("last_cycle:", st.get("last_cycle"))
    print("latest_completed_market_session:", last_completed_session())
    print("bridge:", bridge_status())


if __name__ == "__main__":
    if "--status" in sys.argv:
        status()
    elif "--run-session" in sys.argv:
        run_cycle(sys.argv[sys.argv.index("--run-session") + 1])
    else:
        check()
