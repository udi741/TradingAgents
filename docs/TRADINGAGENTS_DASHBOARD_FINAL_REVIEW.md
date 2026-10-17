# TradingAgents Command Center — Final Review (for independent review)

## WHAT THIS MEANS FOR THE USER

You now have a single local web page that answers "what is the system doing,
what do we own, why, what is the plan, what is pending, are we making money,
is anything broken" against the **real** ALPHA and C12 state — no mock data.
It is read-only by design: the only actions it can trigger are the existing
`ops.ta` health/status/backup commands, each behind an explicit confirmation.
It cannot place, cancel, or modify any order; it cannot touch
`monitor_state.json`, C12, or any economics. Run it, close it, delete it —
live trading state is unaffected either way.

## 1. Mission result

Complete. All 12 primary views render real authoritative data, reconciliation
tests pass field-by-field including the PBF canary, E2E is green with zero
console errors and zero API 5xx, docs/registry updated, drift check green.

## 2. Git base / branch / worktree

- Worktree: `/home/udi/udi_provate/TradingAgents-dashboard`
- Branch: `feature/tradingagents-command-center`
- Base reasoning: `origin/main` is the upstream TauricResearch repo and
  contains **none** of the project work (verified: none of e60fa413,
  684636ee, b3107445, 1c6ab22e, e9bb2f1a are ancestors of origin/main).
  The accepted work lives on `exp/alpha-rnd-v1` (Phase G code, tip
  684636ee) and `project/tracks` (canonical docs + ops, tip e9bb2f1a).
- Integration: branched from `684636ee`, merged `project/tracks`
  (`e9bb2f1a`) — **zero conflicts** (all additions). Merge commit
  `4fc04282`. Dashboard commit `9470d9b0`.
- Existing worktrees (alpha-rnd, c12, expert, time-machine, tracks) were
  never modified — verified by git status in those trees (untouched) and
  by the economic baseline diff below.

## 3. Architecture

```
Browser SPA (no build, vanilla JS) ──> FastAPI /api/* (127.0.0.1:8420)
                                          │
        adapters/alpha.py ──> TradingAgents-alpha-rnd/{alpha_rnd,evaluations/alpha_rnd_v1}
        adapters/c12.py ────> TradingAgents-c12/evaluations/gate_c12_prospective
        adapters/capabilities.py ──> docs/TRADINGAGENTS_CAPABILITY_REGISTRY.yaml
        adapters/providers.py ───> alpha_rnd/infra_status.py (imported, live probe)
        adapters/health.py ──────> ops.ta health|status (subprocess), bridge probe, systemctl
```

Every read goes through `readutil.py` and returns `(value, meta)` where
meta = `{path, state: ok|missing|malformed|empty|unreadable, mtime_utc,
age_seconds}`. API responses embed meta; the UI renders `—`/UNKNOWN for
absent data and never substitutes zero.

## 4. Technology choices and why

- **FastAPI + uvicorn**: already installed, typed, async-friendly, serves
  both JSON and static files in one process.
- **No-build static SPA** (vanilla JS, hash routing, hand-rolled SVG chart):
  zero npm/build risk, works offline, trivially auditable. Deliberately
  chosen over React/Vite for an internal overnight deliverable.
- **Import of `alpha_rnd.infra_status`** for upstream/model health instead
  of reimplementing its journal-derived logic — no duplicate truth.
- **ops.ta subprocess wrapper** for health/backup — the authoritative ops
  commands rather than a parallel health implementation.

## 5. Pages implemented

