#!/usr/bin/env python3
"""Phase C — shadow post-entry model reassessment.

Consumes Phase B SHADOW_TRIGGERED requests, builds an immutable bounded
context (original thesis + what happened since entry + why it triggered +
fresh bounded info), asks the model a POSITION-MANAGEMENT question, and
writes a SHADOW recommendation artifact. No economics, no orders, no stops.

States: SUCCESS / RETRY_PENDING / FAILED_TERMINAL — same generic infra
reason codes as the analysis pipeline. NO VALID MODEL RESULT -> NO
MANAGEMENT RECOMMENDATION.

  python -m alpha_rnd.mgmt_reassess run --ticker PBF
  python -m alpha_rnd.mgmt_reassess run --ticker TWST --as-of 2026-10-07
"""
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from alpha_rnd import infra_status as inf
from alpha_rnd import mgmt
from alpha_rnd.synthesize import call_bridge, TranslatorInfra, MODEL

ROOT = Path(__file__).resolve().parents[1]
AR = ROOT / "alpha_rnd"
EV = ROOT / "evaluations" / "alpha_rnd_v1"
CTX_DIR = EV / "management_contexts"
ANA_DIR = EV / "management_analyses"
DEC_DIR = EV / "management_decisions"
ACTIONS = ["HOLD_UNCHANGED", "HOLD_AND_TIGHTEN_RISK", "PARTIAL_EXIT",
           "FULL_EXIT", "REASSESS_LATER"]
THESIS = ["STRENGTHENED", "INTACT", "WEAKENED", "LARGELY_REALIZED",
          "INVALIDATED", "UNCERTAIN"]
CATALYST = ["PENDING", "OCCURRED_POSITIVE", "OCCURRED_NEGATIVE", "DELAYED",
            "CANCELLED", "PRICED_IN", "NOT_APPLICABLE", "UNKNOWN"]


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


# ---------------- context ----------------


def _fingerprint(pos: dict | None, reqs: list[dict]) -> str:
    """Position/context identity captured pre-call; compared post-call."""
    core = {"shares": (pos or {}).get("shares"),
            "fill": (pos or {}).get("fill"),
            "stop": (pos or {}).get("stop_rule"),
            "reqs": sorted(r.get("request_id") for r in reqs)}
    return hashlib.sha256(json.dumps(core, sort_keys=True).encode()).hexdigest()


def _bars_window(ticker: str, entry: str, asof: str, n: int = 15):
    """Last n completed daily bars <= asof, plus since-entry stats."""
    from ta_eval_alpha import e17_screener as e17
    d, _ = e17.fetch_batch_ohlcv([ticker, "SPY"], ent_start(entry),
                                 asof_next(asof), batch_size=2)
    df = d.get(ticker)
    spy = d.get("SPY")
    if df is None or not len(df):
        return None, None
    df = df[df.index.strftime("%Y-%m-%d") <= asof]
    since = df[df.index.strftime("%Y-%m-%d") >= entry]
    bars = [{"d": str(x.date()), "o": round(r.Open, 2), "h": round(r.High, 2),
             "l": round(r.Low, 2), "c": round(r.Close, 2),
             "v": int(r.Volume)} for x, r in df.tail(n).iterrows()]
    spy_ret = None
    if spy is not None and len(spy):
        s = spy[spy.index.strftime("%Y-%m-%d") <= asof]
        if len(s) >= 2:
            spy_ret = round((float(s["Close"].iloc[-1]) /
                             float(s["Close"].iloc[0]) - 1) * 100, 2)
    return {"recent_bars": bars,
            "since_entry": {"high": round(float(since["High"].max()), 2),
                            "low": round(float(since["Low"].min()), 2),
                            "sessions": len(since)},
            "spy_window_return_pct": spy_ret}, df


def ent_start(entry: str) -> str:
    from datetime import date
    y, m, dd = entry.split("-")
    return str(date(int(y), int(m), 1) )
    # noqa


def asof_next(asof: str) -> str:
    from datetime import date, timedelta
    d = date.fromisoformat(asof) + timedelta(days=1)
    return str(d)


def _sec_catalysts(ticker: str, entry: str, asof: str):
    """SEC filings window bounded <= asof (filed-date bounded = PIT)."""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "disco", EV / "discovery.py")
        dm = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(dm)
        evs = dm.sec_catalyst_events(asof, {ticker})
        out = [e for e in (evs.get(ticker) or []) if e.get("filed", "") <= asof]
        return out[-10:]
    except Exception as e:
        return [{"error": f"sec_catalysts_unavailable: {e!r}"[:160]}]


