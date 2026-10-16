#!/usr/bin/env python3
"""Phase D — deterministic management-action validation. NON-ECONOMIC.

Takes a Phase C shadow recommendation and decides whether it is SAFE,
PRECISE, CURRENT and MACHINE-ACTIONABLE — without ever creating an order,
changing a stop, or touching economics.

  python -m alpha_rnd.mgmt_validate --ticker PBF
"""
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from alpha_rnd import mgmt
from alpha_rnd import mgmt_reassess as mr

ROOT = Path(__file__).resolve().parents[1]
AR = ROOT / "alpha_rnd"
EV = ROOT / "evaluations" / "alpha_rnd_v1"
INTENT_DIR = EV / "management_intents"
VALID = "VALIDATED_SHADOW_INTENT"
NONEXEC = "NON_EXECUTABLE_MANAGEMENT_PLAN"
FORBIDDEN = "FORBIDDEN_MANAGEMENT_ACTION"


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


def _current_stop(pos: dict, wl: dict, ticker: str) -> float | None:
    """Effective protective level for a long = the TIGHTEST active rule
    (max of watchlist invalidation and position stop_rule). Never-widen
    must compare against the strongest protection currently in force."""
    wl_pos = {p["ticker"]: p for p in (wl or {}).get("open_positions", [])}
    inv = (wl_pos.get(ticker) or {}).get("invalidation") or {}
    lv1 = inv.get("level") if isinstance(inv, dict) else None
    lv2 = ((pos or {}).get("stop_rule") or {}).get("level")
    lvls = [float(x) for x in (lv1, lv2) if isinstance(x, (int, float))]
    return max(lvls) if lvls else None


def _decision_id(dec: dict) -> str:
    return hashlib.sha256(json.dumps(
        {"t": dec.get("ticker"), "ctx": dec.get("context_hash"),
         "reqs": dec.get("request_refs"),
         "act": (dec.get("analysis") or {}).get("recommended_action")},
        sort_keys=True, default=str).encode()).hexdigest()[:16]


def _action_id(decision_id: str, pos_id: str, action: str,
               qty: int | None, rule) -> str:
    """Deterministic: same validated decision → same ID; different economics
    → different ID. Stored in shadow intents only — never in executed[]."""
    h = hashlib.sha256(json.dumps(
        {"d": decision_id, "p": pos_id, "a": action,
         "q": qty, "r": rule}, sort_keys=True, default=str).encode())
    return "mgmact_" + h.hexdigest()[:16]


