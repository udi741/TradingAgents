#!/usr/bin/env python3
"""R2 rank-cohort outcome tracking (ex-post evaluation layer only).

Reads frozen R1 funnel artifacts (ex-ante authority — cohort membership is
never recomputed), attaches forward-market outcomes at standardized
horizons, append-only: one record per (session, ticker, horizon), written
once when mature. Never touches trading state. No LLM.

Usage:
  python -m alpha_rnd.cohort_outcomes update
  python -m alpha_rnd.cohort_outcomes status
  python -m alpha_rnd.cohort_outcomes session 2026-10-14

Prices: canonical yfinance auto_adjust=True (split/dividend-adjusted),
same convention as the discovery screener.
"""
import fcntl
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ta_eval_alpha import e17_screener as e17  # noqa: E402
from alpha_rnd import funnel  # noqa: E402

EV = ROOT / "evaluations" / "alpha_rnd_v1"
OUT_DIR = EV / "rank_cohort_outcomes"
LOG = ROOT / "alpha_rnd" / "cohort_outcomes.log"
LOCK = ROOT / "alpha_rnd" / "cohort_outcomes.lock"
HEALTH = ROOT / "alpha_rnd" / "cohort_outcomes_state.json"
BENCH = "SPY"
HORIZONS = {"H1": 1, "H5": 5, "H20": 20, "H60": 60}


def _log(msg: str) -> None:
    with open(LOG, "a") as f:
        f.write(f"{datetime.now(timezone.utc).isoformat()} {msg}\n")


def _health(**kw) -> None:
    try:
        h = json.loads(HEALTH.read_text()) if HEALTH.exists() else {}
    except Exception:
        h = {}
    h.update(kw)
    h["updated_at"] = datetime.now(timezone.utc).isoformat()
    tmp = HEALTH.with_suffix(".tmp")
    tmp.write_text(json.dumps(h, indent=1))
    tmp.replace(HEALTH)


def run_locked() -> dict:
    """Updater entrypoint for scheduled execution: non-blocking flock so an
    overlapping invocation exits cleanly; catch-up across offline gaps is
    inherent — update() walks every frozen session and matures all horizons
    whose target session has completed."""
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    with LOCK.open("w") as lf:
        try:
            fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            _log("update skipped: another run holds the lock")
            return {"skipped": "locked"}
        try:
            res = update()
            _health(last_run=res.get("latest_completed"),
                    last_success=datetime.now(timezone.utc).isoformat(),
                    sessions_touched=res.get("sessions_touched"),
                    status="OK")
            _log(f"update ok sessions={res['sessions_touched']}")
            return res
        except Exception as e:
            _health(last_run=datetime.now(timezone.utc).isoformat(),
                    status=f"ERROR {e!r}")
            _log(f"update ERROR {e!r}")
            raise


def _sessions_index() -> list[str]:
    """Completed regular sessions calendar from SPY (canonical source)."""
    end = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")
    d, _ = e17.fetch_batch_ohlcv(["SPY"], "2026-01-01", end, batch_size=1)
    spy = d["SPY"]
    today = pd.Timestamp.now(tz="US/Eastern").normalize().tz_localize(None)
    return [str(x.date()) for x in spy.index if x < today]


def _entry_and_targets(disc: str, cal: list[str]) -> dict | None:
    after = [s for s in cal if s > disc]
    if not after:
        return None
    entry = after[0]
    ei = cal.index(entry)
    tgt = {}
    for h, n in HORIZONS.items():
        j = ei + n - 1
        tgt[h] = cal[j] if j < len(cal) else None
    return {"entry": entry, "targets": tgt}


def _fetch(tickers, start, end):
    md, fails = {}, []
    CH = 250
    all_t = [BENCH] + tickers
    for i in range(0, len(all_t), CH):
        d, f = e17.fetch_batch_ohlcv(all_t[i:i + CH], start, end, batch_size=CH)
        md.update(d)
        fails += f
        time.sleep(10)
    return md, fails


