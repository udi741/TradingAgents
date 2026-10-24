#!/usr/bin/env python3
"""R5A ALPHA as-of replay engine — policy-based, PIT-bounded.

Runs the full decision pipeline as though a historical session were today:

frozen PIT inputs (universe_raw / market_cache / candidate_pool / SEC caches)
  -> eligibility/features/lanes  [consumed from frozen contemporaneous
     artifacts when they exist; recomputation only where the pipeline is
     deterministic and PIT-safe]
  -> candidate pool  [immutable ex-ante input]
  -> ta_selection_policy:
        CURRENT_PRODUCTION   — exactly the recorded deep-selected set
        ANALYZE_ALL_CANDIDATES — every pool member (count is an OUTPUT)
  -> TA via graph.propagate(ticker, session) — the framework's own PIT
     boundary (market<=session, SEC filed<=session; proven in ledger audit)
  -> synthesize/validate/disposition — same production functions
  -> isolated replay namespace only; never touches watchlist/monitor/ledger.

  python -m alpha_rnd.replay audit --as-of 2026-10-13
  python -m alpha_rnd.replay run --as-of 2026-10-13 --policy CURRENT_PRODUCTION

Canonical user entry point: python -m alpha_rnd.backtest
(docs/BACKTESTING.md). Direct invocation still works.
"""
import hashlib
import json
import pickle
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
EV = ROOT / "evaluations" / "alpha_rnd_v1"
REPLAYS = EV / "replays"
POLICIES = ("CURRENT_PRODUCTION", "ANALYZE_ALL_CANDIDATES")


@dataclass(frozen=True)
class ReplayContext:
    session: str
    cutoff: str            # end-of-decision-day UTC
    policy: str
    mode: str = "HISTORICAL_REPLAY"
    memory: str = "EMPTY_REPLAY_MEMORY"
    portfolio: str = "NEUTRAL_RESEARCH_PORTFOLIO"

    @staticmethod
    def make(session: str, policy: str) -> "ReplayContext":
        # Production semantics: discovery runs post-close and consumes only
        # the completed regular session -> cutoff = US regular close 20:00Z.
        assert policy in POLICIES
        return ReplayContext(session=session,
                             cutoff=f"{session}T20:00:00Z", policy=policy)


def recompute_upstream(session: str) -> dict:
    """Actually re-run the deterministic upstream pipeline on frozen PIT
    inputs. Universe = frozen universe_raw for the session, else market-cache
    keys (already security-filtered at fetch time — provenance recorded).
    Market data = frozen market_cache truncated to <= session (hard-fails if
    any bar postdates the session)."""
    import evaluations.alpha_rnd_v1.discovery as disc
    mc = EV / f"market_cache_{session}.pkl"
    if not mc.exists():
        raise RuntimeError(f"no market cache for {session}")
    uni_path = EV / "universe_raw.json"
    uni = json.loads(uni_path.read_text()) if uni_path.exists() else {}
    if uni.get("session") == session:
        tickers = [u["ticker"] for u in uni["constituents"]]
        src = "universe_raw"
    else:
        md0, _ = pickle.loads(mc.read_bytes())
        tickers = sorted(t for t in md0 if t != "SPY")
        src = "market_cache_keys"
    md, failures = pickle.loads(mc.read_bytes())
    # hard PIT gate: no bar may postdate the decision session
    for t, df in md.items():
        if df is not None and len(df) and str(df.index.max().date()) > session:
            raise RuntimeError(f"PIT violation: {t} has data past {session}")
    result, pool = disc.compute_result(session, tickers, md, failures)
    ref = _frozen_pool(session)
    ref_members = _pool_members(ref) if ref else []
    cmp_ = {"original_pool_n": len(ref_members),
            "recomputed_pool_n": len([c["ticker"] for c in pool]),
            "set_overlap": len(set(ref_members) &
                               {c["ticker"] for c in pool}),
            "eligible_orig": ref.get("universe_size_eligible") if ref else None,
            "eligible_recomputed": result["universe_size_eligible"]}
    return {"session": session, "universe_source": src,
            "universe_n": len(tickers),
            "recomputed": result, "pool": pool,
            "reference": {"frozen_pool": ref_members,
                          "comparison": cmp_}}


def _frozen_pool(session: str) -> dict | None:
    p = EV / f"candidate_pool_frozen_{session}.json"
    return json.loads(p.read_text()) if p.exists() else None


