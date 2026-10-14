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

from alpha_rnd import infra_status as inf

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
# Per-stage subprocess bounds. The same numbers bound staleness: a run whose
# last durable progress is older than its stage timeout + slack is STALLED.
STAGE_TIMEOUTS = {"book": 600, "discovery": 7200, "ta": 14400,
                  "synthesize": 1320, "publish": 300}
STALE_SLACK_S = 900
# TA needs Python >=3.11 (official code uses datetime.UTC/StrEnum); the repo
# venv is the canonical interpreter, falling back to the system python.
_TA_PY = ROOT / ".venv312" / "bin" / "python"
TA_PY = str(_TA_PY) if _TA_PY.exists() else PY


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
        _terminal(st, session, "COMPLETE")
    _state_txn(_mut)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pid_alive(pid) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except (ProcessLookupError, TypeError, ValueError):
        return False
    except PermissionError:
        return True


def _terminal(st: dict, session: str, status: str) -> None:
    """Exactly one durable terminal status per run attempt; called under the
    state lock. A later successful retry honestly overwrites INTERRUPTED."""
    if st.get("current_run", {}).get("session") == session:
        st.pop("current_run")
    st.setdefault("session_status", {})[session] = status


def _finish_run(session: str, status: str) -> None:
    _state_txn(lambda st: _terminal(st, session, status))


def _start_run(session: str) -> None:
    ts = _utcnow()
    def _mut(st):
        st["current_run"] = {"session": session, "run_id": ts,
                             "pid": os.getpid(), "started_at": ts,
                             "stage": "book", "last_progress_at": ts,
                             "deep_total": 0, "ta_completed": 0, "ta_failed": 0}
    _state_txn(_mut)


def _run_progress(stage: str, **kw) -> None:
    def _mut(st):
        cr = st.get("current_run")
        if cr is None:
            return
        cr.update(kw)
        cr["stage"] = stage
        cr["last_progress_at"] = _utcnow()
    _state_txn(_mut)


def _refresh_ta_progress(session: str) -> None:
    """Refresh durable per-ticker counts from artifacts on disk; only real
    movement bumps last_progress_at so staleness stays meaningful."""
    ca = EV_DIR / "case_artifacts"
    good = sum(1 for p in ca.glob(f"*_{session}.json")
               if not p.name.endswith(".error.json"))
    bad = len(list(ca.glob(f"*_{session}.error.json")))
    def _mut(st):
        cr = st.get("current_run")
        if not cr:
            return
        if cr.get("ta_completed") != good or cr.get("ta_failed") != bad:
            cr["ta_completed"], cr["ta_failed"] = good, bad
            cr["last_progress_at"] = _utcnow()
    _state_txn(_mut)


def _reap_current_run(st: dict) -> bool:
    """Inspect the tracked run. Returns True if a live run exists (caller
    should return early). Dead-pid runs are marked INTERRUPTED once and the
    record cleared so the normal due logic relaunches (resume-safe)."""
    cr = st.get("current_run")
    if not cr:
        return False
    session = cr["session"]
    if _pid_alive(cr.get("pid")):
        if cr.get("stage") == "ta":
            _refresh_ta_progress(session)
            cr = (_j(SCHED_STATE, {}) or {}).get("current_run", cr)
        bound = STAGE_TIMEOUTS.get(cr.get("stage"), 1800) + STALE_SLACK_S
        try:
            age = (datetime.now(timezone.utc) -
                   datetime.fromisoformat(cr["last_progress_at"])).total_seconds()
        except Exception:
            age = 0
        if age > bound and not cr.get("stalled_notified"):
            event("ALPHA_CYCLE_STALLED", session=session, stage=cr.get("stage"),
                  age_s=int(age), pid=cr.get("pid"))
            _state_txn(lambda x: x.get("current_run", {}).__setitem__("stalled_notified", True))
        _log(f"cycle {session} RUNNING stage={cr.get('stage')} "
             f"ta={cr.get('ta_completed', 0)}/{cr.get('deep_total', '?')} "
             f"pid={cr.get('pid')} age={int(age)}s")
        return True
    # run-session process is gone — orphan, not silently
    already = (st.get("session_status") or {}).get(session)
    _finish_run(session, "INTERRUPTED")
    if already != "INTERRUPTED":
        event("ALPHA_DISCOVERY_INTERRUPTED", session=session,
              stage=cr.get("stage"), pid=cr.get("pid"),
              note="run-session process gone; due-check will resume "
                   "prospectively from frozen inputs/artifacts")
    return False


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


