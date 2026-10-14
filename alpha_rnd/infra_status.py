"""Infrastructure failure classification for SWE/bridge analysis.

Separates BRIDGE_PROCESS health from UPSTREAM_MODEL status, classifies failed
inference into machine-readable reason codes, and derives upstream status only
from recent executor evidence (never from /v1/models alone). Deterministic; the
only I/O is the optional journal read and the local bridge probe. Makes no model
calls.
"""
import json
import re
import subprocess
import urllib.request
from datetime import datetime, timedelta, timezone

BRIDGE_UNIT = "tradingagents-swe-bridge.service"
BRIDGE_MODELS_URL = "http://127.0.0.1:8765/v1/models"
ANALYSIS_STATUS = "ANALYSIS_INFRASTRUCTURE_FAILED"
REASONS = ("MODEL_RATE_LIMITED", "MODEL_QUOTA_EXHAUSTED", "MODEL_UNAVAILABLE",
           "MODEL_TIMEOUT", "BRIDGE_FAILURE", "TA_RUNTIME_FAILURE",
           "MALFORMED_MODEL_OUTPUT", "UNKNOWN_MODEL_FAILURE")
NON_RETRYABLE = {"MODEL_QUOTA_EXHAUSTED", "TA_RUNTIME_FAILURE"}
USER_ACTION_REASONS = {"MODEL_QUOTA_EXHAUSTED"}
EVIDENCE_WINDOW = timedelta(hours=6)
_CODE_EXC = {"ImportError", "AttributeError", "KeyError", "TypeError",
             "IndexError", "NameError"}
_PATTERNS = [
    ("MODEL_RATE_LIMITED", re.compile(r"rate limit|\b429\b|too many requests", re.I)),
    ("MODEL_QUOTA_EXHAUSTED", re.compile(
        r"quota|insufficient (balance|funds|credits)|credits? (exhausted|exceeded)|\b402\b|payment required", re.I)),
    ("MODEL_TIMEOUT", re.compile(r"timed? ?out", re.I)),
    ("BRIDGE_FAILURE", re.compile(
        r"connection refused|name or service not known|BrokenPipe|Remote end closed", re.I)),
    ("MODEL_UNAVAILABLE", re.compile(
        r"unavailable|\b50[234]\b|devin_cli_error|bad gateway", re.I)),
]
_RESET_ABS = re.compile(r"reset in (.+?) \(at (\d{2}):(\d{2}) UTC\)")
_RESET_REL = re.compile(r"reset in (?:(\d+) hours?)?\s*(?:(\d+) minutes?)?\s*(?:(\d+) seconds?)?")


def classify(text: str, exc_name: str = "") -> str:
    for reason, rx in _PATTERNS:
        if rx.search(text or ""):
            return reason
    if exc_name in _CODE_EXC:
        return "TA_RUNTIME_FAILURE"
    return "UNKNOWN_MODEL_FAILURE"


def _reset_at(text: str, ts: datetime) -> datetime | None:
    m = _RESET_ABS.search(text)
    if m:
        u = ts.astimezone(timezone.utc)
        r = u.replace(hour=int(m.group(2)), minute=int(m.group(3)), second=0, microsecond=0)
        return r if r > u else r + timedelta(days=1)
    m = _RESET_REL.search(text)
    if m and any(m.groups()):
        h, mi, s = (int(x or 0) for x in m.groups())
        return ts + timedelta(hours=h, minutes=mi, seconds=s)
    return None


