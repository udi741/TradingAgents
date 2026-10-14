#!/usr/bin/env python3
"""R6 low-price shadow lane — observational only.

Reads the SAME raw universe + market cache discovery already fetched
(never refetches, never alters ALPHA rules). Freezes one artifact per
session for the $1.00-$4.99 population, with counterfactual non-price
eligibility and intra-shadow lane ranks. No TA, no watches, no orders.

  python -m alpha_rnd.low_price_shadow build <session>
  python -m alpha_rnd.low_price_shadow status
  python -m alpha_rnd.low_price_shadow session <d>
  python -m alpha_rnd.low_price_shadow case <d> <t>
"""
import json
import pickle
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ta_eval_alpha import e17_screener as e17  # noqa: E402
import evaluations.alpha_rnd_v1.discovery as disc  # noqa: E402

EV = ROOT / "evaluations" / "alpha_rnd_v1"
LP_DIR = EV / "low_price_shadow"
MAIN_PRICE_FLOOR = disc.MIN_PRICE      # 5.0 (observed, not changed)
LP_FLOOR = 1.0
HORIZONS = ("H1", "H5", "H20", "H60")


def _band(p: float) -> str:
    for lo in (1, 2, 3, 4):
        if lo <= p < lo + 1:
            return f"${lo}.00-{lo}.99"
    return "other"


def build(session: str) -> dict:
    """Freeze the low-price shadow cohort for `session` from already-fetched
    data. Idempotent: existing artifact is returned unchanged."""
    LP_DIR.mkdir(parents=True, exist_ok=True)
    out_path = LP_DIR / f"{session}.json"
    if out_path.exists():
        return json.loads(out_path.read_text())
    uni = json.loads((EV / "universe_raw.json").read_text())
    if uni["session"] != session:
        raise RuntimeError(f"universe_raw.json is for {uni['session']}, "
                           f"not {session} — cannot rebuild honestly")
    mc = EV / f"market_cache_{session}.pkl"
    if not mc.exists():
        raise RuntimeError(f"no market cache for {session}")
    md, failures = pickle.loads(mc.read_bytes())
    spy_close = md["SPY"]["Close"]
    spy_close = spy_close[spy_close.index <= pd.Timestamp(session)]

    tickers = {}
    below1 = 0
    for u in uni["constituents"]:
        t = u["ticker"]
        df = md.get(t)
        if df is None:
            continue
        df = df[df.index <= pd.Timestamp(session)]
        if df.empty:
            continue
        close = float(df["Close"].iloc[-1])
        if close < LP_FLOOR:
            below1 += 1
            continue
        if close >= MAIN_PRICE_FLOOR:
            continue
        f = e17.compute_features(df["Close"], df["High"], df["Volume"], spy_close)
        nonprice_excl = []
        if f is None:
            nonprice_excl.append("INSUFFICIENT_HISTORY")
        elif f["median_dollar_volume_20"] < disc.MIN_MEDIAN_DV20:
            nonprice_excl.append("LIQUIDITY")
        rec = {
            "ticker": t, "session": session, "price": round(close, 4),
            "price_band": _band(close),
            "universe_sources": u.get("indices"),
            "security_type": "universe_member",  # passed universe junk filter
            "counterfactual": {
                "would_be_main_eligible_if_price_floor_removed":
                    not nonprice_excl,
                "nonprice_exclusion_reasons": nonprice_excl},
            "liquidity": {"median_dv20": int(f["median_dollar_volume_20"])
                          if f else None,
                          "main_threshold": disc.MIN_MEDIAN_DV20,
                          "passes": bool(f and f["median_dollar_volume_20"]
                                         >= disc.MIN_MEDIAN_DV20)},
            "features": ({"ret_5": round(f["ret_5"], 4),
                          "ret_20": round(f["ret_20"], 4),
                          "rs_60": round(f["rs_60"], 4),
                          "rsi_14": round(f["rsi_14"], 1),
                          "pullback_20": round(f["pullback_20"], 3),
                          "vol_ratio_5_20": round(f["volume_ratio_5_20"], 2)}
                         if f else None),
            "feature_unavailable_reason": None if f else "insufficient_history",
            # funnel-compatible shape so the R2 outcome engine consumes it
            "eligibility": {"eligible": True},
            "deep": {"selected": False},
        }
        tickers[t] = rec

    # shadow lane scoring over the low-price population only
    feats_ok = {t: e17.compute_features(
                    md[t][md[t].index <= pd.Timestamp(session)]["Close"],
                    md[t][md[t].index <= pd.Timestamp(session)]["High"],
                    md[t][md[t].index <= pd.Timestamp(session)]["Volume"],
                    spy_close)
                for t, r in tickers.items() if r["features"]}
    feats_ok = {t: f for t, f in feats_ok.items() if f}
    fdf = pd.DataFrame(feats_ok).T
    if len(fdf):
        lanes = {"A": e17.score_lane_a(fdf), "B": e17.score_lane_b(fdf),
                 "C": e17.score_lane_c(fdf)}
        for name, s in lanes.items():
            s = s.sort_values(ascending=False)
            for i, t in enumerate(s.index, 1):
                tickers[t].setdefault("shadow_lanes", {})[name] = [
                    round(float(s[t]), 4), i]
        for t, r in tickers.items():
            l = r.get("shadow_lanes") or {}
            r["screen"] = {"cohort": "LP_PRIMARY",
                           "primary_rank": min((v[1] for v in l.values()),
                                               default=None),
                           "lane_ranks": {k: v[1] for k, v in l.items()}}
            r["cohort"] = ("LP_PASSES_NONPRICE_MAIN_FILTERS"
                           if r["counterfactual"]
                           ["would_be_main_eligible_if_price_floor_removed"]
                           else "LP_" + "+".join(r["counterfactual"]
                                                 ["nonprice_exclusion_reasons"]))
    for t, r in tickers.items():
        r.setdefault("screen", {"cohort": r.get("cohort", "LP_NO_FEATURES")})
        r.setdefault("cohort", r.get("screen", {}).get("cohort", "LP_OTHER"))

    counts = {"below_1": below1, "price_1_to_5": len(tickers)}
    for r in tickers.values():
        for reason in r["counterfactual"]["nonprice_exclusion_reasons"]:
            counts[f"fails_{reason.lower()}"] = \
                counts.get(f"fails_{reason.lower()}", 0) + 1
    counts["passes_nonprice_main_filters"] = sum(
        1 for r in tickers.values()
        if r["counterfactual"]["would_be_main_eligible_if_price_floor_removed"])
    doc = {"schema_version": 1, "session": session,
           "created_at": datetime.now(timezone.utc).isoformat(),
           "shadow_only": True, "note": "R6 observational lane; never traded",
           "thresholds": {"main_price_floor": MAIN_PRICE_FLOOR,
                          "low_price_floor": LP_FLOOR,
                          "min_history": disc.MIN_HISTORY,
                          "min_median_dv20": disc.MIN_MEDIAN_DV20},
           "counts": counts,
           "provenance": {"universe_raw_sha": disc.sha(
                              json.dumps(uni["constituents"],
                                         sort_keys=True))[:16],
                          "market_cache": f"market_cache_{session}.pkl"},
           "tickers": tickers}
    out_path.write_text(json.dumps(doc, indent=1, sort_keys=True))
    return doc


