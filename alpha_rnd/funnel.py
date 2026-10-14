#!/usr/bin/env python3
"""R1 opportunity-funnel instrumentation (observability only).

Builds one immutable ex-ante artifact per session:
  evaluations/alpha_rnd_v1/opportunity_funnel/<session>.json

Joins only already-frozen evidence: universe_raw, candidate_pool_frozen,
publication_intents dispositions, live_watchlist, monitor_state, ledger.
Never changes any trading decision. Build is idempotent: an existing
artifact for the session is preserved (byte-stable).
"""
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EV = ROOT / "evaluations" / "alpha_rnd_v1"
FUNNEL_DIR = EV / "opportunity_funnel"

# map frozen-pool reason keys -> machine-readable taxonomy
EXCLUSION_TAXONOMY = {
    "price_below_5": "PRICE_BELOW_MIN",
    "illiquid": "LIQUIDITY",
    "insufficient_history": "INSUFFICIENT_HISTORY",
    "fetch_failed": "DATA_UNAVAILABLE",
    "security_type": "SECURITY_TYPE",
}


def _cohort(rank: int) -> str:
    for lo, hi, name in ((1, 10, "TOP_1_10"), (11, 25, "RANK_11_25"),
                         (26, 50, "RANK_26_50"), (51, 100, "RANK_51_100")):
        if lo <= rank <= hi:
            return name
    return "RANK_101_PLUS"


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def build(session: str, root: Path | None = None) -> dict:
    ev = (root or ROOT) / "evaluations" / "alpha_rnd_v1"
    if root:
        FUNNEL_DIR_OUT = ev / "opportunity_funnel"
    else:
        FUNNEL_DIR_OUT = FUNNEL_DIR
    FUNNEL_DIR_OUT.mkdir(parents=True, exist_ok=True)
    out_path = FUNNEL_DIR_OUT / f"{session}.json"
    if out_path.exists():
        return json.loads(out_path.read_text())  # immutable

    pool = json.loads((ev / f"candidate_pool_frozen_{session}.json").read_text())
    intents_path = ev / f"publication_intents_{session}.json"
    intents = json.loads(intents_path.read_text()) if intents_path.exists() else {}
    wl_path = (root or ROOT) / "alpha_rnd" / "live_watchlist.json"
    wl = json.loads(wl_path.read_text()) if wl_path.exists() else {"watches": []}
    st_path = (root or ROOT) / "alpha_rnd" / "monitor_state.json"
    st = json.loads(st_path.read_text()) if st_path.exists() else {}
    incomplete = [k for k in ("exclusions", "eligible_features")
                  if k not in pool]

    # candidate ranking (prefer persisted rank; recompute for legacy docs)
    cands = pool.get("candidates", [])
    if cands and "deep_score" not in cands[0]:
        for c in cands:
            labs = [x for x in (c.get("labels") or []) if x != "MULTI_SIGNAL"]
            c["deep_score"] = round(10 * len(labs)
                                    + 2 * min(max(c.get("rs_60") or 0, 0), 2)
                                    + (1 if "CATALYST" in labs else 0), 4)
    ranked = sorted(cands, key=lambda x: (-x.get("deep_score", 0), x["ticker"]))
    for i, c in enumerate(ranked, 1):
        c.setdefault("rank", i)
    quota = pool.get("deep_quota", 10)
    deep_selected = [c["ticker"] for c in ranked[:quota]]
    rank_of = {c["ticker"]: c["rank"] for c in ranked}

    disps = intents.get("dispositions") or {}
    watch_by_t = {w["ticker"]: w for w in wl.get("watches", [])}
    positions = st.get("positions") or {}
    emitted = set(st.get("emitted_ids") or [])
    exclusions = pool.get("exclusions") or {}
    elig_feats = pool.get("eligible_features") or {}

    tickers = {}
    # excluded tickers (when per-ticker detail exists)
    for reason, ts in exclusions.items():
        for t in ts:
            tickers[t] = {
                "ticker": t, "session": session,
                "universe": {"present": True, "source": "discovery_universe"},
                "eligibility": {"eligible": False,
                                "exclusion_reason": EXCLUSION_TAXONOMY.get(reason, reason.upper()),
                                "exclusion_details": reason,
                                "threshold": pool.get("filters")},
                "screen": None, "deep": {"selected": False, "quota": quota,
                                         "selection_reason": "not eligible"},
                "ta": None, "publication": None, "monitor": None,
                "portfolio": None}
    # eligible non-pool
    for t, f in elig_feats.items():
        if t in tickers:
            continue
        tickers[t] = {
            "ticker": t, "session": session,
            "universe": {"present": True, "source": "discovery_universe"},
            "eligibility": {"eligible": True, "exclusion_reason": None,
                            "exclusion_details": None},
            "screen": {"score": None, "rank": None,
                       "cohort": None,
                       "price": f.get("close"), "rs_60": f.get("rs_60"),
                       "signal_flags": None,
                       "note": "eligible; below frozen-pool cutoff"},
            "deep": {"selected": False, "quota": quota,
                     "selection_reason": "not in candidate pool"},
            "ta": None, "publication": None, "monitor": None,
            "portfolio": None}
    # pool candidates
    for c in ranked:
        t = c["ticker"]
        disp = (disps.get(t) or {})
        w = watch_by_t.get(t)
        triggerable = bool((w or {}).get("trigger_type"))
        rec = {
            "ticker": t, "session": session,
            "universe": {"present": True, "source": "discovery_universe"},
            "eligibility": {"eligible": True, "exclusion_reason": None,
                            "exclusion_details": None},
            "screen": {"score": c.get("deep_score"), "rank": rank_of[t],
                       "cohort": _cohort(rank_of[t]),
                       "price": c.get("close"),
                       "signal_flags": c.get("labels"),
                       "ret_5": c.get("ret_5"), "rs_60": c.get("rs_60"),
                       "vol_ratio_5_20": c.get("vol_ratio_5_20")},
            "deep": {"selected": t in deep_selected, "quota": quota,
                     "selection_reason": ("deep_score rank %d <= quota %d"
                                          % (rank_of[t], quota)
                                          if t in deep_selected
                                          else "deep_score rank %d > quota %d"
                                          % (rank_of[t], quota))},
            "ta": None, "publication": None, "monitor": None,
            "portfolio": {"existing_position": t in positions,
                          "paper_entry_created": None,
                          "paper_entry_filled": None}}
        art_file = ev / "case_artifacts" / f"{t}_{session}.json"
        if t in disps or art_file.exists():
            sig = None
            if art_file.exists():
                sig = json.loads(art_file.read_text()).get("signal")
            rec["ta"] = {"attempted": True,
                         "artifact": (disps.get(t) or {}).get("artifact")
                                     or f"case_artifacts/{t}_{session}.json",
                         "final_signal": sig,
                         "valid": bool(disps.get(t))}
        if t in disps:
            rec["publication"] = {
                "disposition": disps[t].get("disposition"),
                "executable": disps[t].get("executable"),
                "reason": disps[t].get("violations"),
                "artifact": disps[t].get("artifact")}
        if w:
            rec["monitor"] = {
                "trigger_type": w.get("trigger_type"),
                "triggerable": triggerable,
                "triggered": any(e.startswith(f"paper_entry:")
                                 and t in e for e in emitted) or None,
                "blocked_reason": (st.get("risk_blocked") or {}).get(t)}
        tickers[t] = rec

    counts = {}
    for d in disps.values():
        counts[d["disposition"]] = counts.get(d["disposition"], 0) + 1
    excl_counts = {EXCLUSION_TAXONOMY.get(k, k.upper()): len(v)
                   for k, v in exclusions.items()}
    cohorts = {}
    for c in ranked:
        co = _cohort(rank_of[c["ticker"]])
        cohorts[co] = cohorts.get(co, 0) + 1

    doc = {
        "schema_version": 1,
        "session": session,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_universe": "wikipedia_indices+nasdaqtrader_common_stock",
        "raw_universe_count": pool.get("universe_size_raw"),
        "eligible_count": pool.get("universe_size_eligible"),
        "deep_quota": quota,
        "deep_selected_count": len(deep_selected),
        "ta_completed_count": len(disps) or None,
        "publication_disposition_counts": counts,
        "executable_watch_count": counts.get("EXECUTABLE_WATCH", 0),
        "triggered_count": None,   # prospective; filled by outcome layer (R2)
        "paper_entry_count": None,  # prospective; filled by outcome layer (R2)
        "provenance": {
            "candidate_pool_sha256": pool.get("artifact_sha256"),
            "intents_doc_sha256": _sha(intents_path.read_text())[:16]
            if intents_path.exists() else None,
            "backfilled": bool(incomplete),
            "incomplete_fields": incomplete,
        },
        "summary": {
            "excluded": excl_counts,
            "eligible": len(elig_feats) or pool.get("universe_size_eligible"),
            "rank_cohorts": cohorts,
            "deep_selected": deep_selected,
        },
        "tickers": tickers,
    }
    out_path.write_text(json.dumps(doc, indent=1, sort_keys=True))
    return doc