def _upstream_snapshot() -> dict:
    """Bridge process + upstream model status, derived from executor evidence."""
    return inf.status_report()


def _analysis_fields(a: dict) -> dict:
    return {k: a.get(k) for k in ("analysis_complete", "ta_requested", "ta_succeeded",
                                  "ta_failed", "failed_tickers", "ta_failure_reasons",
                                  "dominant_reason")}


def _write_failure(session: str, t: str, up: dict, raw: str, reason: str | None = None) -> None:
    rec = inf.failure_record(session, t, "ta", raw, reason=reason, upstream=up["upstream"],
                             bridge=up["bridge_process"])
    rec["error"] = rec["raw_error"]
    p = EV_DIR / "case_artifacts" / f"{t}_{session}.error.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rec, indent=1))


def _analysis_summary(session: str, deep: list[str]) -> dict:
    ca = EV_DIR / "case_artifacts"
    ok, bad = [], {}
    for t in deep:
        a = _j(ca / f"{t}_{session}.json", None)
        if a is not None and a.get("signal"):
            ok.append(t)
            continue
        if a is not None:
            bad[t] = {"reason_code": "TA_RUNTIME_FAILURE", "retryable": False,
                      "raw_error": "artifact without signal"}
            continue
        e = _j(ca / f"{t}_{session}.error.json", None) or {}
        bad[t] = {"reason_code": e.get("reason_code") or "UNKNOWN_MODEL_FAILURE",
                  "retryable": e.get("retryable", True),
                  "raw_error": (e.get("raw_error") or e.get("error") or "no artifact produced")[:300]}
    summ = inf.analysis_summary(session, deep, ok, bad)
    (EV_DIR / f"analysis_status_{session}.json").write_text(
        json.dumps({**summ, "checked_at": _utcnow()}, indent=1, default=str))
    return summ


def _alert_analysis(session: str, summ: dict, kind: str | None = None, stage: str = "ta") -> None:
    """At most one bounded operational alert per session per distinct status."""
    kind = kind or ("ALPHA_ANALYSIS_INFRASTRUCTURE_FAILED" if summ["ta_succeeded"] == 0
                    else "ALPHA_ANALYSIS_DEGRADED")
    sig = "|".join([kind, str(summ.get("dominant_reason")), str(summ.get("ta_succeeded")),
                    ",".join(summ.get("failed_tickers") or [])])
    if ((_j(SCHED_STATE, {}) or {}).get("analysis_alerts") or {}).get(session) == sig:
        return
    event(kind, session=session, stage=stage,
          reason_code=summ.get("dominant_reason"),
          ta_requested=summ.get("ta_requested"), ta_succeeded=summ.get("ta_succeeded"),
          ta_failed=summ.get("ta_failed"), failed_tickers=summ.get("failed_tickers"),
          user_action_required=("REQUIRED" if summ.get("dominant_reason") in inf.USER_ACTION_REASONS
                                else "NONE"))
    _state_txn(lambda st: st.setdefault("analysis_alerts", {}).__setitem__(session, sig))


def run_cycle(session: str) -> None:
    """One full normal cycle for `session` (internal, holds cycle lock).

    Every exit path leaves exactly one durable terminal status in
    session_status: COMPLETE, ERROR, or BLOCKED. STARTED-without-terminal is
    forbidden — a crash/timeout still writes ERROR before the process exits,
    and a vanished process is reaped INTERRUPTED by the next check() tick."""
    with CYCLE_LOCK.open("w") as lf:
        try:
            fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            _log(f"cycle {session} already running elsewhere; exiting")
            return
        try:
            _start_run(session)
            event("ALPHA_DISCOVERY_STARTED", session=session)
            _run_cycle(session)
        except subprocess.TimeoutExpired as e:
            stage = (_j(SCHED_STATE, {}) or {}).get("current_run", {}).get("stage")
            _finish_run(session, "ERROR")
            event("ALPHA_DISCOVERY_ERROR", session=session,
                  stage=stage or "unknown",
                  tail=f"stage timeout after {e.timeout}s")
        except Exception as e:
            stage = (_j(SCHED_STATE, {}) or {}).get("current_run", {}).get("stage")
            _finish_run(session, "ERROR")
            event("ALPHA_DISCOVERY_ERROR", session=session,
                  stage=stage or "unknown", tail=repr(e)[-400:])