def build_context(ticker: str, pos: dict | None, rec: dict,
                  reqs: list[dict], snap: dict, asof: str,
                  session: str) -> dict:
    """Everything the model is allowed to know — frozen verbatim."""
    bars, df = _bars_window(ticker, snap.get("entry_session") or
                            rec.get("entry_session"), asof)
    ctx = {
        "context_schema": 1, "ticker": ticker, "as_of": asof,
        "frozen_at": _utc(),
        "position_id": f"{ticker}:{snap.get('entry_session')}",
        "entry_snapshot": snap,
        "current_state": {
            "shares": (pos or rec.get("shares_ref") or {}),
            "mark": rec.get("latest_price"),
            "unrealized_pct": rec.get("unrealized_pct"),
            "peak_unrealized_pct": rec.get("peak_unrealized_pct"),
            "drawdown_from_peak_pct": rec.get("drawdown_from_peak_pct"),
            "mae_pct": rec.get("mae_pct"),
            "sessions_held": rec.get("sessions_held"),
            "active_stop": rec.get("stop_ref"),
            "pending_actions": []},
        "success_plan": __import__(
            "alpha_rnd.success_plan", fromlist=["mcf"]).mgmt_context_fields(
            snap.get("success_plan"), snap.get("entry_price"),
            rec.get("latest_price")),
        "triggers": [{"request_id": r.get("request_id"),
                      "family": r.get("trigger_family"),
                      "urgency": r.get("urgency"),
                      "session": r.get("fired_session"),
                      "metric": r.get("value"), "threshold": r.get("threshold"),
                      "reason": r.get("reason")} for r in reqs],
        "price_path": bars,
        "new_information": {"sec_catalysts": _sec_catalysts(
            ticker, snap.get("entry_session") or rec.get("entry_session"),
            asof)},
    }
    ctx["context_hash"] = hashlib.sha256(
        json.dumps({k: ctx[k] for k in ctx if k != "context_hash"},
                   sort_keys=True, default=str).encode()).hexdigest()
    ctx["position_state_hash"] = _fingerprint(pos, reqs)
    return ctx


# ---------------- prompt ----------------

PROMPT = """You are a position-management analyst. WE ALREADY OWN THIS POSITION.
This is NOT a new-entry question.

Given: (a) why we entered (frozen entry thesis/plan), (b) what has happened
since entry, (c) why a reassessment was triggered, and (d) bounded new
information — decide how the EXISTING position should be managed now.

Analyze explicitly:
1. thesis_status: STRENGTHENED|INTACT|WEAKENED|LARGELY_REALIZED|INVALIDATED|UNCERTAIN
2. catalyst_status: PENDING|OCCURRED_POSITIVE|OCCURRED_NEGATIVE|DELAYED|CANCELLED|PRICED_IN|NOT_APPLICABLE|UNKNOWN
3. price_vs_thesis: confirming|extended/outpaced|contradicting|normal_noise|materially_changed_risk_reward
4. remaining upside / 5. current downside / 6. is original risk allowance still appropriate
7. is profit protection justified / 8. should capital stay fully deployed
9. recommended management action — exactly one of:
   HOLD_UNCHANGED | HOLD_AND_TIGHTEN_RISK | PARTIAL_EXIT | FULL_EXIT | REASSESS_LATER

Output STRICT JSON only:
{"ticker":str,"thesis_status":str,"catalyst_status":str,
 "reward_risk_status":str,"price_vs_thesis":str,
 "recommended_action":str,
 "proposed_stop":{"type":str|null,"level":number|null,"rationale":str|null},
 "partial_exit":{"fraction":number|null,"rationale":str|null},
 "next_reassessment":str|null,
 "confidence":"high"|"medium"|"low",
 "reasoning_summary":str,"data_limitations":str}

Rules: every number must be justified by the provided context; propose nothing
that widens the existing authorized downside; if uncertain choose
REASSESS_LATER or HOLD_UNCHANGED with reasoning."""


# ---------------- validation ----------------


def validate_result(t: str, d: dict) -> tuple[dict | None, list[str]]:
    errs = []
    if d.get("recommended_action") not in ACTIONS:
        errs.append("bad recommended_action")
    if d.get("thesis_status") not in THESIS:
        errs.append("bad thesis_status")
    if d.get("catalyst_status") not in CATALYST:
        errs.append("bad catalyst_status")
    if d.get("confidence") not in ("high", "medium", "low"):
        errs.append("bad confidence")
    ps = d.get("proposed_stop") or {}
    if ps.get("level") is not None and not isinstance(ps["level"], (int, float)):
        errs.append("proposed_stop.level not numeric")
    pe = d.get("partial_exit") or {}
    if pe.get("fraction") is not None and not (0 < pe["fraction"] < 1):
        errs.append("partial_exit.fraction must be in (0,1)")
    if errs:
        return None, errs
    out = {k: d.get(k) for k in ("ticker", "thesis_status", "catalyst_status",
                                 "reward_risk_status", "price_vs_thesis",
                                 "recommended_action", "proposed_stop",
                                 "partial_exit", "next_reassessment",
                                 "confidence", "reasoning_summary",
                                 "data_limitations")}
    out["ticker"] = t
    return out, []