| Route | Content |
|---|---|
| `#/overview` | cash, NAV, market value, exposure, realized/unrealized P&L, positions, pending orders, watch status, attention-required panel, scheduler last cycle |
| `#/funnel` | stage band universe→eligible→pool→deep→TA→publication→exec-watch→triggered→entries (nulls = UNKNOWN), exclusion counts, rank cohorts, session selector, candidate pool + publication intents merged table |
| `#/research` | artifact index (112 artifacts incl. error artifacts), per-ticker detail with signal/ratings/model/duration header + collapsible report sections |
| `#/positions` | position table; `#/positions/{T}` detail: current state, Phase-G entry snapshot (or honest LEGACY/SEEDED notice), watch rules, mgmt actions, shadow analyses/intents (labeled), merged timeline |
| `#/management` | deterministic (pending exits, invalidations) vs adaptive (policy flag, action lifecycle, remainder rules, shadow analyses, deduped event log, trigger families) |
| `#/executions` | pending entries/exits, `executed[]` (labeled fill authority), ledger tail, trigger events; intent≠pending≠fill banner |
| `#/performance` | NAV/realized/unrealized, fills table, unrealized-over-sessions chart, cohort state, INSUFFICIENT_SAMPLE banner (6 closes < 20) |
| `#/providers` | bridge process + upstream model status (journal-derived), registry provider semantics (PIT, retry, fail-visibility, key NAMES only), model failures, market-data health |
| `#/health` | ops.ta health checks + overall, status lines, bridge probe, systemd units |
| `#/capabilities` | live registry browser: 68 capabilities, status chips as filters, search, expandable purpose/modules/limitations |
| `#/tracks` | ALPHA/C12/EXPERT/research panels with explicit boundary warnings; C12 NAV + open trades shown only here |
| `#/controls` | safe-control allowlist with two-step typed confirmation |

## 6. Controls implemented

| Control | Backend | Effect |
|---|---|---|
| health-check | `POST /api/controls/health-check` | runs `ops.ta health` (read-only) |
| status | `POST /api/controls/status` | runs `ops.ta status` (read-only) |
| backup | `POST /api/controls/backup` | runs `ops.ta backup --output artifacts/backups/<ts>.tar.gz`; takes the same flocks briefly; writes only the archive |

All require `?confirm=I_UNDERSTAND`; without it the API returns 428. Unknown
control IDs return 404. Verified live: backup produced a validated 23-file,
70,545-byte archive; health returned real output.

## 7. Controls intentionally kept read-only

- **Adaptive-execution kill switch** (`management_policy.json`) — mutates
  live economics; remains a manual file edit per policy.
- **Scheduler pause/resume, manual pipeline invocation** — cron/systemd
  control was not provably safe from a web process; left to CLI.
- **Any order/management action** — would be a new economic pathway;
  forbidden by mission rules.
- No raw shell, no file editor, no state mutation endpoint exists at all.

## 8. Authoritative data-source map

`dashboard/truth_ledger.py` (24 entries, also served at
`/api/truth-ledger`). Excerpt: cash/nav/realized/positions/pendings ←
`monitor_state.json`; fills ← `executed[]` + `alpha_paper_ledger.jsonl`;
funnel ← `opportunity_funnel/<session>.json`; candidates ←
`candidate_pool_frozen_<session>.json`; research ← `case_artifacts/`;
Phase-G plan ← `entry_snapshots/`; mgmt lifecycle ← `management_actions.json`;
provider semantics ← registry YAML; model health ← `infra_status.status_report()`;
system health ← `ops.ta`.

## 9. Reconciliation results

`dashboard/tests/test_reconciliation.py` — 12 tests, all pass. They read the
underlying files directly and assert API equality (not just JSON parseability).

## 10. PBF canary reconciliation

| FIELD | AUTHORITATIVE SOURCE | API | UI | MATCH |
|---|---|---|---|---|
| shares | monitor_state positions.PBF.shares = 62 | 62 | 62 | YES |
| entry | positions.PBF.fill = 80.00 | 80.00 | $80.00 | YES |
| mark | positions.PBF.mark = 84.52 | 84.52 | $84.52 | YES |
| unrealized | positions.PBF.unrealized = 280.24 | 280.24 | +280.24 (5.65%) | YES |
| pending exit | pending_open_exits[0] = partial 31sh mgmact_444a58f499a499f0 | same | "31 / partial / ENQUEUED" | YES |
| remainder rule | management_actions[..].remainder_rule = close_below @ 83.5, PENDING_FILL | same | "close_below @ 83.5 / PENDING_FILL" | YES |
| entry snapshot | entry_snapshots/PBF_2026-10-02.json: entry 80.0, stop 74.5, seeded missing cost_basis | same | shown with missing_context | YES |
| thesis status | latest shadow reassess 2026-10-16: LARGELY_REALIZED, catalyst PRICED_IN | same | SHADOW analyses table | YES |

