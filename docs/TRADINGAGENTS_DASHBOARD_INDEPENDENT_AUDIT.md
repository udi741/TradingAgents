# TradingAgents Command Center — Independent Acceptance Audit

Date: 2026-10-18. Reviewer: independent — did not build the dashboard.
Scope: audit only. No fixes, no economic mutation, no PBF/C12 changes,
real money remains OFF.

## WHAT THIS MEANS FOR THE USER

On the live machine the dashboard is honest: every economic number on it was
traced to `monitor_state.json`, `alpha_paper_ledger.jsonl`, and the C12 ledger
and matched exactly; the PBF canary reconciles field-by-field; unknowns render
as `—`/UNKNOWN rather than zero; C12 and research never contaminate ALPHA.

Two real problems were found, both survivable but worth knowing:

1. **A fresh deployment made via the documented clone+restore path is silently
   stale for research and funnel data.** `ops.ta backup` carries the economic
   authority files but not `opportunity_funnel/`, `publication_intents_*`,
   `candidate_pool_frozen_*`, or `case_artifacts/`. A restored cockpit shows
   last-committed (≈2026-10-13-era) funnel/research content with fresh-looking
   freshness stamps, while the scheduler state is at 2026-10-16. The user
   asking "what is ALPHA considering right now" gets a 3-session-old answer
   with no staleness warning. This does NOT affect the running dev machine,
   where the dashboard reads live worktrees.
2. **Rejection reasons are not visible in the UI.** The system persists
   precise rejection violations (e.g. "ambiguous: sizing described both as
   ~$25k and ~$33k") but the Funnel page renders only the disposition chip —
   a non-developer cannot answer "why did we not buy this stock" without
   opening JSON.

---

## 1. Independent verdict

The dashboard is substantially trustworthy as an inspection surface on the
live deployment, with two IMPORTANT findings (restored-deployment staleness;
rejection-reason visibility) that prevent an unconditional "ready" verdict.
No fabrication, no silent fallback, no economic mutation observed anywhere.

## 2. Checkout / HEAD reviewed

- Review worktree: `/home/udi/udi_provate/TradingAgents-dashboard`
- Branch: `product/tradingagents-current` — matches the expected canonical
  product branch
- HEAD: `9a040b8643a300ed32d2bc9ee0485f385e9ad4d8`
- Isolated audit clone: `/tmp/ta-audit/TradingAgents` (local clone of the
  shared repo, no sibling worktrees), same HEAD `9a040b8` — verified
- Dashboard under test: the clone's own server, `TA_DASH_PORT=8422`

## 3. Pages visually inspected

All via real Chromium (Playwright) against the isolated clone, plus manual
inspection of the captured screenshots at 1920×1080, 1440×900, 1366×768:

`#/overview`, `#/funnel`, `#/research`, `#/research/PBF`, `#/positions`,
`#/positions/PBF`, `#/management`, `#/executions`, `#/performance`,
`#/providers`, `#/health`, `#/capabilities`, `#/tracks`, `#/controls`.

Screenshots: `/tmp/ta-audit/TradingAgents/artifacts/dashboard_review/`
(16 files incl. all viewports + autorefresh series). Regenerated during this
audit — not reused from the prior review.

No horizontal overflow at 1920 or 1440. At 1366×768 the Overview
pending-orders table's rightmost column (CONFIRM SESS) is clipped — usable,
minor.

## 4. Screenshots

See §3 artifact directory. `e2e_report.json` records per-page console/API
status: all pages ok, zero console errors, zero API ≥500.

## 5. ALPHA lifecycle review

Universe → Eligible → Candidate pool → Deep-selected → TA → Publication
disposition → Watch → Trigger → Pending → Fill → Position → Management → Exit:
every stage is represented and maps to a real persisted artifact. Stage counts
show `UNKNOWN` where the artifact doesn't persist a count (TRIGGERED / PAPER
ENTRIES on the stage band) — honest, not zero.