def _run_cycle(session: str) -> None:
    """Pipeline body; current_run progress is durable at each stage boundary."""
    env = {**os.environ, "PYTHONPATH": str(ROOT)}

    # 1. Existing book first — per-minute monitor bookkeeping pass.
    _run_progress("book")
    subprocess.run([PY, "-m", "alpha_rnd.monitor", "--once"],
                   cwd=ROOT, env=env,
                   capture_output=True, timeout=STAGE_TIMEOUTS["book"])

    # 2. Frozen discovery pipeline.
    _run_progress("discovery")
    r = subprocess.run([PY, str(EV_DIR / "discovery.py"), session],
                       cwd=ROOT, env=env,
                       capture_output=True, text=True,
                       timeout=STAGE_TIMEOUTS["discovery"])
    if r.returncode != 0 or not (EV_DIR / f"candidate_pool_frozen_{session}.json").exists():
        _finish_run(session, "ERROR")
        event("ALPHA_DISCOVERY_ERROR", session=session,
              stage="discovery", tail=(r.stderr or r.stdout)[-400:])
        return
    deep = deep_allocation(session)

    # 3. Bridge, then frozen TA pass on the deep allocation.
    if not ensure_bridge():
        _finish_run(session, "BLOCKED")
        event("ALPHA_DISCOVERY_BLOCKED_BRIDGE", session=session,
              deep=deep, status=bridge_status())
        return  # retried on next tick (not marked done)
    # Resume-safe: run_ta.run_one returns the existing artifact without a
    # model call; pass only missing tickers to keep the subprocess cheap.
    missing = [t for t in deep
               if not (EV_DIR / "case_artifacts" / f"{t}_{session}.json").exists()]
    _run_progress("ta", deep_total=len(deep), deep=deep, ta_missing=missing)
    up = _upstream_snapshot()
    known_block = {"RATE_LIMITED": "MODEL_RATE_LIMITED",
                   "QUOTA_EXHAUSTED": "MODEL_QUOTA_EXHAUSTED"}.get(up["upstream"]["status"])
    if missing and known_block:
        # Upstream is known rate-limited/exhausted: make NO model calls; each
        # missing ticker is recorded as an infrastructure failure (retryable).
        for t in missing:
            _write_failure(session, t, up,
                           f"not attempted: upstream {up['upstream']['status']} until "
                           f"{up['upstream']['reset_at']} (no SWE call made)", reason=known_block)
    else:
        subprocess.run([TA_PY, str(EV_DIR / "run_ta.py"), session, *missing],
                       cwd=ROOT, env=env, capture_output=True, text=True,
                       timeout=STAGE_TIMEOUTS["ta"])
    analysis = _analysis_summary(session, deep)
    _run_progress("ta", ta_completed=analysis["ta_succeeded"], ta_failed=analysis["ta_failed"])
    if analysis["ta_succeeded"] == 0:
        _finish_run(session, "ERROR")
        _alert_analysis(session, analysis)
        return
    if not analysis["analysis_complete"]:
        _alert_analysis(session, analysis)
    arts = sorted((EV_DIR / "case_artifacts").glob(f"*_{session}.json"))
    signals = {}
    for p in arts:
        a = _j(p, {}) or {}
        if a.get("signal"):
            signals[a.get("ticker") or p.stem.split("_")[0]] = a.get("signal")

    # 4. Automatic publication synthesis (translator, not strategy):
    #    frozen TA artifacts -> PublicationIntents -> fail-closed
    #    validation -> canonical publish -> live watchlist.
    _run_progress("synthesize")
    cached = (_j(EV_DIR / f"publication_intents_{session}.json") or {}).get("intents") or {}
    todo = [t for t in signals if t not in cached]
    if todo and known_block:
        status = {"status": inf.ANALYSIS_STATUS, "stage": "publication_synthesis",
                  "reason_code": known_block, "tickers": sorted(todo),
                  "raw_error": "not attempted: upstream known unavailable (no translator call)"}
        (EV_DIR / f"publication_status_{session}.json").write_text(json.dumps(status, indent=1))
        _alert_analysis(session, {**analysis, "dominant_reason": known_block},
                        kind="ALPHA_ANALYSIS_INFRASTRUCTURE_FAILED", stage="publication_synthesis")
        _finish_run(session, "ERROR")
        return
    r = subprocess.run([PY, "-m", "alpha_rnd.synthesize", session],
                       cwd=ROOT, env=env,
                       capture_output=True, text=True,
                       timeout=STAGE_TIMEOUTS["synthesize"])
    pstat = _j(EV_DIR / f"publication_status_{session}.json") or {}
    if pstat.get("status") == inf.ANALYSIS_STATUS:
        _alert_analysis(session, {**analysis, "dominant_reason": pstat.get("reason_code"),
                                  "ta_succeeded": max(analysis["ta_succeeded"], 1)},
                        kind="ALPHA_ANALYSIS_INFRASTRUCTURE_FAILED", stage="publication_synthesis")
        _finish_run(session, "ERROR")
        return
    idoc = _j(EV_DIR / f"publication_intents_{session}.json") or {}
    if r.returncode != 0 and not idoc.get("validated") and not idoc.get("review_required"):
        _finish_run(session, "ERROR")
        event("ALPHA_DISCOVERY_ERROR", session=session,
              stage="publication_synthesis",
              tail=(r.stderr or r.stdout)[-400:])
        return
    reviews = idoc.get("review_required") or []
    disps = idoc.get("dispositions") or {}
    # 5. Canonical publish (atomic, idempotent) — mixed policy: validated
    #    intents publish now; ambiguous cases fail closed to review.
    _run_progress("publish")
    r = subprocess.run([PY, "-m", "alpha_rnd.publish", session],
                       cwd=ROOT, env=env,
                       capture_output=True, text=True,
                       timeout=STAGE_TIMEOUTS["publish"])
    if r.returncode != 0:
        _finish_run(session, "ERROR")
        event("ALPHA_DISCOVERY_ERROR", session=session,
              stage="publish", tail=(r.stderr or r.stdout)[-400:])
        return
    pub = (_j(SCHED_STATE, {}) or {}).get("published_sessions", {}).get(session)
    if not pub:
        _finish_run(session, "ERROR")
        event("ALPHA_DISCOVERY_ERROR", session=session,
              stage="publish_marker", tail="publish ran without marker")
        return
    if disps:
        counts = {}
        for d in disps.values():
            counts[d["disposition"]] = counts.get(d["disposition"], 0) + 1
        # Normal ambiguity is a fail-closed classification, not an emergency:
        # exactly one informational summary, never ACTION_REQUIRED.
        event("ALPHA_PUBLICATION_SUMMARY", session=session,
              dispositions=counts, **_analysis_fields(analysis),
              detail={t: d["disposition"] for t, d in disps.items()},
              user_action_required="none")
    elif reviews:
        # pre-disposition docs only (legacy path; should not occur)
        event("ALPHA_PUBLICATION_SUMMARY", session=session,
              dispositions={"UNCLASSIFIED_REVIEW": len(reviews)},
              user_action_required="none")
    # R1: immutable opportunity-funnel artifact (observability; never fatal)
    try:
        subprocess.run([PY, "-m", "alpha_rnd.funnel", "build", session],
                       cwd=ROOT, env=env, timeout=120)
    except Exception:
        pass
    # R6: low-price shadow cohort freeze (observational; never fatal)
    try:
        subprocess.run([PY, "-m", "alpha_rnd.low_price_shadow", "build",
                        session], cwd=ROOT, env=env, timeout=300)
    except Exception:
        pass
    summary = {"deep": deep, "ta_signals": signals, "analysis": _analysis_fields(analysis),
               "published": pub,
               "validated": idoc.get("validated"),
               "dispositions": {t: d["disposition"] for t, d in disps.items()}}
    mark_done(session, summary)
    event("ALPHA_DISCOVERY_COMPLETE", session=session,
          deep=deep, ta_signals=signals, published=pub,
          dispositions=summary["dispositions"], **_analysis_fields(analysis),
          user_action_required="none")


def check() -> None:
    """Cheap due-cycle check; exits fast when nothing is due."""
    with SCHED_LOCK.open("w") as lf:
        try:
            fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return  # another checker tick in flight
        session = last_completed_session()
        st = _j(SCHED_STATE, {}) or {}
        # Watchdog: a tracked run must resolve to a terminal state or be
        # reaped INTERRUPTED — never silently orphaned after suspend/kill.
        if _reap_current_run(st):
            return
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
    print("current_run:", st.get("current_run"))
    print("session_status:", st.get("session_status"))


if __name__ == "__main__":
    if "--status" in sys.argv:
        status()
    elif "--run-session" in sys.argv:
        run_cycle(sys.argv[sys.argv.index("--run-session") + 1])
    else:
        check()
