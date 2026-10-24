#!/usr/bin/env python3
"""TARGETED_SCENARIO_REPLAY — Level 1 pipeline replay (engineering regression).

Replays a SMALL explicit scenario manifest through the real production
machinery — synthesize.validate, econ_contract, disposition, monitor
close_pass trigger evaluation, entry-gate authorization, resolve_pending
order/fill — using persisted artifacts + cached market bars. No LLM call,
no provider call, no production state mutation. Isolation: all state dicts
are in-memory; notification and publication-authority paths are redirected
to a temp dir for the duration of the run.

  python -m alpha_rnd.scenario_replay <manifest.json> [--ev-dir PATH]

This proves framework behavior, not alpha: scenarios are hindsight-selected
regression shapes.
"""
import json
import pickle
import sys
import tempfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
EV = ROOT / "evaluations" / "alpha_rnd_v1"
from alpha_rnd import econ_contract as _ec  # noqa: E402
from alpha_rnd import entry_gate as _eg  # noqa: E402
from alpha_rnd import monitor as _m  # noqa: E402
from alpha_rnd import synthesize as _syn  # noqa: E402

MAX_SCENARIOS = 12
MAX_SESSIONS = 10

CLASSES = ("POSITIVE_PATH", "NEGATIVE_PATH", "SAFETY_BLOCK",
           "TRIGGER_NOT_REACHED", "TRIGGER_REACHED", "REANALYZE_ONLY",
           "RISK_BLOCK", "AMBIGUITY_RESOLVED", "AMBIGUITY_NONRESOLVABLE")


def _fresh_state():
    return {"last_check_utc": None, "processed_close_sessions": [],
            "confirm": {}, "pending_open_fills": [], "pending_open_exits": [],
            "positions": {}, "cash": 50000.0, "nav_last": 50000.0,
            "watch_status": {}, "executed": [], "emitted_ids": [],
            "event_outbox": [], "risk_blocked": {}}


def _load_cache(ev_dir: Path, need_after: str):
    pkls = sorted(ev_dir.glob("market_cache_*.pkl"))
    for p in reversed(pkls):
        if p.stem.split("_")[-1] >= need_after:
            return pickle.loads(p.read_bytes())[0]
    raise RuntimeError(f"no market cache reaching {need_after}")


def _intent_for(ev_dir: Path, t: str, session: str, overlay: dict) -> dict:
    doc = ev_dir / f"publication_intents_{session}.json"
    base = {}
    if doc.exists():
        base = (json.loads(doc.read_text()).get("intents") or {}).get(t) or {}
    i = dict(base)
    i.update(overlay)
    i.setdefault("ticker", t)
    return i


def _evaluate(i: dict, a: dict):
    errs = _syn.validate(i, a)
    ec_errs, resolved = _ec.validate(
        i.get("economic_authority"), a, i,
        _syn._nums_in_text(_syn.artifact_text(a)))
    if resolved is not None:
        rtypes = {str(r).upper() for r in resolved.get("resolves") or []} \
            & _ec.RESOLVABLE_AMBIGUITY_TYPES
        errs = [e for e in errs
                if not (e.startswith("ambiguous_type:")
                        and e.split(":", 1)[1].upper() in rtypes)]
        i["economic_authority_resolved"] = resolved
    errs = ec_errs + errs
    disp = _syn.disposition(i, errs, set())
    if disp == "EXECUTABLE_WATCH" and resolved is not None and \
            not _ec.has_authority(i, resolved):
        disp = "PUBLISHED_NON_EXECUTABLE"
    return errs, resolved, disp


def _replay_triggers(w: dict, st: dict, df, sessions: list[str],
                     grant_auth: bool, pub_dir: Path, session: str):
    """Drive real close_pass/resolve_pending over sliced historical bars."""
    wl = {"watches": [w], "open_positions": []}
    if grant_auth:
        (pub_dir / f"publication_intents_{session}.json").write_text(json.dumps(
            {"dispositions": {w["ticker"]: {"disposition": "EXECUTABLE_WATCH"}}}))
    trace = {"triggered_at": None, "order_created": False,
             "filled": False, "risk_blocked": False, "not_authorized": False,
             "statuses": []}
    dates = [str(d.date()) for d in df.index]
    later = [d for d in dates if d > session][:MAX_SESSIONS]
    for sess in later:
        sub = {w["ticker"]: df[df.index.strftime("%Y-%m-%d") <= sess]}
        _m.close_pass(st, wl, sub, sess)
        _m.settle_pending(st, wl, sub, sess)   # live=False: fills need open
        # fill path: pending order resolves at next session's actual open
        if st["pending_open_fills"] and sess != later[-1]:
            nxt = later[later.index(sess) + 1]
            sub2 = {w["ticker"]: df[df.index.strftime("%Y-%m-%d") <= nxt]}
            _m.resolve_pending(st, wl, sub2, nxt, live=True)
        trace["statuses"].append(
            (sess, st["watch_status"].get(w["ticker"]),
             len(st["pending_open_fills"])))
        for ev in st.get("event_outbox") or []:
            act = ev.get("action")
            if act == "CONFIRMED":
                trace["triggered_at"] = trace["triggered_at"] or sess
            if act == "CONFIRMED_PENDING_NEXT_OPEN_ENTRY":
                trace["order_created"] = True
            if act == "RISK_PLAN_REQUIRED":
                trace["risk_blocked"] = True
            if act == "NO_ACTION" and "not_authorized" in str(
                    ev.get("why")):
                trace["not_authorized"] = True
        if w["ticker"] in st["positions"]:
            trace["filled"] = True
        st["event_outbox"] = []
    return trace