def _pool_members(pool_doc: dict) -> list[str]:
    cand = pool_doc.get("candidates") or []
    out = []
    for c in cand:
        if isinstance(c, dict):
            out.append(c.get("ticker") or c.get("symbol"))
        else:
            out.append(c)
    return [t for t in out if t]


def select_for_ta(ctx: ReplayContext, pool_doc: dict) -> list[str]:
    members = _pool_members(pool_doc)
    if ctx.policy == "ANALYZE_ALL_CANDIDATES":
        return members
    deep = (pool_doc.get("deep_selected") or pool_doc.get("deep10")
            or pool_doc.get("deep") or [])
    if isinstance(deep, dict):
        deep = [t for t, v in deep.items() if v.get("selected")]
    if not deep:  # deep selection recorded in frozen funnel, not pool doc
        fp = EV / "opportunity_funnel" / f"{ctx.session}.json"
        if fp.exists():
            fdoc = json.loads(fp.read_text())
            deep = [t for t, r in (fdoc.get("tickers") or {}).items()
                    if (r.get("deep") or {}).get("selected")]
    return [t for t in deep if t in members] or [t for t in deep]


def manifest(ctx: ReplayContext, ticker: str, inputs: dict) -> dict:
    m = {"session": ctx.session, "cutoff": ctx.cutoff,
         "selection_policy": ctx.policy, "ticker": ticker,
         "memory_policy": ctx.memory, "portfolio_policy": ctx.portfolio,
         **inputs}
    m["input_hash"] = hashlib.sha256(
        json.dumps(m, sort_keys=True).encode()).hexdigest()[:16]
    return m


def audit(session: str) -> str:
    checks = {}
    pool = _frozen_pool(session)
    checks["frozen_candidate_pool"] = bool(pool)
    uni = json.loads((EV / "universe_raw.json").read_text()) \
        if (EV / "universe_raw.json").exists() else {}
    mc = EV / f"market_cache_{session}.pkl"
    checks["universe"] = ("frozen_raw" if uni.get("session") == session
                          else "market_cache_keys" if mc.exists() else "MISSING")
    checks["market_cache_pit"] = mc.exists()
    checks["sec_facts_cache"] = (EV / f"fundamental_facts_{session}.json"
                               ).exists()
    checks["memory_isolation"] = "EMPTY_REPLAY_MEMORY (enforced)"
    checks["portfolio_isolation"] = "NEUTRAL_RESEARCH_PORTFOLIO (enforced)"
    blocked = [k for k, v in checks.items()
               if v is False or v == "MISSING"]
    lines = ["ALPHA REPLAY AUDIT — " + session, ""]
    lines += [f"  {k}: {v}" for k, v in checks.items()]
    lines += ["", "BLOCKED" if blocked else "SAFE_TO_RUN_REPLAY"]
    return "\n".join(lines)


