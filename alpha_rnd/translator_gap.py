#!/usr/bin/env python3
"""R4 translator-gap measurement — derived read-only view.

For every deep-analyzed ticker, classifies WHY a validated/interesting
intent is not executable, distinguishing three layers:
  A intent quality      — TA prose contradictory/vague (not a translator bug)
  B translation         — deterministic intent exists; no publication mapping
  C monitor capability  — deterministic intent exists; no monitor primitive

Bucket rules (evidence-first, conservative):
  EXISTING_MONITOR_CAPABILITY_BUT_NO_TRANSLATION — frozen evidence has an
    explicit numeric predicate that maps to an existing monitor primitive.
  REQUIRES_NEW_MONITOR_PRIMITIVE — deterministic intent but no primitive.
  FUNDAMENTALLY_NOT_MACHINE_ACTIONABLE — no explicit numeric predicate.
  NOT_TRANSLATOR_GAP — disposition is its own non-executable class.

Capability versioning: trigger support is derived from the monitor.py
revision that was live at the decision session (git rev-list --before),
so capabilities added later never retroactively relabel old cases.

Usage:
  python -m alpha_rnd.translator_gap status
  python -m alpha_rnd.translator_gap session 2026-10-14
  python -m alpha_rnd.translator_gap case 2026-10-14 TEAM
"""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EV = ROOT / "evaluations" / "alpha_rnd_v1"
FUNNEL = EV / "opportunity_funnel"
OUT_DIR = EV / "rank_cohort_outcomes"
HORIZONS = ("H1", "H5", "H20", "H60")

# text patterns naming an explicit numeric predicate -> monitor primitive name
PREDICATE_PATTERNS = [
    ("CLOSE_ABOVE_LEVEL", re.compile(r"close (?:above|over|beyond) \$?\d+\.?\d*",
                                     re.I), "close_breakout_vol/close_breakout"),
    ("RECLAIM_LEVEL", re.compile(r"reclaim (?:of )?\$?\d+\.?\d*", re.I),
     "reclaim_2step"),
    ("NUMERIC_ZONE", re.compile(r"\$\d+\.?\d*\s*[-–]\s*\$?\d+\.?\d*"), 
     "multi_close_in_zone/close_in_zone"),
    ("LIMIT_AT", re.compile(r"limit (?:order )?(?:at|for) \$?\d+\.?\d*", re.I),
     "AUTO_ENTRY zone"),
    ("EVENT_GATED_LEVEL", re.compile(
        r"(earnings|event|catalyst|post-).*\$?\d+\.?\d*", re.I),
     "event_gated_multi_close"),
]
# keys in intent.params that hold a 2-number zone the monitor could evaluate
ZONEISH = re.compile(r"(zone|range|band|shelf|entry_zone|starter_zone|_zone$)", re.I)


def _git_monitor_at(session: str) -> tuple[str, str]:
    """monitor.py content at last commit <= session end-of-day + its sha."""
    try:
        sha = subprocess.run(
            ["git", "rev-list", "-1", f"--before={session}T23:59Z", "HEAD",
             "--", "alpha_rnd/monitor.py"],
            cwd=ROOT, capture_output=True, text=True).stdout.strip()
        src = subprocess.run(
            ["git", "show", f"{sha}:alpha_rnd/monitor.py"],
            cwd=ROOT, capture_output=True, text=True).stdout
        if sha and src:
            return sha[:12], src
    except Exception:
        pass
    return "worktree", (ROOT / "alpha_rnd" / "monitor.py").read_text()


def capability_catalog(session: str) -> dict:
    """Trigger primitives the monitor could evaluate at `session`, extracted
    from the actual source revision (not hand-maintained)."""
    sha, src = _git_monitor_at(session)
    prims = set(re.findall(r'"([a-z_0-9]+)" in tt', src))
    if "AUTO_ENTRY" in src:
        prims.add("AUTO_ENTRY_zone")
    if "intraday_zone_touch" in src:
        prims.add("intraday_zone_touch")
    if "reclaim_2step" in src:
        prims.add("reclaim_2step")
    if "event_gated_multi_close" in src:
        prims.add("event_gated_multi_close")
    return {"session": session, "monitor_sha": sha,
            "primitives": sorted(prims)}