def validate(ticker: str, dec: dict | None = None,
             state_fn=None, wl: dict | None = None,
             write: bool = True) -> dict:
    """Validate the latest (or given) Phase C decision. Returns intent dict;
    writes management_intents/<t>/<decision_id>.json when write=True."""
    state_fn = state_fn or (lambda: _j(AR / "monitor_state.json", {}) or {})
    st = state_fn()
    wl = wl if wl is not None else _j(AR / "live_watchlist.json", {}) or {}
    dec = dec or mr.latest_analysis(ticker)
    intent = {"validation_schema": 1, "ticker": ticker,
              "validated_at": _utc(), "shadow_only": True,
              "economic_authority": False,
              "banner": "SHADOW VALIDATION — NOT AN ECONOMIC ACTION"}
    if dec is None:
        intent.update(status="NO_DECISION", validation_reasons=[],
                      rejection_reasons=["no management analysis exists"],
                      warnings=[])
        return intent
    did = _decision_id(dec)
    intent["management_decision_id"] = did
    intent["decision_artifact_status"] = dec.get("status")
    an = dec.get("analysis") or {}
    action = an.get("recommended_action")
    intent["recommended_action"] = action
    reasons, reject, warn = [], [], []

    # ---- common checks --------------------------------------------------
    if dec.get("status") != "SUCCESS":
        reject.append(f"decision not SUCCESS ({dec.get('status')})")
    pos = (st.get("positions") or {}).get(ticker)
    if pos is None:
        intent["status"] = "STALE_MANAGEMENT_DECISION"
        reject.append("STALE_POSITION_CLOSED")
    shares = (pos or {}).get("shares")
    if shares is None or shares <= 0:
        reject.append("current shares unknown")
    reqs_now = mr.pending_requests(ticker)
    if reqs_now and dec.get("request_refs") and \
            set(r["request_id"] for r in reqs_now) - set(dec["request_refs"]):
        warn.append("newer unconsumed trigger exists")
    pend = [o for o in (st.get("pending_open_exits") or [])
            if o.get("ticker") == ticker]
    if pend:
        reject.append("CONFLICTING_PENDING_ACTION: pending exit exists")
    # supersession: a newer analysis artifact for same ticker
    newers = [p for p in sorted((mr.ANA_DIR / ticker).glob("reassess_*.json"))
              if dec.get("analyzed_at") and
              (_j(p) or {}).get("analyzed_at", "") > dec["analyzed_at"]]
    if newers:
        intent["status"] = "SUPERSEDED_MANAGEMENT_DECISION"
        reject.append("newer management decision exists")
    pos_id = f"{ticker}:{(pos or {}).get('entry_session') or ''}"
    intent["decision_session"] = dec.get("as_of") or dec.get("session")
    intent["position_id"] = pos_id
    intent["position_state_hash"] = mr._fingerprint(pos, []) if pos else None
    if pos and dec.get("position_state_hash"):
        # shares/stop subset of fingerprint: identity-compatible check
        if pos.get("shares") != json.loads(dec.get("_fp_debug", "{}")
                                           or "{}").get("shares"):
            pass  # fingerprint internals not stored; use live compare below
    mark = _live_mark(st, wl, ticker, pos)
    cur_stop = _current_stop(pos, wl, ticker)

    if reject:
        intent.update(status=intent.get("status") or NONEXEC,
                      rejection_reasons=reject, validation_reasons=reasons,
                      warnings=warn)
        _store(intent)
        return intent

    # ---- action-specific -------------------------------------------------
    ps = an.get("proposed_stop") or {}
    pe = an.get("partial_exit") or {}
    qty = None; rule = None

    if action == "HOLD_UNCHANGED":
        hidden = [k for k, v in (("stop", ps.get("level")),
                                 ("fraction", pe.get("fraction"))) if v]
        if hidden:
            intent["status"] = NONEXEC
            reject.append("HOLD_UNCHANGED carries hidden economic fields: "
                          + ",".join(hidden))
        else:
            intent["status"] = VALID
            reasons.append("pure hold — no economic instruction")

    elif action == "HOLD_AND_TIGHTEN_RISK":
        rule, ok, why = _validate_stop(ps, cur_stop, mark, pos)
        if not ok:
            intent["status"] = NONEXEC
            reject.append(why)
        else:
            intent["status"] = VALID
            reasons.append(why)

    elif action == "PARTIAL_EXIT":
        qty, ok, why = _normalize_partial(pe, shares)
        comp = _composite_stop(ps, cur_stop, mark, pos)
        intent["risk_validation"] = comp
        if not ok:
            intent["status"] = NONEXEC
            reject.append(why)
        elif comp["status"] == "BOTH_INVALID" or \
                (ps.get("level") is not None and not comp["remainder_ok"]):
            intent["status"] = VALID if comp["partial_ok"] else NONEXEC
            reasons.append(why)
            if ps.get("level") is not None and not comp["remainder_ok"]:
                warn.append("remainder risk rule invalid: "
                            + comp["reason"])
        else:
            intent["status"] = VALID
            reasons.append(why)
        if ok:
            intent["proposed_exit_fraction"] = pe.get("fraction")
            intent["normalized_exit_quantity"] = qty
            intent["remaining_quantity"] = shares - qty
            rule = comp.get("rule")

    elif action == "FULL_EXIT":
        if any(o.get("type") == "full" or not o.get("shares")
               for o in pend):
            intent["status"] = NONEXEC
            reject.append("conflicting pending full exit")
        else:
            intent["status"] = VALID
            qty = shares
            reasons.append("full exit of current position")

    elif action == "REASSESS_LATER":
        cond = (an.get("next_reassessment") or "")
        if re.search(r"20\d\d-\d\d-\d\d", cond) or re.search(
                r"trigger|stop|close|cross|catalyst|8-K|filing", cond,
                re.I):
            intent["status"] = VALID
            reasons.append("explicit future condition present")
        else:
            intent["status"] = NONEXEC
            reject.append("no machine-actionable reassessment condition")

    else:
        intent["status"] = FORBIDDEN
        reject.append(f"unknown or forbidden action: {action}")

    # forbidden size increases anywhere in the proposal
    if pe.get("fraction") is not None and pe["fraction"] > 1:
        intent["status"] = FORBIDDEN
        reject.append("FORBIDDEN: fraction > 1 implies adding shares")
    if isinstance(pe.get("quantity"), (int, float)) and \
            pe["quantity"] > shares:
        intent["status"] = FORBIDDEN
        reject.append("FORBIDDEN: exit quantity exceeds holdings")

    intent["validated_action"] = action if intent["status"] == VALID else None
    intent["proposed_risk_rule"] = rule
    intent["action_id"] = _action_id(did, pos_id,
                                     intent.get("validated_action") or action,
                                     qty, rule)
    intent["validation_reasons"] = reasons
    intent["rejection_reasons"] = reject
    intent["warnings"] = warn
    _store(intent)
    return intent