def _outcome(df, entry_session, target_session) -> dict:
    df = df[df.index.strftime("%Y-%m-%d") >= entry_session]
    df = df[df.index.strftime("%Y-%m-%d") <= target_session]
    if df.empty:
        return None
    ent = df[df.index.strftime("%Y-%m-%d") == entry_session]
    tgt = df[df.index.strftime("%Y-%m-%d") == target_session]
    if ent.empty or tgt.empty:
        return None
    eo = float(ent["Open"].iloc[0]); tc = float(tgt["Close"].iloc[-1])
    hi = float(df["High"].max()); lo = float(df["Low"].min())
    return {"entry_open": round(eo, 4), "target_close": round(tc, 4),
            "raw_return_pct": round((tc / eo - 1) * 100, 3),
            "max_high": round(hi, 4), "min_low": round(lo, 4),
            "MFE_pct": round((hi / eo - 1) * 100, 3),
            "MAE_pct": round((lo / eo - 1) * 100, 3)}


def build_skeleton(session: str, doc: dict, cal: list[str]) -> dict:
    et = _entry_and_targets(session, cal)
    tickers = {}
    for t, rec in (doc.get("tickers") or {}).items():
        if not (rec.get("eligibility") or {}).get("eligible"):
            continue
        sc = rec.get("screen") or {}
        stage = ("DEEP_SELECTED" if (rec.get("deep") or {}).get("selected")
                 else "POOL_SELECTED_NOT_DEEP" if sc.get("pool_selected") or
                 (rec.get("deep") or {}).get("selection_reason", "").startswith("deep_score rank")
                 else "ELIGIBLE_NOT_POOL_SELECTED")
        # pool membership is proven by presence in pool_rank
        if sc.get("pool_rank") is not None and not (rec.get("deep") or {}).get("selected"):
            stage = "POOL_SELECTED_NOT_DEEP"
        tickers[t] = {
            "cohort": sc.get("cohort"), "primary_rank": sc.get("primary_rank"),
            "lane_ranks": sc.get("lane_ranks"), "pool_rank": sc.get("pool_rank"),
            "pool_selected": sc.get("pool_rank") is not None,
            "deep_selected": bool((rec.get("deep") or {}).get("selected")),
            "stage": stage,
            "entry_session": et["entry"] if et else None,
            "horizons": {h: {"status": "PENDING", "target_session": tgt}
                         for h, tgt in (et["targets"].items() if et else {})}}
    return {"schema_version": 1, "session": session, "created_at":
            datetime.now(timezone.utc).isoformat(),
            "funnel_backfilled": doc.get("provenance", {}).get("backfilled", False),
            "benchmark": BENCH, "price_convention": "auto_adjusted",
            "entry_reference": "NEXT_REGULAR_OPEN",
            "tickers": tickers}


def update(verbose=True) -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cal = _sessions_index()
    latest = cal[-1]
    touched = []
    for fp in sorted((EV / "opportunity_funnel").glob("*.json")):
        session = fp.stem
        doc = json.loads(fp.read_text())
        op = OUT_DIR / f"{session}.json"
        if op.exists():
            out = json.loads(op.read_text())
        else:
            out = build_skeleton(session, doc, cal)
            op.write_text(json.dumps(out, indent=1, sort_keys=True))
        tickers = [t for t, r in out["tickers"].items()
                   if any(h["status"] == "PENDING" and h["target_session"]
                          and h["target_session"] <= latest
                          for h in r["horizons"].values())]
        if not tickers:
            continue
        start = min(r["entry_session"] for r in out["tickers"].values()
                    if r.get("entry_session"))
        end_excl = (pd.Timestamp(latest) + pd.Timedelta(days=1)
                    ).strftime("%Y-%m-%d")
        md, fails = _fetch(tickers, start, end_excl)
        changed = False
        for t in tickers:
            rec = out["tickers"][t]
            df = md.get(t)
            bdf = md.get(BENCH)
            for h, hrec in rec["horizons"].items():
                if hrec["status"] != "PENDING" or not hrec["target_session"] \
                        or hrec["target_session"] > latest:
                    continue
                if df is None and t in fails:
                    continue  # transient fetch failure -> stays PENDING
                changed = True
                if df is None:
                    hrec.update({"status": "DATA_UNAVAILABLE",
                                 "evaluated_at": datetime.now(timezone.utc)
                                 .isoformat()})
                    continue
                o = _outcome(df, rec["entry_session"], hrec["target_session"])
                b = _outcome(bdf, rec["entry_session"],
                             hrec["target_session"]) if bdf is not None else None
                if o is None:
                    hrec.update({"status": "DATA_UNAVAILABLE",
                                 "evaluated_at": datetime.now(timezone.utc)
                                 .isoformat()})
                    continue
                hrec.update({"status": "MATURED", **o,
                             "evaluated_at": datetime.now(timezone.utc)
                             .isoformat(),
                             "benchmark_return_pct": b["raw_return_pct"]
                             if b else None,
                             "excess_return_pct": round(
                                 o["raw_return_pct"] - b["raw_return_pct"], 3)
                             if b else None})
        if changed:
            out["last_update"] = datetime.now(timezone.utc).isoformat()
            op.write_text(json.dumps(out, indent=1, sort_keys=True))
            touched.append(session)
            if verbose:
                print(f"matured outcomes: {session} ({len(tickers)} tickers)")
    return {"sessions_touched": touched, "latest_completed": latest}


