# TradingAgents Command Center — Final Independent Recheck

Date: 2026-10-18. Reviewer: independent — did not implement the remediation.
Scope: verify only that the two IMPORTANT findings of
`docs/TRADINGAGENTS_DASHBOARD_INDEPENDENT_AUDIT.md` are genuinely closed.
No fixes, no features, no economic mutation. Real money remains OFF.

## WHAT THIS MEANS FOR THE USER

Both findings are closed, verified independently against a real
backup → clean clone → restore rehearsal — not from the remediation
report's claims:

1. A restored cockpit now carries the same funnel/research/publication
   evidence as the source (funnel 2026-10-16, pool 28 candidates, 10
   dispositions / 6 with violations, 112 case artifacts, identical
   economics). Freshness is derived from each artifact's own session/as-of
   field: a file copied or restored *today* still displays as its true
   session and is flagged `STALE` when it lags the scheduler — it cannot
   masquerade as current because of its filesystem timestamp. Where no
   semantic timestamp exists the UI says `STALENESS UNVERIFIED` instead of
   implying freshness.
2. "Why was this stock rejected?" is answerable in the UI. The funnel
   candidate table renders the persisted `dispositions[T].violations[]`
   text verbatim — single reasons inline, multiple reasons expandable —
   and honestly prints `REASON NOT PERSISTED` where ALPHA stored none.
   The reason appears via auto-refresh (~1.5 s) without a browser reload.

Caveat carried forward (upstream, not a dashboard defect): candidates never
deep-selected have no persisted per-ticker reason anywhere; the UI shows
`—`, which is honest. Real-money trading remains OFF; this recheck changed
no economic state.

## 1. Branch / HEAD reviewed

- Worktree: `/home/udi/udi_provate/TradingAgents-dashboard`
- Branch: `product/tradingagents-current` — confirmed
- HEAD: `c1b3b7532add8b106e7bc7a4183cff8c4f2ec3e1`
  (remediation commits `b5504560` + `c1b3b753` on top of the audited
  `9a040b86`)
- Isolated recheck clone: `/tmp/ta-recheck/clone` (local `git clone` of the
  canonical repo, no sibling worktrees), same HEAD — verified
- Restored dashboard under test: clone's own server, port 8431,
  `single-checkout` source, siblings rejected via sentinel (`/api/meta`)

## 2. Restored-cockpit reconciliation (independent rehearsal)

`ops.ta backup` (209 files, 2,148,095 bytes, validated) → `git clone` →
checkout `product/tradingagents-current` → `ops.ta restore` (209 files
promoted, journaled, checksum-verified, WARN-only on off-line SHAs) →
dashboard boot:

| FIELD | SOURCE | RESTORED | MATCH |
|---|---|---|---|
| latest funnel session | 2026-10-16 | 2026-10-16 (API + as-of chip) | YES |
| funnel files | 5 sessions (10-12…10-16) | same 5, byte-identical (`diff -r`) | YES |
| candidate pool latest | 2026-10-16, frozen 2026-10-17T04:18:59Z | same | YES |
| candidate count | 28 | 28 | YES |
| publication intents/dispositions | 2026-10-16, 10 disp / 6 w/ violations | same | YES |
| case-artifact count | 112 | 112, byte-identical | YES |
| latest case artifact | ZBRA_2026-10-16 | same | YES |
| entry snapshots | 5 | 5 | YES |
| management analyses/contexts/intents/requests | 4/4/4/5 | 4/4/4/5 | YES |
| latest mgmt action | mgmact_444a58f499a499f0 PARTIAL_EXIT ENQUEUED | same | YES |
| trade_postmortems | 7 | 7 | YES |
| portfolio economics | cash 92899.01133911515, nav 98139.25, mv 5240.24, realized −2140.99 | identical via `/api/overview` | YES |
| PBF position | 62sh @80.00, mark 84.52, +280.24 | identical via `/api/positions/PBF` | YES |
| funnel file mtime | 1792213339.5454435 | identical — source mtime re-applied by restore | YES |

Content diff (`diff -r -q`) of `opportunity_funnel/` and `case_artifacts/`
source vs restored: zero differences. Restored meta `age_seconds` reflects
the source write time (~122,912 s), not restore time — mtimes stay truthful.

## 3. Freshness-failure reproduction → result

Original failure mode reproduced directly on the running restored clone:

- `touch opportunity_funnel/2026-10-12.json` (fs operation "now",
  2026-10-18) → `/api/funnel?session=2026-10-12` returns
  `session=2026-10-12`, `meta.asof=2026-10-12`, `freshness_basis=artifact`,
  `scheduler_latest_session=2026-10-16` — mtime is reported separately as
  "not authoritative". Browser render: `as-of session 2026-10-12` +
  `STALE — scheduler completed 2026-10-16` + `file mtime … (not
  authoritative)`. The touched file is NOT represented as current. CLOSED.
- Synthetic funnel artifact with ok JSON but no session/as-of field →
  `freshness_basis=mtime_only` → UI branch renders
  `STALENESS UNVERIFIED — artifact carries no session/as-of` (app.js:325).
  Verified end-to-end at API level and in code path.
- Scheduler comparison: `scheduler_latest_session` derives from
  `completed_sessions`/`last_cycle` and correctly flags lagging sessions.
- Restore re-applies `src_mtime` via `os.utime` (ops/ta.py `_promote`) —
  verified numerically above.

## 4. Backup scope

Manifest classes: ECONOMIC_AUTHORITY 4, ECONOMIC_EVENT_LOG 1,
ECONOMIC_LEDGER 1, POLICY 1, OPERATIONAL 17, SHADOW_LOG 1,
SHADOW_ARTIFACT 8, DECISION_EVIDENCE 176 — 209 files total.

Present and spot-inspected (contents, not just names):
`opportunity_funnel/` (5), `case_artifacts/` (112), `entry_snapshots/`
(5), `management_analyses|contexts|intents|requests` (17),
`candidate_pool_frozen*` (10), `publication_intents_*` (11),
`publication_resolutions_*` (2), `fundamental_facts_*` (10),
`analysis_status/ledger_*` (6), `trade_postmortems/` (7),
`ta_decisions_summary`, `intraday_trigger_evidence`,
`cohort_outcomes_state`, C12 nav/portfolio/signal ledgers + weeks.

Excluded as designed (confirmed absent from the archive): `cache/`,
`expert_coverage/`, `replays/`, `results/`, `market_cache_*`,
`universe_raw.json`, `low_price_shadow/`, `memory/`, `rank_cohort*`,
`incident_*`, logs.

Secrets: zero suspicious member names (`.env`/token/key patterns) and zero
secret-shaped `key=value` strings in a full payload scan (all files ≤2 MB
scanned). Manifest keeps `secrets_required_not_included` semantics —
"secrets NOT included" printed at backup time.

## 5. Rejection-reason UI verification (real browser, restored clone)

Against `#/funnel` (Chromium 1920×1080), candidate table "Why (persisted
reason)" column:

- `ANF` AMBIGUOUS_REJECTED — persisted text rendered verbatim:
  "ambiguous: conflicting tranche ladders (20/40/40 … ~10% vs ~15% …)".
- `PD` AMBIGUOUS_REJECTED, 2 violations — first rendered with
  "(+1 more)": "ambiguous: earnings date is unconfirmed…"; expanding the
  `<details>` shows both reasons verbatim, incl. "auto entry contradicts
  TA signal Sell". Expansion usable.
- `VEEV`, `TEAM`, `FIGS`, `ZBRA` — each renders its persisted violation.
- `IOVA`/`MRNA`/… REANALYZE_ON_TRIGGER — `—`; trigger text is the reason.
- Rejected-with-no-reasoned case: no such real artifact exists (all 32
  persisted REJECT/RESEARCH_ONLY dispositions across sessions carry
  violations); the honest-absence branch is covered by
  `test_freshness_reasons` (`REASON NOT PERSISTED`, never invented) —
  verified in code + tests.
- All rendered strings compared against
  `publication_intents_2026-10-16.json` — verbatim, no generated
  retrospective explanation.

## 6. Auto-refresh rejection reason

`dashboard/tests/e2e_autorefresh.py` run independently (synthetic isolated
state, browser left open, no reload): the `rejection_reason` stage persists
a publication disposition + violation exactly as ALPHA would and it appears
automatically — latency **1.5 s**. All 7 stages auto-updated, 0 console
errors, 0 API ≥500. `ALL_STAGES_AUTO_UPDATED: True`.

## 7. Visual / minor recheck (real browser)

- 1920×1080: funnel reasons readable, expansion works, as-of chip legible.
- 1440×900 and 1366×768: no page-level horizontal overflow
  (`scrollWidth == clientWidth`); wide tables scroll inside `.tablewrap`
  (`min-width:max-content`) — the prior 1366 CONFIRM SESS clipping is
  resolved by scrolling, not compression.
- `#/research/PBF`: `model: quick=swe-2-medium · deep=swe-2-high` — no
  `[object Object]` anywhere in the page body.