# ---------------- assess ----------------


def pending_requests(ticker: str) -> list[dict]:
    d = REQ_DIR_T(ticker)
    if not d.exists():
        return []
    return [r for r in (_j(p) for p in sorted(d.glob("*.json")))
            if r and r.get("status") == mgmt.REQ_STATUS]


def REQ_DIR_T(t):
    return mgmt.REQ_DIR / t


def assess(ticker: str, session: str, asof: str | None = None,
           model_fn=None, state_fn=None) -> dict:
    """One shadow reassessment. Returns a result record (never economics)."""
    asof = asof or session
    st = (state_fn or (lambda: _j(AR / "monitor_state.json", {}) or {}))()
    pos = (st.get("positions") or {}).get(ticker)
    m = mgmt.load_mgmt()
    rec = (m.get("positions") or {}).get(ticker, {})
    reqs = pending_requests(ticker)
    snap = None
    for p in sorted(mgmt.SNAP_DIR.glob(f"{ticker}_*.json")):
        snap = _j(p)
    dec = {"ticker": ticker, "session": session, "as_of": asof,
           "status": None, "created_at": _utc()}
    if not reqs:
        dec.update(status="NO_PENDING_TRIGGER",
                   note="no SHADOW_TRIGGERED request — no reassessment")
        return dec
    if snap is None:
        dec.update(status="FAILED_TERMINAL", reason_code="NO_ENTRY_SNAPSHOT")
        return dec
    ctx = build_context(ticker, pos, rec, reqs, snap, asof, session)
    ctx_p = CTX_DIR / ticker / f"{asof}_{ctx['context_hash'][:12]}.json"
    _atomic(ctx_p, ctx)
    fp = ctx["position_state_hash"]
    dec.update(context_ref=str(ctx_p), context_hash=ctx["context_hash"],
               position_state_hash=fp,
               request_refs=[r["request_id"] for r in reqs],
               trigger_summary=[r.get("trigger_family") for r in reqs])
    fn = model_fn or _default_model
    try:
        raw = fn(ctx)
    except TranslatorInfra as e:
        dec.update(status="RETRY_PENDING" if e.reason not in inf.NON_RETRYABLE
                   else "FAILED_TERMINAL",
                   reason_code=e.reason, raw_error=e.raw[:400],
                   last_error_at=_utc())
        _atomic(_ana_path(ticker, asof), dec)
        mgmt_ev("MGMT_REASSESS_INFRA", ticker, session, e.reason)
        return dec
    except Exception as e:
        dec.update(status="RETRY_PENDING", reason_code="UNKNOWN_MODEL_FAILURE",
                   raw_error=repr(e)[:400], last_error_at=_utc())
        _atomic(_ana_path(ticker, asof), dec)
        return dec
    try:
        d = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
    except Exception as e:
        dec.update(status="RETRY_PENDING",
                   reason_code="MALFORMED_MODEL_OUTPUT",
                   raw_error=(str(raw)[:300]), last_error_at=_utc())
        _atomic(_ana_path(ticker, asof), dec)
        return dec
    val, errs = validate_result(ticker, d)
    if val is None:
        dec.update(status="FAILED_TERMINAL",
                   reason_code="MALFORMED_MODEL_OUTPUT",
                   raw_error=";".join(errs)[:300])
        _atomic(_ana_path(ticker, asof), dec)
        return dec
    # staleness: position could have changed/closed during the call
    st2 = (state_fn or (lambda: _j(AR / "monitor_state.json", {}) or {}))()
    pos2 = (st2.get("positions") or {}).get(ticker)
    if pos2 is None:
        stale = "STALE_POSITION_CLOSED"
    elif _fingerprint(pos2, reqs) != fp:
        stale = "STALE_POSITION_CHANGED"
    else:
        stale = None
    dec.update(status="STALE" if False else ("SUCCESS" if stale is None else stale),
               analysis=val, analyzed_at=_utc(),
               model=MODEL if model_fn is None else "test",
               shadow=True,
               headline="SHADOW RECOMMENDATION ONLY — NO ECONOMIC ACTION TAKEN")
    _atomic(_ana_path(ticker, asof), dec)
    # mark requests consumed
    for r in reqs:
        rp = REQ_DIR_T(ticker) / f"{r['trigger_family']}_{r['fired_session']}.json"
        if rp.exists():
            r2 = _j(rp); r2["status"] = "CONSUMED_BY_SHADOW_ANALYSIS"
            r2["analysis_ref"] = str(_ana_path(ticker, asof))
            _atomic(rp, r2)
    mgmt_ev("MGMT_REASSESS_SHADOW_DONE", ticker, session,
            val["recommended_action"])
    # update mgmt state view
    rec2 = mgmt.load_mgmt()["positions"].get(ticker)
    if rec2 is not None:
        mm = mgmt.load_mgmt()
        rr = mm["positions"][ticker]
        rr["latest_reassessment"] = {"session": session, "as_of": asof,
                                     "status": dec["status"],
                                     "action": val["recommended_action"],
                                     "thesis_status": val["thesis_status"],
                                     "artifact": str(_ana_path(ticker, asof)),
                                     "shadow": True}
        mgmt.save_mgmt(mm)
    return dec