def _agg(recs, field):
    v = [r[field] for r in recs if r.get(field) is not None]
    return round(sum(v) / len(v), 3) if v else None


def status() -> str:
    lines = ["ALPHA RANK COHORT OUTCOMES", ""]
    docs = [json.loads(p.read_text()) for p in sorted(OUT_DIR.glob("*.json"))]
    clean = [d for d in docs if not d.get("funnel_backfilled")]
    lines.append(f"Prospective sessions tracked: {len(docs)} "
                 f"(clean: {len(clean)})")
    for h in HORIZONS:
        groups = {}
        for d in docs:
            for t, r in d["tickers"].items():
                hr = r["horizons"].get(h)
                if not hr:
                    continue
                g = groups.setdefault(r["cohort"] or "?", {"n": 0, "m": [],
                                                         "p": 0, "u": 0})
                g["n"] += 1
                if hr["status"] == "MATURED":
                    g["m"].append(hr)
                elif hr["status"] == "PENDING":
                    g["p"] += 1
                else:
                    g["u"] += 1
        lines.append(f"\n{h}:")
        for co, g in sorted(groups.items()):
            lines.append(
                f"  {co}: N={g['n']} matured={len(g['m'])} pending={g['p']} "
                f"unavail={g['u']} "
                f"mean_ret={_agg(g['m'], 'raw_return_pct')} "
                f"mean_excess={_agg(g['m'], 'excess_return_pct')} "
                f"mean_MFE={_agg(g['m'], 'MFE_pct')} "
                f"mean_MAE={_agg(g['m'], 'MAE_pct')}")
    return "\n".join(lines)


def session_report(session: str) -> str:
    p = OUT_DIR / f"{session}.json"
    if not p.exists():
        return f"No R2 outcome record for {session}"
    d = json.loads(p.read_text())
    lines = [f"R2 OUTCOMES — {session}",
             f"tickers tracked: {len(d['tickers'])}",
             f"entry (next open): "
             f"{next(iter(d['tickers'].values()), {}).get('entry_session')}",
             f"backfilled-funnel: {d.get('funnel_backfilled')}"]
    by_stage = {}
    for r in d["tickers"].values():
        by_stage.setdefault(r["stage"], 0)
        by_stage[r["stage"]] += 1
    lines.append("stages: " + json.dumps(by_stage))
    for h in HORIZONS:
        st = {}
        for r in d["tickers"].values():
            s = (r["horizons"].get(h) or {}).get("status")
            if s:
                st[s] = st.get(s, 0) + 1
        lines.append(f"  {h}: {st}")
    return "\n".join(lines)


def tracker_status() -> str:
    h = json.loads(HEALTH.read_text()) if HEALTH.exists() else {}
    stats = {"MATURED": 0, "PENDING": 0, "DATA_UNAVAILABLE": 0}
    sessions = [p.stem for p in OUT_DIR.glob("*.json")]
    clean = 0
    for p in OUT_DIR.glob("*.json"):
        d = json.loads(p.read_text())
        clean += 0 if d.get("funnel_backfilled") else 1
        for r in d["tickers"].values():
            for hr in r["horizons"].values():
                stats[hr["status"]] = stats.get(hr["status"], 0) + 1
    return "\n".join([
        "R2 OUTCOME TRACKER", "",
        f"scheduler: {h.get('status', 'NEVER_RUN')}",
        f"last successful run: {h.get('last_success')}",
        f"prospective sessions: {len(sessions)} (clean: {clean})",
        f"pending horizons: {stats.get('PENDING', 0)}",
        f"matured records: {stats.get('MATURED', 0)}",
        f"permanent unavailable: {stats.get('DATA_UNAVAILABLE', 0)}",
        "first clean session: (first schema-v2 funnel session)"])


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "update":
        print(json.dumps(run_locked(), indent=1))
    elif cmd == "health":
        print(tracker_status())
    elif cmd == "session":
        print(session_report(sys.argv[2]))
    else:
        print(status())
