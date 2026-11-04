#!/usr/bin/env python3
"""Tests: POLICY_DERIVED contract construction + hardened lab execution path.

Run:  PYTHONPATH=. python3 alpha_rnd/test_econ_policy.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from alpha_rnd import econ_policy as ep
from alpha_rnd import econ_contract as ec
from alpha_rnd import monitor as mon
from alpha_rnd import decision as dec

P = 0


def ok(name, cond, extra=""):
    global P
    assert cond, f"FAIL {name} {extra}"
    P += 1
    print(f"  ok {name}")


def bars(closes, highs=None, lows=None, opens=None, start="2026-09-01",
         end=None):
    n = len(closes)
    idx = (pd.bdate_range(end=end, periods=n) if end
           else pd.bdate_range(start, periods=n))
    return pd.DataFrame({
        "Open": opens or closes,
        "High": highs or [c * 1.01 for c in closes],
        "Low": lows or [c * 0.99 for c in closes],
        "Close": closes,
        "Volume": [1_000_000] * n}, index=idx)


ART = {"ticker": "XYZ", "decision_session": "2026-10-20", "signal": "Buy",
       "final_trade_decision": "", "trader_investment_plan": "",
       "risk_judge_decision": "", "investment_plan": ""}


def intent(**kw):
    base = {"ticker": "XYZ", "classification": "WATCH_FOR_ENTRY",
            "watch_mode": "AUTO_ENTRY", "ambiguities": [],
            "decision": {"direction": "LONG"}}
    base.update(kw)
    return base


# ── 1. policy construction on constructive judgment with bad authored econ ──
cl = [50.0] * 28 + [100.0]          # jump to 100 at decision close
df = bars(cl)
c, prov, reason = ep.construct(intent(), ART, set(), bars=df)
ok("construct returns contract", c is not None, reason)
ok("direction LONG", c["direction"] == "LONG")
ok("continuation trigger = decision close", c["entry"]["trigger_level"] == 100.0)
ok("confirm window + gap guard", c["entry"]["confirm_within_sessions"] == 5
   and c["entry"]["max_gap_pct"] == 0.03)
a, _ = ep.atr(df)
stop = c["stop"]["level"]
ok("policy stop = ref-1.5ATR", abs(stop - (100 - 1.5 * a)) < 0.01)
tgt = c["objective"]["target"]
ok("policy target = 2R", abs(tgt - (100 + 2 * (100 - stop))) < 0.01)
ok("provenance tagged", prov["entry.trigger_level"] == "POLICY_DERIVED"
   and prov["stop.level"] == "POLICY_DERIVED")

pt = ep.policy_terms(c, prov)
errs, resolved = ec.validate(c, ART, intent(), set(), policy_terms=pt)
ok("policy contract validates", not errs and resolved is not None, errs)
ok("provenance recorded", resolved["number_provenance"] and
   resolved["policy_version"] == 1)
proj = ec.project_execution(resolved)
ok("projects to confirmed_close_above", proj and
   proj["trigger_type"] == "confirmed_close_above")
ok("params carry guards", proj["params"].get("max_gap_pct") == 0.03 and
   proj["params"].get("confirm_within_sessions") == 5)

# fabricated number NOT in policy terms still fails binding
bad = dict(c)
bad["stop"] = dict(c["stop"], level=77.77)
errs2, _ = ec.validate(bad, ART, intent(), set(), policy_terms=pt)
ok("unbound invented stop still fails", any(
    e.startswith("ECON_UNSUPPORTED_NUMBER") for e in errs2), errs2)

# ── 2. eligibility gates ────────────────────────────────────────────────────
ok("Buy+constructive eligible", ep.eligible(intent(), ART)[0])
ok("Hold signal blocked", not ep.eligible(
    intent(), dict(ART, signal="Hold"))[0])
ok("event ambiguity blocked", not ep.eligible(intent(
    ambiguities=[{"type": "EVENT_OUTCOME_UNKNOWN"}]), ART)[0])
ok("untyped ambiguity blocked", not ep.eligible(
    intent(ambiguity="unclear"), ART)[0])
ok("SHORT decision blocked", not ep.eligible(intent(
    decision={"direction": "SHORT"}), ART)[0])
ok("REJECT class blocked", not ep.eligible(
    intent(classification="REJECT"), ART)[0])
ok("sizing ambiguity is resolvable", ep.eligible(intent(
    ambiguities=[{"type": "SIZING_CONFLICT"}]), ART)[0])

# ── 3. authored anchors preserved when bound ────────────────────────────────
src = {90.0, 95.0, 88.0, 120.0}
auth = intent(economic_authority={
    "direction": "LONG",
    "entry": {"mode": "LIMIT_ZONE", "zone": [90.0, 95.0]},
    "stop": {"type": "close_below", "level": 88.0},
    "objective": {"target": 120.0},
    "event_constraints": [], "no_entry_conditions": []})
c2, prov2, _ = ep.construct(auth, ART, src, bars=df)
ok("authored zone kept verbatim", c2["entry"]["zone"] == [90.0, 95.0])
ok("authored stop kept", c2["stop"]["level"] == 88.0
   and c2["stop"]["type"] == "close_below")
ok("authored target kept", c2["objective"]["target"] == 120.0)
ok("anchors SOURCE_AUTHORED", prov2["entry"] == "SOURCE_AUTHORED"
   and prov2["stop.level"] == "SOURCE_AUTHORED"
   and prov2["objective.target"] == "SOURCE_AUTHORED")
ok("sizing POLICY_DERIVED", prov2["sizing.initial_frac"] == "POLICY_DERIVED")
errs3, res3 = ec.validate(c2, ART, auth, src,
                          policy_terms=ep.policy_terms(c2, prov2))
ok("hybrid contract validates", not errs3, errs3)
ok("zone projects intraday_zone_touch",
   ec.project_execution(res3)["trigger_type"] == "intraday_zone_touch")

# fail-closed: no market data at all
c3, _, r3 = ep.construct(intent(), ART, set(), bars=[])
ok("no bars -> explicit non-executable", c3 is None and r3, r3)

# ── 4. monitor: confirmed_close_above path ──────────────────────────────────
mon.authorized = lambda w, pub_dir=None: True
mon.notify = lambda *a, **k: None
import alpha_rnd.mgmt as _mgmt
_mgmt.create_snapshot = lambda *a, **k: None  # fills must not write state


def st0():
    return {"watch_status": {}, "confirm": {}, "positions": {},
            "pending_open_fills": [], "pending_open_exits": [],
            "executed": [], "emitted_ids": [], "event_outbox": [],
            "cash": 100000.0, "realized": 0.0}


def watch_cc(**params):
    p = {"trigger_level": 100.0, "entry_style": "confirmed_close_above",
         "success_criteria": "reaches target"}
    p.update(params)
    return {"ticker": "XYZ", "cls": "AUTO_ENTRY", "v": "auto",
            "trigger_type": "confirmed_close_above", "params": p,
            "size_frac": 0.5, "invalidation": "intraday_stop 95.0",
            "stop_rule": {"type": "intraday_stop", "level": 95.0},
            "exit_rules": [{"type": "intraday_stop", "level": 95.0}],
            "target": 110.0, "horizon": "5 sessions",
            "artifact": "XYZ_2026-10-20.json", "session": "2026-10-20",
            "trigger": "confirmed close above 100"}


wl0 = lambda w: {"watches": [w], "open_positions": []}

# 4a. completed-session close confirms -> pending next-open fill (uses
# df.iloc[-1], the just-closed session; previous session below level)
d1 = bars([98.0] * 27 + [99.0, 101.0], opens=[98.0] * 27 + [99.0, 101.0],
          end="2026-10-23")
st, w = st0(), watch_cc(max_gap_pct=0.03, confirm_within_sessions=5)
mon.close_pass(st, wl0(w), {"XYZ": d1}, "2026-10-23")
ok("confirmation detected on last completed close",
   len(st["pending_open_fills"]) == 1)
od = st["pending_open_fills"][0]
ok("gap guard recorded", od.get("gap_ref") == 101.0
   and od.get("max_gap_pct") == 0.03)

# next open inside guard -> fills at open
d2 = bars([98.0] * 27 + [99.0, 101.0, 102.0],
          opens=[98.0] * 27 + [99.0, 101.0, 102.0], end="2026-10-26")
mon.resolve_pending(st, wl0(w), {"XYZ": d2}, "2026-10-26", live=True)
ok("fills at next open", st["positions"].get("XYZ", {}).get("fill") == 102.0)

# duplicate resolve cannot double-fill
sh = st["positions"]["XYZ"]["shares"]
mon.resolve_pending(st, wl0(w), {"XYZ": d2}, "2026-10-26", live=True)
ok("no duplicate fill", st["positions"]["XYZ"]["shares"] == sh)

# 4b. gap beyond guard cancels the entry (consumed, never refires)
st, w = st0(), watch_cc(max_gap_pct=0.03, confirm_within_sessions=5)
mon.close_pass(st, wl0(w), {"XYZ": d1}, "2026-10-23")
d3 = bars([98.0] * 27 + [99.0, 101.0, 105.0],
          opens=[98.0] * 27 + [99.0, 101.0, 105.0], end="2026-10-26")
mon.resolve_pending(st, wl0(w), {"XYZ": d3}, "2026-10-26", live=True)
ok("gap guard cancels entry", "XYZ" not in st["positions"])
ok("cancelled order consumed",
   any(x.startswith("entry:XYZ") for x in st["executed"]))
mon.resolve_pending(st, wl0(w), {"XYZ": d3}, "2026-10-26", live=True)
ok("cancelled order never refires", "XYZ" not in st["positions"])

# 4c. confirmation window expires the setup
st, w = st0(), watch_cc(confirm_within_sessions=1)
dflat = bars([99.0] * 30, opens=[99.0] * 30, end="2026-10-23")
mon.close_pass(st, wl0(w), {"XYZ": dflat}, "2026-10-23")
ok("first session no trigger", st["watch_status"].get("XYZ") is None)
mon.close_pass(st, wl0(w), {"XYZ": dflat}, "2026-10-26")
ok("window expiry kills watch", st["watch_status"].get("XYZ") == "EXPIRED")

# ── 5. event-prerequisite gate ──────────────────────────────────────────────
w_ev = watch_cc()
w_ev["event_constraints"] = ["await FDA decision on 2026-11-15"]
st = st0()
mon.close_pass(st, wl0(w_ev), {"XYZ": d1}, "2026-10-23")
ok("unverifiable event blocks trigger", not st["pending_open_fills"])
ok("block event emitted", any("event_block" in str(e.get("event_id"))
                              for e in st["event_outbox"]))
mon.do_fill(st, wl0(w_ev), "XYZ", 101.0, 0.5)
ok("unverifiable event blocks fill", "XYZ" not in st["positions"])

# encodable constraints pass through as machine params (RHI-shaped)
rhi = {"schema_version": 1, "direction": "LONG",
       "entry": {"mode": "LIMIT_ZONE", "zone": [41.0, 41.95],
                 "condition": "buy the pullback; do not chase above $44.98"},
       "sizing": {"initial_frac": 0.5, "max_frac": 1.0,
                  "tranches": [{"frac": 0.5, "level": 45.87}]},
       "stop": {"type": "close_below", "level": 38.8,
                "label": "hard invalidation $38.79"},
       "objective": {"base_case_value_range": [47.14, 47.14],
                     "expected_reward_to_risk": 1.65,
                     "success_criteria": "Q4 positive OCF",
                     "profit_realization_plan": "partial at 44.98-47.14",
                     "legacy_target": 47.14, "base_case_top": 47.14},
       "horizon": "1-2 quarters",
       "event_constraints": ["exit on any dividend action",
                             "exit on another negative-OCF quarter"],
       "no_entry_conditions": ["chasing above $44.98",
                               "daily close below $38.80"],
       "resolves": ["SIZING_CONFLICT"]}
proj_rhi = ec.project_execution(rhi)
ok("RHI still projects pullback", proj_rhi["trigger_type"] ==
   "intraday_zone_touch" and proj_rhi["params"]["zone"] == [41.0, 41.95])
ok("RHI ceiling encoded", proj_rhi["params"].get("max_entry_price") == 44.98)
ok("RHI kill encoded", proj_rhi["params"].get("kill_level") == 38.80)
ok("RHI exit constraints observational", len(
    proj_rhi["params"].get("exit_constraints_observational") or []) == 2)
ok("RHI no unverified prerequisites",
   proj_rhi["event_constraints"] == [])
ok("RHI fills under ceiling", not mon._event_unverified(
    dict(proj_rhi)))

# max_entry_price enforced at fill
st = st0()
w_rhi = {"ticker": "RHI", "cls": "AUTO_ENTRY", "v": "auto",
         "trigger_type": "intraday_zone_touch",
         "params": {"zone": [41.0, 41.95], "entry_price": 41.95,
                    "max_entry_price": 44.98,
                    "success_criteria": "x"},
         "size_frac": 0.5, "invalidation": "close_below 38.8",
         "stop_rule": {"type": "close_below", "level": 38.8},
         "exit_rules": [{"type": "close_below", "level": 38.8}],
         "target": 47.14, "horizon": "2q", "trigger": "zone 41-41.95",
         "artifact": "RHI_2026-10-28.json", "session": "2026-10-28"}
mon.do_fill(st, wl0(w_rhi), "RHI", 41.95, 0.5)
ok("fill at zone top under ceiling executes",
   st["positions"].get("RHI", {}).get("fill") == 41.95)
st2 = st0()
mon.do_fill(st2, wl0(w_rhi), "RHI", 45.50, 0.5)
ok("fill above max_entry_price refused", "RHI" not in st2["positions"])

# unencodable no_entry condition stays blocking
bad_rhi = dict(rhi, no_entry_conditions=["only if Fed holds rates"])
proj_bad = ec.project_execution(bad_rhi)
ok("unencodable no_entry stays unverified",
   proj_bad["event_constraints"] == ["only if Fed holds rates"])

# kill_level kills the watch on close-through
st = st0()
w_k = dict(proj_rhi)
w_k.update({"ticker": "RHI", "v": "auto",
            "artifact": "RHI_2026-10-28.json", "horizon": "2q",
            "invalidation": "close_below 38.8", "size_frac": 0.5,
            "trigger": "zone", "session": "2026-10-28"})
dkill = bars([42.0] * 28 + [41.5, 38.5], opens=[42.0] * 28 + [41.5, 38.5])
mon.close_pass(st, wl0(w_k), {"RHI": dkill}, "2026-10-29")
ok("kill_level expires watch", st["watch_status"].get("RHI") == "KILLED")

# ── 6. decision passthrough ─────────────────────────────────────────────────
d = dec.from_economic_authority(resolved, "2026-10-20", "XYZ", "Buy",
                                ref_price=100.0)
ok("decision carries policy provenance",
   d.get("policy_version") == 1 and d.get("constructed_by"))

print(f"\nPASS {P} checks")