def latest_session() -> str:
    pools = sorted(EV.glob("candidate_pool_frozen_*.json"))
    return pools[-1].stem.rsplit("_", 1)[-1]


def status(session: str = "latest") -> str:
    if session == "latest":
        session = latest_session()
    p = FUNNEL_DIR / f"{session}.json"
    if not p.exists():
        return f"No funnel artifact for {session}"
    d = json.loads(p.read_text())
    s = d["summary"]
    lines = [f"ALPHA OPPORTUNITY FUNNEL — {session}", "",
             f"Raw universe: {d['raw_universe_count']}",
             f"Eligible: {d['eligible_count']}", "", "Excluded:"]
    for k, v in sorted(s["excluded"].items()):
        lines.append(f"  {k.lower()}: {v}")
    lines += ["", "Rank cohorts:"]
    for k in ("TOP_1_10", "RANK_11_25", "RANK_26_50", "RANK_51_100", "RANK_101_PLUS"):
        if k in s["rank_cohorts"]:
            lines.append(f"  {k}: {s['rank_cohorts'][k]}")
    lines += ["", f"Deep TA: {d['deep_selected_count']} selected / quota {d['deep_quota']}",
              "Publication:"]
    for k, v in sorted((d.get("publication_disposition_counts") or {}).items()):
        lines.append(f"  {k}: {v}")
    lines += [f"Executable: {d['executable_watch_count']}",
              f"Triggered: {d['triggered_count']}",
              f"Bought: {d['paper_entry_count']}"]
    if d["provenance"]["backfilled"]:
        lines.append(f"(backfilled; incomplete: {d['provenance']['incomplete_fields']})")
    return "\n".join(lines)


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "status":
        print(status(sys.argv[2]))
    elif len(sys.argv) > 2 and sys.argv[1] == "build":
        build(sys.argv[2])
    else:
        s = latest_session()
        build(s)
        print(status(s))
