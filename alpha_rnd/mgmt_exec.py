#!/usr/bin/env python3
"""Phase E — adaptive management EXECUTION machinery. Currently DISABLED.

Converts a Phase D VALIDATED_SHADOW_INTENT into canonical paper economics
(pending_open_exits / stop_rule) — but only when the kill switch is ON.

Kill switch: management_policy.json -> "execution": {"enabled": false}
Default FALSE. When off, everything in this module is a pure no-op that
still records a SKIP decision for audit.

Never edits shares/cash directly — exits go through pending_open_exits
(canonical next-open fill + pro-rata cost basis in monitor.do_exit);
tighten goes through position stop_rule with never-widen + idempotent
action IDs in st["executed"].
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from alpha_rnd import mgmt
from alpha_rnd import mgmt_reassess as mr
from alpha_rnd import mgmt_validate as mv

ROOT = Path(__file__).resolve().parents[1]
AR = ROOT / "alpha_rnd"


def _utc():
    return datetime.now(timezone.utc).isoformat()


def _j(p, d=None):
    try:
        return json.loads(p.read_text())
    except Exception:
        return d


def enabled() -> bool:
    pol = mgmt.policy()
    return bool((pol.get("execution") or {}).get("enabled"))


def _latest_intent(ticker: str) -> dict | None:
    d = mv.INTENT_DIR / ticker
    if not d.exists():
        return None
    fs = sorted(d.glob("*.json"))
    return _j(fs[-1]) if fs else None


def latest_decision_id(ticker: str) -> str | None:
    d = mv.INTENT_DIR / ticker
    if not d.exists():
        return None
    return sorted(d.glob("*.json"))[-1].stem


def _done(st: dict, aid: str) -> bool:
    return aid in (st.get("executed") or [])


def revalidate(ticker: str, intent: dict, st: dict, wl: dict) -> list[str]:
    """Execution-time gate. Any non-empty list = DO NOT EXECUTE."""
    errs = []
    pos = (st.get("positions") or {}).get(ticker)
    if pos is None:
        return ["STALE_POSITION_CLOSED"]
    if intent.get("position_id") and \
            not str(intent["position_id"]).endswith(
                str(pos.get("entry_session") or "")):
        errs.append("STALE_POSITION_CHANGED: entry_session mismatch")
    if intent.get("status") != "VALIDATED_SHADOW_INTENT":
        errs.append(f"intent status {intent.get('status')}")
    if latest_decision_id(ticker) != intent.get("management_decision_id"):
        errs.append("SUPERSEDED_MANAGEMENT_DECISION")
    if _done(st, intent.get("action_id")):
        errs.append("ALREADY_EXECUTED")
    if any(o.get("ticker") == ticker for o in
           (st.get("pending_open_exits") or [])):
        errs.append("CONFLICTING_PENDING_ACTION")
    shares = pos.get("shares")
    if intent.get("validated_action") == "PARTIAL_EXIT":
        q = intent.get("normalized_exit_quantity")
        if not isinstance(q, int) or q <= 0 or q >= shares:
            errs.append(f"PARTIAL_QTY_INVALID: {q} of {shares}")
    if intent.get("validated_action") == "FULL_EXIT" and not shares:
        errs.append("nothing to exit")
    rule = intent.get("proposed_risk_rule")
    if rule:
        cur = mv._current_stop(pos, wl, ticker)
        mark = mv._live_mark(st, wl, ticker, pos)
        if cur is not None and rule["level"] < cur:
            errs.append(f"NEVER_WIDEN violated at exec time: "
                        f"{rule['level']} < {cur}")
        if cur is not None and rule["level"] == cur:
            errs.append("stop already at proposed level")
        if mark is not None and rule["level"] >= mark:
            errs.append(f"proposed stop {rule['level']} obsolete "
                        f"vs mark {mark}")
    return errs


def execute(ticker: str, st: dict, wl: dict,
            intent: dict | None = None) -> dict:
    """Convert a validated intent into canonical paper economics.
    Caller must hold the monitor state lock. Returns an audit record."""
    rec = {"ticker": ticker, "at": _utc(), "executed": []}
    if not enabled():
        rec["result"] = "SKIP_EXECUTION_DISABLED"
        _audit(rec)
        return rec
    intent = intent or _latest_intent(ticker)
    if intent is None:
        rec["result"] = "NO_INTENT"
        _audit(rec)
        return rec
    errs = revalidate(ticker, intent, st, wl)
    if errs:
        intent["status"] = "STALE_MANAGEMENT_DECISION"
        intent["exec_revalidation_errors"] = errs
        mv._store(intent)
        rec.update(result="REVALIDATION_FAILED", errors=errs)
        _audit(rec)
        return rec
    pos = st["positions"][ticker]
    aid = intent["action_id"]
    act = intent["validated_action"]

    if act == "PARTIAL_EXIT":
        q = intent["normalized_exit_quantity"]
        st.setdefault("pending_open_exits", []).append({
            "ticker": ticker, "shares": q, "type": "partial",
            "reason": f"MGMT_ADAPTIVE {aid}",
            "order_id": f"pending_exit:{aid}",
            "confirmation_session": st.get("last_eval_session"),
            "mgmt_action": aid})
        st.setdefault("executed", []).append(aid)
        rec["executed"].append(f"pending_partial:{q}")
        # composite: remainder stop becomes authoritative immediately —
        # it is attached to the position, independent of the pending fill,
        # so a crash between order and fill cannot leave it unprotected.
        if intent.get("proposed_risk_rule"):
            _apply_stop(pos, intent["proposed_risk_rule"], st, aid)
            rec["executed"].append("remainder_stop:" + aid)
    elif act == "FULL_EXIT":
        st.setdefault("pending_open_exits", []).append({
            "ticker": ticker, "type": "full",
            "reason": f"MGMT_ADAPTIVE {aid}", "order_id": f"pending_exit:{aid}",
            "confirmation_session": st.get("last_eval_session"),
            "mgmt_action": aid})
        st.setdefault("executed", []).append(aid)
        rec["executed"].append("pending_full")
    elif act == "HOLD_AND_TIGHTEN_RISK":
        _apply_stop(pos, intent["proposed_risk_rule"], st, aid)
        st.setdefault("executed", []).append(aid)
        rec["executed"].append("tightened:" + aid)
    rec["result"] = "EXECUTED_ADAPTIVE_SHADOW"
    _audit(rec)
    return rec


def _apply_stop(pos: dict, rule: dict, st: dict, aid: str) -> None:
    """Tighten only — never widen, never weaken an existing stronger rule."""
    cur = (pos.get("stop_rule") or {}).get("level")
    if cur is not None and rule["level"] <= cur:
        return  # stronger rule already in place — idempotent
    pos["stop_rule"] = {"type": rule["type"], "level": rule["level"],
                        "label": rule.get("label"), "mgmt_action": aid,
                        "applied_at": _utc()}


def _audit(rec: dict) -> None:
    with mgmt.MEVENTS.open("a") as f:
        f.write(json.dumps({"kind": "MGMT_EXECUTION", **rec},
                           default=str) + "\n")


def run_exec_pass(st: dict, wl: dict) -> list[dict]:
    """Called inside the monitor lock. No-op unless execution enabled."""
    if not enabled():
        return []
    out = []
    for t in list((st.get("positions") or {})):
        out.append(execute(t, st, wl))
    return out


def main():
    a = sys.argv
    if len(a) > 1 and a[1] == "status":
        print(f"adaptive execution: {'ENABLED' if enabled() else 'DISABLED'}")
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