def classify_gap(session: str, ticker: str, intents: dict, disp: str) -> dict:
    """Deterministic gap classification from frozen evidence only."""
    cap = capability_catalog(session)
    rec = {"gap_layer": None, "gap_reasons": [], "capability_sha": cap["monitor_sha"],
           "matched_pattern": None, "existing_primitive_available": False,
           "safe_translation_candidate": False,
           "requires_new_monitor_primitive": False,
           "fundamentally_not_machine_actionable": False}
    if disp == "EXECUTABLE_WATCH":
        rec["gap_layer"] = "NONE"
        return rec
    if disp in ("AMBIGUOUS_REJECTED",):
        rec["gap_layer"] = "A_INTENT_QUALITY"
        rec["gap_reasons"] = ["contradictory/ambiguous frozen evidence"]
        return rec
    if disp in ("RISK_PLAN_REQUIRED",):
        rec["gap_layer"] = "D_RISK_PLAN"  # not a translator problem
        rec["gap_reasons"] = ["no machine-actionable post-entry risk plan"]
        return rec
    if disp in ("REANALYZE_ON_TRIGGER", "RESEARCH_ONLY", "NO_ACTION",
                "OPEN_POSITION_MANAGEMENT"):
        rec["gap_layer"] = "D_OTHER_DISPOSITION"
        rec["gap_reasons"] = [f"disposition is {disp}, not a translator gap"]
        return rec
    # PUBLISHED_NON_EXECUTABLE: intent validated but monitor can't evaluate
    i = intents.get(ticker) or {}
    params = i.get("params") or {}
    trig = str(i.get("trigger") or "")
    # structured params first: zone-like numeric pair -> zone primitive exists
    zone_like = [k for k, v in params.items()
                 if ZONEISH.search(k) and isinstance(v, list)
                 and len(v) == 2 and all(isinstance(x, (int, float)) for x in v)]
    if zone_like:
        rec.update({"gap_layer": "B_TRANSLATION",
                    "matched_pattern": "PARAM_ZONE_LIKE",
                    "existing_primitive_available":
                        "multi_close_in_zone" in cap["primitives"]
                        or "close_in_zone" in cap["primitives"],
                    "safe_translation_candidate": True,
                    "gap_reasons": [f"zone-like params {zone_like} not mapped "
                                    "to monitor trigger_type"]})
        return rec
    for pid, rx, prim in PREDICATE_PATTERNS:
        if rx.search(trig):
            rec.update({"gap_layer": "B_TRANSLATION", "matched_pattern": pid,
                        "existing_primitive_available": True,
                        "safe_translation_candidate": True,
                        "gap_reasons": [f"explicit predicate '{pid}' maps to "
                                        f"{prim} but intent carried no "
                                        "monitor trigger_type"]})
            return rec
    # no explicit numeric predicate anywhere
    rec.update({"gap_layer": "A_INTENT_QUALITY",
                "fundamentally_not_machine_actionable": True,
                "gap_reasons": ["no explicit numeric entry predicate in frozen "
                                "trigger/params"]})
    return rec


def observations(session: str | None = None, clean_only=True) -> list[dict]:
    out = []
    for fp in sorted(FUNNEL.glob("*.json")):
        sess = fp.stem
        if session and sess != session:
            continue
        fdoc = json.loads(fp.read_text())
        clean = not fdoc.get("provenance", {}).get("backfilled", True)
        if clean_only and not clean:
            continue
        ipath = EV / f"publication_intents_{sess}.json"
        intents = (json.loads(ipath.read_text()).get("intents")
                   if ipath.exists() else {}) or {}
        odoc = {}
        op = OUT_DIR / fp.name
        if op.exists():
            odoc = json.loads(op.read_text())
        for t, r in (fdoc.get("tickers") or {}).items():
            if not (r.get("deep") or {}).get("selected"):
                continue
            pub = r.get("publication") or {}
            disp = pub.get("disposition")
            g = classify_gap(sess, t, intents, disp)
            r2 = (odoc.get("tickers") or {}).get(t) or {}
            out.append({"session": sess, "ticker": t, "clean": clean,
                        "raw_ta_signal": (r.get("ta") or {}).get("final_signal"),
                        "disposition": disp,
                        "executable": pub.get("executable"),
                        "decision_context":
                            "OPEN_POSITION_MANAGEMENT"
                            if (r.get("portfolio") or {}).get("existing_position")
                            else "NEW_ENTRY",
                        **g, "r2": r2})
    return out


