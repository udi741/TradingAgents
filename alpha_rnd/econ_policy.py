#!/usr/bin/env python3
"""Policy-derived economic construction (POLICY_DERIVED number source).

The AI authors investment JUDGMENT (direction, thesis, evidence, catalysts,
risks). When that judgment is constructive but the authored economics are
missing, unbound, or incoherent, this module constructs a complete contract
from predeclared, versioned strategy rules evaluated against market data
available at the decision timestamp.

Hard rules:
- every numeric term is tagged SOURCE_AUTHORED (bound verbatim to the
  research text) or POLICY_DERIVED (computed by this module); a policy
  number can never masquerade as authored;
- policy numbers are exempt from the validator's source-binding check but
  must pass every other fail-closed gate (geometry, stop, sizing,
  success plan);
- nothing is invented: insufficient market data or a judgment that does
  not support an entry style yields an explicit NON_EXECUTABLE outcome;
- uses ONLY data at/before the artifact's decision_session (no lookahead).

Policy constants reuse values already declared elsewhere in the framework;
they are not tuned against any observed outcome.
"""
from __future__ import annotations

POLICY_VERSION = 1

RISK_BUDGET_FRAC = 0.01        # decision.permissible_size default
COST_BPS = 0.001               # monitor.COST_BPS
SLIPPAGE_BPS = 0.0005          # entry_shadow fill slippage
ATR_PERIOD = 14
ATR_STOP_MULT = 1.5            # entry_shadow B_confirmed stop rule
TARGET_R = 2.0                 # entry_shadow B_confirmed target rule
GAP_GUARD_PCT = 0.03           # entry_shadow gap guard
CONFIRM_WINDOW_SESSIONS = 5    # entry_shadow confirmation window
TIME_EXIT_SESSIONS = 20        # entry_shadow time exit

CONSTRUCTIVE = ("Buy", "Overweight")

# Ambiguity codes that block construction: anything not contract-resolvable
# is a judgment-level uncertainty, not a numeric defect.
from alpha_rnd.econ_contract import RESOLVABLE_AMBIGUITY_TYPES