def parse_journal(text: str) -> list[dict]:
    """Executor outcomes keyed by request id (short-iso journal lines)."""
    out: dict[str, dict] = {}
    for line in (text or "").splitlines():
        if not line.strip():
            continue
        head = line.split(" ", 1)[0]
        try:
            ts = datetime.strptime(head, "%Y-%m-%dT%H:%M:%S%z")
        except ValueError:
            continue
        m = re.search(r"request=([0-9a-f]+)", line)
        if not m:
            continue
        rid = m.group(1)
        if " exit=0 " in line:
            out[rid] = {"request": rid, "ts": ts, "ok": True, "reason": None,
                        "reset_at": None, "raw": None}
        elif "executor error" in line:
            out[rid] = {"request": rid, "ts": ts, "ok": False,
                        "reason": classify(line), "reset_at": _reset_at(line, ts),
                        "raw": line[-600:]}
        elif re.search(r" exit=[1-9]", line) and rid not in out:
            out[rid] = {"request": rid, "ts": ts, "ok": False,
                        "reason": "UNKNOWN_MODEL_FAILURE", "reset_at": None, "raw": line[-600:]}
    return sorted(out.values(), key=lambda e: e["ts"])


def upstream_status(events: list[dict], now: datetime) -> dict:
    """Derived ONLY from executor evidence. No evidence -> UNKNOWN, never AVAILABLE."""
    succ = [e["ts"] for e in events if e["ok"]]
    fail = [e for e in events if not e["ok"]]
    base = {"latest_success_at": max(succ).isoformat() if succ else None,
            "latest_failure_at": max(e["ts"] for e in fail).isoformat() if fail else None,
            "reset_at": None, "reason_code": None, "evidence_count": len(events)}
    if not events:
        return {**base, "status": "UNKNOWN"}
    last = events[-1]
    if last["ok"]:
        status = "AVAILABLE" if now - last["ts"] <= EVIDENCE_WINDOW else "UNKNOWN"
        return {**base, "status": status}
    reason, reset = last["reason"], last["reset_at"]
    base.update({"reason_code": reason, "reset_at": reset.isoformat() if reset else None})
    if reason == "MODEL_RATE_LIMITED":
        return {**base, "status": "RATE_LIMITED" if reset and now < reset else "UNKNOWN"}
    if reason == "MODEL_QUOTA_EXHAUSTED":
        return {**base, "status": "QUOTA_EXHAUSTED"}
    if reason in ("MODEL_UNAVAILABLE", "MODEL_TIMEOUT", "UNKNOWN_MODEL_FAILURE") \
            and now - last["ts"] <= EVIDENCE_WINDOW:
        return {**base, "status": "UNAVAILABLE"}
    return {**base, "status": "UNKNOWN"}


def bridge_process(unit_active: bool, models_ok: bool) -> str:
    return "HEALTHY" if unit_active and models_ok else "DOWN"


def capability(bridge: str, upstream: str) -> str:
    if bridge == "DOWN" or upstream == "QUOTA_EXHAUSTED":
        return "BLOCKED"
    if upstream in ("RATE_LIMITED", "UNAVAILABLE"):
        return "DEGRADED"
    if upstream == "AVAILABLE":
        return "HEALTHY"
    return "UNKNOWN"


def probe_bridge() -> dict:
    try:
        active = subprocess.run(["systemctl", "--user", "is-active", "--quiet", BRIDGE_UNIT],
                                capture_output=True, timeout=10).returncode == 0
    except Exception:
        active = False
    try:
        d = json.loads(urllib.request.urlopen(BRIDGE_MODELS_URL, timeout=5).read())
        ids = {m.get("id") for m in d.get("data", [])}
        models = {"devin-quick", "devin-deep"} <= ids
    except Exception:
        models = False
    return {"unit_active": active, "models_endpoint_ok": models}


def read_journal(since: str = "-6h") -> str:
    try:
        return subprocess.run(["journalctl", "--user", "-u", BRIDGE_UNIT, "--since", since,
                               "-o", "short-iso", "--no-pager"],
                              capture_output=True, text=True, timeout=30).stdout
    except Exception:
        return ""


