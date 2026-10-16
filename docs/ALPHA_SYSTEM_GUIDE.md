# ALPHA System Guide

How the ALPHA_RND track of TradingAgents actually works today, written for an
engineer who has never seen this repository. Read `START_HERE.md` first; this
guide is second. Code lives in `TradingAgents-alpha-rnd` (the ALPHA_RND
worktree); project control docs live in `TradingAgents-tracks` (this repo).

This document describes CURRENT behavior, verified against code. Where it
disagrees with an older document, the code wins and the older document is
obsolete.

---

## 1. What the system is

ALPHA is a **paper-trading research pipeline**. Every day after the US market
close it discovers candidate stocks, runs a multi-agent LLM analysis
(TradingAgents) on a small selected subset, translates the results into
publication decisions, maintains a watchlist of conditional entry triggers,
monitors those triggers and any open positions, and paper-executes entries and
exits. Everything is simulated; no real money moves.

The project's governing constraint: **claims about whether recommendations
work come only from evidence accumulated prospectively or from isolated,
honest replay experiments — never from hindsight edits.**

## 2. Top-level architecture

```
raw universe (~thousands of tickers)
  → eligibility filters                     [deterministic]
  → per-ticker features                     [deterministic]
  → multi-lane scoring (A/B/C + RS + catalysts) [deterministic]
  → candidate pool (~28/session, frozen)    [deterministic]
  → TA-selection policy (deep quota: 10)    [deterministic]
  → TradingAgents inference per ticker      [MODEL/INFERENCE]
  → synthesis: TA artifact → publication intent [MODEL translator + deterministic validation]
  → publication disposition                 [deterministic, fail-closed]
  → live watchlist (watch/reanalysis state) [deterministic, atomic]
  → per-minute monitor                      [deterministic]
  → entry authorization gate                [deterministic, fail-closed]
  → paper fills / exits                     [ECONOMIC AUTHORITY]
```

Component classes:

- **Deterministic** — discovery, scoring, pool, TA selection, disposition
  classification, watchlist generation, the monitor, the entry gate, the
  scheduler's control flow. No model involvement; fully replayable.
- **Model/inference** — the per-ticker TradingAgents analysis (`run_ta.py`)
  and the translator inside `alpha_rnd/synthesize.py` that converts TA prose
  into structured intents. Both go through the local model bridge.
- **Economic/authoritative** — `monitor_state.json` (cash, positions,
  pending orders, executed IDs) and `alpha_paper_ledger.jsonl`. Only the
  monitor mutates them, under lock, atomically, idempotently.

## 3. Scheduling — when things run

Actual installed configuration (`crontab -l`):

- **Every minute:** `alpha_rnd.monitor --once` — one monitor pass. Intraday
  polls 1-minute bars while the US session is open; evaluates watch triggers
  and position stops; after the close runs the "close pass" (close-based
  triggers, end-of-day marks, pending-order settlement).
- **Hourly at :07:** `alpha_rnd.daily_scheduler --check` — due-cycle check.
  Decides whether the latest completed US session has been processed; if not,
  launches `--run-session`. Also revisits older sessions that still have
  retry-pending tickers.
- **Hourly at :23:** `alpha_rnd.cohort_outcomes update` — matures R2 outcome
  horizons (H1/H5/H20/H60) for all frozen funnel sessions; self-healing
  catch-up under a lock.
- **Hourly at :00:** the C12 track's own scheduler (separate worktree,
  separate cron line).

Services (`systemctl --user`):