## 11. C12 / track isolation

`test_c12_isolation` + `test_c12_track_page`: C12 NAV (98446.48) and cash
(85000) asserted NOT to appear in ALPHA endpoints; C12 shown only on
`#/tracks` under a "frozen control — never mixed" banner; EXPERT parked and
research-simulation panels carry explicit non-authority notes.

## 12. Capability-center verification

`/api/capabilities` loads `TRADINGAGENTS_CAPABILITY_REGISTRY.yaml` live each
request. API count (68 = 67 + new dashboard entry) asserted equal to YAML
count by test; UI filter chips cover every observed status.

## 13. Provider-health verification

`/api/providers` returns `infra_status.status_report()` live (bridge HEALTHY,
upstream AVAILABLE, capability HEALTHY at review time), registry
provider_semantics (9 providers: PIT flags, retry policy, fail-visibility,
key names only), latest analysis_status, and monitor `data_health`
(22/23 daily bars ok). Test asserts allowed status vocabulary.

## 14. Screenshots

`artifacts/dashboard_review/`: overview.png, overview_1440x900.png,
overview_1366x768.png, funnel.png, research.png, research_PBF.png,
positions.png, position_PBF.png, management.png, executions.png,
performance.png, providers.png, health.png, capabilities.png, tracks.png,
controls.png, interaction_research_filter.png, e2e_report.json.

## 15–17. Test results

- Unit/contract/safety/reconciliation: `pytest dashboard/tests/` = **21 passed**
  (covers parsers/meta states, endpoint 200s, ticker/session input rejection,
  confirm-gate 428/404, secret-value regex, no-mutation-by-read,
  missing/malformed-state graceful degradation, all reconciliation asserts).
- Integration: reconciliation + provider + C12 tests above run against the
  real live state.
- E2E: `dashboard/tests/e2e_browser.py` (Playwright/Chromium): 14 routes,
  all rendered, screenshots captured; PASS.

## 18–19. Browser / console / network

Zero console errors across all pages. Zero API ≥500 responses during crawl.
Interaction smoke (research filter) OK. 1440×900 and 1366×768 overviews OK.

## 20. Performance / restart

Cold start verified: server restarted from clean process, `/api/overview`
200 in ~26 ms; endpoints read files per request (no daemon state to leak).
No background threads/polling server-side; the SPA polls every 60 s
client-side only.

## 21. Security / safety

- Binds 127.0.0.1 by default (env-overridable, documented).
- Ticker regex `^[A-Z0-9.]{1,10}$`, session regex `YYYY-MM-DD`; traversal
  attempts return 400/missing, tested.
- Secret-VALUE regex test over all endpoints: clean (key NAMES like
  `FRED_API_KEY` shown as names only).
- `test_dashboard_does_not_mutate_state`: mtime+size of all economic files
  unchanged after hitting every endpoint.
- Controls: allowlist dict; no shell passthrough; confirm token required.

## 22. Before/after production-state verification

| Metric | Before | After | Δ |
|---|---|---|---|
| ALPHA cash | 92899.01133911515 | 92899.01133911515 | none |
| realized | −2140.99 | −2140.99 | none |
| NAV | 98139.25 | 98139.25 | none |
| PBF | 62sh @80.00, mark 84.52 | same | none |
| pending exits | 1 (PBF 31sh ENQUEUED) | same | none |
| executed[] | 6 ids | 6 ids | none |
| C12 latest nav | 98446.48 (20:00Z) | 98446.48 (20:00Z) | none |

