#!/usr/bin/env python3
"""Post-entry adaptive management — Phase B, SHADOW ONLY.

Observes open positions, keeps immutable entry snapshots, tracks the price
path since entry, and fires deterministic "think again" triggers.

INVARIANT: this module NEVER writes economic state. It cannot create orders,
change stops, or touch cash/realized/shares/executed. A trigger produces at
most a SHADOW reassessment request artifact — never an action, never a model
call.

  python -m alpha_rnd.mgmt status        # read-only per-position view
  python -m alpha_rnd.mgmt backfill      # create missing snapshots (PBF etc.)
  python -m alpha_rnd.mgmt replay        # historical trigger replay (audit)
"""
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AR = ROOT / "alpha_rnd"
EV = ROOT / "evaluations" / "alpha_rnd_v1"
SNAP_DIR = EV / "entry_snapshots"
REQ_DIR = EV / "management_requests"
STATE = EV / "management_state.json"
POLICY_P = AR / "management_policy.json"
MEVENTS = AR / "management_events.jsonl"
SNAP_SCHEMA = 1
REQ_STATUS = "SHADOW_TRIGGERED"

# ---------------- policy ----------------


def policy() -> dict:
    return json.loads(POLICY_P.read_text())


# ---------------- small io helpers ----------------


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _j(p: Path, default=None):
    try:
        return json.loads(p.read_text())
    except Exception:
        return default


def _atomic(p: Path, doc) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, indent=1, default=str, sort_keys=True))
    tmp.replace(p)


def _mev(rec: dict) -> None:
    with MEVENTS.open("a") as f:
        f.write(json.dumps({"ts": _utc(), **rec}, sort_keys=True) + "\n")


# ---------------- immutable entry snapshot ----------------


def snapshot_path(ticker: str, entry_session: str) -> Path:
    return SNAP_DIR / f"{ticker}_{entry_session}.json"


def snapshot_exists(ticker: str, entry_session: str) -> bool:
    return snapshot_path(ticker, entry_session).exists()


def create_snapshot(ticker: str, entry_session: str, *, watch: dict | None,
                    pos: dict, intent: dict | None,
                    artifact_ref: str | None, extra: dict | None = None,
                    missing: list[str] | None = None) -> Path | None:
    """Write-once: never overwrite an existing snapshot."""
    p = snapshot_path(ticker, entry_session)
    if p.exists():
        return None
    doc = {
        "schema": SNAP_SCHEMA, "ticker": ticker,
        "position_id": f"{ticker}:{entry_session}",
        "entry_session": entry_session,
        "created_at": _utc(),
        "entry_price": pos.get("fill"),
        "initial_shares": pos.get("shares"),
        "artifact_ref": artifact_ref or (watch or {}).get("artifact"),
        "watch_revision": (watch or {}).get("v"),
        "watch_trigger": (watch or {}).get("trigger"),
        "watch_trigger_type": (watch or {}).get("trigger_type"),
        "thesis": ((intent or {}).get("thesis")
                   or (intent or {}).get("summary")),
        "bear_case": ((intent or {}).get("bear_case")
                      or (intent or {}).get("invalidation")),
        "catalysts": ((intent or {}).get("catalysts")
                      or (intent or {}).get("reevaluation")),
        "risk_plan": {"invalidation": (intent or pos).get("invalidation")
                      if isinstance((intent or pos).get("invalidation"), str)
                      else (watch or pos).get("invalidation"),
                      "stop_level": (intent or {}).get("stop_level"),
                      "stop_rule": pos.get("stop_rule")},
        "horizon": (intent or pos).get("horizon"),
        "reevaluation": ((watch or {}).get("reeval")
                         or (intent or {}).get("reevaluation")),
        "artifact_sha256": _art_sha(artifact_ref or (watch or {}).get("artifact")),
        "missing_context": missing or [],
        **(extra or {}),
    }
    _atomic(p, doc)
    return p


def _art_sha(ref: str | None) -> str | None:
    if not ref:
        return None
    p = EV / "case_artifacts" / ref
    if not p.exists():
        return None
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _latest_intent(ticker: str) -> dict | None:
    best = None
    for p in sorted(EV.glob("publication_intents_*.json")):
        d = _j(p, {}) or {}
        i = (d.get("intents") or {}).get(ticker)
        if i is not None:
            best = i
    return best