Stage reasons verified for the latest available session (2026-10-13 in the
clone — see IMPORTANT-1): selection (deep_selected list + rank cohorts),
TA decision (case artifacts with signal/ratings + full report sections),
publication dispositions with violation text in the API, watch state
(TRIGGERED / RISK_PLAN_REQUIRED with blocked-watch ids), trigger reasons
(trigger text per intent), pending (order_id + reason), fill (executed[] +
ledger), management (action lifecycle + shadow analyses labeled SHADOW).

## 6. Approved / rejected examples

- `IOVA` — AMBIGUOUS_REJECTED, violations persisted in API; UI shows chip
  only (IMPORTANT-2). Watch now `RISK_PLAN_REQUIRED` — correctly surfaced in
  the ATTENTION REQUIRED panel with the blocking artifact id.
- `HPE` — RESEARCH_ONLY ("auto entry contradicts TA signal Sell") — persisted,
  chip-only in UI.
- `MRNA`, `QMCO` — REANALYZE_ON_TRIGGER with trigger text rendered in the
  pool table — good.
- `ECO`, `KOD` — candidates never deep-selected: shown with `—` disposition.
  The system persists no per-ticker non-selection reason; the UI honestly
  shows `—` rather than inventing one. Acceptable, noted as informational.
- `PBF` — full lifecycle to position; entry plan vs management plan separated.

## 7. PBF reconciliation (authoritative = isolated clone's restored
`monitor_state.json` + `management_actions.json` + `entry_snapshots/`)

| FIELD | AUTHORITATIVE SOURCE | AUTH VALUE | API | UI | MATCH |
|---|---|---|---|---|---|
| ticker | positions.PBF | PBF | PBF | PBF | YES |
| shares | positions.PBF.shares | 62 | 62 | 62 | YES |
| entry | positions.PBF.fill | 80.0 | 80.0 | $80.00 | YES |
| cost basis | — (seeded; missing) | — | missing_context flagged | "cost_basis (legacy/seeded)" | YES (honest) |
| current mark | positions.PBF.mark | 84.52 (session 2026-10-16) | same | $84.52 MARKED, sess shown | YES |
| unrealized | positions.PBF.unrealized | 280.24 | 280.24 | +280.24 (5.65%) | YES |
| realized | monitor_state.realized | -2140.99 | -2140.99 | -$2,140.99 | YES |
| original stop | entry_snapshots/PBF_2026-10-02 risk_plan | 74.5 | 74.5 | $74.50 under ENTRY PLAN | YES |
| original R basis | snapshot stop vs entry | 5.5 risk/sh | shown via stop_level | shown | YES |
| legacy target | none persisted | — | not fabricated | not shown | YES |
| success plan | schema-1 snapshot only | bear_case/catalysts/horizon | same | shown with missing_context | YES |
| thesis status | latest shadow reassess | LARGELY_REALIZED | same | SHADOW analyses table | YES |
| catalyst status | same | PRICED_IN | same | shown | YES |
| mgmt triggers | management policy/trigger families | 5 families | same | TRIGGER FAMILIES block | YES |
| latest mgmt decision | management_actions mgmact_444a58f499a499f0 | PARTIAL_EXIT ENQUEUED | same | MGMT_ACTION banner + actions table | YES |
| pending exit | pending_open_exits[0] | partial 31sh confirm 2026-10-16 | same | "31 / partial / ENQUEUED" | YES |
| remainder rule | action.remainder_rule | close_below @ 83.5 PENDING_FILL | same | shown with rationale label | YES |
| execution status | adaptive policy | ENABLED w/ provenance | same | ENABLED banner (red) | YES |
| executed fill ids | executed[] | 6 ids | same 6 | FILL AUTHORITY panel | YES |

Original entry plan vs current management plan are on separate labeled
blocks (ENTRY PLAN / PHASE-G SNAPSHOT vs MANAGEMENT ACTIONS + remainder rule).
Recommendation vs fill is distinguished everywhere
(`recommendation ≠ pending ≠ fill` banner; SHADOW labels on analyses/intents).

