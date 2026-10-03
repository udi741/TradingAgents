# RUNBOOK: C12_PROSPECTIVE

Owner: Devin session `kindly-nightshade`.
Worktree: `/home/udi/udi_provate/TradingAgents-c12` (branch
`exp/gate-c12-prospective`).

## Purpose

Run the frozen official v0.5.0 pipeline prospectively each weekly cycle and
record honest, scoreable results. This is the control — not a place for new
ideas.

## When it runs

Once per weekly cycle, timed so that decisions exist BEFORE the scheduled
next regular-session open (execution deadline). Calendar/market driven.

## What makes a cycle scoreable

- Decisions committed before the execution deadline.
- Data as-of the decision session only (SEC `filed <= decision_session`).
- Pipeline = Lane A (S&P 500) -> top 10 -> full official v0.5.0 -> flat
  PortfolioContext -> external paper portfolio.
- If decisions land after the deadline: mark the cycle
  `LATE_DECISION_NON_SCOREABLE`, create zero paper orders, move on.

## How to resume

Open/resume the Devin session **`kindly-nightshade`** and give it:
"Continue C12 Epoch 2 per `runbooks/C12_PROSPECTIVE.md` in
TradingAgents-tracks. Run the next weekly cycle under the timing guard."

## Concrete cycle procedure (per due decision session S)

1. Verify bridge exposes `devin-quick`/`devin-deep`; relaunch with
   `--timeout 1200` if needed (deep calls exceed the 180s default).
2. After ISO-week finality (Fri ≥21:00 UTC or weekend) AND after the
   current-only rollover (the Saturday ~05:00 UTC after decision Friday —
   so withheld/current-only adapters agree S is in the past):
   `PYTHONPATH=. python3 -m ta_eval.gate_c12_prospective --prepare-week`
   `PYTHONPATH=. python3 -m ta_eval.gate_c12_prospective --run-week S`
3. Retry only missing/invalid candidate artifacts by re-running
   `--run-week S`; never alter prompts/models/token semantics.
4. The timing guard decides scoreability at decision freeze; do not settle
   fills before the next session completes
   (`--settle-pending-fills`, `--score-matured`, `--update-marks` afterwards).
5. If a cycle freezes late: `--dispose-week S` marks it
   LATE_DECISION_NON_SCOREABLE and voids its orders.

No background sleeper is currently running; do not assume one exists.

## What must never change

- The v0.5.0 decision layer, prompts, graph.
- The SEC fail-closed statement pins (get_balance_sheet /
  get_income_statement / get_cashflow -> sec_edgar, no yfinance fallback).
- The timing guard. No retroactive fills. Append-only ledger.

## What a cycle report must return

- Cycle date, decision session, scoreable or non-scoreable (with reason).
- Recommendations produced; paper orders created (if scoreable).
- Fills and marks for prior open positions.
- Files/commits touched; which docs were updated (track md, state yaml,
  registry row if a gate completed).
