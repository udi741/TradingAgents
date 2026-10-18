# TRADINGAGENTS CANONICAL PRODUCT CONSOLIDATION — REVIEW

Date: 2026-10-18. Scope: repository consolidation/portability only.
No strategy features, no ALPHA economics changes, no PBF/C12 changes,
real money remains OFF.

## 1. Old repository/worktree situation

One shared git repository, five+ sibling worktrees under
`/home/udi/udi_provate/`:

| worktree | branch | role |
|---|---|---|
| TradingAgents | infra/devin-bridge | BASE — vendored TA + SWE bridge |
| TradingAgents-alpha-rnd | exp/alpha-rnd-v1 | ALPHA runtime/state |
| TradingAgents-c12 | exp/gate-c12-prospective | frozen C12 control |
| TradingAgents-tracks | project/tracks | docs/control hub |
| TradingAgents-dashboard | feature/tradingagents-command-center | dashboard |
| TradingAgents-expert-rnd | exp/expert-rnd-v2 | optional research |
| TradingAgents-time-machine-rnd | research/true-time-machine-v1 | optional research |

`ops/ta.py`, `ops/telegram_relay.py`, and `alpha_repo_docs_drift_check.py`
hardcoded or required those sibling paths; a fresh machine needed the full
worktree set to run.

## 2. New canonical model

ONE repository, ONE canonical product branch
`product/tradingagents-current`. A single checkout contains code,
templates, docs, dashboard, tests, and the SWE bridge. Sibling worktrees
become a developer convenience only (parallel sessions), not a deployment
requirement.

- Code ← git (canonical branch)
- Mutable state ← `ops.ta backup` / `restore` (journaled, fail-closed)
- Secrets ← `~/.config/tradingagents/` (never committed)

`ops.ta` auto-detects layout: sibling worktree present at prefix →
multi-worktree (dev) layout; absent while the checkout itself carries
`alpha_rnd/` → single-checkout layout where every role root is the
checkout. Detection is restricted to `prefix == checkout parent` so a
foreign `--prefix` (sim/rehearsal) can never resolve into the live repo.

## 3. Canonical branch

`product/tradingagents-current` — created in the
`TradingAgents-dashboard` worktree (same shared object store; visible to
all worktrees).

## 4. Exact integration base

