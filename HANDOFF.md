# TradingAgents — Handoff (as of 2026-11-04)

One document. Read this first. Everything else links from here.

## What is running RIGHT NOW (production, ~/udi_provate/TradingAgents, main@4ab2440f)

- **ALPHA scheduler**: hourly cron `python3 -m alpha_rnd.daily_scheduler --check`.
  Default deep-research quota **10**; pilot_sessions.json had whitelisted
  10-29/30 + 11-02 at 20 (all expired → auto-reverted, verified by 11-03
  running quota=10).
- **Real paper position**: RHI only — `PAPER_ENTRY 41.95×59` (10-28),
  mark ~44.7, +$105 uPnL. Book NAV ~97.7k. Ledger:
  `evaluations/alpha_rnd_v1/alpha_paper_ledger.jsonl`.
- **Entry-shadow observer** (passive, deployed 24bf422e + fix 4ab2440f):
  `backtest/entry_shadow.py update` fires hourly (≤1×/UTC-day) + post-publish.
  Writes ONLY to `~/udi_provate/research-results-archive/entry_shadow_ledger.json`.
  REPLAY/PROSPECTIVE attribution enforced; activation = commit 24bf422e
  2026-11-04T06:48:39Z. Currently 12 records, all REPLAY.
- C12, PBF, independent shadow portfolios: untouched, running as before.
- Production has ~300 untracked + ~11 dirty files = NORMAL operational state
  (logs, state jsons). Never `git clean`/`reset` this checkout.

## Pipeline map

`discovery` (rank ~60→quota via research_quota()) → `daily_scheduler.run`
→ deep TA per ticker → `case_artifacts/<T>_<sess>.json` (evidence, frozen)
→ `synthesize.py` (1 bridge call/session → publication_intents_<sess>.json;
  prompt = AUTHORING source; numeric-binding rules live here)
→ `econ_contract.validate` (bound-numbers, geometry, success-plan gates)
→ `econ_contract.repair` (LAB: strip unbound terms, fill from text)
→ `decision.from_economic_authority` / `select_plan` (LAB: alternates)
→ `entry_feasibility` diagnostic (pullback/continuation, near/deep_stale)
→ `econ_contract.project_execution` (LIMIT_ZONE→watch; STOP_ENTRY→
  confirmed_close_above trigger — LAB only) → `live_watchlist.json`
→ `monitor.py` (triggered() → pending_open_fills → next-open fill)
→ ledger. SHORT contracts → PUBLISHED_NON_EXECUTABLE always.

## Feature inventory

| Feature | Commit | Where | Live? | Tested? | Empirically validated? |
|---|---|---|---|---|---|
| Quota-10 default + pilot mechanism | 4796f6d0 | prod | yes | yes | yes (10-28..11-03) |
| Disposition repair (REA/PNE) | 3404d5d4→39b462e1 | prod | yes | yes | yes |
| Entry-shadow observer | 87d476bf→24bf422e | prod | yes | yes | prospective (running) |
| Evidence-class integrity | 4ab2440f | prod | yes | yes | running |
| entry_feasibility fields | 9547370b | **lab only** | no | yes (6/6) | n/a (diagnostic) |
| alternate_plans schema+select_plan | 4f5a63cb,fb74a320,8c3a4b4b | **lab only** | no | yes | NO — see A/B below |
| confirmed_close_above trigger | 8c3a4b4b | **lab only** | no | partial | no |
| econ_contract.repair | 761e1989,e5c8fe7c | **lab only** | no | yes | yes→0/12 (see below) |
| Prompt numeric-binding fix | 9f04a428 | **lab only** | no | yes | tested in A/B → insufficient |

## Established findings (evidence, not hypotheses)

- **NO demonstrated profitable edge** (verdict v2, archive). H1 +1.78%
  dir-adj/+1.93% xs (n53), H3 +5.96%/+8.58% (n16, 10-28 only) — driven by
  bearish accuracy 42/47 (89%); LONG-side n=2 at H3, no claim.
- **0 achievable missed fills**: every "miss" (REPL+20.7% etc.) had zones
  2–17% BELOW market, never touched. RHI (rank18) is the only fill ever.
- **Bearish accuracy ≠ short profit**: hypothetical shorts net −$165.84
  vs SPY-short −0.12% (short_shadow_verdict.md).
- **Synthesis A/B (12 cases, ~$8)**: alternate_plans emitted 3/12, ZERO
  survived validation; unbound numbers (0.75, 0.075), invented tranches,
  LONG-on-Hold contradictions persist (ab_new_prompt_outputs.json).
- **Contract repair: 0/12 newly valid** — model's numbers are economically
  INCOHERENT (CDNA base_case 80 < entry 83), not merely unsupported.
- Prior mechanical backtests (REPORT*.md): lookahead+reproducibility
  defects corrected; no deployable edge; do not revive.

## Unresolved blocker

Model authoring discipline: evaluation quality >> contract-authoring
quality. Prompt instructions fail to bind numbers; deterministic repair
can't fix incoherence. **Before reconsidering deployment**: ≥1 bounded
synthesis run where ≥30% constructive cases yield VALID contracts and
alternates pass validation at ≥80%. Not yet met.

## Runbook (verified commands)

```bash
# state/health (read-only)
cd ~/udi_provate/TradingAgents && git status -sb
grep '"session"' alpha_rnd/scheduler_events.jsonl | tail -5
python3 -c "import json;print(json.load(open('evaluations/alpha_rnd_v1/alpha_paper_ledger.jsonl'))[-1])"
cat alpha_rnd/live_watchlist.json | python3 -m json.tool | head -40

# entry-shadow ledger
python3 backtest/entry_shadow.py update   # idempotent; FREE (yf only)
python3 -c "import json;lg=json.load(open('../research-results-archive/entry_shadow_ledger.json'));print(lg['last_mark'],len(lg['records']))"

# tests (lab worktree)
cd ~/udi_provate/TradingAgents-contract
PYTHONPATH=.:backtest python3 backtest/test_entry_feasibility.py
PYTHONPATH=.:backtest python3 backtest/test_authoring_prompt.py
PYTHONPATH=.:backtest python3 backtest/test_entry_shadow.py
# NOTE: alpha_rnd/test_monitor.py has PRE-EXISTING collection error (KeyError 'ZZZ')

# COSTS MONEY — do not run casually:
#   alpha_rnd.daily_scheduler --run (TA deep research ~$3/name)
#   synthesize on artifacts = 1 model call/session batch (~$1)
# Deploy pattern (when approved): git checkout origin/research/alpha-lab
#   -- <files> in prod, commit, push main. Rollback: git checkout <prev> -- <files>.
```

## Artifact manifest (md5, ~/udi_provate/research-results-archive/)

missed_opportunity_audit.json 11e47dcf • directional_windows.json 4f74ce60
directional_windows_v2.json 84a9c5ef • entry_reachability.json 117f5e9c
entry_shadow_ledger.json 2b9f7ced • .pre-evidence.bak (integrity backup)
short_shadow_eval.json c2e93dc6 • short_shadow_verdict.md 90cf7344
ab_new_prompt_outputs.json 00094cea • ECONOMIC_VERDICT*_v2.md 35374cec
pilot_20stock_final.json 587a1394 • REPORT1-13.md + mission JSONs (older)

**BACKUP GAP**: this archive is a single local directory, NOT in git and
NOT mirrored. Irreplaceable items above should be copied to durable
storage; flagged, not silently assumed safe.
