# TradingAgents Command Center — Audit Remediation Report

Date: 2026-10-18. Scope: remediation of
`docs/TRADINGAGENTS_DASHBOARD_INDEPENDENT_AUDIT.md` findings only.
No dashboard redesign, no strategy/investment-logic/PBF/C12 changes,
real money remains OFF.

## WHAT THIS MEANS FOR THE USER

Two real problems are fixed at the source:

1. **A fresh deployment no longer goes silently stale.** `ops.ta backup`
   now carries the research/funnel evidence the cockpit shows
   (`opportunity_funnel/`, `candidate_pool_frozen_*`,
   `publication_intents_*`/`resolutions_*`, `case_artifacts/`,
   `entry_snapshots/`, management analyses/contexts/requests, analysis and
   fundamental-facts snapshots, `trade_postmortems/`). Restore also
   **re-applies each file's source mtime**, so an old artifact can never
   masquerade as freshly generated — and the dashboard now displays the
   artifact's own session/as-of, not file mtime, as authoritative.
2. **"Why did ALPHA reject this stock?" is answerable in the UI.** The
   funnel candidate table renders the persisted `dispositions[T].violations[]`
   text (multi-violation rows expandable). Where ALPHA persisted no reason
   the cell honestly reads `REASON NOT PERSISTED` — nothing is invented.

Verified by a real rehearsal: live backup → clean clone → restore →
dashboard boot → the restored cockpit serves the same latest evidence
(funnel 2026-10-16, 112 case artifacts, 10 dispositions / 6 with
violations) and the same economics (cash 92,899.01, NAV 98,139.25, PBF
62sh @80.00 → 84.52, realized −2,140.99).

## 1. Original independent findings

IMPORTANT-1: backup omitted funnel/publication/pool/case evidence →
restored cockpit served committed ~2026-10-13 baseline with fresh-looking
mtimes.
IMPORTANT-2: `dispositions[T].violations[]` persisted but never rendered.
MINOR: `[object Object]` model chip; duplicated controls banner; CONFIRM
SESS clipping at 1366; `ops.ta health` subprocess on every poll; no
persisted non-selection reason (upstream limitation).

## 2. Root causes

- `_BACKUP_SET`/`_BACKUP_DIRS` covered only economic/operational authority;
  the decision-evidence layer the dashboard reads was never included.
- Restore rewrote file mtimes (extraction time), and the only freshness
  signal was mtime — so stale content looked current.
- The funnel UI joined candidates to `publication.intents` only; the
  authoritative `publication.dispositions` map (which owns `violations[]`)
  was never read.
- `model_routing` is an object `{quick, deep}` rendered raw.
- `/api/health` spawned `ops.ta health` + bridge probe + systemctl on every
  call, including each 60 s topbar poll.

## 3. Changes

- `ops/ta.py`: `_BACKUP_SET` extended; new `_BACKUP_GLOBS` for
  session-stamped families; `_BACKUP_DIRS` extended with evidence dirs.
  Manifest records `src_mtime` per file; `_stage_from_archive`/`_promote`
  re-apply it via `os.utime`. Disposable caches unchanged-excluded.
- `dashboard/adapters/alpha.py`: `_content_meta()` annotates `meta.asof` +
  `meta.freshness_basis` (`artifact` | `mtime_only` | `unverifiable`) on
  funnel, candidate pool, publication intents, case artifact,
  analysis status.
- `dashboard/server.py`: `/api/funnel` adds `scheduler_latest_session`;
  `/api/health` serves a cached snapshot (`TA_DASH_HEALTH_TTL_S`, default
  120 s) with `?refresh=1` forcing the authoritative run.
- `dashboard/static/app.js`: funnel shows as-of/STALE/STALENESS-UNVERIFIED
  chips + non-authoritative mtime note; candidate table gains a
  "Why (persisted reason)" column rendering `dispositions[t].violations`
  verbatim (first + expandable rest), `REASON NOT PERSISTED` for rejected
  without reasons, `—` for non-rejected/unpublished; model chip stringifies
  `model_routing`; controls banner deduplicated; health page shows snapshot
  age + "authoritative check now" button.
- `styles.css`: `table.dt` gets `min-width:max-content` so narrow viewports
  scroll horizontally instead of clipping; `.why-cell` wraps.

## 4. Backup scope before/after

Before: 15 files + 2 dirs (~75 KB) — economics + scheduler state only.
After: 209 files (~2.1 MB) — same authority set plus DECISION_EVIDENCE.
Deliberately excluded as DERIVED_REBUILDABLE / DISPOSABLE_CACHE /
RESEARCH_ONLY: `cache/` (155 MB), `expert_coverage/` (92 MB), `replays/`
(197 MB), `results/` (8 MB), `market_cache_*.pkl`, `universe_raw.json`,
`low_price_shadow/`, `memory/`, `rank_cohort*`, `incident_*`, logs.
No secrets: archive scanned — no `.env`/token paths; `secrets_required_
not_included` manifest note retained.

## 5. Freshness semantics

Authoritative freshness for sessioned artifacts = the **content's own**
session/as-of fields (`session`, `decision_session`, `frozen_at`,
`created_at`, `synthesized_at`). File mtime is displayed as transport
metadata labeled "not authoritative". Restore re-applies source mtimes so
mtime stays truthful too. Unverifiable → `STALENESS UNVERIFIED`, never
"fresh". Funnel additionally flags `STALE` when its session lags the
scheduler's latest completed session.

## 6. Restored-deployment reconciliation (this remediation's rehearsal)