- `#/controls`: single "Safe operations. allowlist only; …" banner — no
  duplication.
- `#/health`: still authoritative `ops.ta health` output (OVERALL FAILED
  only on "ALPHA monitor ticking — log missing", expected fail-closed on a
  fresh sim that never ticked — identical to audit behavior).

## 8. Health-cache semantics

- `/api/health` result still comes from `health.health()` =
  `ops.ta health` — authoritative, unchanged.
- Ordinary polls serve a cached snapshot (TTL 120 s,
  `TA_DASH_HEALTH_TTL_S`): measured `age_s` 66.1 → 68.1 across two calls —
  no subprocess per poll.
- `?refresh=1` forced a fresh authoritative run: `age_s` reset to 0.0 in
  ~115 ms.
- Response always carries `cache{age_s, ttl_s, authoritative_cmd, note}`
  and the page labels the snapshot age with an "↻ authoritative check
  now" button — a stale snapshot cannot be mistaken for a fresh check.
- The `health-check` safe control still runs live `ops.ta health`.

## 9. Economic safety (before → after recheck)

| Field | Before | After | Match |
|---|---|---|---|
| ALPHA cash | 92899.01133911515 | 92899.01133911515 | YES |
| NAV / market value | 98139.25 / 5240.24 | same | YES |
| realized | −2140.99 | −2140.99 | YES |
| PBF | 62 @ 80.00, mark 84.52 | same | YES |
| pending exit | PBF 31sh ENQUEUED mgmact_444a58f4… | same | YES |
| executed fills | 6 ids | same 6 | YES |
| C12 nav / cash | 98446.48 / 85000.0 | same | YES |

Backup ran read-only under flocks; restore wrote only into the isolated
clone; dashboard reads are read-path only. No economic mutation caused by
this recheck.

## 10. Targeted automated verification (run independently in the restored clone)

- `pytest dashboard/tests ops/test_ta.py` — **86 passed** (includes
  `test_cockpit_continuity_roundtrip` + 9 freshness/reasons/health-cache
  tests in `test_freshness_reasons.py`).
- `e2e_browser.py` vs restored clone — 14 routes, **0 console errors,
  0 API ≥500**; viewport screenshots regenerated.
- `e2e_autorefresh.py` — **ALL_STAGES_AUTO_UPDATED: True** (incl.
  rejection_reason, 1.5 s).
- `alpha_repo_docs_drift_check.py` — **drift errors: none** (exit 0).
- Pre-existing state-dependent failures from the audit
  (`alpha_rnd/test_monitor.py` collection, `test_mgmt_exec.py::C2` ×3) were
  not re-run here — they collide with live state and are documented as
  pre-existing, unrelated to this remediation.

## 11. Remaining findings

None at IMPORTANT or BLOCKING level. Known honest gaps (unchanged, by
design): non-selected candidates have no persisted per-ticker reason
(upstream observability gap — `—` is truthful); health snapshot can be up
to TTL seconds old and says so; restored clone's health fails closed on
"monitor ticking" until a real monitor tick exists — correct behavior.

## 12. Final verdict

Both IMPORTANT findings are closed at the source and reproduced-closed
independently. The dashboard now survives the documented
clone+restore deployment path without silent staleness, and rejection
reasons are auditable by a non-developer.

---

RESTORED_COCKPIT_MATCHES_SOURCE_EVIDENCE: YES
SEMANTIC_FRESHNESS_VERIFIED: YES
STALE_RESTORED_DATA_CANNOT_APPEAR_CURRENT: YES
BACKUP_SCOPE_SUFFICIENT_FOR_COCKPIT_CONTINUITY: YES
BACKUP_CONTAINS_NO_SECRETS: YES
REJECTION_REASONS_VISIBLE_TO_NORMAL_USER: YES
REJECTION_REASONS_MATCH_PERSISTED_EVIDENCE: YES
MISSING_REJECTION_REASON_HANDLED_HONESTLY: YES
REJECTION_REASON_AUTO_REFRESH_VERIFIED: YES
MINIMUM_VIEWPORT_USABLE: YES
HEALTH_CACHE_PRESERVES_AUTHORITATIVE_SEMANTICS: YES
PBF_RECONCILIATION_PASSED: YES
PORTFOLIO_RECONCILIATION_PASSED: YES
ECONOMIC_STATE_UNCHANGED_BY_RECHECK: YES
IMPORTANT_FINDINGS: 0
KNOWN_DATA_MISMATCHES: 0
READY_AS_PRIMARY_TRADING_COCKPIT: YES
STATUS: COMPLETE