## 8. Portfolio reconciliation

Recalculated independently from `monitor_state.json` in the clone:

| Metric | Authority | API | UI | Match |
|---|---|---|---|---|
| cash | 92899.01133911515 | 92899.01133911515 | $92,899.01 | YES |
| NAV | book.nav 98139.25 | 98139.25 | $98,139.25 | YES (authoritative field, not recomputed) |
| market value | book.market_value 5240.24 | same | $5,240.24 | YES |
| unrealized | 280.24 | 280.24 | $280.24 | YES (62×(84.52−80)=280.24 ✓) |
| realized | −2140.99 | −2140.99 | −$2,140.99 | YES |
| pending entries | [] | [] | none | YES |
| pending exits | 1 (PBF 31sh) | same | same | YES |
| executed | 6 ids | same | same | YES |

No rounding drift, no double-count, no intent-as-fill, no C12/research
contamination (C12 nav 98446.48/cash 85000 asserted absent from ALPHA
endpoints by tests; tracks page shows it only under a "never mixed" banner).

## 9. Profit / exit-plan review

For PBF the user can see: entry rationale (artifact ref + invalidation text),
original stop (74.5) vs current tightened remainder rule (close_below 83.5),
bear case, catalysts, horizon/time-box, reevaluation checkpoint, current
thesis (LARGELY_REALIZED) and catalyst (PRICED_IN) statuses from the latest
shadow reassessment, the pending 50% partial exit with rationale ("bank half
the gain ahead of the scheduled review"), and that no numeric target/bull
case exists for this seeded legacy trade — `missing_context` says so rather
than fabricating Phase-G fields. Verified: no legacy trade is presented with
structured data it never had. TWST's suspect `stop_rule.level=1.0` anomaly is
shown as source data (per documented caveat).

## 10. Performance / evidence review

`INSUFFICIENT SAMPLE — 6 closed trades; rate/expectancy statistics withheld
below 20 closed trades` banner is prominent. Shows raw fills (3), closed exit
events (6), realized/unrealized, and an unrealized-over-sessions chart (the
only honest equity proxy — no authoritative NAV series exists). Win-rate /
expectancy / MFE/MAE tables are withheld, not zeroed. Not misleading.

## 11. Provider / system health

`/api/providers` = live `infra_status.status_report()` + registry provider
semantics: 9 providers with PIT flags, retry policy, fail-visibility, key
NAMES only (no values). FRED, Reddit, SEC EDGAR, yfinance, TODAY_ONLY and
withheld-historical semantics present and consistent with the registry.
Upstream/model state honestly UNKNOWN in the clone (bridge process healthy,
upstream status unknown — journal-derived, nothing invented).

`/api/health` wraps `ops.ta health` (authoritative, not a dashboard imitation):
15 checks rendered, OVERALL HEALTHY in the clone after restore+one real
monitor tick — matching CLI output verbatim.

Caveat: each `/api/health` call spawns `ops.ta health` (≤90 s timeout),
a bridge `/v1/models` probe, and `systemctl` — invoked on every 60 s topbar
poll. Measured ~125 ms; works but heavier than necessary. The bridge probe is
a local metadata probe, not inference — no model/provider calls are triggered
by ordinary page refresh (verified: page fetches only `/api/*` which read
files; health poll is the sole probe).

## 12. Capability-center reconciliation

`/api/capabilities` loads the registry YAML live each request. Verified
independently: YAML count 68 = API count 68; status histogram identical
(50 ACTIVE_PRODUCTION, 9 RESEARCH_ONLY, 4 ACTIVE_PARTIAL, 3 UNUSED, 1 LEGACY,
1 SHADOW_ONLY). UI chips cover all statuses; names/modules/limitations come
from the file — no hardcoded copy.

## 13. Track isolation

C12 shown only on `#/tracks` under "C12 frozen control — never mixed";
EXPERT "parked — never mixed"; time-machine "research simulations are not
live economics". `test_c12_isolation` asserts C12 nav/cash absent from ALPHA
endpoints. Roots in `/api/meta` resolve correctly in the clone
(single-checkout; siblings absent and reported absent, not faked). Verified.

## 14. Auto-refresh verification

`dashboard/tests/e2e_autorefresh.py` re-run independently on synthetic
isolated state: all six stages (funnel_candidate, ta_result, publication,
watch, position, management) auto-updated WITHOUT reload; latency 0.9–1.5 s;
no console errors, no 5xx. Production refresh: 30 s guarded page re-render
(disabled while hidden/modal-open/typing) + 60 s topbar poll —
`app.js:1157-1206`. Confirmed in code.

## 15. Failure-state testing

- Missing ticker (`/api/positions/zzzz`) → honest nulls, `state:"missing"`.
- Bad session param → 400. Encoded traversal → 404. Ticker regex enforced.
- missing/malformed/empty/unreadable meta states covered by
  `dashboard/tests` (28 tests incl. edge cases) — all pass.
- Restored stale-artifact case observed live (IMPORTANT-1): NOT flagged —
  this is where the honest-freshness model breaks down (restore/git-checkout
  mtime ≠ content session).
- Monitor stopped / missing tick: `ops.ta health` fails closed — verified in
  earlier clean-clone rehearsal and reproduced here (HEALTHY only after a
  real `monitor --once` tick).
- No positions/candidates/providers-degraded states exercised via synthetic
  state in `e2e_autorefresh` + tests — render `—`/empty notes, no crash.

## 16. Safe-controls audit

Allowlist of 3 (health-check, status, backup). Verified live:
no-confirm POST → 428; unknown id → 404; shell-metachar id → 404. Backup
control exercised in the clone: produced a validated 74,862-byte archive of
the CLONE's state (`--prefix` correctly resolves to the isolated workspace —
no live-worktree access). No shell passthrough, no economic file editing,
no order actions. Controls deliberately exclude scheduler pause/kill switch —
documented and confirmed absent.