def backfill_missing(st: dict, wl: dict) -> list[str]:
    """Create snapshots for open positions lacking one (e.g. seeded PBF).
    Records missing context honestly — never fabricates."""
    made = []
    wl_pos = {p["ticker"]: p for p in wl.get("open_positions", [])}
    wl_watch = {w["ticker"]: w for w in wl.get("watches", [])}
    for t, pos in st.get("positions", {}).items():
        sess = pos.get("entry_session") or _guess_entry_session(t)
        if not sess:
            continue
        if snapshot_exists(t, sess):
            continue
        spec = wl_pos.get(t) or wl_watch.get(t) or {}
        intent = _latest_intent(t)
        missing = []
        if intent is None:
            missing.append("publication intent")
        if not spec.get("artifact") and not (intent or {}).get("artifact"):
            missing.append("artifact_ref")
        if not pos.get("cost"):
            missing.append("cost_basis (legacy/seeded)")
        e = create_snapshot(t, sess, watch=spec, pos=pos, intent=intent,
                            artifact_ref=spec.get("artifact")
                            or (intent or {}).get("artifact"),
                            missing=missing)
        if e:
            made.append(str(e.name))
            _mev({"kind": "ENTRY_SNAPSHOT_BACKFILLED", "ticker": t,
                  "session": sess, "missing": missing})
    return made


def _guess_entry_session(ticker: str) -> str | None:
    """Seeded positions: entry session from the ledger's PAPER_FILL row."""
    led = EV / "alpha_paper_ledger.jsonl"
    if led.exists():
        for l in led.read_text().splitlines():
            try:
                r = json.loads(l)
            except Exception:
                continue
            if r.get("ticker") == ticker and r.get("type") == "PAPER_FILL":
                s = r.get("session") or r.get("entry_session")
                if s:
                    return s
    return None


# ---------------- management state ----------------


def load_mgmt() -> dict:
    return _j(STATE, {"positions": {}}) or {"positions": {}}


def save_mgmt(m: dict) -> None:
    _atomic(STATE, m)


def _pos_rec(m: dict, ticker: str) -> dict:
    return m.setdefault("positions", {}).setdefault(
        ticker, {"ticker": ticker, "triggers": {}})


def _sess_count(dates: list[str], entry: str) -> int:
    return sum(1 for d in dates if d >= entry)


# ---------------- metrics ----------------

def update_metrics(rec: dict, pos: dict, df, session: str,
                   intraday_df=None) -> dict:
    """Completed-session bars are canonical; intraday bars update peak/trough
    while the session is live. Basis recorded per metric — never mixed."""
    fill = pos["fill"]
    d = df[df.index.strftime("%Y-%m-%d") >= (rec.get("entry_session") or "9999")]
    hcol = d["High"] if "High" in d else d["Close"]
    lcol = d["Low"] if "Low" in d else d["Close"]
    hi = float(hcol.max()) if len(d) else fill
    lo = float(lcol.min()) if len(d) else fill
    dates = [str(x.date()) for x in d.index]
    peak_basis = "close_bars"
    if intraday_df is not None and len(intraday_df):
        ihi, ilo = float(intraday_df["High"].max()), float(intraday_df["Low"].min())
        if ihi > hi:
            hi = ihi
            peak_basis = "close+intraday"
        lo = min(lo, ilo)
    mark = pos.get("mark") or (float(df["Close"].iloc[-1]) if len(df) else fill)
    unr = round((mark / fill - 1) * 100, 2)
    peak_unr = round((hi / fill - 1) * 100, 2)
    mae = round((lo / fill - 1) * 100, 2)
    rec.update({
        "entry_price": fill,
        "latest_price": mark,
        "latest_session": session,
        "high_since_entry": round(hi, 4),
        "low_since_entry": round(lo, 4),
        "peak_unrealized_pct": peak_unr,
        "unrealized_pct": unr,
        "drawdown_from_peak_pct": round(peak_unr - unr, 2),
        "mae_pct": mae,
        "sessions_held": _sess_count(dates, rec.get("entry_session") or session),
        "metrics_basis": peak_basis,
        "metrics_at": _utc(),
    })
    return rec


# ---------------- triggers ----------------

DATE_RX = re.compile(r"20\d\d-\d\d-\d\d")


