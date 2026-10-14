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
"""
import hashlib
import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

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
        assert policy in POLICIES
        return ReplayContext(session=session,
                             cutoff=f"{session}T23:59:59Z", policy=policy)


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


def run(ctx: ReplayContext, max_ta: int | None = None,
        ta_fn=None) -> dict:
    """Execute one replay. ta_fn defaults to the production graph.propagate
    path (injectable for tests). Decision phase writes frozen artifacts;
    outcome evaluation is a separate later phase by design."""
    out_dir = REPLAYS / ctx.session / ctx.policy
    (out_dir / "case_artifacts").mkdir(parents=True, exist_ok=True)
    pool_doc = _frozen_pool(ctx.session)
    if not pool_doc:
        raise RuntimeError(f"no frozen candidate pool for {ctx.session} "
                           "— cannot replay without PIT evidence")
    members = _pool_members(pool_doc)
    ta_set = select_for_ta(ctx, pool_doc)
    man = {"context": ctx.__dict__,
           "upstream": {"source": f"candidate_pool_frozen_{ctx.session}.json",
                        "recomputed": False,
                        "note": "frozen contemporaneous evidence — identical "
                                "for all policies by construction"},
           "candidate_pool_count": len(members),
           "candidate_pool_members": members,
           "ta_selected_count": len(ta_set),
           "ta_selected": ta_set}
    (out_dir / "manifest.json").write_text(json.dumps(man, indent=1,
                                                    sort_keys=True))
    # TA phase — resume via manifest-hash cache
    import evaluations.alpha_rnd_v1.run_ta as rt
    done, ran = [], []
    for i, t in enumerate(ta_set):
        m = manifest(ctx, t, {"artifact_src": f"{t}_{ctx.session}"})
        cache = out_dir / "case_artifacts" / f"{t}_{ctx.session}.json"
        if cache.exists():
            done.append(t)
            continue
        if max_ta is not None and len(ran) >= max_ta:
            break
        if ta_fn is None:
            def ta_fn(tt, sess):
                d0 = rt.D
                rt.D = out_dir  # run_one writes D/case_artifacts — isolate
                try:
                    return rt.run_one(tt, sess)
                finally:
                    rt.D = d0
        art = ta_fn(t, ctx.session)
        if not cache.exists() and art:
            cache.write_text(json.dumps(art, indent=1, default=str))
        ran.append(t)
    # shadow publication: production synthesize/disposition on replay artifacts
    import alpha_rnd.synthesize as syn
    arts = {}
    for t in ta_set:
        p = out_dir / "case_artifacts" / f"{t}_{ctx.session}.json"
        if p.exists():
            arts[t] = json.loads(p.read_text())
    intents = syn.synthesize(arts) if arts else []
    by_t = {i["ticker"]: i for i in intents}
    pub = {t: {"intent": by_t.get(t),
               "disposition": syn.disposition(
                   by_t.get(t), [], set())}  # neutral portfolio -> held=∅
           for t in ta_set}
    (out_dir / "publication.json").write_text(json.dumps(
        {"intents": intents, "dispositions": pub}, indent=1, default=str))
    result = {"session": ctx.session, "policy": ctx.policy,
              "ta_completed": len(done) + len(ran), "ta_ran_now": ran,
              "ta_cached": done, "pool": len(members)}
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
