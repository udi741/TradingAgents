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
SCHED_STATE_LOCK = AR / "scheduler_state.lock"
EVENTS = AR / "scheduler_events.jsonl"
LOG = AR / "scheduler.log"

BRIDGE_MODELS_URL = "http://127.0.0.1:8765/v1/models"
# Bridge process lifecycle is owned by tradingagents-swe-bridge.service.
# The accepted config lives in that unit; schedulers only consume :8765.
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
        "alpha_discovery",
        ROOT / "evaluations" / "alpha_rnd_v1" / "discovery.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def last_completed_session() -> str:
    return _load_discovery().last_completed_session()


def cycle_done(session: str) -> bool:
    st = _j(SCHED_STATE, {}) or {}
    return session in (st.get("completed_sessions") or [])


def _state_txn(fn):
    """Serialized read-modify-write of scheduler_state.json (flock + atomic
    replace). Call inside check()/run_cycle/publish — never while already
    holding this lock."""
    with SCHED_STATE_LOCK.open("w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        st = _j(SCHED_STATE, {}) or {}
        fn(st)
        tmp = SCHED_STATE.with_suffix(".tmp")
        tmp.write_text(json.dumps(st, indent=1))
        tmp.replace(SCHED_STATE)


def mark_done(session: str, summary: dict) -> None:
    def _mut(st):
        done = st.get("completed_sessions") or []
        if session not in done:
            done.append(session)
        st["completed_sessions"] = done
        st["last_cycle"] = {"session": session,
                            "finished_at": datetime.now(timezone.utc).isoformat(),
                            "summary": summary}
    _state_txn(_mut)


def deep_allocation(session: str) -> list[str]:
    """Delegate to the canonical implementation in discovery.py —
    orchestration only, no strategy logic duplicated here."""
    pool = (_j(EV_DIR / f"candidate_pool_frozen_{session}.json", {}) or {}) \
        .get("candidates") or []
    return _load_discovery().select_deep_candidates(pool, quota=DEEP_QUOTA)


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


def _systemctl_env() -> dict:
    """cron lacks XDG_RUNTIME_DIR/DBUS; derive the user bus path from UID."""
    env = dict(os.environ)
    rd = f"/run/user/{os.getuid()}"
    env.setdefault("XDG_RUNTIME_DIR", rd)
    env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path={rd}/bus")
    return env


def ensure_bridge() -> bool:
    """Bridge lifecycle is owned by tradingagents-swe-bridge.service only.

    Schedulers are consumers: they may ask systemd to recover the service
    and wait, but must never spawn a bridge process directly (would create
    an unmanaged duplicate that fights the supervised owner for :8765).
    """
    st = bridge_status()
    if st == "ok":
        return True
    if st == "foreign_busy":
        return False
    # down: nothing is listening, so no in-flight request can be disturbed;
    # delegate recovery to the supervised owner.
    _log("bridge down; requesting systemd restart of tradingagents-swe-bridge")
    subprocess.run(
        ["systemctl", "--user", "restart", "tradingagents-swe-bridge.service"],
        check=False, capture_output=True, env=_systemctl_env())
    for _ in range(45):
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
        # Resume-safe: run_ta.run_one returns the existing artifact without a
        # model call; pass only missing tickers to keep the subprocess cheap.
        missing = [t for t in deep
                   if not (EV_DIR / "case_artifacts" / f"{t}_{session}.json").exists()]
        r = subprocess.run([PY, str(EV_DIR / "run_ta.py"), session, *missing],
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
        # 4. Automatic publication synthesis (translator, not strategy):
        #    frozen TA artifacts -> PublicationIntents -> fail-closed
        #    validation -> canonical publish -> live watchlist.
        r = subprocess.run([PY, "-m", "alpha_rnd.synthesize", session],
                           cwd=ROOT,
                           env={**os.environ, "PYTHONPATH": str(ROOT)},
                           capture_output=True, text=True, timeout=1320)
        idoc = _j(EV_DIR / f"publication_intents_{session}.json") or {}
        if r.returncode != 0 and not idoc.get("validated") and not idoc.get("review_required"):
            event("ALPHA_DISCOVERY_ERROR", session=session,
                  stage="publication_synthesis",
                  tail=(r.stderr or r.stdout)[-400:])
            return
        reviews = idoc.get("review_required") or []
        # 5. Canonical publish (atomic, idempotent) — mixed policy: validated
        #    intents publish now; ambiguous cases fail closed to review.
        r = subprocess.run([PY, "-m", "alpha_rnd.publish", session],
                           cwd=ROOT,
                           env={**os.environ, "PYTHONPATH": str(ROOT)},
                           capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            event("ALPHA_DISCOVERY_ERROR", session=session,
                  stage="publish", tail=(r.stderr or r.stdout)[-400:])
            return
        pub = (_j(SCHED_STATE, {}) or {}).get("published_sessions", {}).get(session)
        if not pub:
            event("ALPHA_DISCOVERY_ERROR", session=session,
                  stage="publish_marker", tail="publish ran without marker")
            return
        if reviews:
            event("ALPHA_PUBLICATION_REVIEW_REQUIRED", session=session,
                  tickers=[x["ticker"] for x in reviews],
                  violations={x["ticker"]: x["violations"] for x in reviews},
                  resume="feather-room")
        summary = {"deep": deep, "ta_signals": signals,
                   "published": pub,
                   "validated": idoc.get("validated"),
                   "pending_review": [x["ticker"] for x in reviews]}
        mark_done(session, summary)
        event("ALPHA_DISCOVERY_COMPLETE", session=session,
              deep=deep, ta_signals=signals, published=pub,
              pending_review=[x["ticker"] for x in reviews],
              user_action_required="review_pending" if reviews else "none")


def check() -> None:
    """Cheap due-cycle check; exits fast when nothing is due."""
    with SCHED_LOCK.open("w") as lf:
        try:
            fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return  # another checker tick in flight
        session = last_completed_session()
        st = _j(SCHED_STATE, {}) or {}
        # Publication landed for a session whose analysis finished: close it.
        pub = (st.get("published_sessions") or {})
        ad = (st.get("analysis_done") or {})
        for s, summ in ad.items():
            if s in pub and not cycle_done(s):
                mark_done(s, {"deep": summ.get("deep"),
                              "ta_signals": summ.get("ta_signals"),
                              "published": pub[s]})
                event("ALPHA_DISCOVERY_COMPLETE", session=s,
                      deep=summ.get("deep"),
                      ta_signals=summ.get("ta_signals"),
                      published=pub[s],
                      user_action_required="none")
        if session in ad and session not in pub:
            _log(f"session {session} analysis complete; awaiting publication")
            return
        if session in ad and session in pub:
            return  # just closed above
        if cycle_done(session):
            if st.get("uptodate_reported") != session:
                _state_txn(lambda x: x.__setitem__("uptodate_reported", session))
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