The backup control wrote only `artifacts/backups/dashboard-backup-*.tar.gz`
inside the dashboard worktree (non-economic). **The dashboard caused zero
economic mutation.**

## 23–24. Docs / drift

- Registry: new capability `ops.command_center_dashboard` (ACTIVE_PRODUCTION,
  modules/docs/tests declared). Count now 68.
- Reference: new "Command Center dashboard" section under Operations.
- START_HERE.md: dashboard line added. Runbook: `docs/TRADINGAGENTS_DASHBOARD.md`.
- `python3 alpha_repo_docs_drift_check.py` → **drift errors: none**.

## 25. Files changed

Added `dashboard/` (server.py, config.py, readutil.py, truth_ledger.py,
adapters/{alpha,c12,capabilities,health,providers}.py, static/{index.html,
app.js,styles.css}, tests/{test_reconciliation,test_api_safety}.py,
e2e_browser.py), `docs/TRADINGAGENTS_DASHBOARD.md`, this file,
`artifacts/dashboard_review/*`. Modified registry YAML, reference MD,
START_HERE.md.

## 26. Commits

- `4fc04282` merge project/tracks onto alpha-rnd base
- `9470d9b0` TradingAgents Command Center: read-only institutional dashboard

## 27. Known limitations

- Funnel per-ticker table is large (whole universe); local-only so acceptable.
- ~~`ops.ta health` reports FAILED on "adaptive execution DISABLED
  (expected)"~~ — FIXED in remediation: see FINAL ACCEPTANCE REMEDIATION
  below; health is now legitimately HEALTHY.
- No NAV equity-curve for ALPHA (no authoritative NAV series exists — only
  ledger MARKs); performance shows unrealized-over-sessions instead.

## 28. Unresolved bugs (pre-existing, observed not caused)

- `management_events.jsonl` grows ~1 `MGMT_EXECUTION/ALREADY_ENQUEUED` line
  per minute while the PBF partial exit awaits a valid open — real system
  behavior (off-hours weekend), flagged for the operator.
- `TWST_2026-10-16` entry snapshot has a suspect `stop_rule.level=1.0` —
  source-data anomaly, displayed as-is.
- Root `tests/conftest.py` fails under Python 3.10 (`enum.StrEnum`) —
  pre-existing; dashboard tests live in `dashboard/tests/` to avoid it.

## 29. Future improvements (not required for correctness)

- Confirm-gated scheduler pause/kill-switch control once a sanctioned
  mechanism exists; NAV series recorder; per-ticker chart from market_cache.

## 30. Final acceptance argument

Every required view renders authoritative real state (verified by
reconciliation tests + screenshots, not by self-report). PBF matches its
sources field-by-field. C12 is isolated. Zero unauthorized mutation
proven by before/after diff and a no-mutation test. Docs and drift check
green.

## FINAL ACCEPTANCE REMEDIATION

### Hardcoded worktree dependencies — did they exist?

Yes. The original `dashboard/config.py` derived all roots from a hardcoded
`~/udi_provate` prefix and sibling-worktree names
(`TradingAgents-alpha-rnd`, `TradingAgents-c12`). Remediated.

### Path-resolution architecture after remediation

New module `dashboard/paths.py` resolves every role root explicitly:

| Root | Resolution |
|---|---|
| DASHBOARD CODE ROOT | the checkout containing `dashboard/` (`paths.SELF_ROOT`) — never configured |
| ALPHA RUNTIME/STATE ROOT | `TA_DASH_ALPHA_ROOT` env → `ops/workspace.json` `roles.ALPHA.path` under PREFIX → this checkout if it holds `alpha_rnd/monitor_state.json` (single-checkout deploy) |
| C12 ROOT | `TA_DASH_C12_ROOT` env → spec `roles.C12.path` under PREFIX |
| CAPABILITY/DOC ROOT | `TA_DASH_TRACKS_ROOT` env → this checkout's own `docs/` → spec `roles.TRACKS.path` |
| RESEARCH ROOT (EXPERT, optional) | `TA_DASH_EXPERT_ROOT` env → spec `roles.EXPERT.path` |