def _r_context(snap: dict | None, fill: float) -> dict:
    """Initial risk unit (1R) from the frozen snapshot's machine-actionable
    stop. Never fabricates a risk distance."""
    rp = (snap or {}).get("risk_plan") or {}
    sr = rp.get("stop_rule") or {}
    lv = sr.get("level") or rp.get("stop_level")
    try:
        lv = float(lv)
    except (TypeError, ValueError):
        lv = None
    if not fill or lv is None or lv >= fill:
        return {"r_available": False, "reason": "R_CONTEXT_UNAVAILABLE"}
    r_abs = fill - lv
    return {"r_available": True, "stop_level": lv,
            "r_abs": round(r_abs, 4),
            "r_pct": round(r_abs / fill * 100, 3)}


def _horizon_date(snap: dict | None) -> str | None:
    """First explicit date in the reevaluation/horizon text — machine
    checkpoint; descriptive horizons with no date yield None."""
    for k in ("reevaluation", "horizon"):
        txt = (snap or {}).get(k) or ""
        m = DATE_RX.search(txt)
        if m:
            return m.group(0)
    return None


def _urgent(fam: str) -> str:
    return {"ADVERSE_ACCELERATION": "URGENT",
            "PEAK_GIVEBACK": "NORMAL",
            "APPRECIATION": "NORMAL",
            "HORIZON_REVIEW": "NORMAL",
            "CATALYST_MATERIALIZATION": "NORMAL",
            "R_CONTEXT_UNAVAILABLE": "LOW"}[fam]


def evaluate(ticker: str, rec: dict, snap: dict | None,
             pol: dict, session: str) -> list[dict]:
    """Pure trigger evaluation. Returns candidate trigger events (not yet
    debounced). A trigger is a request to think again — never an action."""
    out = []
    u = rec.get("unrealized_pct") or 0.0
    pk = rec.get("peak_unrealized_pct") or 0.0
    mae = rec.get("mae_pct") or 0.0
    dd = rec.get("drawdown_from_peak_pct") or 0.0
    fill = rec.get("entry_price") or 0.0
    tp = pol["triggers"]
    r = _r_context(snap, fill)
    r_pct = r.get("r_pct")

    if r["r_available"]:
        ur = u / r_pct
        pkr = pk / r_pct
        maer = mae / r_pct
        # A. appreciation — favorable excursion reaches configured R multiple
        a = tp["appreciation"]
        if ur >= a["r_multiple"]:
            out.append({"family": "APPRECIATION", "value": round(ur, 2),
                        "threshold": a["r_multiple"],
                        "reason": f"favorable excursion {ur:.2f}R "
                                  f"(unrealized {u}% vs 1R={r_pct}%)"})
        # B. peak giveback — a real winner (peak >= min_peak_r) surrendering
        #    a configured fraction of its favorable excursion
        g = tp["peak_giveback"]
        if pkr >= g["min_peak_r"] and pk > 0 and \
                dd / pk >= g["giveback_fraction"]:
            out.append({"family": "PEAK_GIVEBACK", "value": round(dd, 2),
                        "threshold": round(g["giveback_fraction"] * pk, 2),
                        "reason": f"peak {pkr:.2f}R, surrendered {dd}pp "
                                  f"({round(dd / pk * 100)}% of excursion)"})
        # C. adverse acceleration — MAE beyond configured R multiple
        c = tp["adverse_acceleration"]
        if maer <= -c["mae_r_multiple"]:
            out.append({"family": "ADVERSE_ACCELERATION", "value": round(maer, 2),
                        "threshold": -c["mae_r_multiple"],
                        "reason": f"MAE {maer:.2f}R beyond -{c['mae_r_multiple']}R "
                                  f"(1R={r_pct}%)"})
    else:
        out.append({"family": "R_CONTEXT_UNAVAILABLE",
                    "value": None, "threshold": None,
                    "reason": "no machine-actionable original stop in "
                              "snapshot; price triggers suppressed",
                    "observational": True})

    # D. horizon review — parsed checkpoint date reached
    hd = _horizon_date(snap)
    if hd and session >= hd:
        out.append({"family": "HORIZON_REVIEW", "value": session,
                    "threshold": hd,
                    "reason": f"reeval checkpoint {hd} reached at {session}"})

    # E. catalyst — schema only, disabled (needs news daemon per Phase A)
    if tp["catalyst"]["enabled"]:
        pass

    for ev in out:
        ev["urgency"] = _urgent(ev["family"])
    return out


# ---------------- debounce ----------------