def status() -> str:
    docs = [json.loads(p.read_text()) for p in sorted(LP_DIR.glob("*.json"))]
    lines = ["ALPHA LOW-PRICE SHADOW", ""]
    lines.append(f"Sessions tracked: {len(docs)}")
    if docs:
        d = docs[-1]
        c = d["counts"]
        lines += [f"Latest session: {d['session']}",
                  f"$1-$5 names: {c['price_1_to_5']}",
                  f"below $1 (not in cohort): {c['below_1']}",
                  f"price-floor-only excluded "
                  f"(pass all non-price filters): {c['passes_nonprice_main_filters']}"]
        by_band = {}
        for r in d["tickers"].values():
            by_band[r["price_band"]] = by_band.get(r["price_band"], 0) + 1
        lines.append("price bands: " + json.dumps(by_band, sort_keys=True))
    return "\n".join(lines)


def session_report(session: str) -> str:
    p = LP_DIR / f"{session}.json"
    if not p.exists():
        return f"No R6 shadow artifact for {session}"
    d = json.loads(p.read_text())
    lines = [f"LOW-PRICE SHADOW — {session}", json.dumps(d["counts"], indent=1)]
    top = sorted(d["tickers"].values(),
                 key=lambda r: (r["screen"].get("primary_rank") or 9999))[:15]
    for r in top:
        lines.append(f"  {r['ticker']:6} ${r['price']} {r['cohort']} "
                     f"prank={r['screen'].get('primary_rank')}")
    return "\n".join(lines)


def case_report(session: str, ticker: str) -> str:
    p = LP_DIR / f"{session}.json"
    if not p.exists() or ticker not in json.loads(p.read_text())["tickers"]:
        return f"No R6 record for {ticker} @ {session}"
    return json.dumps(json.loads(p.read_text())["tickers"][ticker],
                      indent=1)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "build":
        print(json.dumps(build(sys.argv[2])["counts"]))
    elif cmd == "session":
        print(session_report(sys.argv[2]))
    elif cmd == "case":
        print(case_report(sys.argv[2], sys.argv[3]))
    else:
        print(status())
