#!/usr/bin/env python3
"""R3: TA accept/reject outcome tracking — derived read-only view.

Joins frozen ex-ante evidence (funnel artifact -> TA signal + publication
disposition) to canonical R2 outcomes (rank_cohort_outcomes/). Computed on
demand; no separate collection, no fetches, no LLM. Current-by-construction:
when R2 matures a horizon, the next status call reflects it.

Usage:
  python -m alpha_rnd.ta_outcomes status
  python -m alpha_rnd.ta_outcomes session 2026-10-14
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EV = ROOT / "evaluations" / "alpha_rnd_v1"
FUNNEL = EV / "opportunity_funnel"
OUT_DIR = EV / "rank_cohort_outcomes"
HORIZONS = ("H1", "H5", "H20", "H60")

# normalization discovered from frozen artifacts (Buy/Overweight/Hold/
# Sell/Underweight observed in production artifacts)
SIGNAL_GROUP = {"Buy": "POSITIVE", "Overweight": "POSITIVE",
                "Hold": "NEUTRAL",
                "Sell": "NEGATIVE", "Underweight": "NEGATIVE"}
POSITIVE = {"Buy", "Overweight"}
NEUTRAL = {"Hold"}
NEGATIVE = {"Sell", "Underweight"}


def norm_group(sig: str | None) -> str:
    return SIGNAL_GROUP.get(sig, "UNKNOWN")


def _sessions() -> list[tuple[str, bool, dict, dict]]:
    """(session, is_clean, funnel_doc, outcomes_doc)."""
    out = []
    for fp in sorted(FUNNEL.glob("*.json")):
        doc = json.loads(fp.read_text())
        op = OUT_DIR / fp.name
        odoc = json.loads(op.read_text()) if op.exists() else {}
        out.append((fp.stem,
                    not doc.get("provenance", {}).get("backfilled", True),
                    doc, odoc))
    return out


def observations(session: str | None = None,
                 clean_only: bool = True) -> list[dict]:
    """One frozen decision observation per (session, deep ticker)."""
    obs = []
    for sess, clean, fdoc, odoc in _sessions():
        if session and sess != session:
            continue
        if clean_only and not clean:
            continue
        for t, rec in (fdoc.get("tickers") or {}).items():
            if not (rec.get("deep") or {}).get("selected"):
                continue  # TA population = deep-analyzed only
            pub = rec.get("publication") or {}
            ta = rec.get("ta") or {}
            disp = pub.get("disposition")
            ctx = ("OPEN_POSITION_MANAGEMENT"
                   if disp == "OPEN_POSITION_MANAGEMENT"
                   or (rec.get("portfolio") or {}).get("existing_position")
                   else "NEW_ENTRY")
            r2 = (odoc.get("tickers") or {}).get(t) or {}
            obs.append({
                "session": sess, "ticker": t, "clean": clean,
                "raw_ta_signal": ta.get("final_signal"),
                "normalized_ta_group": norm_group(ta.get("final_signal")),
                "artifact": ta.get("artifact"),
                "disposition": disp,
                "executable": pub.get("executable"),
                "decision_context": ctx,
                "r2": r2})
    return obs


def _agg(vals):
    v = [x for x in vals if x is not None]
    if not v:
        return "n/a", "n/a"
    vs = sorted(v)
    med = vs[len(vs) // 2] if len(vs) % 2 else (vs[len(vs) // 2 - 1] + vs[len(vs) // 2]) / 2
    return round(sum(v) / len(v), 3), round(med, 3)


def _line(label, recs, h):
    n = len(recs)
    mat = [r for r in recs if (r["r2"].get("horizons") or {}).get(h, {}).get("status") == "MATURED"]
    una = [r for r in recs if (r["r2"].get("horizons") or {}).get(h, {}).get("status") == "DATA_UNAVAILABLE"]
    hrs = [r["r2"]["horizons"][h] for r in mat]
    mr, mdr = _agg([x["raw_return_pct"] for x in hrs])
    me, mde = _agg([x["excess_return_pct"] for x in hrs])
    mf, mdf = _agg([x["MFE_pct"] for x in hrs])
    ma, mda = _agg([x["MAE_pct"] for x in hrs])
    return (f"  {label}: N={n} matured={len(mat)} pending={n-len(mat)-len(una)} "
            f"unavail={len(una)} ret={mr}/{mdr} excess={me}/{mde} "
            f"MFE={mf}/{mdf} MAE={ma}/{mda}")


def status() -> str:
    obs = observations(clean_only=False)
    lines = ["ALPHA TA OUTCOME EVALUATION", ""]
    clean_obs = [o for o in obs if o["clean"]]
    diag = [o for o in obs if not o["clean"]]
    lines.append(f"Clean prospective deep-analyzed: {len(clean_obs)} "
                 f"(diagnostic/backfilled: {len(diag)})")
    for h in HORIZONS:
        lines.append(f"\n=== {h} (clean sessions only) ===")
        if not clean_obs:
            lines.append("  no clean prospective observations yet")
            continue
        for grp in ("POSITIVE", "NEUTRAL", "NEGATIVE", "UNKNOWN"):
            recs = [o for o in clean_obs if o["normalized_ta_group"] == grp]
            if recs:
                lines.append(_line(f"TA {grp}", recs, h))
        for disp in sorted({o["disposition"] for o in clean_obs if o["disposition"]}):
            recs = [o for o in clean_obs if o["disposition"] == disp]
            lines.append(_line(f"PUB {disp}", recs, h))
        for ex in (True, False):
            recs = [o for o in clean_obs
                    if o["executable"] is ex and o["decision_context"] == "NEW_ENTRY"]
            if recs:
                lines.append(_line(f"EXEC {ex}", recs, h))
    if diag:
        lines.append("\n(diagnostic sessions excluded from headline stats)")
    return "\n".join(lines)


def session_report(session: str) -> str:
    obs = observations(session=session, clean_only=False)
    if not obs:
        return f"No deep-analyzed tickers for {session}"
    lines = [f"R3 TA OUTCOMES — {session}", ""]
    for o in sorted(obs, key=lambda x: x["ticker"]):
        hz = " ".join(
            f"{h}:{(o['r2'].get('horizons') or {}).get(h, {}).get('status', '-')}"
            for h in HORIZONS)
        rets = " ".join(
            f"{h}={o['r2']['horizons'][h]['raw_return_pct']}"
            for h in HORIZONS
            if (o["r2"].get("horizons") or {}).get(h, {}).get("status") == "MATURED")
        lines.append(
            f"{o['ticker']:6} {str(o['raw_ta_signal']):11} "
            f"{o['normalized_ta_group']:9} {str(o['disposition']):26} "
            f"exec={o['executable']} ctx={o['decision_context']}")
        lines.append(f"       {hz}  {rets}")
    return "\n".join(lines)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "session":
        print(session_report(sys.argv[2]))
    else:
        print(status())