def _fire(ticker: str, rec: dict, ev: dict, pol: dict, session: str) -> bool:
    """Edge-trigger + cooldown + hysteresis re-arm. Persisted in rec['triggers']."""
    fam = ev["family"]
    st = rec.setdefault("triggers", {}).setdefault(fam, {})
    cool = pol["debounce"]["cooldown_sessions"]
    hyst = pol["debounce"]["hysteresis_fraction"]
    armed_val = st.get("armed_below")
    v = ev["value"]
    th = ev["threshold"]
    is_date = fam == "HORIZON_REVIEW"
    if is_date:
        # one-shot per checkpoint value
        if st.get("fired_value") == v:
            return False
        st["fired_value"] = v
    else:
        numeric = isinstance(v, (int, float)) and isinstance(th, (int, float))
        if numeric:
            # re-arm only after value retreats by hysteresis band
            if armed_val is not None:
                band = abs(th) * hyst or 1.0
                recovered = (v < th - band) if fam != "ADVERSE_ACCELERATION" \
                    else (v > th + band)
                if not recovered:
                    return False
                st.pop("armed_below", None)
            if st.get("active"):
                return False
            if st.get("cooldown_until") and session <= st["cooldown_until"]:
                return False
        else:
            if st.get("fired_value") == v:
                return False
    st["fired_at"] = session
    st["last_value"] = v
    if not is_date and isinstance(v, (int, float)):
        st["active"] = True
        st["armed_below"] = v
        st["cooldown_sessions"] = cool
    req_id = f"{ticker}:{fam}:{session}:{round(v, 2) if isinstance(v, float) else v}"
    req = {"request_id": req_id, "ticker": ticker,
           "position_id": rec.get("entry_ref"),
           "trigger_family": fam, "urgency": ev["urgency"],
           "fired_session": session, "fired_at": _utc(),
           "value": v, "threshold": ev.get("threshold"),
           "reason": ev["reason"],
           "metrics": {k: rec.get(k) for k in
                       ("entry_price", "latest_price", "unrealized_pct",
                        "peak_unrealized_pct", "drawdown_from_peak_pct",
                        "mae_pct", "sessions_held", "metrics_basis")},
           "entry_snapshot": str(snapshot_path(ticker, rec.get("entry_session") or "")),
           "risk_plan_ref": (rec.get("stop_ref")),
           "policy_version": pol.get("version"),
           "status": REQ_STATUS,
           "note": "shadow request: think again — NOT an action, NOT a model call"}
    _atomic(REQ_DIR / ticker / f"{fam}_{session}.json", req)
    st["last_request"] = req_id
    _mev({"kind": "REASSESSMENT_TRIGGERED_SHADOW", "ticker": ticker,
          "family": fam, "urgency": ev["urgency"], "session": session,
          "reason": ev["reason"], "request_id": req_id})
    rec["last_trigger"] = {"family": fam, "session": session,
                           "reason": ev["reason"], "urgency": ev["urgency"]}
    return True


# cooldown via session-count difference: recompute at evaluate-time
def _cooldown_ok(st: dict, fired_sess: str, cur_sess: str,
                 daily_sessions: list[str], cool: int) -> bool:
    idx = {d: i for i, d in enumerate(daily_sessions)}
    if fired_sess not in idx or cur_sess not in idx:
        return cur_sess > fired_sess
    return idx[cur_sess] - idx[fired_sess] >= cool


# ---------------- observe (monitor hook) ----------------