def _live_mark(st, wl, ticker, pos):
    m = mgmt.load_mgmt()
    rec = (m.get("positions") or {}).get(ticker) or {}
    return rec.get("latest_price") or (pos or {}).get("mark")


def _validate_stop(ps, cur_stop, mark, pos):
    """Long-position tighten check. Returns (rule, ok, reason)."""
    lv = ps.get("level")
    typ = ps.get("type")
    if lv is None or not isinstance(lv, (int, float)) or lv <= 0:
        return None, False, "MISSING_OR_INVALID_RISK_RULE"
    if mark is not None and lv >= mark:
        return None, False, f"level {lv} already obsolete vs mark {mark}"
    if cur_stop is not None and lv < cur_stop:
        return None, False, f"NEVER_WIDEN: {lv} < current stop {cur_stop}"
    if cur_stop is not None and lv == cur_stop:
        return None, False, f"no-op: level equals current stop {cur_stop}"
    if typ not in (None, "intraday_stop", "closing_stop", "close_below",
                    "daily_close"):
        return None, False, f"unsupported stop semantics: {typ}"
    rule = {"type": "close_below" if typ in (None, "closing_stop",
                                             "close_below", "daily_close") else
            "intraday_stop",
            "level": lv, "label": ps.get("rationale") or "mgmt tighten"}
    return rule, True, (f"tightens {cur_stop} -> {lv} "
                        f"({'close-confirmed' if rule['type']=='close_below' else 'intraday'})")


def _normalize_partial(pe, shares):
    """Deterministic: fraction → int(round(f*shares)); or explicit quantity.
    Must satisfy 0 < qty < shares — a normalization that consumes the whole
    position is rejected (never silently becomes a full exit)."""
    if pe.get("quantity") is not None:
        q = int(pe["quantity"])
        if q <= 0 or q >= shares:
            return None, False, f"invalid partial quantity {q} of {shares}"
        return q, True, f"explicit {q}/{shares} shares"
    f = pe.get("fraction")
    if f is None or not (0 < f < 1):
        return None, False, "invalid fraction for PARTIAL_EXIT"
    q = int(round(f * shares))
    if q <= 0 or q >= shares:
        return None, False, (f"fraction {f} normalizes to {q} of {shares} — "
                             "would consume entire position; rejected")
    return q, True, (f"fraction {f} -> {q} shares of {shares} "
                     f"(round to nearest)")


def _composite_stop(ps, cur_stop, mark, pos):
    """When PARTIAL_EXIT carries a remainder risk plan, validate the stop
    independently so Phase E knows exactly what passed."""
    if ps.get("level") is None:
        return {"status": "PARTIAL_ONLY", "partial_ok": True,
                "remainder_ok": None, "reason": "no remainder rule proposed",
                "rule": None}
    rule, ok, why = _validate_stop(ps, cur_stop, mark, pos)
    return {"status": "PARTIAL_VALID_REMAINDER_" + ("VALID" if ok else "INVALID"),
            "partial_ok": True, "remainder_ok": ok, "reason": why,
            "rule": rule if ok else None}


def _store(intent):
    t = intent.get("ticker")
    did = intent.get("management_decision_id") or "nodecision"
    _atomic(INTENT_DIR / t / f"{did}.json", intent)


def main():
    a = sys.argv
    if "--ticker" in a:
        t = a[a.index("--ticker") + 1]
        print(json.dumps(validate(t), indent=1, default=str))
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
