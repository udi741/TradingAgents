# RUNBOOK: C12_PROSPECTIVE

Owner: Devin session `kindly-nightshade`.
Worktree: `/home/udi/udi_provate/TradingAgents-c12` (branch
`exp/gate-c12-prospective`).

## Purpose

Run the frozen official v0.5.0 pipeline prospectively each weekly cycle and
record honest, scoreable results. This is the control — not a place for new
ideas. Historical evaluation explains the framework and generates hypotheses,
but only never-observed future weeks can answer whether ENTRY decisions beat
NO_ENTRY decisions without leakage or hindsight.

## Automation (current mode)

Cycles run in the background, not from a chat prompt. An **hourly cron
checker** executes:

```
0 * * * * cd /home/udi/udi_provate/TradingAgents-c12 && PYTHONPATH=. \
  /usr/bin/python3 -m ta_eval.c12_scheduler --check \
  >> evaluations/gate_c12_prospective/scheduler.log 2>&1
```

Each tick the checker (deterministic, no LLM): finds the last completed
weekly decision session; verifies it is post-activation, not already
frozen/disposed, past the current-only rollover, and still before its
next-session-open execution deadline; verifies the bridge is up with the
accepted config (restarts it only when it is down or verifiably idle with a
wrong timeout — a busy foreign bridge blocks the cycle with
`C12_AUTOMATION_BLOCKED_BRIDGE`, never disturbs it); then invokes the frozen
`--prepare-week` / `--run-week S` commands. Every tick also runs the frozen
bookkeeping (`--settle-pending-fills`, `--score-matured`, `--update-marks`) so
pending orders fill at their real next-session opens with no human prompt.

Locks: the checker takes `c12_scheduler.lock` (flock, non-blocking); the gate
itself holds `c12.lock` during a cycle — a tick while a cycle runs exits
quietly. Nothing runs while the machine is off, and nothing is backfilled:
a due session whose deadline passed unrun is recorded
`LATE_DECISION_NON_SCOREABLE` (journal `week_missed`).

Status: `python3 -m ta_eval.c12_scheduler --status` → "C12 BACKGROUND STATUS".
Durable event log: `evaluations/gate_c12_prospective/c12_notifications.jsonl`
(plus `notify-send` popups when available).
Disable: `crontab -e`, remove the `ta_eval.c12_scheduler` line.

## Manual fallback (if automation is disabled)

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