Backup `/tmp/ta-remed/backup.tar.gz` (209 files, validated, no secrets) →
`git clone` → checkout `product/tradingagents-current` → `ops.ta restore`
(209 files promoted, journaled, checksummed) → dashboard boot on :8427:

| Check | Source | Restored | Match |
|---|---|---|---|
| latest funnel session | 2026-10-16 | 2026-10-16 (asof chip) | YES |
| candidate pool | 2026-10-16, 28 cands | same | YES |
| publication intents | 2026-10-16, 10 dispositions | same, 6 w/ violations | YES |
| case artifacts | 112 | 112 | YES |
| PBF economics | 62sh @80.00, mark 84.52, +280.24 | same | YES |
| portfolio | cash 92899.01, nav 98139.25, 6 fills | same | YES |
| funnel file mtime | 1792213339.5 | identical (source mtime) | YES |
| capabilities | 68 | 68 (identical histogram) | YES |

Restored health: FAILED only on "ALPHA monitor ticking — log missing"
(expected fail-closed on a fresh sim; monitor never ticked — identical to
audit behavior, not a regression).

## 7. Rejection-reason UX

Case B reproduced fixed: `ANF` shows AMBIGUOUS_REJECTED + "conflicting
tranche ladders (20/40/40 …)"; `PD` shows two violations (expandable);
`REANALYZE_ON_TRIGGER`/`EXECUTABLE_WATCH` show `—` (their trigger text is
the reason); non-published candidates show `—`. Approval rationale
(trigger/invalidation/stop/target/horizon) already rendered from intents.

## 8. Minor fixes

- `model: [object Object]` → `model: quick=swe-2-medium · deep=swe-2-high`.
- Controls banner no longer repeats "allowlist only".
- 1366×768: tables scroll horizontally; no compressed-cell clipping.
- Health: subprocess now at most once per 120 s TTL; manual authoritative
  refresh preserved (button + `?refresh=1`); control `health-check` still
  runs live `ops.ta health`.
- Non-selection reason: pool artifacts persist only aggregate
  `exclusions` counts — no per-ticker reason exists upstream; UI keeps
  honest `—`. Documented upstream observability gap, not a dashboard bug.

## 9. Screenshots

`artifacts/dashboard_review/rem_*_{1920x1080,1440x900,1366x768}.png`
(restored clone) + refreshed e2e set incl. `autorefresh_rejection_reason.png`.

## 10. Tests

- `pytest ops/test_ta.py dashboard/tests` — 86 passed (new:
  `test_cockpit_continuity_roundtrip` incl. no-cache-capture + source-mtime
  restore; `test_freshness_reasons.py` 9 tests: semantic asof, stale
  context, dispositions verbatim, health cache/refresh, no economic
  mutation).
- `e2e_browser.py` vs restored clone — 14 pages, 0 console errors, 0 API 5xx.
- `e2e_autorefresh.py` — all 7 stages auto-update (new `rejection_reason`
  stage proves a persisted violation appears without reload, ~1.5 s).
- `alpha_repo_docs_drift_check.py` — green.
- Pre-existing state-dependent failures (`alpha_rnd/test_monitor.py`
  collection, `test_mgmt_exec.py::C2` ×3) unchanged — live-state collisions,
  not touched by this remediation.

## 11. Economic-state safety

Backup remains read-only (flocks held briefly). Restore is new/empty-target
fail-closed, journaled, checksum-verified — unchanged. Dashboard changes
are read-path only; `test_no_economic_mutation_from_health` asserts economic
file mtimes untouched. Reconciliation values identical to audit §7/§8.

## 12. Commits

`product/tradingagents-current`: remediation commit (this change) +
remediation report. Audit doc preserved unmodified.

## 13. Remaining limitations

- Non-selection reasons: upstream observability gap (pool persists bucket
  counts only) — honest `—` retained.
- `fundamental_facts_*`/`analysis_*` backed up as session families; very
  old sessions ride along (bounded, small).
- `/api/health` snapshot can be up to TTL seconds old by design; the label
  says so and `refresh=1` bypasses.

## 14. Final acceptance argument

Both IMPORTANT findings fixed at the source and reproduced-closed: restored
cockpits carry the same latest evidence (CASE A) and rejection reasons are
visible without JSON (CASE B). Freshness is content-derived, not
mtime-derived. No economic path changed.

---

RESTORED_COCKPIT_PRESERVES_LATEST_EVIDENCE: YES
RESTORED_ARTIFACTS_CANNOT_FALSELY_APPEAR_FRESH: YES
REJECTION_REASONS_VISIBLE_IN_UI: YES
REJECTION_REASONS_USE_ONLY_PERSISTED_EVIDENCE: YES
PBF_RECONCILIATION_PASSED: YES
PORTFOLIO_RECONCILIATION_PASSED: YES
RESEARCH_RECONCILIATION_PASSED: YES
AUTO_REFRESH_STILL_WORKS: YES
MINIMUM_VIEWPORT_USABLE: YES
HEALTH_POLLING_EFFICIENT: YES
BROWSER_CONSOLE_CLEAN: YES
NO_PRIMARY_API_500_ERRORS: YES
DOC_DRIFT_CHECK_GREEN: YES
DASHBOARD_CAUSED_NO_ECONOMIC_MUTATION: YES
IMPORTANT_FINDINGS_REMAIN: 0
KNOWN_DATA_MISMATCHES_REMAIN: 0
READY_FOR_INDEPENDENT_RECHECK: YES
STATUS: COMPLETE