PREFIX = `TA_DASH_PREFIX` env else the checkout's parent directory.
Sibling worktree names are read from the canonical `ops/workspace.json`
spec, not hardcoded. Each candidate must pass a sentinel-content check
(`alpha_rnd/` for ALPHA, `evaluations/gate_c12_prospective/` for C12).
Spec-derived and single-checkout candidates whose git branch contradicts
the spec's expected branch are **rejected** — necessary because economic
state files are git-tracked and a wrong checkout carries a stale committed
`monitor_state.json` (verified: this checkout's committed copy was 1 day
stale). Env overrides are honored but branch mismatches are surfaced in
`/api/meta`. Unresolvable roots produce `meta.state="missing"` everywhere —
no silent fallback reads.

`ops.ta` invocations now pass `--prefix <resolved PREFIX>` explicitly.

### Portability tests

`dashboard/tests/test_paths.py` — 7 tests on synthetic tmp-dir layouts with
deliberately unrelated worktree names (`zzz-live`, `repo-dash`): spec-driven
resolution, env-override precedence, sentinel rejection, single-checkout
fallback, missing-root clear failure, end-to-end API "missing" behavior, and
an assertion that no user-specific path or current sibling names appear in
the resolution report. All pass.

### Stale health check — root cause and fix

`ops/ta.py` `cmd_health` contained
`chk("adaptive execution DISABLED (expected)", not en)` — written before the
2026-10-16 E1 acceptance legitimately enabled adaptive paper execution.
Root cause: the check encoded a pre-activation policy as permanent.

Fix: replaced with a provenance check — `enabled` requires `activated_at` +
`activated_for`; `enabled` non-boolean → FAIL; enabled without provenance →
DEGRADED; disabled → OK (conservative default). Detection semantics
preserved; only the stale expectation removed. Regression tests added in
`ops/test_ta.py`: enabled+provenance → OK, enabled w/o provenance →
DEGRADED, malformed policy → FAILED, disabled → OK.

### Final `ops.ta health` output (verbatim tail)

```
  [     OK] adaptive execution ENABLED with provenance  activated 2026-10-16 for fresh PBF 2026-10-16 decision accepted
  [     OK] alpha_rnd writable
  [     OK] gate_c12_prospective writable

OVERALL: HEALTHY        (exit 0, all 16 checks OK)
```

### Existing-suite coverage accounting

- `ops/test_ta.py` — **48 tests, all pass** (includes 4 new adaptive-policy
  regression tests; the stale `test_adaptive_disabled_reported` was updated).
- `dashboard/tests/` — **28 tests, all pass** (reconciliation, safety,
  edge cases, new portability tests).
- `alpha_rnd/` suite (live worktree, ~20 files) — **216 pass, 3 fail**:
  `test_mgmt_exec.py::C2::{test_decision_session_anchor,
  test_disabled_cancels_pending, test_disabled_no_reverse_after_fill}`.
  Pre-existing isolation weakness: `mgmt_exec.ACTIONS_P` points at the live
  `evaluations/alpha_rnd_v1/management_actions.json`, so these tests
  read/collide with the real ENQUEUED PBF action. Not dashboard-caused;
  the registry file content was verified clean/intact afterward.
  `test_monitor.py` fails collection with `KeyError: 'ZZZ'` — pre-existing,
  related to the committed ZZZ test artifact in live state.
- `tests/` (repo root) — **cannot run: 49 collection errors**, pre-existing
  (`tests/conftest.py` imports `cli.prefs` which needs `enum.StrEnum`,
  absent on Python 3.10, plus other pre-existing import errors). Untouched,
  unrelated to dashboard; dashboard tests deliberately live under
  `dashboard/tests/`.