`feature/tradingagents-command-center` @ `5816a1f0` ("near-live refresh:
30s guarded page auto-rerender"), which already contains the merged
accepted work:

- ALPHA implementation incl. Phase G success-plan contract (`e60fa413`,
  `684636ee` gate fix)
- adaptive management + enabled paper execution (`a0c97f8e`, `fdd316c2`,
  `8355c176`)
- merged tracks/canonical docs + capability registry (`4fc04282`,
  `b3107445`, `1c6ab22e`, `e9bb2f1a`)
- dashboard + health remediation + portable path resolution
  (`9470d9b0`, `75950203`, `ee260719`, `f2edec3f`)

Plus cherry-pick `ceabecf9` → `be267ffb`: the SWE bridge
(`devin_bridge/` + tests + docs) so the product no longer needs the BASE
worktree for inference.

## 5. Capabilities included

core TradingAgents (vendored `tradingagents/`), ALPHA runtime
(`alpha_rnd/`), screening/discovery, TA intelligence path, entry gate +
success-plan + management logic, paper portfolio/execution (paper only),
deterministic + adaptive management, ops tooling (`ops/ta.py`,
`ops/roadmap_status.py`, telegram relay), systemd/cron templates,
dashboard (`dashboard/`), canonical docs + capability registry, tests.

## 6. Capabilities intentionally excluded/optional

- C12 frozen prospective control (`ta_eval`/`evaluations/gate_c12` code)
- EXPERT challenger research
- broad time-machine R&D, lifecycle research artifacts

Their state may still be restored and displayed; their absence is honest
(see §14). No frozen/research economics merged into ALPHA.

## 7. Removed worktree dependencies

| consumer | before | after |
|---|---|---|
| `ops/ta.py` `_layout` | all dirs under sibling worktrees | single-checkout detection → all roles = checkout |
| `ops.ta setup` | required 4 worktrees present | accepts single-checkout git checkout |
| `ops.ta workspace` | MISSING spam | reports SINGLE-CHECKOUT layout |
| `ops.ta restore` | exact per-worktree SHA equality | single-checkout: ALPHA sha must be ancestor-or-equal of HEAD; off-lineage roles warn |
| `ops/ta.py` cron/health | C12 job always expected | conditional on `ta_eval` present (optional track) |
| `ops/telegram_relay.py` | hardcoded `/home/udi/...` roots + cd hints | resolves via `ops.ta` layout |
| `dashboard/paths.py` | single-checkout self rejected by branch guard | accepted (own branch is legitimate); suppressed only under explicit env override |
| `alpha_repo_docs_drift_check.py` | hardcoded sibling ALPHA_ROOT | resolves to its own repo; `devin_bridge` added to coverage gate |

## 8. Runtime/state architecture

Git: code, config templates (`config/`, `ops/templates/`), docs, tests,
committed baseline state files (e.g. `alpha_rnd/monitor_state.json` —
tracked but treated as a *baseline*: restore may overwrite clean tracked
copies, never dirty ones).

Runtime/backup: portfolio state, watches, pending actions, ledgers,
evaluation artifacts — travel via `ops.ta backup` tar.gz (manifest +
sha256 + flock consistency).

Secrets: `~/.config/tradingagents/telegram.env`, devin CLI auth —
outside the repo, transferred by the operator.

## 9. Clean-clone procedure (verified)

```bash
git clone <repo> TradingAgents -b product/tradingagents-current
cd TradingAgents
python3 -m ops.ta workspace status   # SINGLE-CHECKOUT layout
python3 -m ops.ta setup --dry-run    # plan only
python3 -m ops.ta restore <backup.tar.gz>   # optional state
python3 -m ops.ta setup              # venv, units, cron, secrets skeleton
python3 -m ops.ta health             # deep check
python3 -m dashboard.server          # http://127.0.0.1:8420
```

Rehearsed at `/tmp/ta-canon/TradingAgents` (local clone of the shared
repo, no sibling worktrees present).

## 10. Clean-clone verification results

- `workspace status` → `SINGLE-CHECKOUT canonical product`, exit 0
- `status` → reads committed baseline state correctly
- `setup --dry-run` → OK plan; C12 cron line omitted (ta_eval absent)
- `health` → overall FAILED honestly: "ALPHA monitor ticking log missing"
  (no cron ever ran in the clone) — correct behavior, not masked
- `alpha_repo_docs_drift_check.py` → `drift errors: none`
- Module imports: `alpha_rnd.{success_plan,mgmt,mgmt_exec,mgmt_reassess,
  mgmt_validate,monitor,daily_scheduler,entry_gate,funnel}`, `ops.ta`,
  `ops.roadmap_status`, `devin_bridge.server` — all OK
- `ops.roadmap_status` → renders

## 11. Dashboard verification (clean clone)

Server on `TA_DASH_PORT=8421` (8420 occupied by the dev instance):

- `/api/meta`: ALPHA → `/tmp/ta-canon/TradingAgents` source
  `single-checkout`, present=true; C12/EXPERT → present=false (absent,
  reported, not wrong); TRACKS → self-checkout
- `/api/overview` → cash 92899.01, positions/pending fields populated
- `/api/health` → honest FAILED (no monitor tick), not a crash
- No reference to `TradingAgents-alpha-rnd|tracks|dashboard` siblings.

Stale-state masquerade: committed baseline state is shown as
`source: single-checkout` with its real branch in `/api/meta`; ops health
fails closed on missing monitor tick. An explicit-but-invalid
`TA_DASH_ALPHA_ROOT` yields `missing`, never self-fallback (covered by
`test_missing_root_yields_missing_meta_not_wrong_data`).

## 12. ALPHA verification

No economic action executed. Safe non-economic checks only:

- all production modules import from the canonical checkout
- success-plan + management + scheduler/ops paths resolve
- adaptive execution policy read: `enabled=true` WITH provenance
  (`activated_at`/`activated_for`) — health reports OK
- model config: SWE bridge openai_compatible @127.0.0.1:8765/v1
  (devin-quick→swe-2-medium, devin-deep→swe-2-high); no local-model
  fallback introduced or configured

## 13. Backup/restore rehearsal

- `ops.ta backup --prefix /home/udi/udi_provate` → 23-file validated
  archive (read-only vs live state; locks taken briefly)
- Restored into the isolated clone: ALPHA lineage proven via ancestry
  (backup `684636ee` ⊂ product HEAD); BASE `ceabecf9` warns — expected:
  bridge entered product by cherry-pick (new sha `be267ffb`, identical
  content); C12 sha warns (frozen control off the product line) —
  optional-track data still restores
- 23 files promoted; `status`/`monitor_state.json`/ledger present in the
  clone as working-tree content over the committed baseline
- Continuity: cash/positions/executed verified pre-promotion by the tool

## 14. Optional-track behavior

Clone without C12/EXPERT data: dashboard reports both `present:false`;
`ops.ta setup` omits the C12 cron line with an INFO note; health checks
that would have required them are degraded-level only. After restore of
a backup containing C12 state, `evaluations/gate_c12_prospective/` exists
in the checkout and resolves. Absence is never reported as ALPHA failure.

## 15. Tests

Clean-clone run (python3.10 system):

- `pytest alpha_rnd dashboard/tests ops`: **292 passed**, 3 failed
  (`alpha_rnd/test_mgmt_exec.py::C2` ×3), 1 collection error
  (`alpha_rnd/test_monitor.py`, `KeyError ZZZ`)
- Pre-existing on the base branch/dev worktree, reproduced identically —
  state-dependent tests (live PBF pending exit now exists). NOT
  consolidation regressions.
- `dashboard/tests/test_paths.py`: 14/14 incl. portability + wrong-root
  rejection tests.
- `tests/` upstream suite + `test_devin_bridge.py`: cannot collect under
  system python3.10 (`datetime.UTC`, `StrEnum` — need py3.12 venv);
  `.venv312` venv in env lacks pytest + heavy deps. Environment-limited,
  unchanged by consolidation.
- Dashboard E2E (`e2e_autorefresh.py`, `e2e_browser.py`): playwright not
  installed — environment-limited, previously proven on dev machine.

## 16. Docs updates

`START_HERE.md` (canonical repo model section), `docs/NEW_MACHINE_SETUP.md`
(single-checkout deployment path; worktrees demoted to dev-optional;
restore lineage semantics), `docs/PORTABILITY_GAPS.md` (G9 closed, G16
closed), `TRACKS.md` (deployment note), capability registry (module-root
comment, `canonical_product_branch`, bridge modules, vendored-copy
authority).

## 17. Drift-check result

`python3 alpha_repo_docs_drift_check.py` → `drift errors: none` (exit 0)
— now repo-relative, runnable from any clone.

## 18. Before/after economic state

Identical before and after consolidation:

- ALPHA cash: 92899.01133911515 | realized: -2140.99
- Positions: PBF 62sh (fill 80.0)
- PBF pending action: 1 partial exit, 31 shares,
  `pending_exit:mgmact_444a58f499a499f0`, confirm_session 2026-10-16
- PBF protection unchanged (remainder stop pending fill)
- executed[]: 6 records, unchanged
- C12: nav 98446.48, cash 85000, 3 open positions — unchanged
- Adaptive execution: enabled with provenance — unchanged

No economic mutation was performed or observed during consolidation.

## 19. Files changed

`ops/ta.py`, `ops/telegram_relay.py`, `ops/test_telegram_relay.py`,
`dashboard/paths.py`, `alpha_repo_docs_drift_check.py`,
`START_HERE.md`, `TRACKS.md`, `docs/NEW_MACHINE_SETUP.md`,
`docs/PORTABILITY_GAPS.md`,
`docs/TRADINGAGENTS_CAPABILITY_REGISTRY.yaml`, this review doc.
Plus cherry-picked `devin_bridge/`, `tests/test_devin_bridge.py`,
`docs/devin-bridge/` (content-identical, new sha).

## 20. Commits on product/tradingagents-current

- `be267ffb` feat: add Devin CLI bridge (cherry-pick of ceabecf9)
- `9fe3ed37` single-checkout canonical product: layout detection,
  optional-track degrade, lineage restore
- `…` telegram_relay test: resolve roots via layout
- `…` docs: canonical single-checkout repository model
- `…` consolidation review artifact

## 21. Known limitations

- `.venv312/` is tracked in git — clones receive a venv skeleton; works
  on this machine layout but a rebuilt venv is cleaner (pre-existing).
- `alpha_rnd/systemd/alpha-rnd-monitor.service` still carries a
  `/home/udi` path — superseded by `ops/templates/`; left as legacy.
- `ops/test_telegram_relay.py` status section still reads real resolved
  state — fails on a machine with no state restored.
- Bridge restore SHA check warns (not fails) on cherry-picked lineage —
  ancestry by sha cannot see identical content across cherry-picks.
- Upstream `tests/` suite needs py3.12 + deps; not runnable from a bare
  product env.

## 22. Remaining repository risks

- Old sibling worktrees still exist and remain the live deployment on
  this machine; switching the live cron/systemd to a single-checkout
  deployment is a separate, deliberate step not taken here.
- Dashboard will show committed baseline ALPHA state on a fresh clone
  before restore (source: single-checkout) — honest, but an operator
  could misread baseline as live; health flags the missing monitor tick.
- Dev `SESSIONS` resume names in telegram_relay are machine-specific
  hints (cosmetic only).

## 23. Recommended future clone/setup command

```bash
git clone <repo-url> TradingAgents
cd TradingAgents
git checkout product/tradingagents-current
python3 -m ops.ta restore /path/to/tradingagents-backup.tar.gz   # state
# fill ~/.config/tradingagents/telegram.env; devin CLI login
python3 -m ops.ta setup
python3 -m ops.ta health
python3 -m dashboard.server    # http://127.0.0.1:8420
```

## Acceptance

CANONICAL_PRODUCT_BRANCH_CREATED: YES
SUPPORTED_PRODUCT_IN_ONE_CHECKOUT: YES
ALPHA_REQUIRES_SIBLING_WORKTREE: NO
DASHBOARD_REQUIRES_SIBLING_WORKTREE: NO
DOCS_REQUIRE_SIBLING_WORKTREE: NO
OPTIONAL_TRACKS_CAN_BE_ABSENT: YES
CLEAN_CLONE_BOOT_VERIFIED: YES
DASHBOARD_CLEAN_CLONE_VERIFIED: YES
OPS_HEALTH_CLEAN_CLONE_VERIFIED: YES
BACKUP_RESTORE_REHEARSAL_PASSED: YES
CAPABILITY_DOCS_UPDATED: YES
DOC_DRIFT_CHECK_GREEN: YES
DASHBOARD_CAUSED_NO_ECONOMIC_MUTATION: YES
CONSOLIDATION_CAUSED_NO_ECONOMIC_MUTATION: YES
REAL_MONEY_REMAINS_OFF: YES
C12_ECONOMICS_UNCHANGED: YES
KNOWN_CRITICAL_PORTABILITY_GAPS_REMAIN: NO
STATUS: COMPLETE