- `tradingagents-swe-bridge.service` — local model bridge on 127.0.0.1:8765,
  routes `devin-quick` → swe-2-medium and `devin-deep` → swe-2-high. Owned by
  the service, not the scheduler; the scheduler can restart it only if it is
  down, never if it is "foreign busy" (serving another track's models).
- `tradingagents-telegram.service` — notification relay, tails event streams
  and delivers Telegram messages.

One pipeline cycle (`run_cycle`) executes, in order, under an exclusive lock:

1. `monitor --once` bookkeeping pass — **the existing book always runs first.**
2. Discovery (skipped on resume — a frozen pool is never rewritten).
3. TA pass on the selected tickers (subprocess, bounded by stage timeouts:
   book 10 min, discovery 2 h, TA 4 h, synthesize/publish bounded).
4. Synthesis → dispositions → `publish` → `live_watchlist.json`.
5. Observational freezers: funnel artifact (R1) and low-price shadow (R6).

### Priority and retry semantics

- **Current session first.** When the latest completed session is due, it is
  launched before any old retry work. An old incomplete session can delay a
  new one only for the duration of one bounded retry run.
- **Background retry is bounded.** A retry of a non-current session attempts
  at most `RETRY_BUDGET = 2` pending tickers per run, least-recently-attempted
  first; across sessions, the least-recently-retried session goes first. This
  prevents a stale session from starving new market days (each retry run is
  short; the TA stage timeout is 4 h and a full old retry list could hold the
  lock for hours).
- **Cycle locking** is real flock ownership (`_cycle_lock_busy` probes the
  lock, not the file's existence), so a stale lock file never blocks.
- **After offline time:** the hourly check sees the latest completed session
  unprocessed and runs it; monitor pending orders whose target session passed
  while the machine was off are marked MISSED — never filled retroactively.

## 4. Discovery

`evaluations/alpha_rnd_v1/discovery.py` is a deterministic, point-in-time-safe
pipeline (no LLM calls, no future data):

1. **Universe** — scraped ticker tables (NASDAQ-listed et al.).
2. **Eligibility** — data-availability and basic screens over fetched OHLCV.
   Roughly ~1800 tickers survive.
3. **Features** — returns, relative strength vs SPY (`rs_60`), RSI, pullback,
   volume ratios, etc.
4. **Lanes** — independent scorers: Lane A (momentum), Lane B (quality
   pullback), Lane C (breakout), plus an RS-leader series, a CATALYST lane
   (SEC 8-K/10-Q filing in the last 10 business days AND a market signature),
   and FUNDAMENTAL_ACCELERATION (SEC companyfacts, filed-date ≤ session).
5. **Candidate pool** — the union of lane tops plus catalysts/RS leaders,
   ~28 tickers per session, frozen to
   `candidate_pool_frozen_<session>.json`.

**Important:** there is no single fabricated global rank across the ~1800
eligible names. Each ticker carries its real per-lane score and rank
(`eligible_features`, schema v2), and `primary_rank` = its best lane rank.
Eligible-universe → pool and pool → TA selection are **separate research
questions** and are evaluated separately.

**TA selection** (`select_deep_candidates`, quota 10): deterministic score
`10×labels + 2×clip(rs_60,0,2) + 1 if CATALYST`, tie-broken by ticker. The
same function is used by the scheduler and manual runs — it is the canonical
implementation, not duplicated.

## 5. Inference architecture (model-agnostic)

Conceptually: `TradingAgents run → inference route/backend → provider/model`.
Nothing in the scheduler is provider-specific.

Current implementation: `run_ta.py` invokes a full TradingAgents analysis per
ticker through the local bridge at `127.0.0.1:8765` with two routes:
`devin-quick` (fast calls) and `devin-deep` (the heavy analyst/manager calls).
The translator in `synthesize.py` calls the same bridge to convert TA prose
into structured publication intents, then validates them deterministically
(fail-closed).

`alpha_rnd/infra_status.py` classifies backend status **from execution
evidence only** — never from "the bridge process is up" or `/v1/models`
answering:

- Bridge process: HEALTHY / DOWN / foreign-busy (checked separately from
  upstream).
- Upstream model: `AVAILABLE` (recent success evidence), `RATE_LIMITED`
  (within a known reset window), `QUOTA_EXHAUSTED`, `UNAVAILABLE`, `UNKNOWN`
  (no usable evidence — including an expired reset window with nothing newer).
- Reason codes: `MODEL_RATE_LIMITED`, `MODEL_QUOTA_EXHAUSTED`,
  `MODEL_UNAVAILABLE`, `MODEL_TIMEOUT`, `BRIDGE_FAILURE`,
  `TA_RUNTIME_FAILURE`, `MALFORMED_MODEL_OUTPUT`, `UNKNOWN_MODEL_FAILURE`,
  `RETRY_WINDOW_EXPIRED`. Non-retryable: `MODEL_QUOTA_EXHAUSTED`,
  `TA_RUNTIME_FAILURE`. Quota exhaustion also sets `user_action_required`.

**Core invariant: NO VALID MODEL RESULT → NO INVESTMENT-SEMANTIC RESULT.**
An infrastructure failure can never become a BUY/SELL/HOLD or any disposition;
it stays an infrastructure record. An investment rejection is a modeled
decision; an infrastructure failure is the absence of one.

## 6. Retry state machine

Per ticker, derived from disk evidence every cycle:

| State | Meaning | Retried? |
|---|---|---|
| `SUCCESS` | valid TA artifact with a signal on disk | never — artifacts are never rerun |
| `RETRY_PENDING` | retryable infrastructure failure (rate limit, timeout, temporary unavailable, bridge failure), or never attempted | yes, by the bounded background retry |
| `FAILED_TERMINAL` | non-retryable failure, or retryable failure past its lifetime | no |

- **Reset windows:** while a rate-limit reset time is in the future, the
  scheduler makes **zero** inference calls and just re-records the pending
  state. After the reset passes with no newer evidence, status becomes
  `UNKNOWN` (never claimed AVAILABLE) and one normal attempt is allowed; a
  success then establishes availability, a new 429 starts a new window.
- **Bounded lifetime:** `RETRY_LIFETIME = 7 days` from first observed failure.
  Expiry → `FAILED_TERMINAL` with `RETRY_WINDOW_EXPIRED`; the original reason,
  attempt count, and first/last attempt times are preserved in
  `analysis_ledger_<session>.json`.
- **Persistence:** state is derived from artifacts, error records, and the
  per-session ledger on disk — it survives restarts.
- **Session semantics:** `session_terminal` = no `RETRY_PENDING` remains
  (successes + terminal failures). `analysis_complete` = **every** ticker
  succeeded. A session with terminal failures is `session_terminal=true,
  analysis_complete=false` and is summarized as
  `ANALYSIS INCOMPLETE — TERMINAL FAILURES`.

## 7. Publication dispositions

Produced by `alpha_rnd/synthesize.py::disposition()` — deterministic,
fail-closed. Canonical vocabulary (`DISPOSITIONS`):

| Disposition | Meaning | Creates entry? | Monitored? | Telegram |
|---|---|---|---|---|
| `EXECUTABLE_WATCH` | validated intent with machine-evaluable trigger params AND a machine-actionable risk plan | YES — the only class that can | per-minute monitor evaluates trigger mechanically | enters watchlist via publish |
| `REANALYZE_ON_TRIGGER` | gated on news/catalyst/event — needs a fresh model look, not a price trigger | NO | kept as reanalysis state | no individual alert |
| `RISK_PLAN_REQUIRED` | actionable intent but no machine-enforceable stop/invalidation | NO (fail-closed) | no | no individual alert (summary only) |
| `PUBLISHED_NON_EXECUTABLE` | valid research result that is not machine-executable (e.g. descriptive trigger) | NO | no | no individual alert |
| `AMBIGUOUS_REJECTED` | translator output missing/malformed/ambiguous classification | NO | no | no individual alert |
| `RESEARCH_ONLY` | residual fail-closed class for unresolvable cases | NO | no | no |
| `NO_ACTION` | TA classified REJECT/NO_WATCH | NO | no | no |
| `OPEN_POSITION_MANAGEMENT` | intent concerns a held position — routed to position management, not entry | NO (manages existing) | position monitor | via monitor events |

Validation rule worth knowing: an intent with a news/catalyst-gated trigger
is forced to `REANALYZE_ON_TRIGGER` — a price monitor cannot evaluate "wait
for the 8-K".

Notes on `EXECUTABLE_WATCH`: it means *the trigger is mechanically evaluable
and risk-planned*, not that the signal is bullish. A Sell-signal artifact can
yield an executable watch whose trigger is a conditional long re-entry gated
on the bearish thesis being invalidated (e.g. "reclaim $34 and hold").

## 8. Entry authorization (fail-closed gate)

`alpha_rnd/entry_gate.py`: a watch may open a **new** position only if the
watch's revision is the **latest frozen publication decision** for that
ticker AND that decision is `EXECUTABLE_WATCH`.

Consequences:

- A stale/legacy watch (no matching current publication evidence) cannot buy.
- A newer non-executable revision **supersedes** an older executable watch —
  the old trigger loses entry capability.
- `REANALYZE_ON_TRIGGER` never reaches this gate; it produces reanalysis
  requests only.
- Authorization is checked twice: when the monitor evaluates the trigger and
  again inside `do_fill` — the **fill choke-point**, so no code path can
  bypass the gate.
- Rationale (briefly): a legacy watch once fired days after a newer rejection
  existed (the ASST class of problem). The revision check exists so that
  class cannot recur.

## 9. Position management

Existing positions are managed by the monitor independently of model
availability — **"model backend down" never means "stop managing PBF."**

- Every minute, the monitor checks all open positions (intraday stops via
  typed `stop_rule`s — e.g. `intraday_stop`, `close_below`; gap-through opens
  exit at the actual open).
- `pending_open_fills` / `pending_open_exits` settle at their target session
  open; a target already passed is marked MISSED — no retroactive fills.
- Executed IDs make each economic action idempotent: the same exec_id is
  never applied twice.
- Events are queued in an **outbox inside the state file** and flushed to the
  immutable `trigger_events.jsonl` transactionally — a crash mid-write can
  produce at most a duplicate durable line, never a lost event and never a
  half-applied fill. Dedup is semantic (transition identity), so a repeated
  detection is one event.
- After the close: `close_pass` evaluates close-based triggers, end-of-day
  marks positions, settles pending orders.

## 9a. Post-entry shadow management (Phase B — observational only)

An observational layer now watches open positions after entry. It is
**shadow-only**: it cannot create orders, change stops, or touch economics.

- **Entry snapshots** (`evaluations/alpha_rnd_v1/entry_snapshots/`): written
  once at fill (and backfilled for seeded positions) — entry price/session,
  shares, artifact ref+hash, thesis, invalidation, catalysts, risk plan,
  horizon/reeval text. Immutable, restart-safe; incomplete context is
  recorded as missing, never fabricated.
- **Management state** (`evaluations/alpha_rnd_v1/management_state.json`):
  peak/trough since entry, peak and current unrealized %, drawdown from
  peak, MAE, sessions held, horizon checkpoint, trigger/cooldown state.
  Observational — `monitor_state.json` remains sole economic authority.
- **Shadow triggers** (`alpha_rnd/mgmt.py` + `management_policy.json`):
  APPRECIATION, PEAK_GIVEBACK, ADVERSE_ACCELERATION, HORIZON_REVIEW
  (CATALYST schema reserved, disabled). Edge-triggered with cooldown and
  hysteresis. A trigger writes a `SHADOW_TRIGGERED` request artifact in
  `evaluations/alpha_rnd_v1/management_requests/` — **"think again",
  never an action**. No model call, no Telegram alert, no economic write.
  Runs inside the monitor pass after all safety logic, fully guarded —
  a failure there can never block a stop.
- Operator view: `python -m alpha_rnd.mgmt status`.

Model reassessment (Phase C) and any economic management action (Phase E)
do **not** exist yet.

## 10. Economic state authority

Authoritative (in order):

1. `alpha_rnd/monitor_state.json` — cash, realized P&L, positions,
   pending entries/exits, executed IDs, event outbox. Mutated only by the
   monitor under `locked_state()` (flock + atomic write).
2. `evaluations/alpha_rnd_v1/alpha_paper_ledger.jsonl` — append-only fill
   ledger.
3. `alpha_rnd/live_watchlist.json` — current watch specs (regenerated
   atomically by `publish`; same spec → same file).
4. `alpha_rnd/trigger_events.jsonl`, `alpha_rnd/scheduler_events.jsonl` —
   immutable event audit streams.

**NOT authoritative:** Telegram messages (delivery layer — a message can be
lost, duplicated, or suppressed and changes nothing), duplicate JSONL audit
rows (idempotency residue), replay/research artifacts, human-readable
summaries and reports.

## 11. Telegram

The relay (`ops/telegram_relay.py` in the tracks repo, running as
`tradingagents-telegram.service`) tails the event streams and delivers
messages by severity:

- `ACTION_REQUIRED` / `ERROR` → immediate message (e.g. quota exhausted,
  missed execution, discovery errors, publication review required).
- Informational transitions → included in summaries; normal research
  dispositions (`RISK_PLAN_REQUIRED`, `PUBLISHED_NON_EXECUTABLE`,
  `AMBIGUOUS_REJECTED`, …) **never** produce individual alerts — one
  `ALPHA_PUBLICATION_SUMMARY` per session reports counts.
- Degraded/partial analysis → one `ALPHA_ANALYSIS_DEGRADED` or
  `ALPHA_ANALYSIS_INFRASTRUCTURE_FAILED` per session **per distinct status**
  (signature = reason + success count + failed tickers; identical repeats are
  suppressed). The same outage seen from two stages is one notification.
- **Semantic dedup:** events are deduplicated by transition identity, not by
  line content — a producer-side `event_id` wins if present.
- **Circuit breaker:** bounds any remaining pathological burst even if a
  producer regresses.

"USER ACTION: NONE" outcomes are audit records, not interruptions.

The daily summary's research line distinguishes `last valid` session from
`last attempted` session + status (from `session_status`), so a failed recent
attempt is always visible rather than pinned to a historical invalid marker.

## 12. Replay (R5A engine)

`alpha_rnd/replay.py` — the historical time machine. For a past session it:

1. Loads **frozen point-in-time inputs** (cached market data, fundamentals,
   universe snapshots).
2. Recomputes the **same** deterministic pipeline via
   `discovery.compute_result` — eligibility, features, lanes, pool — never
   consumes the frozen pool directly.
3. Applies a **selection policy**:
   - `CURRENT_PRODUCTION` — the production quota selection.
   - `ANALYZE_ALL_CANDIDATES` — TA on the whole pool.
   (These are policies over whatever pool discovery produces — not a fixed
   "deep-10/deep-28" architecture; pool size is an output.)
4. Runs isolated TA into `replays/<session>/<policy>/case_artifacts/`.
5. Writes isolated shadow publication (`publication.json`) — **no** live
   watchlist, ledger, cash, positions, or production Telegram event is ever
   touched.
6. Only afterward evaluates outcomes against future data.

Resume semantics: a ticker whose `case_artifacts/<T>_<session>.json` exists
is never re-called; runs are crash-safe and resumable
(`R5B_CHECKPOINT.json` pins artifact hashes).

## 13. R5B current state

Paired experiment `CURRENT_PRODUCTION` vs `ANALYZE_ALL_CANDIDATES` on
2026-10-07 / 10-09 / 10-12 (28 pool candidates each).

- **84/84 TA artifacts complete and hash-frozen** (`R5B_CHECKPOINT.json`).
- Status: **R5B_ACCEPTED_PRELIMINARY**.
- Maturity: H1 mature for all three sessions; H5 mature for 10-07 (target
  10-14), pending for 10-09 (10-16) and 10-12 (10-19); H20 pending into
  November. H5/H20 mature automatically via the R2-style evaluation — no
  model calls.
- Preliminary finding (H1, plus 10-07 H5): the production-selected cohort
  outperformed the excluded-from-TA cohort on all three H1 windows and on
  10-07 H5. This is **PRELIMINARY_SHORT_HORIZON_SIGNAL**, not
  investment-horizon evidence, and **not** a claim that the current gate is
  optimal.
- Session-selection caveat (R5B-B2 audit): 10-09/10-12 did not satisfy the
  "H5-evaluable at selection" requirement — older mature sessions existed.
  Evidence retained; sessions labeled pending-maturity.
- PIT flags on four artifacts (SDGR, HPE, MGNI, WDAY) were all classified
  forward-looking calendar references — no exclusions.
- **No live strategy change has been approved from R5B.**

## 14. Prospective evaluation tracks (R1–R7)

Separate from replay: these observe the **live** pipeline going forward.

- **R1 — funnel instrumentation:** freeze per-session opportunity-funnel
  artifacts (universe → eligible → pool → TA → publication counts plus
  per-ticker per-lane scores/ranks). Ex-ante authority for cohort membership.
- **R2 — cohort outcomes:** for every frozen funnel stage, track each
  ticker's forward outcomes — next-open entry, H1/H5/H20/H60, SPY excess,
  MFE/MAE. Autonomous hourly maturation. Answers "what did each filter
  stage keep and kill?"
- **R3 — TA outcomes:** read-only join of R1 artifacts + R2 outcomes — did
  the TA signal add value over the mechanical cohort?
- **R4 — translator gap:** measures where valid analysis fails to become an
  executable intent (capability/translation gap), with provenance against the
  monitor revision live at the time.
- **R5 — pool→TA coverage:** should TA analyze more than the selected quota?
  R5A is the replay engine; R5B is the paired experiment above.
- **R6 — low-price shadow:** a shadow cohort of sub-$X names observed
  alongside production (no trades).
- **R7 — postmortems:** deterministic teardown of original trades
  (PBF, ACN, APPS, PGEN, TWST, SDGR) reconciling realized P&L to the cent.

Retrospective replay evidence and prospective evidence are **never mixed**.

## 15. The three tracks

| Track | Status | Purpose |
|---|---|---|
| **C12_PROSPECTIVE** | Active, frozen control | Official TradingAgents v0.5.0 run prospectively, paper-only, own worktree/cron — the clean validation baseline |
| **ALPHA_RND** | Active | This system: discovery → TA → publication → monitor → paper trades, plus the R-tracks |
| **EXPERT_RND** | Parked | External-expert decision analysis; isolated, no shared state |

Isolation: tracks have separate worktrees, ledgers, configs, and artifacts.
No track may mutate another's state. The model bridge is shared, and the
scheduler explicitly never restarts a bridge serving foreign models.

## 16. Operator commands

All run from `/home/udi/udi_provate/TradingAgents-alpha-rnd` unless noted
(PYTHONPATH=. ; production runtime is `.venv312/bin/python` — the code uses
`datetime.UTC`, which system Python 3.10 lacks).

| Command | What it shows/does |
|---|---|
| `python -m ops.roadmap_status` (tracks repo) | roadmap/task state, deterministic, no network |
| `python -m alpha_rnd.daily_scheduler --status` | completed sessions, current run, bridge, session statuses |
| `python -m alpha_rnd.daily_scheduler --check` | one due-cycle check (the hourly cron entry) |
| `python -m alpha_rnd.infra_status` | bridge process + upstream model status, reason codes, capability |
| `python -m alpha_rnd.monitor --once` | one monitor pass (what cron runs every minute) |
| `python -m alpha_rnd.monitor --status` | book view: positions, waiting watches, triggered, reanalysis |
| `python -m alpha_rnd.cohort_outcomes status` | R2 evaluator health/last run |
| `python -m alpha_rnd.cohort_outcomes session <date>` | per-session cohort outcome report |
| `python -m alpha_rnd.cohort_outcomes update` | mature pending horizons (what the :23 cron runs) |
| `python -m alpha_rnd.funnel_status --session <date>` | R1 funnel artifact view |
| `python -m alpha_rnd.ta_outcomes session <date>` | R3 signal-vs-outcome view |
| `python -m alpha_rnd.translator_gap session <date>` / `case <date> <t>` | R4 gap report |
| `python -m alpha_rnd.low_price_shadow status` / `session` / `case` | R6 shadow lane |
| `python -m alpha_rnd.investigate --ticker <T>` / `--all` / `--build` | R7 postmortems |
| `python -m alpha_rnd.replay audit --as-of <date>` | replay PIT audit (no inference) |
| `python -m alpha_rnd.replay run --as-of <date> --policy <P>` | isolated replay run (does call the model) |
| `python -m alpha_rnd.r5b_report` | R5B paired comparison report |
| `python -m alpha_rnd.mgmt status` | post-entry shadow management view (Phase B) |

## 17. Failure scenarios

| Situation | Behavior | User action |
|---|---|---|
| Model rate-limited | TA stage makes zero calls inside the reset window; pending tickers stay `RETRY_PENDING`; one degraded/infrastructure alert per session | none |
| Quota exhausted | `QUOTA_EXHAUSTED` is non-retryable and flagged `user_action_required` → ACTION_REQUIRED alert | required |
| Bridge process down | Cycle ends `BLOCKED`; scheduler can restart only a *down* bridge, never a foreign-busy one; retried next tick | none normally |
| Partial TA success | Session stays incomplete; successes preserved; pending retried in bounded background runs; publication marks "ANALYSIS INCOMPLETE" | none |
| Translator/malformed output | Deterministic validation fails closed: `AMBIGUOUS_REJECTED`/`RESEARCH_ONLY`, never an investment action; malformed *calls* become infrastructure failures | none |
| Machine off overnight | Next check runs the latest completed session; pending orders whose opens passed are MISSED, not retro-filled; monitor resumes next tick | none |
| Stale watch exists | Entry gate requires latest-revision `EXECUTABLE_WATCH`; stale watches cannot buy | none |
| Telegram relay restarts | Relay state persists; semantic dedup and circuit breaker prevent floods; a lost message loses nothing (Telegram is not authority) | none |
| Replay crashes mid-run | Completed artifacts persist; resume skips them; known wart R5B-B1: a translator 502 can abort `run()` before `run_result.json` — artifacts still safe | none |
| Market data fetch fails | Transient fetch failures keep outcomes `PENDING` rather than burning them as unavailable | none |

## 18. Safety invariants

Verified against current code/tests:

- [ ] No valid inference result → no investment-semantic result.
- [ ] Only the latest-revision `EXECUTABLE_WATCH` may create a new entry;
      checked again inside `do_fill`.
- [ ] Replay cannot mutate cash, positions, watchlist, pending orders,
      production publication, or production Telegram events.
- [ ] Successful TA artifacts are never rerun.
- [ ] The current market session is never starved by old retries (priority +
      bounded background retry + fair ordering + 7-day lifetime).
- [ ] Existing-position monitoring runs every minute independent of fresh
      inference, and runs first inside every pipeline cycle.
- [ ] Infrastructure failures stay infrastructure failures — they cannot
      become dispositions; terminal failures make a session
      `session_terminal` but never `analysis_complete`.
- [ ] Economic actions are idempotent (executed IDs, outbox pattern,
      semantic event dedup).
- [ ] Audit/notification duplication is not economic authority.
- [ ] Non-executable research outcomes never produce individual Telegram
      alerts.

## 19. File and artifact map

| Path | Role |
|---|---|
| `alpha_rnd/monitor_state.json` | **economic authority**: cash, realized, positions, pending orders, exec IDs |
| `alpha_rnd/live_watchlist.json` | current watch specs (regenerated atomically) |
| `alpha_rnd/trigger_events.jsonl` | immutable event audit |
| `alpha_rnd/scheduler_state.json` + `scheduler_events.jsonl` | scheduler lifecycle + events |
| `alpha_rnd/scheduler.log`, `monitor_cron.log`, `cohort_outcomes.log` | logs |
| `evaluations/alpha_rnd_v1/candidate_pool_frozen_<s>.json` | frozen daily pools |
| `evaluations/alpha_rnd_v1/case_artifacts/<T>_<s>.json` (+ `.error.json`) | production TA artifacts / failure records |
| `evaluations/alpha_rnd_v1/analysis_status_<s>.json` + `analysis_ledger_<s>.json` | per-ticker analysis state + retry ledger |
| `evaluations/alpha_rnd_v1/publication_intents_<s>.json` / `publication_status_<s>.json` | intents + dispositions |
| `evaluations/alpha_rnd_v1/alpha_paper_ledger.jsonl` | append-only fill ledger |
| `evaluations/alpha_rnd_v1/opportunity_funnel/` | R1 frozen funnels |
| `evaluations/alpha_rnd_v1/rank_cohort_outcomes*/` | R2/R6 outcome stores |
| `evaluations/alpha_rnd_v1/replays/` | R5A/R5B isolated replay artifacts + checkpoints + `R5B_REPORT.txt` / `R5B_RESULTS.json` |
| `evaluations/alpha_rnd_v1/market_cache_*.pkl`, `fundamental_facts_*.json`, `universe*` | frozen PIT inputs |
| `TradingAgents-tracks/state/alpha_opportunity_coverage.yaml` | roadmap source of truth |
| `TradingAgents-tracks/docs/ALPHA_OPPORTUNITY_COVERAGE_ROADMAP.md` | canonical roadmap |

## 20. Current limitations

- **PIT news granularity:** replay news/sentiment is only approximately
  point-in-time; the post-check flags post-session dates in artifact text but
  scheduled forward dates (earnings, investor days) are legitimate and were
  verified manually, not mechanically.
- **Horizon maturity:** R5B's H5 for 10-09/10-12 and all H20 are pending;
  session selection preferred recency over maturity (logged as B2 finding).
- **Inference cost/latency:** a full-pool TA pass is expensive (~25 bridge
  calls per ticker, ~8 min each); coverage decisions must respect that.
- **Provider-status evidence:** upstream status derives only from real
  execution evidence; after a reset window expires the system is honestly
  `UNKNOWN` until the next attempt succeeds or fails.
- **Historical universe fidelity:** replay universes are reconstructed;
  survivorship/delisting completeness is bounded by the frozen inputs.
- **R5B-B1:** a translator bridge failure mid-replay can abort `run()`
  before `run_result.json` is written (artifacts persist; resume is safe;
  engine fix deferred).
- **Single-machine, single-user operation:** no HA, no multi-writer support;
  correctness relies on flock discipline and atomic writes.

## 21. Keeping this guide true

Per `docs/ROADMAP_OPERATING_RULES.md`: any change that alters disposition
meanings, entry authorization, economic authority, scheduler lifecycle,
inference-failure semantics, retry behavior, replay behavior, or operator
commands **must update this guide in the same task/commit set.**
