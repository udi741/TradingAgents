# TradingAgents Capability Reference — human map of the framework

Canonical machine registry: `docs/TRADINGAGENTS_CAPABILITY_REGISTRY.yaml`.
This document is the narrative map; the registry is the drift-checkable truth.

## Core invariants

- **EVERY BUY DEFINES FAILURE AND SUCCESS** — an executable long needs both a
  machine-actionable post-entry risk rule AND a valid success plan, enforced
  fail-closed in `monitor.do_fill` via `post_entry_risk_plan` +
  `entry_success_plan`.
- **NO RUNNER WITHOUT A REMAINING THESIS** — `success_plan.runner_contract_ok`
  requires remaining thesis + revised/remaining value objective + positive
  residual upside; the mgmt validator rejects an unjustified HOLD on a
  realized objective.
- **`executed[]` means FILLED** — queued/adaptive orders live in
  `management_actions.json` (ENQUEUED→FILLED); never conflate.
- **Deterministic safety always wins** — intraday/close_below stops run before
  and independently of any inference.
- **A trigger means "think again", never "sell"** — triggers only schedule a
  bounded reassessment.

## Lifecycle map

### Universe / Discovery — ACTIVE_PRODUCTION
- `discovery.py` builds the PIT universe → eligibility (liquidity/history) →
  relative-strength lanes → `candidate_pool_frozen_<session>.json` (authoritative).
- `run_ta.py` runs the TradingAgents debate via the bridge
  (`devin-quick`/`devin-deep`); `daily_scheduler` adds bounded fair retries
  (7-day lifetime, ≤2/run). Limitation: ~25 calls/ticker; pretrained knowledge
  makes historical inference HISTORICAL_RESEARCH_EVIDENCE only.
- `case_artifacts/<T>_<sess>.json` = analysis authority;
  `publication_intents_<sess>.json` = decision authority.

### Entry contract — ACTIVE_PRODUCTION
- `synthesize.py` translates TA text → machine intents (trigger, params,
  invalidation, stop_level, horizon, reevaluation, size_frac, target).
- Legacy `target` is a single number (LEGACY — preserved, superseded).
- Phase G `success_plan` (see below) is the structured upside contract.

### Entry — ACTIVE_PRODUCTION
- `monitor.do_fill`: authorization → risk-plan gate → success-plan gate →
  next-open canonical fill; pro-rata cost basis; exec-id dedup.

### Portfolio / economics — ACTIVE_PRODUCTION
- `alpha_rnd/monitor_state.json` is THE economic authority: cash, positions,
  pending_open_exits, executed[] (fill IDs), outbox. `alpha_paper_ledger.jsonl`
  is the evidence trail.

### Deterministic management — ACTIVE_PRODUCTION
- `intraday_pass`/`close_pass`: hard stops and close_below rules → next-open
  exits. Inference-independent, always precedes adaptive logic.

### Adaptive management — ACTIVE_PRODUCTION (paper)
- `mgmt.py`: immutable `entry_snapshots/` (incl. frozen success_plan),
  observational `management_state.json`, R-based triggers
  (APPRECIATION 1.0R, PEAK_GIVEBACK ≥50% of peak from ≥1R,
  ADVERSE_ACCELERATION −1.25R, HORIZON_REVIEW per-snapshot date; catalyst
  schema-reserved/disabled), debounce/hysteresis/cooldown.
- `mgmt_reassess.py`: frozen per-trigger contexts → bridge inference →
  `management_analyses/`; stale-fingerprint rejection; urgent scheduling.
- `mgmt_validate.py`: intents `management_intents/` — never-widen, partial
  normalization, size bounds, stale/superseded, runner contract.
- `mgmt_exec.py`: VALID intent → `management_actions.json` ENQUEUED →
  canonical pending exit → next-open fill; kill switch
  (`management_policy.json execution.enabled`, currently ON) cancels unfilled
  adaptive orders, never reverses fills. Deterministic hard stop (`74.50`-type)
  is never overridden.

### Profit management — ACTIVE_PRODUCTION (Phase G)
- Original plan frozen in snapshot; revised plans recorded separately.
- Management context exposes: % original upside realized, base/bull-reached
  flags, remaining upside to base/bull, priced-in rule, success criteria.
- Reaching base-case triggers reassessment, not a blind exit.

### Evaluation / backtesting — RESEARCH_ONLY
- `replay.py`, `r5b_report.py`, `mgmt_time_machine.py` simulate fills and
  compare control vs treatment. They are NEVER economic authority and must
  never write `monitor_state.json`. V1 = deterministic-priority regression;
  V2 = archive insufficiency; V3 stopped. A dedicated true time-machine
  backtester is planned as a separate worktree — not built yet.

### Operations — ACTIVE_PRODUCTION
- `daily_scheduler.py`: cycle lock, stage timeouts, urgent-mgmt pre-pass.
- `telegram_relay.py`: notification dedup + circuit breaker; delivery ≠ proof.
- Bridge journal = model-call evidence. `monitor_state.json` remains the only
  economic truth.

## Duplication / authority (summary)

| Capability | Authoritative | Non-authoritative |
|---|---|---|
| Portfolio/fills | `monitor.py` + `monitor_state.json` | `mgmt_time_machine.py`, `replay.py`, `backtest.py` |
| Exit execution | `pending_open_exits` + `resolve_pending` | time-machine treatment fills |
| Trigger logic | `mgmt.py::evaluate` | replay copies (research) |

## State authority (summary)

AUTHORITATIVE: monitor_state.json (economics), management_actions.json
(adaptive lifecycle), entry_snapshots/ (immutable entry belief),
management_intents/ (validated decisions), live_watchlist.json (watches/stops).
OBSERVABILITY_ONLY: management_state.json, management_requests/.
EVIDENCE: ledgers, event streams, bridge journal.

## Known documentation gaps (honest)

- TradingAgents vendored-library internals are described only at bridge level.
- Provider fail-soft and PIT-withholding semantics live in code comments.
- The `OPEN_POSITION_MANAGEMENT` disposition is UNUSED (audit label only).