def _agg(vals):
    v = [x for x in vals if x is not None]
    return (round(sum(v) / len(v), 3) if v else None)


def status() -> str:
    obs = observations(clean_only=False)
    lines = ["ALPHA TRANSLATOR GAP", "",
             f"clean prospective deep-analyzed: "
             f"{sum(1 for o in obs if o['clean'])} "
             f"(total incl diagnostic: {len(obs)})"]
    pnx = [o for o in obs if o["disposition"] == "PUBLISHED_NON_EXECUTABLE"]
    cats = {}
    for o in pnx:
        cats[o["gap_layer"]] = cats.get(o["gap_layer"], 0) + 1
    lines.append("\nPUBLISHED_NON_EXECUTABLE gap layers:")
    for k, v in sorted(cats.items()):
        lines.append(f"  {k}: {v}")
    pats = {}
    for o in obs:
        if o["matched_pattern"]:
            pats[o["matched_pattern"]] = pats.get(o["matched_pattern"], 0) + 1
    lines.append("\nRecurring patterns:")
    for k, v in sorted(pats.items()):
        lines.append(f"  {k}: {v}")
    # outcome linkage
    lines.append("\nOutcomes (H1, all sessions incl. diagnostic):")
    for layer in sorted({o["gap_layer"] for o in obs if o["gap_layer"]}):
        sub = [o for o in obs if o["gap_layer"] == layer]
        mat = [o["r2"]["horizons"]["H1"]["raw_return_pct"] for o in sub
               if (o["r2"].get("horizons") or {}).get("H1", {}).get("status")
               == "MATURED"]
        lines.append(f"  {layer}: N={len(sub)} H1_matured={len(mat)} "
                     f"mean_ret={_agg(mat)}")
    return "\n".join(lines)


def session_report(session: str) -> str:
    obs = observations(session=session, clean_only=False)
    if not obs:
        return f"No deep-analyzed tickers for {session}"
    lines = [f"TRANSLATOR GAP — {session}", ""]
    for o in sorted(obs, key=lambda x: x["ticker"]):
        hz = " ".join(f"{h}:{(o['r2'].get('horizons') or {}).get(h, {}).get('status','-')}"
                      for h in HORIZONS)
        lines.append(f"{o['ticker']:6} {str(o['raw_ta_signal']):11} "
                     f"{str(o['disposition']):26} exec={o['executable']}")
        lines.append(f"       layer={o['gap_layer']} pattern={o['matched_pattern']} "
                     f"primitive={o['existing_primitive_available']} "
                     f"safe={o['safe_translation_candidate']}")
        lines.append(f"       {hz}")
    return "\n".join(lines)


def case_report(session: str, ticker: str) -> str:
    obs = [o for o in observations(session=session, clean_only=False)
           if o["ticker"] == ticker]
    if not obs:
        return f"No record for {ticker} @ {session}"
    o = obs[0]
    ipath = EV / f"publication_intents_{session}.json"
    intent = (json.loads(ipath.read_text())["intents"].get(ticker)
              if ipath.exists() else None)
    return json.dumps({**{k: v for k, v in o.items() if k != "r2"},
                       "frozen_intent": intent,
                       "r2_horizons": (o["r2"].get("horizons") or {})},
                      indent=1, default=str)


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "session":
        print(session_report(sys.argv[2]))
    elif len(sys.argv) > 3 and sys.argv[1] == "case":
        print(case_report(sys.argv[2], sys.argv[3]))
    else:
        print(status())