def run_manifest(path: str, ev_dir: Path | None = None) -> dict:
    ev_dir = Path(ev_dir) if ev_dir else EV
    scenarios = json.loads(Path(path).read_text())["scenarios"]
    if len(scenarios) > MAX_SCENARIOS:
        raise RuntimeError(f"cap exceeded: {len(scenarios)} > {MAX_SCENARIOS}")
    tmp = Path(tempfile.mkdtemp(prefix="scenario_replay_"))
    pub_dir = tmp / "pub"; pub_dir.mkdir()
    print(f"workload: {len(scenarios)} scenarios, <= {MAX_SESSIONS} sessions "
          f"each, 0 model calls, 0 provider calls; state dir {tmp}")
    out = []
    with mock.patch.object(_m, "NOTIFY", tmp / "notify.log"), \
         mock.patch.object(_m, "desktop_notify", lambda *a, **k: None), \
         mock.patch.object(_eg, "PUB_DIR", pub_dir):
        for sc in scenarios:
            t, sess = sc["ticker"], sc["session"]
            tr = {"id": sc["id"], "class": sc["class"], "ticker": t,
                  "session": sess}
            ap = ev_dir / "case_artifacts" / f"{t}_{sess}.json"
            tr["artifact"] = ap.exists()
            if not tr["artifact"]:
                tr["result"] = "FAIL"; tr["stop"] = "artifact missing"
                out.append(tr); continue
            a = json.loads(ap.read_text())
            i = _intent_for(ev_dir, t, sess, sc.get("intent") or {})
            errs, resolved, disp = _evaluate(i, a)
            tr.update(errors=errs, disposition=disp,
                      contract="VALID" if resolved else
                      ("INVALID" if i.get("economic_authority") else "NONE"))
            # trigger replay for executable watches
            wspec = sc.get("watch") or {}
            md = _load_cache(ev_dir, sess)
            df = md.get(t)
            if disp == "EXECUTABLE_WATCH" and wspec and df is not None:
                w = {"ticker": t, "cls": i.get("watch_mode"),
                     "trigger_type": wspec.get("trigger_type"),
                     "params": wspec.get("params") or i.get("params") or {},
                     "size_frac": i.get("size_frac") or 0.5,
                     "invalidation": wspec["invalidation"]
                     if "invalidation" in wspec
                     else (i.get("invalidation") or ""),
                     "stop_rule": wspec["stop_rule"]
                     if "stop_rule" in wspec else
                     ({"type": "intraday_stop", "level": i["stop_level"]}
                      if i.get("stop_level") else {}),
                     "trigger": i.get("trigger") or "", "horizon": "x",
                     "artifact": f"case_artifacts/{t}_{sess}.json",
                     "session": sess}
                st = _fresh_state()
                sc_pub = pub_dir / sc["id"]          # isolated per scenario
                sc_pub.mkdir()
                with mock.patch.object(_eg, "PUB_DIR", sc_pub):
                    tr["replay"] = _replay_triggers(
                        w, st, df, [sess],
                        sc.get("grant_authorization", True),
                        sc_pub, sess)
            exp = sc.get("expected") or {}
            tr["expected"] = exp
            ok = (disp == exp.get("disposition", disp) and
                  tr.get("replay", {}).get("triggered_at") is not None
                  if exp.get("trigger") == "reached" else True)
            if exp.get("trigger") == "not_reached":
                ok = ok and not (tr.get("replay") or {}).get("triggered_at")
            if exp.get("order") == "created":
                ok = ok and (tr.get("replay") or {}).get("order_created")
            if exp.get("order") == "none":
                ok = ok and not (tr.get("replay") or {}).get("order_created")
            if exp.get("risk_blocked"):
                ok = ok and (tr.get("replay") or {}).get("risk_blocked")
            if exp.get("not_authorized"):
                ok = ok and (tr.get("replay") or {}).get("not_authorized")
            tr["result"] = "PASS" if ok else "FAIL"
            out.append(tr)
    n_ok = sum(1 for r in out if r["result"] == "PASS")
    summary = {"scenarios": len(out), "passed": n_ok,
               "failed": len(out) - n_ok,
               "orders_created": sum(1 for r in out
                                     if (r.get("replay") or {})
                                     .get("order_created")),
               "model_calls": 0, "provider_calls": 0}
    for r in out:
        rp = r.get("replay") or {}
        print(f"SCENARIO: {r['id']}\n"
              f"  CLASS: {r['class']}  ARTIFACT: {r.get('artifact')}  "
              f"CONTRACT: {r.get('contract')}\n"
              f"  DISPOSITION: {r.get('disposition')}  "
              f"TRIGGER: {rp.get('triggered_at') or 'not reached'}  "
              f"ORDER: {'created' if rp.get('order_created') else 'none'}  "
              f"FILLED: {rp.get('filled')}\n"
              f"  EXPECTED: {r.get('expected')}  RESULT: {r['result']}  "
              f"ERRORS: {r.get('errors')}")
    print("SUMMARY:", json.dumps(summary))
    return {"scenarios": out, "summary": summary}


if __name__ == "__main__":
    ev = None
    if "--ev-dir" in sys.argv:
        i = sys.argv.index("--ev-dir")
        ev = sys.argv[i + 1]
        sys.argv.pop(i); sys.argv.pop(i)
    res = run_manifest(sys.argv[1], ev)
    sys.exit(0 if res["summary"]["failed"] == 0 else 1)
