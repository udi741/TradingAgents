# WORKSPACE INVENTORY — TradingAgents directories under /home/udi/udi_provate

Audit timestamp: 2026-10-03 (PROJECT_CONTROL_V2_WORKSPACE_AUDIT, read-only —
nothing was deleted, moved, pruned, killed, or altered).

Common git dir for all registered worktrees: `/home/udi/udi_provate/TradingAgents/.git`.
Remotes: `origin` = TauricResearch/TradingAgents (upstream),
`fork` = github.com/udi741/TradingAgents.

## Registered git worktrees (`git worktree list`)

| Directory | Registered | Branch | HEAD | Size | Status |
|---|---|---|---|---|---|
| TradingAgents | YES (base repo) | exp/gate-c6-selection-execution-split | d629034c | 804M | clean |
| TradingAgents-c12 | YES | exp/gate-c12-prospective | 5d9eea5c | ACTIVE | 1 untracked (run_week2_armed.sh) |
| TradingAgents-alpha-rnd | YES | exp/alpha-rnd-v1 | c2b47110 | ACTIVE | 1 modified (monitor_state.json — live monitor) |
| TradingAgents-expert-rnd | YES | exp/expert-rnd-v2 | 0a20d59d | ACTIVE | clean |
| TradingAgents-tracks | YES | project/tracks | 4724b736 | ACTIVE | clean |
| TradingAgents-c7 | YES | exp/gate-c8-full-stack-attribution | b6ff29d9 | 145M | 2 untracked (see below) |
| TradingAgents-c9 | YES | exp/gate-c9-fresh-dev-replication | 93c3be3b | 116M | clean |
| TradingAgents-c10 | YES | exp/gate-c10-fresh-dev-expansion | 63ec1b99 | 130M | clean |
| TradingAgents-c11 | YES | exp/gate-c11-final-fresh-dev | 7118fda5 | 111M | clean |
| TradingAgents-d1 | YES | exp/gate-d1-feasibility | 49f8105a | 545M | 2 untracked (cache only) |
| TradingAgents-mimic | YES | exp/gate-m4-entry-quality | 2d05fd56 | 314M | 2 untracked (see below) |
| TradingAgents-ext | YES | exp/external-watchlist | aef48bb0 | 23M | clean |
| tradingagents_gate_d_backup | **NO — not a git repo** | n/a | n/a | 30M | manual backup |

All branch tips are committed history: worktree removal does NOT delete the
branch, so no committed result is lost by removing a physical worktree.
None of the experiment branch tips are pushed to a remote (local-only
history — backup consideration, not a deletion blocker).

## Unique / uncommitted data findings

- **TradingAgents-c7** (holds the C8 branch): untracked
  `evaluations/gate_c7_v050_full_fidelity/` — **139M of genuine C7 gate
  results** (c7_summary.json, c7_scoring_key.json, c7_inference_manifest,
  case_artifacts, results, journal.jsonl) plus untracked harness
  `ta_eval/gate_c7_v050_swe2_full_fidelity.py`. **Committed C8 results
  (30 files) are tracked.** The C7 outputs exist ONLY on this disk.
- **TradingAgents-mimic**: untracked `evaluations/gate_m5_fresh_disjoint/` —
  **248M**, of which 242M is a re-derivable market-data `cache/`. The
  valuable ~6M: `m5_joined.json` (372K — the winner/loser labels every
  M4/X1/X2/X3 conclusion cites), `m5_selection_manifest`,
  `m5_exclusion_manifest`, `m5_metrics`, `artifacts/` (2.6M), `upstream/`
  (3.1M), `journal.jsonl`, plus untracked `ta_eval/gate_m5_fresh_disjoint.py`.
  Referenced by hard-coded path in
  `TradingAgents-expert-rnd/evaluations/expert_rnd_x2/x2_engine.py`
  (`MIMIC = "/home/udi/udi_provate/TradingAgents-mimic/evaluations"`).
  Committed: benchmark_v1, challenge, external_watchlist, m2, m3, m4
  evaluations (199 files).
- **TradingAgents-d1**: untracked items are `gate_d1_feasibility/cache/` and
  `raw/company_tickers.json` — re-derivable fetch artifacts. **All gate
  results (d1_1, d2, d3, d4 = 3847 files, incl. 456M d2_candidates) are
  committed.** No valuable unique data.
- **tradingagents_gate_d_backup**: manual 2026-09-13 shutdown backup. Git
  bundle `evaluator.bundle` (5.4M, evaluator repo at SHA 7e61e71a — that
  exact commit exists as branch `feat/baseline-retro-evaluator` in the main
  repo) + `evaluations/` (24M: gate_b_smoke, gate_c, gate_c_stability,
  gate_d_experiment, gate_d_pilot, smoke — rescued from /tmp) +
  integrity_manifest.txt + RESUME_HANDOFF.md. Whether these pre-git run
  outputs are fully superseded by later committed evaluations is
  **unverified**.
- Ignored-but-benign everywhere: `.ruff_cache/`, `__pycache__/`, `*.log`.
- No secrets/credentials found in audited untracked files.

## Live dependency findings (read-only audit)

- cron (user udi): one entry — per-minute ALPHA monitor, path
  `/home/udi/udi_provate/TradingAgents-alpha-rnd`. UNCHANGED.
