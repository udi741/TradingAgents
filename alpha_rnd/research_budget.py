#!/usr/bin/env python3
"""Research-budget dry-run: which candidates a given DEEP_QUOTA selects.

Selection is the EXISTING production rule, not a new one: candidates
are ranked by persisted deep_score (labels*10 + 2*min(rs_60,2) +
CATALYST bonus, tie -> ticker), quota takes the top N. This module only
projects the selection and cost — it never runs inference.

Cost model: one bounded TA pipeline run per candidate.
Measured: mean duration ~417s/run (227 Oct artifacts).
Dollar bound: $1-3 per run (bridge routing, documented in
daily_scheduler DEEP_QUOTA comment) -> worst-case $3.

Usage: python -m alpha_rnd.research_budget [pool.json] [quota ...]
"""
import json
import sys
from pathlib import Path

COST_PER_RUN_USD = 3.0      # worst-case bound
MEAN_DURATION_S = 417.2     # measured on 227 Oct artifacts


def score(c: dict) -> float:
    if c.get("deep_score") is not None:
        return c["deep_score"]
    labs = [x for x in (c.get("labels") or []) if x != "MULTI_SIGNAL"]
    return round(10 * len(labs) + 2 * min(max(c.get("rs_60") or 0, 0), 2)
                 + (1 if "CATALYST" in labs else 0), 4)


def select(pool: dict, quota: int) -> list[str]:
    ranked = sorted(pool.get("candidates", []),
                    key=lambda c: (-score(c), c["ticker"]))
    return [c["ticker"] for c in ranked[:quota]]


def report(pool_path: str, quotas=(10, 20, 30)) -> dict:
    pool = json.loads(Path(pool_path).read_text())
    cands = pool.get("candidates", [])
    out = {"session": pool.get("session"), "pool_n": len(cands),
           "cost_per_run_usd_worst": COST_PER_RUN_USD,
           "mean_run_s": MEAN_DURATION_S, "quotas": {}}
    for q in quotas:
        sel = select(pool, q)
        added = len(sel) - min(10, len(sel))
        out["quotas"][q] = {
            "selected": sel,
            "incremental_runs_vs_10": added,
            "incremental_cost_worst_usd": round(added * COST_PER_RUN_USD, 2),
            "session_cost_worst_usd": round(len(sel) * COST_PER_RUN_USD, 2),
            "wallclock_min_at_concurrency_4":
                round(len(sel) * MEAN_DURATION_S / 4 / 60)}
    return out


if __name__ == "__main__":
    pool_path = sys.argv[1] if len(sys.argv) > 1 else \
        "/home/udi/udi_provate/TradingAgents/evaluations/alpha_rnd_v1/" \
        "candidate_pool_frozen_2026-10-27.json"
    quotas = [int(x) for x in sys.argv[2:]] or [10, 20, 30]
    print(json.dumps(report(pool_path, quotas), indent=1))