def status_report(journal_text: str | None = None, probe: dict | None = None,
                  now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    journal_text = read_journal() if journal_text is None else journal_text
    probe = probe_bridge() if probe is None else probe
    up = upstream_status(parse_journal(journal_text), now)
    bridge = bridge_process(probe["unit_active"], probe["models_endpoint_ok"])
    return {"checked_at": now.isoformat(), "bridge_process": bridge,
            "bridge_probe": probe, "upstream": up,
            "analysis_capability": capability(bridge, up["status"])}


def failure_record(session: str, ticker: str | None, stage: str, raw: str,
                   exc_name: str = "", reason: str | None = None,
                   upstream: dict | None = None, bridge: str | None = None) -> dict:
    reason = reason or classify(raw, exc_name)
    up_status = (upstream or {}).get("status")
    if reason == "UNKNOWN_MODEL_FAILURE" and up_status in ("RATE_LIMITED", "QUOTA_EXHAUSTED"):
        reason = "MODEL_RATE_LIMITED" if up_status == "RATE_LIMITED" else "MODEL_QUOTA_EXHAUSTED"
    return {"session": session, "ticker": ticker, "stage": stage,
            "status": ANALYSIS_STATUS, "reason_code": reason,
            "retryable": reason not in NON_RETRYABLE,
            "user_action": "REQUIRED" if reason in USER_ACTION_REASONS else "NONE",
            "raw_error": (raw or "")[:2000],
            "attempted_at": datetime.now(timezone.utc).isoformat(),
            "bridge_process": bridge or "UNKNOWN",
            "upstream_model_status": up_status or "UNKNOWN"}


def analysis_summary(session: str, requested: list[str], succeeded: list[str],
                     failures: dict[str, dict]) -> dict:
    """Per-ticker terminal model: SUCCESS, FAILED_TERMINAL (non-retryable), or
    RETRY_PENDING (retryable, or never attempted). Session complete = no RETRY_PENDING."""
    states, reasons = {}, {}
    for t in requested:
        if t in succeeded:
            states[t] = "SUCCESS"
            continue
        f = failures.get(t) or {}
        states[t] = "FAILED_TERMINAL" if f.get("retryable") is False else "RETRY_PENDING"
        if f:
            r = f.get("reason_code") or "UNKNOWN_MODEL_FAILURE"
            reasons[r] = reasons.get(r, 0) + 1
    pending = sorted(t for t, v in states.items() if v == "RETRY_PENDING")
    terminal = sorted(t for t, v in states.items() if v == "FAILED_TERMINAL")
    all_ok = bool(requested) and len(succeeded) == len(requested)
    complete = all_ok  # fully analysed: every ticker SUCCESS
    session_terminal = bool(requested) and not pending  # nothing left to retry
    if all_ok:
        status = "COMPLETE"
    elif pending:
        status = "DEGRADED" if succeeded else ANALYSIS_STATUS
    else:
        status = "COMPLETE_WITH_TERMINAL_FAILURES"
    dominant = max(reasons, key=lambda k: (reasons[k], k)) if reasons else None
    return {"session": session, "status": status, "analysis_complete": complete,
            "session_terminal": session_terminal, "all_succeeded": all_ok,
            "ta_requested": len(requested), "ta_succeeded": len(succeeded),
            "ta_failed": len(pending) + len(terminal),
            "failed_tickers": sorted(pending + terminal),
            "retry_pending": pending, "failed_terminal": terminal,
            "ticker_states": states,
            "ta_failure_reasons": reasons, "dominant_reason": dominant,
            "failures": failures}


def main() -> None:
    s = status_report()
    up = s["upstream"]
    print("SWE STATUS")
    print(f"  bridge process:        {s['bridge_process']} "
          f"(unit_active={s['bridge_probe']['unit_active']}, "
          f"models_endpoint_ok={s['bridge_probe']['models_endpoint_ok']})")
    print(f"  upstream model:        {up['status']}"
          + (f" ({up['reason_code']})" if up["reason_code"] else ""))
    print(f"  latest success:        {up['latest_success_at'] or 'none in window'}")
    print(f"  latest failure:        {up['latest_failure_at'] or 'none in window'}")
    print(f"  reset (if limited):    {up['reset_at'] or 'n/a'}")
    print(f"  analysis capability:   {s['analysis_capability']}")


if __name__ == "__main__":
    main()