- Running processes referencing any TradingAgents path: none at audit time.
- systemd user units: none referencing TradingAgents.
- Hard-coded path references into old worktrees found in ACTIVE dirs:
  `TradingAgents-expert-rnd/evaluations/expert_rnd_x2/x2_engine.py` ->
  `TradingAgents-mimic/evaluations` (X2 consumed-data engine).
- `alpha_rnd/systemd/alpha-rnd-monitor.service` (in-repo alternative unit)
  references only the alpha worktree.

## Classification

| Directory | Classification | Reason / precondition |
|---|---|---|
| TradingAgents | KEEP_ACTIVE | base repo + all branches' history; also hosts C6 work |
| TradingAgents-c12 | KEEP_ACTIVE | active control; Epoch-2 cycle frozen, pending orders |
| TradingAgents-alpha-rnd | KEEP_ACTIVE | active R&D + cron monitor dependency |
| TradingAgents-expert-rnd | KEEP_ACTIVE | active track |
| TradingAgents-tracks | KEEP_ACTIVE | project control |
| TradingAgents-c7 | ARCHIVE_REQUIRED_BEFORE_REMOVE | hosts uncommitted C7 results (139M, incl. scoring key + case_artifacts); also keep branch `exp/gate-c8-full-stack-attribution` (committed C8 results) |
| TradingAgents-mimic | ARCHIVE_REQUIRED_BEFORE_REMOVE | uncommitted M5 dataset (~6M valuable + 242M re-derivable cache); referenced by x2_engine.py — reconcile path or archive data first; keep branch `exp/gate-m4-entry-quality` |
| TradingAgents-d1 | SAFE_TO_REMOVE_WORKTREE* | results committed (3847 files); only re-derivable cache untracked; keep branch `exp/gate-d1-feasibility` |
| TradingAgents-c9 | SAFE_TO_REMOVE_WORKTREE* | clean; keep branch `exp/gate-c9-fresh-dev-replication` |
| TradingAgents-c10 | SAFE_TO_REMOVE_WORKTREE* | clean; keep branch `exp/gate-c10-fresh-dev-expansion` |
| TradingAgents-c11 | SAFE_TO_REMOVE_WORKTREE* | clean; keep branch `exp/gate-c11-final-fresh-dev` |
| TradingAgents-ext | SAFE_TO_REMOVE_WORKTREE* | clean; tip contained in expert-mimic/m2/m4 branches; keep branch anyway (free) |
| tradingagents_gate_d_backup | BACKUP_REVIEW | manual shutdown-rescue backup; verify gate_d_experiment/pilot outputs are superseded by committed history before removal; evaluator.bundle is redundant with local branch but is a bundle (verify before discard) |
| (note) c7 dir hosts C8 branch | — | branch/dir name mismatch; cosmetic |

*SAFE_TO_REMOVE_WORKTREE = the physical directory may go in a future
approved cleanup; the branch always stays. This audit does not authorize
deletion of anything.

## Preservation required before any removal

1. **c7**: commit or archive `evaluations/gate_c7_v050_full_fidelity/` +
   `ta_eval/gate_c7_v050_swe2_full_fidelity.py` (C7 gate results — the only
   copy on disk).
2. **mimic**: commit or archive non-cache contents of
   `evaluations/gate_m5_fresh_disjoint/` + `ta_eval/gate_m5_fresh_disjoint.py`;
   either update `x2_engine.py`'s MIMIC path or accept the data moving to an
   archive location; cache (242M) may be dropped.
3. **gate_d_backup**: verify `evaluations/gate_d_experiment` +
   `gate_d_pilot` content is represented in committed history (compare
   against integrity_manifest.txt hashes) before discarding.
4. Everywhere: record what was preserved in `docs/EXPERIMENT_REGISTRY.md`
   artifact column before retiring the directory.

## Proposed final active layout

```text
/home/udi/udi_provate/
    TradingAgents/               (base repo — ALL branches/history stay)
    TradingAgents-c12/
    TradingAgents-alpha-rnd/
    TradingAgents-expert-rnd/
    TradingAgents-tracks/
+ optionally one archive location for preserved eval data
  (e.g. TradingAgents-archive/ or committed inside base repo)
```

Retirable after preservation: c7, c9, c10, c11, d1, ext, mimic,
gate_d_backup — pending the ARCHIVE items above and explicit approval.

## Proposed cleanup commands (NOT EXECUTED — for a future approved gate)

```bash
BASE=/home/udi/udi_provate/TradingAgents
# registered worktrees (branches survive automatically):
git -C $BASE worktree remove /home/udi/udi_provate/TradingAgents-c9
git -C $BASE worktree remove /home/udi/udi_provate/TradingAgents-c10
git -C $BASE worktree remove /home/udi/udi_provate/TradingAgents-c11
git -C $BASE worktree remove /home/udi/udi_provate/TradingAgents-d1
git -C $BASE worktree remove /home/udi/udi_provate/TradingAgents-ext
# only AFTER archiving C7 results:
git -C $BASE worktree remove /home/udi/udi_provate/TradingAgents-c7
# only AFTER archiving m5 non-cache data and reconciling x2_engine.py:
git -C $BASE worktree remove /home/udi/udi_provate/TradingAgents-mimic
# only AFTER BACKUP_REVIEW confirms supersession:
rm -rf /home/udi/udi_provate/tradingagents_gate_d_backup
# branch deletion is NOT proposed; all branches stay.
```