def observe(st: dict, wl: dict, daily: dict, session: str,
            intraday: dict | None = None) -> dict:
    """Called inside the monitor's locked pass, AFTER all safety logic.
    Read economics; write ONLY mgmt state/snapshots/request artifacts.
    Any exception is swallowed by the caller — triggers never block exits."""
    pol = policy()
    if pol.get("mode") != "shadow":
        return {"mode": pol.get("mode"), "skipped": True}
    m = load_mgmt()
    made = backfill_missing(st, wl)
    wl_pos = {p["ticker"]: p for p in wl.get("open_positions", [])}
    dates_idx = sorted({str(x.date()) for df in daily.values()
                        for x in df.index})
    fired = []
    for t in list(st.get("positions", {})):
        pos = st["positions"][t]
        df = daily.get(t)
        if df is None or not len(df):
            continue
        rec = _pos_rec(m, t)
        snap_path = None
        for cand in sorted(SNAP_DIR.glob(f"{t}_*.json")):
            snap_path = cand
        snap = _j(snap_path, None) if snap_path else None
        rec["entry_session"] = rec.get("entry_session") or pos.get("entry_session") \
            or (snap or {}).get("entry_session") or _guess_entry_session(t)
        rec["entry_ref"] = f"{t}:{rec['entry_session']}" if rec.get("entry_session") else None
        rec["shares_ref"] = pos.get("shares")          # reference only
        rec["horizon"] = (snap or {}).get("horizon") or pos.get("horizon")
        rec["horizon_checkpoint"] = _horizon_date(snap)
        rec["original_stop"] = (snap or {}).get("risk_plan") or pos.get("stop_rule")
        rec["stop_ref"] = (wl_pos.get(t) or {}).get("invalidation") or pos.get("stop_rule")
        rec["snapshot"] = str(snap_path) if snap_path else None
        update_metrics(rec, pos, df, session,
                       (intraday or {}).get(t))
        for ev in evaluate(t, rec, snap, pol, session):
            fam = ev["family"]
            if fam == "R_CONTEXT_UNAVAILABLE":
                rec["r_context"] = "R_CONTEXT_UNAVAILABLE"
                continue
            tg = rec["triggers"].get(fam) or {}
            if fam != "HORIZON_REVIEW" and tg.get("fired_at") and \
                    not _cooldown_ok(tg, tg["fired_at"], session, dates_idx,
                                     pol["debounce"]["cooldown_sessions"]):
                continue
            if _fire(t, rec, ev, pol, session):
                fired.append(f"{t}:{fam}")
        rec["status"] = "SHADOW_OBSERVING"
    # closed-position cleanup: keep history, mark inactive
    for t in list(m["positions"]):
        if t not in st.get("positions", {}):
            m["positions"][t]["status"] = "CLOSED"
    m["last_observe"] = {"session": session, "at": _utc(),
                         "fired": fired, "backfilled": made}
    save_mgmt(m)
    return {"fired": fired, "backfilled": made}


# ---------------- status ----------------


def status() -> str:
    m = load_mgmt()
    lines = ["ALPHA POST-ENTRY MANAGEMENT (shadow) — observational only", ""]
    if not m.get("positions"):
        return "\n".join(lines + ["(no tracked positions)"])
    for t, r in sorted(m["positions"].items()):
        if r.get("status") == "CLOSED":
            continue
        lt = r.get("last_trigger") or {}
        ra = r.get("latest_reassessment") or {}
        lines += [
            f"{t}  entry {r.get('entry_session')} @{r.get('entry_price')}   "
            f"mark {r.get('latest_price')} ({r.get('latest_session')})",
            f"  unrealized {r.get('unrealized_pct')}%   "
            f"peak {r.get('peak_unrealized_pct')}%   "
            f"drawdown {r.get('drawdown_from_peak_pct')}pp   "
            f"MAE {r.get('mae_pct')}%   held {r.get('sessions_held')} sessions   "
            f"R: {r.get('r_context', 'available')}",
            f"  original stop {json.dumps((r.get('original_stop') or {}).get('stop_rule') or r.get('original_stop'))[:80]}",
            f"  active stop {json.dumps(r.get('stop_ref'))[:80]}",
            f"  horizon: {str(r.get('horizon'))[:70]}   checkpoint {r.get('horizon_checkpoint')}",
            f"  last trigger: {lt.get('family') or 'none'} {lt.get('session') or ''} "
            f"{lt.get('reason') or ''} ({lt.get('urgency') or ''})",
            f"  pending shadow reassessment: "
            f"{'YES' if any((REQ_DIR / t).glob('*') if (REQ_DIR / t).exists() else False for _ in [0]) else 'no'}",
        ]
        if ra:
            ana = _j(Path(ra["artifact"]), {}) if ra.get("artifact") else {}
            an = (ana or {}).get("analysis") or {}
            ps = an.get("proposed_stop") or {}
            pe = an.get("partial_exit") or {}
            lines += [
                f"  === SHADOW REASSESSMENT — NOT AN ECONOMIC ACTION ===",
                f"  status {ra.get('status')}  analyzed {ra.get('as_of')}  "
                f"thesis {ra.get('thesis_status')}",
                f"  shadow recommendation: {ra.get('action')}   "
                f"(proposal only — nothing executed, nothing pending)",
                f"  proposed stop {json.dumps(ps.get('level'))} "
                f"({str(ps.get('type'))})   "
                f"proposed partial {json.dumps(pe.get('fraction'))}",
                f"  next reassessment: {str(an.get('next_reassessment'))[:70]}",
                f"  failure/retry: {ra.get('status') if 'RETRY' in str(ra.get('status')) or 'FAILED' in str(ra.get('status')) else 'none'}",
                f"  stale: {'YES — ' + ra.get('status') if str(ra.get('status','')).startswith('STALE') else 'no'}",
            ]
        vi_dir = Path(__file__).resolve().parents[1] / "evaluations" / \
            "alpha_rnd_v1" / "management_intents" / t
        if vi_dir.exists():
            vi = _j(sorted(vi_dir.glob("*.json"))[-1], {})
            lines += [
                f"  === SHADOW VALIDATION — NOT AN ECONOMIC ACTION ===",
                f"  validator: {vi.get('status')}   "
                f"validated_action: {vi.get('validated_action')}   "
                f"action_id: {vi.get('action_id')}",
                f"  exit qty {vi.get('normalized_exit_quantity')} -> "
                f"remaining {vi.get('remaining_quantity')}   "
                f"risk rule {json.dumps(vi.get('proposed_risk_rule'))[:70]}",
                f"  reasons: {str(vi.get('validation_reasons'))[:80]}",
                f"  rejections: {str(vi.get('rejection_reasons'))[:80]}",
                f"  ECONOMIC STATE: NO ORDER, NO STOP CHANGE, NO EXECUTION",
            ]
        lines += [""]
    return "\n".join(lines)