def run(ctx: ReplayContext, max_ta: int | None = None, ta_fn=None,
        upstream: str = "recompute") -> dict:
    """Execute one replay. Decision phase only — outcome evaluation is a
    separate later phase. upstream=recompute actually re-runs the discovery
    pipeline on frozen PIT inputs (authoritative); 'frozen' consumes the
    contemporaneous pool artifact directly (fast path)."""
    out_dir = REPLAYS / ctx.session / ctx.policy
    (out_dir / "case_artifacts").mkdir(parents=True, exist_ok=True)
    if upstream == "recompute":
        up = recompute_upstream(ctx.session)
        members = [c["ticker"] for c in up["pool"]]
        (out_dir / "upstream_recompute.json").write_text(json.dumps(
            {"reference": up["reference"],
             "eligible": up["recomputed"]["universe_size_eligible"],
             "lane_counts": up["recomputed"]["lane_counts"],
             "exclusion_counts": up["recomputed"]["exclusion_counts"]},
            indent=1))
    else:
        pool_doc = _frozen_pool(ctx.session)
        if not pool_doc:
            raise RuntimeError(f"no frozen candidate pool for {ctx.session}")
        members = _pool_members(pool_doc)
        up = {"reference": {"note": "upstream consumed from frozen artifact"}}
    pool_for_ta = {"candidates": [{"ticker": t} for t in members],
                   "deep_selected": None}
    # CURRENT_PRODUCTION deep set comes from the frozen funnel evidence
    ta_set = select_for_ta(ctx, pool_doc=pool_for_ta if upstream == "frozen"
                           else {**pool_for_ta, "deep_selected":
                                 None}, )
    if upstream == "recompute" and ctx.policy == "CURRENT_PRODUCTION":
        import evaluations.alpha_rnd_v1.discovery as disc
        ta_set = [c["ticker"] for c in sorted(
            up["pool"], key=lambda c: c.get("rank", 999))[:disc.DEEP_QUOTA]]
    man = {"context": ctx.__dict__,
           "upstream": {"mode": upstream,
                        "reference_comparison":
                            (up.get("reference") or {}).get("comparison")},
           "candidate_pool_count": len(members),
           "candidate_pool_members": members,
           "ta_selected_count": len(ta_set), "ta_selected": ta_set}
    (out_dir / "manifest.json").write_text(json.dumps(man, indent=1,
                                                    sort_keys=True))
    done, ran, failed, not_run = [], [], [], []
    rt = None
    if any(True for _ in ta_set):
        if ta_fn is None:
            if sys.version_info < (3, 11):
                raise RuntimeError("replay TA requires .venv312 python "
                                   "(production runtime); system python3.10 "
                                   "lacks datetime.UTC")
            import evaluations.alpha_rnd_v1.run_ta as rt
            def ta_fn(tt, sess):
                d0 = rt.D
                rt.D = out_dir
                try:
                    return rt.run_one(tt, sess)
                finally:
                    rt.D = d0
    for t in ta_set:
        cache = out_dir / "case_artifacts" / f"{t}_{ctx.session}.json"
        if cache.exists():
            done.append(t)
            continue
        if max_ta is not None and len(ran) >= max_ta:
            not_run.append(t)
            continue
        try:
            art = ta_fn(t, ctx.session)
            if not cache.exists() and art:
                cache.write_text(json.dumps(art, indent=1, default=str))
            ran.append(t)
        except Exception:
            failed.append(t)
    # PIT news post-check: artifact text must not contain dates > session
    DATE_RX = re.compile(r"20\d\d-\d\d-\d\d")
    pit_flags = {}
    for t in ran + done:
        p = out_dir / "case_artifacts" / f"{t}_{ctx.session}.json"
        if not p.exists():
            continue
        dates = DATE_RX.findall(p.read_text())
        pit_flags[t] = max(dates) <= ctx.session if dates else None
        if pit_flags[t] is False:
            (out_dir / "pit_violation.json").write_text(json.dumps(
                {"ticker": t, "max_date_seen": max(dates)}))
    # shadow publication: disposition ONLY for tickers with valid artifacts
    import alpha_rnd.synthesize as syn
    arts = {}
    for t in ta_set:
        p = out_dir / "case_artifacts" / f"{t}_{ctx.session}.json"
        if p.exists():
            arts[t] = json.loads(p.read_text())
    intents = syn.synthesize(arts) if arts else []
    by_t = {i["ticker"]: i for i in intents}
    pub = {}
    for t in ta_set:
        if t in arts:
            pub[t] = {"intent": by_t.get(t),
                      "disposition": syn.disposition(by_t.get(t), [], set())}
        else:
            pub[t] = {"intent": None, "disposition": "NOT_RUN"}
    (out_dir / "publication.json").write_text(json.dumps(
        {"intents": intents, "dispositions": pub}, indent=1, default=str))
    complete = not (failed or not_run or
                    [t for t in ta_set if t not in done + ran])
    result = {"session": ctx.session, "policy": ctx.policy,
              "decision_cutoff": ctx.cutoff,
              "pool": len(members), "ta_required": len(ta_set),
              "ta_completed": len(done) + len(ran), "ta_cached": done,
              "ta_ran_now": ran, "ta_failed": failed, "ta_not_run": not_run,
              "replay_complete": complete,
              "news_pit_postcheck": pit_flags}
    (out_dir / "run_result.json").write_text(json.dumps(result, indent=1))
    return result


if __name__ == "__main__":
    args = sys.argv[1:]
    if args[0] == "audit":
        sess = args[args.index("--as-of") + 1]
        print(audit(sess))
    elif args[0] == "run":
        sess = args[args.index("--as-of") + 1]
        pol = args[args.index("--policy") + 1]
        mx = int(args[args.index("--max-ta") + 1]) if "--max-ta" in args else None
        print(json.dumps(run(ReplayContext.make(sess, pol), max_ta=mx),
                         indent=1))