def _f(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v and v > 0 else None


def _bound(v, src_nums: set) -> bool:
    """Number is present in the source text (same tolerance as the validator)."""
    return v is not None and any(
        abs(v - s) <= max(0.005 * abs(s), 0.01) for s in src_nums)


def _zone(e):
    z = (e or {}).get("zone")
    if isinstance(z, (list, tuple)) and len(z) == 2:
        lo, hi = _f(z[0]), _f(z[1])
        if lo and hi and lo < hi:
            return [lo, hi]
    return None


def _trig(e):
    return _f((e or {}).get("trigger_level") or (e or {}).get("level"))


def eligible(intent: dict, artifact: dict) -> tuple[bool, str]:
    """Constructive LONG judgment whose failure is economic, not directional.

    Requires a constructive signal AND a constructive intent classification
    (or an authored LONG contract), no unresolved judgment-level ambiguity,
    and no authored decision contradicting LONG."""
    if artifact.get("signal") not in CONSTRUCTIVE:
        return False, "signal not constructive"
    ec = intent.get("economic_authority") or {}
    cls = intent.get("classification")
    dec_dir = str((intent.get("decision") or {}).get("direction") or "")
    authored_long = str(ec.get("direction") or "").upper() == "LONG"
    if cls not in ("ACTIONABLE_NOW", "WATCH_FOR_ENTRY") and not authored_long:
        return False, f"not constructive class {cls}"
    if dec_dir and dec_dir != "LONG":
        return False, f"authored decision {dec_dir}"
    if intent.get("ambiguity"):
        return False, "untyped ambiguity"
    for a in intent.get("ambiguities") or []:
        t = str((a or {}).get("type") or "").upper()
        if t and t not in RESOLVABLE_AMBIGUITY_TYPES:
            return False, f"blocking ambiguity {t}"
    return True, "ok"


def atr(bars, period: int = ATR_PERIOD):
    """Mean true range over the last `period` rows of daily bars.
    bars: sequence of (high, low, close) or a DataFrame with High/Low/Close.
    Returns (atr, ref_close) or (None, None) when data is insufficient."""
    if hasattr(bars, "columns"):
        try:
            h = [float(x) for x in bars["High"]]
            l = [float(x) for x in bars["Low"]]
            c = [float(x) for x in bars["Close"]]
        except Exception:
            return None, None
    else:
        rows = list(bars or [])
        try:
            h = [float(r[0]) for r in rows]
            l = [float(r[1]) for r in rows]
            c = [float(r[2]) for r in rows]
        except Exception:
            return None, None
    n = len(c)
    if n < period + 1:
        return None, (c[-1] if n else None)
    trs = []
    for i in range(n - period, n):
        trs.append(max(h[i] - l[i], abs(h[i] - c[i - 1]),
                       abs(l[i] - c[i - 1])))
    return sum(trs) / period, c[-1]


def _fetch_bars(ticker: str, session: str):
    """Decision-time bars: daily history ending AT `session` (inclusive —
    the decision session is a completed session when contracts are built).
    Never returns data after `session`."""
    try:
        import datetime as _dt
        import yfinance as yf
        end = (_dt.date.fromisoformat(session)
               + _dt.timedelta(days=1)).isoformat()
        start = (_dt.date.fromisoformat(session)
                 - _dt.timedelta(days=120)).isoformat()
        df = yf.download(ticker, start=start, end=end, progress=False,
                         auto_adjust=True)
        if df is None or df.empty:
            return None
        if isinstance(df.columns, __import__("pandas").MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.dropna()
        return df if {"High", "Low", "Close"} <= set(df.columns) else None
    except Exception:
        return None


def construct(intent: dict, artifact: dict, src_nums: set,
              bars=None) -> tuple[dict | None, dict, str]:
    """Build a policy contract for a constructive LONG judgment.

    Returns (contract, provenance, reason). contract=None with a reason
    when construction is impossible — an explicit non-executable outcome,
    never a partially-nulled record counted as success.

    provenance maps contract field paths -> SOURCE_AUTHORED | POLICY_DERIVED.
    """
    entry0 = ((intent.get("economic_authority") or {}).get("entry") or {})
    azone, atrig = _zone(entry0), _trig(entry0)
    stop0 = _f(((intent.get("economic_authority") or {})
                .get("stop") or {}).get("level"))
    obj0 = (intent.get("economic_authority") or {}).get("objective") or {}
    tgt0 = _f(obj0.get("target"))
    if tgt0 is None and isinstance(obj0.get("base_case_value_range"),
                                   (list, tuple)):
        tgt0 = _f(obj0["base_case_value_range"][1]
                  if len(obj0["base_case_value_range"]) == 2 else None)

    if bars is None:
        bars = _fetch_bars(artifact.get("ticker"),
                           artifact.get("decision_session") or "")
    a, ref = atr(bars)
    if ref is None:
        return None, {}, "no decision-time market data"
    if a is None:
        return None, {}, "insufficient bars for ATR policy"

    prov = {}
    # --- entry anchor --------------------------------------------------
    if azone and all(_bound(z, src_nums) for z in azone):
        entry = {"mode": "LIMIT_ZONE", "zone": azone}
        prov["entry"] = "SOURCE_AUTHORED"
        entry_ref = azone[1]
    elif atrig and _bound(atrig, src_nums):
        mode = entry0.get("mode")
        entry = {"mode": mode if mode in ("CONDITIONAL", "STOP_ENTRY")
                 else "CONDITIONAL",
                 "trigger_level": atrig}
        if entry0.get("condition"):
            entry["condition"] = entry0["condition"]
        prov["entry"] = "SOURCE_AUTHORED"
        entry_ref = atrig
    else:
        # No usable authored level: the predeclared continuation policy —
        # enter only if a completed session confirms above the decision
        # close, at the next eligible open, inside the confirm window.
        entry = {"mode": "CONDITIONAL", "trigger_level": ref,
                 "condition": "policy: confirmed close above decision close"}
        prov["entry"] = "POLICY_DERIVED"
        prov["entry.trigger_level"] = "POLICY_DERIVED"
        entry_ref = ref
    if entry["mode"] in ("CONDITIONAL", "STOP_ENTRY"):
        entry["max_gap_pct"] = GAP_GUARD_PCT
        entry["confirm_within_sessions"] = CONFIRM_WINDOW_SESSIONS
        prov["entry.max_gap_pct"] = "POLICY_DERIVED"
        prov["entry.confirm_within_sessions"] = "POLICY_DERIVED"
    # --- stop -----------------------------------------------------------
    s0 = (intent.get("economic_authority") or {}).get("stop") or {}
    if stop0 and _bound(stop0, src_nums) and stop0 < entry_ref \
            and s0.get("type") in ("close_below", "intraday_stop",
                                   "price_below"):
        stop = {"type": s0["type"], "level": stop0,
                "label": s0.get("label") or f"authored stop {stop0}"}
        prov["stop.level"] = "SOURCE_AUTHORED"
    else:
        s = round(entry_ref - ATR_STOP_MULT * a, 4)
        if s <= 0:
            return None, {}, "policy stop nonpositive"
        stop = {"type": "intraday_stop", "level": s,
                "label": f"policy stop entry-1.5xATR({round(a, 2)})"}
        prov["stop.level"] = "POLICY_DERIVED"
    stop_lvl = stop["level"]
    # --- objective ------------------------------------------------------
    risk = entry_ref - stop_lvl
    if tgt0 and _bound(tgt0, src_nums) and tgt0 > entry_ref:
        tgt = tgt0
        prov["objective.target"] = "SOURCE_AUTHORED"
    else:
        tgt = round(entry_ref + TARGET_R * risk, 4)
        prov["objective.target"] = "POLICY_DERIVED"
    objective = {"target": tgt,
                 "base_case_value_range": [tgt, tgt],
                 "expected_upside_pct": round((tgt / entry_ref - 1) * 100, 2),
                 "expected_reward_to_risk": round((tgt - entry_ref) / risk, 2)}
    prov["objective.base_case_value_range"] = prov["objective.target"]
    prov["objective.expected_upside_pct"] = "POLICY_DERIVED"
    prov["objective.expected_reward_to_risk"] = "POLICY_DERIVED"
    # --- sizing (deterministic risk budget, capped) ---------------------
    dist = risk / entry_ref
    init = round(min(1.0, RISK_BUDGET_FRAC / dist), 4)
    if init <= 0:
        return None, {}, "no permissible size"
    prov["sizing.initial_frac"] = "POLICY_DERIVED"
    prov["sizing.max_frac"] = "POLICY_DERIVED"
    # --- horizon / events ------------------------------------------------
    ec0 = intent.get("economic_authority") or {}
    horizon = (ec0.get("horizon") or intent.get("horizon")
               or f"<={TIME_EXIT_SESSIONS} sessions")
    contract = {
        "schema_version": 1,
        "direction": "LONG",
        "entry": entry,
        "sizing": {"initial_frac": init, "max_frac": init, "tranches": []},
        "stop": stop,
        "objective": objective,
        "success_criteria":
            (ec0.get("success_criteria")
             or "policy: exit at target, stop, or time horizon"),
        "profit_realization_plan":
            (ec0.get("profit_realization_plan")
             or f"policy: realize at {TARGET_R}R target "
               f"or {TIME_EXIT_SESSIONS}-session time exit"),
        "horizon": horizon,
        "event_constraints": list(
            ec0.get("event_constraints") or []),
        "no_entry_conditions": list(
            ec0.get("no_entry_conditions") or []),
        # the policy contract genuinely resolves the intent's economic-prose
        # conflicts (sizing/tranche/cap/zone) by replacing them with
        # deterministic terms; judgment-level ambiguities can never be
        # claimed here (they already block construction via eligible()).
        "resolves": sorted(
            {str(a.get("type")).upper()
             for a in (intent.get("ambiguities") or [])
             if isinstance(a, dict) and a.get("type")}
            & RESOLVABLE_AMBIGUITY_TYPES),
        "constructed_by": f"econ_policy_v{POLICY_VERSION}",
        "policy_version": POLICY_VERSION,
    }
    prov["horizon"] = ("SOURCE_AUTHORED" if ec0.get("horizon")
                       else "POLICY_DERIVED")
    return contract, prov, "ok"


def policy_terms(contract: dict, prov: dict) -> set:
    """Set of numeric contract terms tagged POLICY_DERIVED — the exemption
    set handed to econ_contract.validate so only policy-computed numbers
    bypass source binding."""
    from alpha_rnd.econ_contract import _contract_numbers
    out = set()
    for v in _contract_numbers(contract):
        # a field-level tag covers every number under it; find the finest
        # matching key — any POLICY_DERIVED tag on a containing path marks
        # the number. Fields are flat enough that scanning suffices.
        for path, tag in prov.items():
            if tag != "POLICY_DERIVED":
                continue
            if _leaf_contains(contract, path, v):
                out.add(v)
                break
    return out


def _leaf_contains(obj, path: str, v) -> bool:
    """True when `v` is the numeric value stored at `path` in `obj`
    (or an element of the list stored there)."""
    cur = obj
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, (list, tuple)):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return False
        else:
            return False
    if isinstance(cur, (list, tuple)):
        return any(isinstance(x, (int, float)) and float(x) == float(v)
                   for x in cur)
    return isinstance(cur, (int, float)) and float(cur) == float(v)