- No dashboard/health/path code lacks coverage because of the broken root
  conftest — all new code is covered by `dashboard/tests/` + `ops/test_ta.py`.

### Refreshed reconciliation

Re-ran after path-resolution changes: **28/28 dashboard tests pass**,
including cash, positions, PBF shares/entry/original-stop(74.5)/
remainder-rule(close_below 83.5)/pending-action(mgmact_…, 31sh ENQUEUED),
executed[] authority, latest funnel session+counts, registry count=YAML,
C12 isolation (nav/cash exclusion).

### Refreshed browser verification

Dashboard restarted cleanly (cold start `/api/overview` 200 in ~26 ms).
Playwright re-run: 14 routes all render, 0 console errors, 0 API 5xx.
`health.png` regenerated — now shows `OVERALL: HEALTHY` with the corrected
check line.

### Post-remediation economic state (unchanged)

cash 92899.01133911515 · realized −2140.99 · nav 98139.25 · PBF 62@80.00
mark 84.52 · pending exit 31sh ENQUEUED · executed[] 6 · C12 nav 98446.48 /
cash 85000 — identical to the remediation-time baseline; the only writes
were the archive artifact and non-economic files in the dashboard worktree.

### Remediation commits

(add this commit) — paths resolution (`dashboard/paths.py`, config rewrite,
`--prefix` plumbing), stale health-check fix + 4 regression tests,
test-isolation hardening, doc updates.

DASHBOARD_BOOTS_FROM_CLEAN_START: YES
OVERVIEW_WORKING: YES
OPPORTUNITY_FUNNEL_WORKING: YES
TA_RESEARCH_VIEW_WORKING: YES
SUCCESS_PLAN_VIEW_WORKING: YES
PORTFOLIO_VIEW_WORKING: YES
TRADE_MANAGEMENT_VIEW_WORKING: YES
EXECUTION_VIEW_WORKING: YES
PERFORMANCE_VIEW_WORKING: YES
PROVIDER_HEALTH_VIEW_WORKING: YES
SYSTEM_HEALTH_VIEW_WORKING: YES
CAPABILITY_CENTER_WORKING: YES
TRACK_ISOLATION_WORKING: YES
SAFE_CONTROLS_WORKING: YES
REAL_DATA_RECONCILIATION_PASSED: YES
PBF_CANARY_MATCHES_AUTHORITATIVE_STATE: YES
C12_NOT_MIXED_WITH_ALPHA: YES
ALL_PRIMARY_E2E_TESTS_GREEN: YES
BROWSER_CONSOLE_CLEAN: YES
NO_PRIMARY_API_500_ERRORS: YES
MISSING_STALE_DEGRADED_STATES_TESTED: YES
SECRETS_REDACTED: YES
DASHBOARD_CAUSED_NO_UNAUTHORIZED_ECONOMIC_MUTATION: YES
REAL_MONEY_REMAINS_OFF: YES
C12_ECONOMICS_UNCHANGED_BY_DASHBOARD: YES
CAPABILITY_REGISTRY_UPDATED: YES
CAPABILITY_REFERENCE_UPDATED: YES
DASHBOARD_RUNBOOK_CREATED: YES
DOC_DRIFT_CHECK_GREEN: YES
KNOWN_CRITICAL_BUGS_REMAIN: NO
KNOWN_DATA_MISMATCHES_REMAIN: NO
HARDCODED_USER_WORKTREE_PATHS_REQUIRED: NO
SINGLE_CHECKOUT_COMPATIBLE_ARCHITECTURE: YES
CURRENT_MULTI_WORKTREE_LAYOUT_SUPPORTED: YES
OPS_TA_HEALTH_STALE_EXPECTATION_FIXED: YES
OPS_TA_HEALTH_VERIFIED: YES
RELEVANT_EXISTING_TEST_COVERAGE_ACCOUNTED_FOR: YES
STATUS: COMPLETE