## 17. Code/API findings

- `readutil.py` meta states (ok/missing/malformed/empty/unreadable/partial)
  enforced consistently; JSONL bad-line counting correct.
- `paths.py` resolution: env → ops/workspace.json → single-checkout with
  sentinel + branch guards; verified in the clone (`single-checkout` source,
  siblings honestly absent). No `/home/udi` hardcoding found in dashboard code.
- No duplicated economic math found — `nav` reads `book.nav`/`nav_last`
  (authoritative fields), not cash+MV arithmetic.
- Exception handling: bounded, returns meta/error fields rather than
  swallowing silently (spot-checked readutil, health, providers, paths).
- Secret-VALUE scan test passes; providers page shows key names only.
- `server.py` control allowlist is a dict of fixed ops — no arbitrary shell.

## 18. Automated test results (run independently in the clone)

- `pytest dashboard/tests/` — **28 passed** (reconciliation incl. PBF
  field asserts, safety, portability, edge cases)
- `pytest alpha_rnd ops` — **264 passed, 3 failed, 1 collection error**
  - `alpha_rnd/test_monitor.py` collection error: `KeyError 'ZZZ'` —
    state-dependent, pre-existing
  - `test_mgmt_exec.py::C2` ×3 — state-dependent (collide with live ENQUEUED
    PBF action) — pre-existing, matches prior reports exactly
- `alpha_repo_docs_drift_check.py` — **drift errors: none** (exit 0)
- `e2e_browser.py` — 14 routes, all render, 0 console errors, 0 API 5xx;
  1440×900 and 1366×768 ok
- `e2e_autorefresh.py` — `ALL_STAGES_AUTO_UPDATED: True`
- Backup control exercised: valid archive produced
- Upstream `tests/` suite: not runnable under system python3.10
  (pre-existing, documented)