def latest_analysis(ticker: str) -> dict | None:
    d = ANA_DIR / ticker
    if not d.exists():
        return None
    fs = sorted(d.glob("reassess_*.json"))
    return _j(fs[-1]) if fs else None


def work_order(open_tickers: list[str], urgent_only: bool) -> list[str]:
    """Fair ordering: urgent-first; within a class, least-recently-analyzed
    first (None = never analyzed = oldest). Skip tickers whose latest result
    is a terminal/success or a recent rate-limit retry — no backend hammering."""
    urg_rank = {"URGENT": 0, "NORMAL": 1, "LOW": 2}
    cands = []
    for t in open_tickers:
        reqs = pending_requests(t)
        if not reqs:
            continue
        u = min(urg_rank.get(r.get("urgency"), 1) for r in reqs)
        if urgent_only and u != 0:
            continue
        prev = latest_analysis(t)
        if prev and prev.get("status") in ("SUCCESS", "STALE_POSITION_CLOSED",
                                         "STALE_POSITION_CHANGED",
                                         "FAILED_TERMINAL"):
            continue  # frozen result — never rerun
        if prev and prev.get("status") == "RETRY_PENDING" and \
                prev.get("reason_code") == "MODEL_RATE_LIMITED":
            cands.append((u, prev.get("last_error_at") or "9", t, True))
        else:
            cands.append((u, prev.get("analyzed_at") or "9" if prev else "0",
                          t, False))
    # rate-limited retries go last within their urgency class
    cands.sort(key=lambda x: (x[0], x[3], x[1], x[2]))
    return [c[2] for c in cands]


def run_bounded(session: str, urgent_only: bool, limit: int = 2) -> list[dict]:
    """Bounded management work for one scheduler invocation."""
    st = _j(AR / "monitor_state.json", {}) or {}
    out = []
    for t in work_order(list((st.get("positions") or {})), urgent_only):
        if len(out) >= limit:
            break
        d = assess(t, session)
        out.append(d)
        try:  # Phase D shadow validation — never economic
            from alpha_rnd import mgmt_validate
            if d.get("status") == "SUCCESS":
                mgmt_validate.validate(t, dec=d)
        except Exception:
            pass
    return out


def _default_model(ctx: dict) -> str:
    brief = {"position_management_request": PROMPT, "context": ctx}
    return call_bridge({"model": MODEL, "temperature": 0,
                        "messages": [{"role": "user",
                                      "content": json.dumps(brief,
                                                            default=str)}]})


def _ana_path(ticker: str, asof: str) -> Path:
    return ANA_DIR / ticker / f"reassess_{asof}.json"


def mgmt_ev(kind: str, t: str, s: str, detail: str) -> None:
    with mgmt.MEVENTS.open("a") as f:
        f.write(json.dumps({"ts": _utc(), "kind": kind, "ticker": t,
                            "session": s, "detail": detail}) + "\n")


def main() -> None:
    a = sys.argv
    if len(a) > 1 and a[1] == "run" and "--ticker" in a:
        t = a[a.index("--ticker") + 1]
        asof = a[a.index("--as-of") + 1] if "--as-of" in a else None
        sess = asof or __import__("alpha_rnd.daily_scheduler",
                                  fromlist=["last_completed_session"]
                                  ).last_completed_session()
        print(json.dumps(assess(t, sess, asof=asof), indent=1, default=str))
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
