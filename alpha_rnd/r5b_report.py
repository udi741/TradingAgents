#!/usr/bin/env python3
"""R5B paired experiment analysis — CURRENT_PRODUCTION vs
ANALYZE_ALL_CANDIDATES on replay sessions.

Joins frozen replay manifests + TA artifacts to canonical R2 outcome
semantics (next-open entry, H1/H5/H20, SPY excess, MFE/MAE). Read-only;
RETROSPECTIVE_RESEARCH only — never merged into prospective evidence.

  python -m alpha_rnd.r5b_report [session ...]
"""
import json
import pickle
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ta_eval_alpha import e17_screener as e17  # noqa: E402
from alpha_rnd import cohort_outcomes as co  # noqa: E402
from alpha_rnd.ta_outcomes import norm_group  # noqa: E402

EV = ROOT / "evaluations" / "alpha_rnd_v1"
REPLAYS = EV / "replays"


def _sessions_dirs() -> list[Path]:
    return sorted(p for p in REPLAYS.glob("*") if p.is_dir())


def session_compare(session: str) -> dict:
    """CURRENT_PRODUCTION vs excluded-from-TA cohorts, joined to outcomes."""
    adir = REPLAYS / session / "ANALYZE_ALL_CANDIDATES"
    man = json.loads((adir / "manifest.json").read_text())
    pub = json.loads((adir / "publication.json").read_text())
    res = json.loads((adir / "run_result.json").read_text())
    members = man["candidate_pool_members"]
    # production-selected subset = funnel deep.selected (frozen evidence);
    # fallback: production case artifacts = the set TA actually ran
    fdoc_p = EV / "opportunity_funnel" / f"{session}.json"
    if fdoc_p.exists():
        fdoc = json.loads(fdoc_p.read_text())
        prod = {t for t, r in (fdoc["tickers"]).items()
                if (r.get("deep") or {}).get("selected")}
    else:
        prod = {p.stem.rsplit("_", 1)[0]
                for p in (EV / "case_artifacts").glob(f"*_{session}.json")}
    excluded = [t for t in members if t not in prod]
    arts = {}
    for t in members:
        p = adir / "case_artifacts" / f"{t}_{session}.json"
        if p.exists():
            a = json.loads(p.read_text())
            arts[t] = {"signal": a.get("signal"),
                       "group": norm_group(a.get("signal"))}
    # outcomes: next-open entry, R2 _outcome semantics (phase-2 fetch allowed)
    cal = co._sessions_index()
    et = co._entry_and_targets(session, cal)
    outc = {}
    if et:
        entry = et["entry"]
        targets = {h: et["targets"].get(h) for h in ("H1", "H5", "H20")}
        md, _ = co._fetch(members + ["SPY"], entry,
                          (pd.Timestamp(cal[-1]) + pd.Timedelta(days=1)
                           ).strftime("%Y-%m-%d"))
        bdf = md.get("SPY")
        for t in members:
            df = md.get(t)
            rec = {}
            for h, ts in targets.items():
                if not ts or ts > cal[-1]:
                    rec[h] = {"status": "PENDING"}
                    continue
                o = co._outcome(df, entry, ts) if df is not None else None
                b = co._outcome(bdf, entry, ts)
                rec[h] = ({"status": "MATURED", **o,
                           "excess": round(o["raw_return_pct"]
                                           - b["raw_return_pct"], 3)}
                          if o and b else {"status": "DATA_UNAVAILABLE"})
            outc[t] = rec
    def agg(ts, h):
        vs = [outc[t][h] for t in ts
              if outc.get(t, {}).get(h, {}).get("status") == "MATURED"]
        ret = [v["raw_return_pct"] for v in vs]
        exc = [v["excess"] for v in vs]
        mfe = [v["MFE_pct"] for v in vs]
        mae = [v["MAE_pct"] for v in vs]
        med = sorted(ret)
        return {"N": len(ts), "matured": len(vs),
                "mean_ret": round(sum(ret) / len(ret), 2) if ret else None,
                "median_ret": round(med[len(med) // 2], 2) if ret else None,
                "mean_excess": round(sum(exc) / len(exc), 2) if exc else None,
                "mean_MFE": round(sum(mfe) / len(mfe), 2) if mfe else None,
                "mean_MAE": round(sum(mae) / len(mae), 2) if mae else None}
    # winner-capture: rank whole pool by H5
    h5 = sorted(((t, outc[t]["H5"]["raw_return_pct"]) for t in members
                 if outc.get(t, {}).get("H5", {}).get("status") == "MATURED"),
                key=lambda x: -x[1])
    top5 = [t for t, _ in h5[:5]]
    top10 = [t for t, _ in h5[:10]]
    excl_pos = [t for t in excluded
                if arts.get(t, {}).get("group") == "POSITIVE"]
    return {
        "session": session, "pool": len(members),
        "current_production_selected": sorted(prod & set(members)),
        "excluded": excluded,
        "ta_complete": res["ta_completed"], "ta_not_run": res["ta_not_run"],
        "selected_agg": {h: agg(sorted(prod & set(members)), h)
                         for h in ("H1", "H5")},
        "excluded_agg": {h: agg(excluded, h) for h in ("H1", "H5")},
        "excluded_positive": excl_pos,
        "excluded_positive_agg": {h: agg(excl_pos, h) for h in ("H1", "H5")},
        "signals_excluded": {t: arts.get(t) for t in excluded},
        "dispositions": {t: pub["dispositions"].get(t, {}).get("disposition")
                         for t in members},
        "top5_h5": top5, "top10_h5": top10,
        "top5_captured": [t for t in top5 if t in prod],
        "top10_captured": [t for t in top10 if t in prod],
        "h5_ranked": h5}


def report(sessions: list[str]) -> str:
    lines = ["ALPHA R5B — CURRENT_PRODUCTION vs ANALYZE_ALL_CANDIDATES",
             "RETROSPECTIVE_RESEARCH (not prospective evidence)", ""]
    tot_pool = tot_sel = tot_top5 = tot_top10 = 0
    for s in sessions:
        r = session_compare(s)
        lines.append(f"=== {s} pool={r['pool']} "
                     f"ta_complete={r['ta_complete']}/{r['pool']}")
        for grp in ("selected_agg", "excluded_agg", "excluded_positive_agg"):
            for h in ("H1", "H5"):
                lines.append(f"  {grp} {h}: {r[grp][h]}")
        lines.append(f"  top5 H5: {r['top5_h5']} "
                     f"(captured by current: {r['top5_captured']})")
        lines.append(f"  top10 H5: {r['top10_h5']} "
                     f"(captured: {r['top10_captured']})")
        tot_pool += r["pool"]
        tot_sel += len(r["current_production_selected"])
        tot_top5 += len(r["top5_captured"])
        tot_top10 += len(r["top10_captured"])
    lines += ["", "AGGREGATE:",
              f"  pool total {tot_pool}, TA selected {tot_sel}, "
              f"top5 captured {tot_top5}/15, top10 {tot_top10}/30"]
    return "\n".join(lines)


if __name__ == "__main__":
    ss = sys.argv[1:] or [p.name for p in _sessions_dirs()
                          if (p / "ANALYZE_ALL_CANDIDATES" /
                              "run_result.json").exists()]
    print(report(ss))