# ---------------- historical replay ----------------


def replay() -> str:
    """Run the same trigger logic over the five closed positions' daily bars.
    Audit only — proves the engine would have created 'think again'
    opportunities; says nothing about what a model would decide."""
    import pandas as pd  # noqa
    from ta_eval_alpha import e17_screener as e17
    pol = policy()
    # (entry_session, fill, exit_session, original stop level)
    hist = {"ACN": ("2026-10-02", 205.0, "2026-10-07", 194.0),
            "APPS": ("2026-10-02", 11.30, "2026-10-07", 10.42),
            "PGEN": ("2026-10-05", 8.20, "2026-10-06", 7.75),
            "TWST": ("2026-10-06", 209.55, "2026-10-12", 164.0),
            "SDGR": ("2026-10-06", 31.00, "2026-10-13", 27.29)}
    lines = []
    for t, (ent, fill, exit_, stop) in hist.items():
        snap = {"risk_plan": {"stop_rule": {"type": "close_below",
                                            "level": stop}}}
        d, _ = e17.fetch_batch_ohlcv([t], "2026-09-15", "2026-10-16",
                                     batch_size=1)
        df = d.get(t)
        if df is None:
            lines.append(f"{t}: DATA_UNAVAILABLE")
            continue
        first = None
        for i in range(len(df)):
            sess = str(df.index[i].date())
            if sess <= ent or sess > exit_:
                continue
            sub = df[(df.index >= df.index[0]) & (df.index <= df.index[i])]
            sub = sub[sub.index.strftime("%Y-%m-%d") >= ent]
            if not len(sub):
                continue
            hi, lo = float(sub["High"].max()), float(sub["Low"].min())
            c = float(df["Close"].iloc[i])
            rec = {"entry_price": fill, "entry_session": ent,
                   "unrealized_pct": round((c / fill - 1) * 100, 2),
                   "peak_unrealized_pct": round((hi / fill - 1) * 100, 2),
                   "drawdown_from_peak_pct": round((hi - c) / fill * 100, 2),
                   "mae_pct": round((lo / fill - 1) * 100, 2)}
            evs = [e for e in evaluate(t, rec, snap, pol, sess)
                   if e["family"] != "R_CONTEXT_UNAVAILABLE"]
            for ev in evs:
                if first is None:
                    first = (sess, ev["family"], ev["value"],
                             ev["threshold"], ev["reason"],
                             rec["peak_unrealized_pct"])
        if first:
            sess, fam, v, th, why, pk = first
            days = len([x for x in df.index
                        if ent < str(x.date()) <= sess])
            metric = "R" if isinstance(v, float) and fam != "HORIZON_REVIEW" \
                else ""
            lines.append(f"{t}: first trigger {fam} on {sess} "
                         f"(trigger metric {v}{metric} vs threshold {th}{metric}; "
                         f"peak {pk}%) — {why}; exit {exit_} "
                         f"({days} sessions of runway)")
        else:
            lines.append(f"{t}: no trigger before exit {exit_}")
    return "\n".join(lines)


def main() -> None:
    arg = sys.argv[1] if len(sys.argv) > 1 else "status"
    if arg == "status":
        print(status())
    elif arg == "backfill":
        st = _j(AR / "monitor_state.json", {}) or {}
        wl = _j(AR / "live_watchlist.json", {}) or {}
        print(backfill_missing(st, wl))
    elif arg == "replay":
        print(replay())
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
