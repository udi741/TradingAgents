#!/usr/bin/env python3
"""Phase E — adaptive management EXECUTION machinery. Currently DISABLED.

Kill switch: management_policy.json -> "execution": {"enabled": false}
When off, everything here is a pure no-op (SKIP_EXECUTION_DISABLED).

Canonical semantics preserved:
- `executed[]` / order_id = FILL authority. Only resolve_pending's
  `_exec_commit` may write it — an enqueued order is NOT executed.
- Management actions have their own durable registry
  (evaluations/.../management_actions.json):
      VALIDATED -> ENQUEUED -> FILLED -> EXECUTED
      plus CANCELLED_POSITION_CLOSED / MISSED / SUPERSEDED /
      EXECUTED_REMAINDER_REJECTED
- Composite PARTIAL_EXIT + remainder stop: the remainder rule stays
  PENDING until the partial fill is observed and the authoritative
  remaining quantity is known; it is then exec-time revalidated and only
  then applied. The original deterministic stop protects the full
  position while the order is pending.
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
ACTIONS_P = mgmt.EV / "management_actions.json"


def _utc():
    return datetime.now(timezone.utc).isoformat()


def _j(p, d=None):
    try:
        return json.loads(p.read_text())
    except Exception:
        return d


def _atomic(p, doc):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, indent=1, default=str, sort_keys=True))
    tmp.replace(p)


def enabled() -> bool:
    return bool((mgmt.policy().get("execution") or {}).get("enabled"))


def _actions() -> dict:
    return _j(ACTIONS_P, {}) or {}


def _save_actions(d: dict) -> None:
    _atomic(ACTIONS_P, d)


def _latest_intent(ticker: str) -> dict | None:
    d = mv.INTENT_DIR / ticker
    if not d.exists():
        return None
    fs = sorted(d.glob("*.json"))
    return _j(fs[-1]) if fs else None


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
    d = mv.INTENT_DIR / ticker
    if d.exists() and sorted(d.glob("*.json"))[-1].stem != \
            intent.get("management_decision_id"):
        errs.append("SUPERSEDED_MANAGEMENT_DECISION")
    if any(o.get("ticker") == ticker for o in
           (st.get("pending_open_exits") or [])
           if o.get("mgmt_action") != intent.get("action_id")):
        errs.append("CONFLICTING_PENDING_ACTION")
    shares = pos.get("shares")
    if intent.get("validated_action") == "PARTIAL_EXIT":
        q = intent.get("normalized_exit_quantity")
        if not isinstance(q, int) or q <= 0 or q >= shares:
            errs.append(f"PARTIAL_QTY_INVALID: {q} of {shares}")
    if intent.get("validated_action") == "FULL_EXIT" and not shares:
        errs.append("nothing to exit")
    return errs


def _remainder_errors(rule: dict, pos: dict, st: dict, wl: dict,
                      ticker: str) -> list[str]:
    cur = mv._current_stop(pos, wl, ticker)
    mark = mv._live_mark(st, wl, ticker, pos)
    if cur is not None and rule["level"] < cur:
        return [f"NEVER_WIDEN at activation: {rule['level']} < {cur}"]
    if cur is not None and rule["level"] == cur:
        return ["no-op: equals current stop"]
    if mark is not None and rule["level"] >= mark:
        return [f"obsolete vs mark {mark}"]
    return []


def _enqueue_exit(st: dict, ticker: str, aid: str, qty: int | None,
                  session: str | None) -> dict:
    od = {"ticker": ticker, "type": "partial" if qty else "full",
          "reason": f"MGMT_ADAPTIVE {aid}",
          "confirm_session": session,  # = decision's completed session
          "order_id": f"pending_exit:{aid}", "mgmt_action": aid}
    if qty:
        od["shares"] = qty
    st.setdefault("pending_open_exits", []).append(od)
    return od


def execute(ticker: str, st: dict, wl: dict,
            intent: dict | None = None) -> dict:
    """Convert a validated intent into canonical paper economics.
    Caller must hold the monitor state lock. Audit record only reports
    what was queued/applied — canonical 'executed' means FILLED."""
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
    aid = intent["action_id"]
    acts = _actions()
    prev = acts.get(aid)
    if prev and prev["status"] in ("ENQUEUED", "FILLED", "EXECUTED"):
        rec["result"] = "ALREADY_ENQUEUED"
        _audit(rec)
        return rec
    errs = revalidate(ticker, intent, st, wl)
    if errs:
        intent["status"] = "STALE_MANAGEMENT_DECISION"
        intent["exec_revalidation_errors"] = errs
        mv._store(intent)
        acts[aid] = {"action_id": aid, "ticker": ticker,
                     "status": "STALE_MANAGEMENT_DECISION",
                     "errors": errs, "at": _utc()}
        _save_actions(acts)
        rec.update(result="REVALIDATION_FAILED", errors=errs)
        _audit(rec)
        return rec
    pos = st["positions"][ticker]
    act = intent["validated_action"]
    rec_a = {"action_id": aid, "ticker": ticker,
             "decision_id": intent["management_decision_id"],
             "action": act, "enqueued_at": _utc()}

    if act == "PARTIAL_EXIT":
        q = intent["normalized_exit_quantity"]
        od = _enqueue_exit(st, ticker, aid, q,
                           intent.get("decision_session"))
        # remainder stop is PENDING — not applied to the pre-fill position
        rec_a.update({"status": "ENQUEUED", "qty": q,
                      "expected_remaining": pos["shares"] - q,
                     "pending_order_id": od["order_id"],
                     "remainder_rule": intent.get("proposed_risk_rule"),
                      "remainder_status": "PENDING_FILL"
                      if intent.get("proposed_risk_rule") else None})
        rec["executed"].append(f"enqueued_partial:{q}")
    elif act == "FULL_EXIT":
        od = _enqueue_exit(st, ticker, aid, None,
                           intent.get("decision_session"))
        rec_a.update({"status": "ENQUEUED", "qty": pos["shares"],
                      "expected_remaining": 0,
                      "pending_order_id": od["order_id"]})
        rec["executed"].append("enqueued_full")
    elif act == "HOLD_AND_TIGHTEN_RISK":
        errs2 = _remainder_errors(intent["proposed_risk_rule"], pos, st,
                                  wl, ticker)
        if errs2:
            rec_a.update({"status": "STALE_MANAGEMENT_DECISION",
                          "errors": errs2})
            rec.update(result="REVALIDATION_FAILED", errors=errs2)
        else:
            _apply_stop(pos, intent["proposed_risk_rule"], st, aid)
            rec_a.update({"status": "EXECUTED", "note": "stop tightened"})
            rec["executed"].append("tightened:" + aid)
    else:  # HOLD_UNCHANGED / REASSESS_LATER — nothing to enqueue
        rec_a.update({"status": "EXECUTED",
                      "note": "no economic action needed"})
        rec["executed"].append("noop:" + act)
    acts[aid] = rec_a
    _save_actions(acts)
    if rec.get("result") is None:
        rec["result"] = "ENQUEUED_ADAPTIVE"
    _audit(rec)
    return rec


def _apply_stop(pos: dict, rule: dict, st: dict, aid: str) -> None:
    """Tighten only — never widen, never weaken an existing stronger rule."""
    cur = (pos.get("stop_rule") or {}).get("level")
    if cur is not None and rule["level"] <= cur:
        return
    pos["stop_rule"] = {"type": rule["type"], "level": rule["level"],
                        "label": rule.get("label"), "mgmt_action": aid,
                        "applied_at": _utc()}


def _tick_actions(st: dict, wl: dict) -> None:
    """Lifecycle transitions for enqueued management actions. Runs inside
    the monitor lock every tick (enabled only)."""
    acts = _actions()
    changed = False
    for aid, a in acts.items():
        if a.get("status") != "ENQUEUED":
            continue
        t = a["ticker"]
        pos = (st.get("positions") or {}).get(t)
        pend = [o for o in (st.get("pending_open_exits") or [])
                if o.get("mgmt_action") == aid]
        if pos is None or pos.get("shares") in (None, 0):
            a["status"] = "CANCELLED_POSITION_CLOSED"
            changed = True
            continue
        # supersession: a newer decision exists -> pull the pending order
        if (mv.INTENT_DIR / t).exists() and \
                sorted((mv.INTENT_DIR / t).glob("*.json"))[-1].stem != \
                a.get("decision_id"):
            st["pending_open_exits"] = [
                o for o in st["pending_open_exits"]
                if o.get("mgmt_action") != aid]
            a["status"] = "SUPERSEDED"
            changed = True
            continue
        if pend:
            continue  # still queued — original protection active
        # pending order consumed
        if a.get("pending_order_id") in (st.get("executed") or []) or \
                pos["shares"] == a.get("expected_remaining"):
            a["status"] = "FILLED"
            # activate remainder stop only now, after revalidation
            rr = a.get("remainder_rule")
            if rr:
                errs = _remainder_errors(rr, pos, st, wl, t)
                if errs:
                    a["status"] = "EXECUTED_REMAINDER_REJECTED"
                    a["remainder_errors"] = errs
                else:
                    _apply_stop(pos, rr, st, aid + ":rem")
                    a["remainder_status"] = "EXECUTED"
                    a["status"] = "EXECUTED"
            else:
                a["status"] = "EXECUTED"
            changed = True
        else:
            a["status"] = "MISSED_OR_CONSUMED_UNKNOWN"
            changed = True
    if changed:
        _save_actions(acts)


def _audit(rec: dict) -> None:
    with mgmt.MEVENTS.open("a") as f:
        f.write(json.dumps({"kind": "MGMT_EXECUTION", **rec},
                           default=str) + "\n")


def cancel_pending_adaptive(st: dict) -> list[str]:
    """Kill-switch sweep: unfilled adaptive pending exits are removed and
    marked. Never touches non-adaptive orders or fills."""
    acts = _actions()
    dropped = []
    keep = []
    for o in st.get("pending_open_exits") or []:
        aid = o.get("mgmt_action")
        if aid:
            a = acts.get(aid)
            if a and a.get("status") == "ENQUEUED":
                a["status"] = "CANCELLED_BY_KILL_SWITCH"
                a["cancelled_at"] = _utc()
                dropped.append(aid)
                continue
        keep.append(o)
    st["pending_open_exits"] = keep
    if dropped:
        _save_actions(acts)
        with mgmt.MEVENTS.open("a") as f:
            f.write(json.dumps({"kind": "MGMT_CANCELLED_BY_KILL_SWITCH",
                                "actions": dropped, "at": _utc()}) + "\n")
    return dropped


def run_exec_pass(st: dict, wl: dict) -> list[dict]:
    """Called inside the monitor lock. Disabled -> cancel pending adaptive
    orders (fail-closed) and finish FILLED remainder lifecycle only."""
    if not enabled():
        cancel_pending_adaptive(st)
        acts = _actions()
        # FILLED actions may still complete remainder-protection activation
        for a in acts.values():
            if a.get("status") == "FILLED" and a.get("remainder_rule"):
                pass  # handled below via _tick_actions
        _tick_actions(st, wl)
        return []
    _tick_actions(st, wl)
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
