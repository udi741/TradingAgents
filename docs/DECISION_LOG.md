# DECISION LOG — append-only durable project decisions

Format: DATE / DECISION / WHY / CONSEQUENCES / TRACKS AFFECTED.
Never edit an existing entry; corrections are new dated entries.

---

**2026-09 (pre-registry, recorded retroactively)**
DECISION: Separate validation from R&D.
WHY: One pipeline cannot honestly measure itself while being modified.
CONSEQUENCES: C12 frozen control created; all experimentation moves to
side tracks; C12 results become the honest benchmark.
TRACKS AFFECTED: all.

**2026-09**
DECISION: Freeze C12 as official v0.5.0 control.
WHY: A control must be fixed to be interpretable.
CONSEQUENCES: C12 decision layer never changes except explicit provider
pins; Epoch 1 timed cycles.
TRACKS AFFECTED: C12.

**2026-09-25**
DECISION: Late decisions are non-scoreable; timing guard added.
WHY: The 2026-09-25 cycle created decisions after the scheduled next-session
open; counting it would fake prospective integrity.
CONSEQUENCES: LATE_DECISION_NON_SCOREABLE cycles produce zero fills and zero
scoreable observations; guard is permanent.
TRACKS AFFECTED: C12 (rule applies project-wide to fills).

**2026-10**
DECISION: Pin the three statement tools fail-closed to SEC EDGAR.
WHY: Fundamentals provider policy tightened; filing-date-aware SEC data is
the defensible source.
CONSEQUENCES: get_balance_sheet / get_income_statement / get_cashflow ->
sec_edgar, no yfinance fallback, `filed <= decision_session`; Epoch 2 opened.
TRACKS AFFECTED: C12, ALPHA (same pin policy).

**2026-10-02**
DECISION: Close historical expert mimic; require prospective capture.
WHY: M2, M4, X2, X3 all failed; the historical dataset is winner-biased and
cannot answer "is the edge real" without losers.
CONSEQUENCES: production layer stays official v0.5.0 (M5.1); prospective
capture protocol frozen; reopen only at ≥20 signals / ≥5 losers or 25% /
≥15 exits.
TRACKS AFFECTED: EXPERT.

**2026-10-02**
DECISION: Create ALPHA_RND active opportunity track.
WHY: The project needs active progress toward useful trades in parallel
with slow validation; "wait for C12" is not a strategy.
CONSEQUENCES: separate worktree/ledger; paper-only; frozen triggers and
exit rules; watch-trigger discipline.
TRACKS AFFECTED: ALPHA.

**2026-10-03**
DECISION: Monitor uses frozen triggers only; close-confirmed conditions
execute next open; missed opens are never filled retroactively.
WHY: Same-close fills and invented later fills violate prospective
integrity and are unfalsifiable.
CONSEQUENCES: PENDING_NEXT_OPEN semantics for all close-confirmed rules;
MISSED_EXECUTION_REVIEW_REQUIRED for machine-off gaps; append-only event
log.
TRACKS AFFECTED: ALPHA (rule project-wide).

**2026-10-03**
DECISION: Intended holding horizon ≠ research evaluation horizon.
WHY: ACN's frozen 6–12mo intent conflicted with a universal 60-session max;
conflating them would force wrong exits.
CONSEQUENCES: 5/20/60/120/250-session marks are measurements, not exits;
exits follow frozen invalidation/event/time-box/target/reevaluation
hierarchy.
TRACKS AFFECTED: ALPHA, C12 (measurement policy).

**2026-10-03**
DECISION: Repository docs replace chat history as project source of truth.
WHY: The project outgrew conversation memory; sessions must resume from the
repo, not from scrollback.
CONSEQUENCES: this document tree; per-track doc ownership; documentation
definition-of-done for every task; chat history is last resort.
TRACKS AFFECTED: all.