## 19. BLOCKING findings

None.

## 20. IMPORTANT findings

1. **Restored deployments are silently stale for funnel/research data.**
   `ops.ta backup` (23 files) omits `opportunity_funnel/`,
   `publication_intents_*.json`, `candidate_pool_frozen_*.json`, and
   `case_artifacts/`. A restored single-checkout cockpit serves the committed
   git baseline (funnel sessions ≤2026-10-13, 82 case artifacts) while live
   has sessions through 2026-10-16 (112 artifacts). Freshness indicators show
   checkout/restore-time mtimes, so nothing warns the user that "what is
   ALPHA considering" is 3 sessions old. Either include these artifacts in
   backup, or flag funnel/research content age against `scheduler_state`'s
   completed sessions. (Affects only restored/fresh deployments; the live
   multi-worktree machine is correct.)
2. **Publication rejection reasons not visible in the UI.** API persists
   explicit `dispositions[T].violations[]` text but the Funnel page renders
   only the disposition chip; the actual reason requires reading JSON.
   A non-developer cannot answer "why was this stock rejected" — classified
   an important UX/product gap per the audit criteria.

## 21. MINOR findings

- `#/research/{T}` header chip renders `model: [object Object]` (raw object
  not stringified).
- Controls page banner repeats "allowlist only; allowlist only".
- Overview at 1366×768: pending-orders table's CONFIRM SESS column clipped.
- Every topbar poll (60 s) runs the full `ops.ta health` subprocess +
  bridge probe + systemctl — heavier than needed; ~125 ms measured.
- Funnel "not selected" candidates have no persisted reason; UI shows `—`
  (honest, but "why not bought" unanswerable for that stage).

## 22. INFORMATIONAL findings

- Runbook claims a "merged timeline" on position detail; implemented
  client-side from ledger/trigger/management events — present and correct,
  wording nit.
- Clone `/api/meta` reports `branch_match: false` for ALPHA/C12 under
  single-checkout — expected and documented, but could confuse.
- Restored clone shows 82 research artifacts vs 112 live (part of
  IMPORTANT-1).

## 23. Final recommendation

On the current live machine: trustworthy cockpit — economics, lifecycle,
isolation, honesty all verified end-to-end. As the *documented deployment*
(primary cockpit after clean clone + restore): not yet — fix IMPORTANT-1
(state coverage or staleness surfacing) and IMPORTANT-2 (surface rejection
violations) before declaring unconditional readiness.

---

INDEPENDENT_REVIEWER: YES
ALL_PRIMARY_PAGES_VISUALLY_INSPECTED: YES
ALPHA_LIFECYCLE_VISIBLE_AND_UNDERSTANDABLE: YES
APPROVAL_REJECTION_REASONS_AUDITABLE: NO
ENTRY_AND_SUCCESS_PLANS_AUDITABLE: YES
CURRENT_EXIT_PLAN_AUDITABLE: YES
PBF_RECONCILIATION_PASSED: YES
PORTFOLIO_RECONCILIATION_PASSED: YES
PERFORMANCE_PAGE_NOT_MISLEADING: YES
PROVIDER_HEALTH_TRUSTWORTHY: YES
SYSTEM_HEALTH_TRUSTWORTHY: YES
CAPABILITY_CENTER_MATCHES_REGISTRY: YES
TRACK_ISOLATION_VERIFIED: YES
AUTO_REFRESH_VERIFIED_WITHOUT_RELOAD: YES
FAILURE_STATES_TESTED: YES
SAFE_CONTROLS_VERIFIED: YES
BROWSER_CONSOLE_CLEAN: YES
NO_PRIMARY_API_500_ERRORS: YES
BLOCKING_FINDINGS: 0
IMPORTANT_FINDINGS: 2
MINOR_FINDINGS: 5
KNOWN_DATA_MISMATCHES: 1
READY_AS_PRIMARY_TRADING_COCKPIT: NO
STATUS: COMPLETE
