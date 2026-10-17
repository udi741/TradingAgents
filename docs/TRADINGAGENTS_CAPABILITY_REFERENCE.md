# TradingAgents Capability Reference — human map of the framework

Canonical machine registry: `docs/TRADINGAGENTS_CAPABILITY_REGISTRY.yaml`
(drift-checkable truth). This document is the narrative map. Module paths are
relative to the ALPHA worktree `/home/udi/udi_provate/TradingAgents-alpha-rnd`;
`tradingagents/` there is the vendored library ALPHA actually imports (the
`tradingagents/` dir in this tracks repo is a byte-identical mirror, and the
C12 worktree carries the frozen v0.5.0 tree — neither is on ALPHA's path).

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
- **Data tools never serve past `trade_date`** — every dated tool clamps
  requested windows to the run date; undated items are kept only when the
  window reaches the present.

## The two stacks

1. **ALPHA operating layer** (`alpha_rnd/`, `evaluations/alpha_rnd_v1/`,
   `ta_eval_alpha/`): discovery → TA deep analysis → synthesis/publication →
   watchlist → monitor/entry → deterministic + adaptive management → outcomes.
2. **Vendored TradingAgents core** (`tradingagents/`): the LangGraph
   multi-agent debate ALPHA invokes per ticker via `run_ta.py` and the
   `tradingagents-swe-bridge` systemd service (OpenAI-compatible endpoint at
   `127.0.0.1:8765/v1`; `devin-quick`=swe-2-medium for analysts/debaters/
   trader, `devin-deep`=swe-2-high for Research Manager + Portfolio Manager;
   temperature 0).

## Vendored TA core — the per-ticker debate

`TradingAgentsGraph.propagate(ticker, trade_date, asset_type, portfolio)`:

1. **Instrument context** — deterministic fail-open yfinance identity lookup
   (`agents/context.py`) injected into every agent so the model anchors to the
   real company; historical runs get the current NAME only, labeled as such
   (today's sector/industry may not have held then).
2. **Memory settle + PIT lessons** — pending same-ticker decisions whose
   holding window (ALPHA: 20 trading days) has traded are settled vs the
   benchmark index, a reflection is written; the PM receives only lessons with
   `resolved:<=trade_date` (#1251).
3. **Analysts in PARALLEL**, each a private subgraph returning only its report,
   each capped at `max_tool_rounds=20` tool rounds then forced to WRAP_UP:
   - *Market* (quick): ≤8 of 12 curated indicators; must call
     `get_stock_data` first; must call `get_verified_market_snapshot` (a
     deterministic OHLCV+indicator truth table) before any exact price claim.
   - *Sentiment* (quick): pre-fetched Yahoo news + StockTwits + Reddit blocks
     (window-trimmed to the 7 days ending trade_date), optional TypeSafe Jev
     screening when `TYPESAFE_API_KEY` is set; structured `SentimentReport`
     (band/score/confidence).
   - *News* (quick): `get_news`, `get_global_news`, `get_macro_indicators`
     (FRED), `get_prediction_markets` (Polymarket).
   - *Fundamentals* (quick): `get_fundamentals`, statements, insider
     transactions — ALPHA pins all statement tools to `sec_edgar`.
4. **Bull/Bear debate** (quick LLM, `2*max_debate_rounds` turns) →
   **Research Manager** (deep LLM, structured `ResearchPlan`: 5-tier
   recommendation + rationale + strategic actions) → **Trader** (quick,
   structured `TraderProposal`: Buy/Hold/Sell + absolute entry/stop prices —
   percentages/ranges are dropped by the schema — + sizing; grounded in the
   market report) → **risk debate** (quick; aggressive→conservative→neutral
   rotation, `3*max_risk_discuss_rounds`) → **Portfolio Manager** (deep,
   structured `PortfolioDecision`: final 5-tier rating + thesis).
5. **Rating/REVIEW** — `final_rating` comes from the PM's structured field;
   free-text fallback parsed by a tolerant label parser; no readable rating →
   `REVIEW` sentinel, never silently Hold.
6. **Persistence** — `record_decision` appends to the append-only memory log
   (idempotent per ticker+date); reports tree via `reporting.py`; per-ticker
   SQLite checkpoint/resume keyed by a run signature (analysts + rounds +
   asset + portfolio fingerprint + config digest), cleared on success.

Structured output everywhere degrades to free text on provider failure —
the pipeline never blocks on schema support (`structured.py`).

## Vendor / data semantics (who can leak the future)

Routing (`dataflows/router.py`): the configured vendor string IS the chain —
no silent fallback to unconfigured vendors; `tool_vendors` overrides
per-tool. Typed failures produce model-visible sentinels
(`NO_DATA_AVAILABLE`/`DATA_UNAVAILABLE` — "do not fabricate"); optional
categories `macro_data`/`prediction_markets` degrade to a sentinel instead of
aborting; core categories raise.

| Source | PIT behavior | Key | Failure semantics |
|---|---|---|---|
| yfinance OHLCV/indicators | as_of-filtered, stale>10d rejected, 5y same-day-TTL cache | none | 429 → 3 exp. retries; empty → host-probed no-data |
| yfinance profile/insider/statements | **TODAY_ONLY — withheld on historical runs** (no vintage/filing date) | none | as above |
| yfinance news | window-trimmed, recent-only feed; coverage_gap honesty | none | sentinel |
| SEC EDGAR statements | **TRUE PIT** — XBRL facts by filed date ≤ as_of, amendments from filing date; US filers only; ALPHA pins statements here | UA env `SEC_EDGAR_USER_AGENT` | non-filer → NoMarketData → next vendor |
| FRED macro | **TRUE PIT** — realtime vintage pinned to `min(as_of, FRED-today CT)` | `FRED_API_KEY`; absent → optional-category sentinel | sentinel, visible to model |
| Polymarket | **TODAY_ONLY** — withheld on historical | none | sentinel |
| Reddit | partial: RSS `t=week`, window-trimmed, ~7d reach; coverage_gap when window unobservable | none | ONE 429 retry (Retry-After, else ~60s jittered); failure = `<unavailable>`, never silence |
| StockTwits | partial: recent stream, window-trimmed | none | no retry; `<unavailable>` placeholder |
| Alpha Vantage | same withhold guards; configured but unused by ALPHA | `ALPHA_VANTAGE_API_KEY` | typed errors → router chain |
| TypeSafe Jev | screens social posts (on-topic ≥0.3, stance ≥0.5 conf) | `TYPESAFE_API_KEY`; absent = off | posts kept, "unscreened" note |

Provider-health ledger: `infra_status.py` classifies bridge journal evidence
into reason codes (`MODEL_RATE_LIMITED`, `QUOTA_EXHAUSTED`, `UNAVAILABLE`,
`TIMEOUT`, `BRIDGE_FAILURE`, `TA_RUNTIME_FAILURE`, `MALFORMED_MODEL_OUTPUT`,
`UNKNOWN`), separates BRIDGE_PROCESS from UPSTREAM_MODEL, and writes
`case_artifacts/*.error.json` failure records + `publication_status_*.json`
translator-failure records. Failures ARE visible downstream — a failed ticker
simply has no intent (fail-closed for entry) and a retryable/non-retryable
verdict for the scheduler.

## ALPHA lifecycle map

### Discovery — ACTIVE_PRODUCTION
`discovery.py` (deterministic, no LLM): Wikipedia/nasdaqtrader universe →
junk-name filter → eligibility (≥252 sessions, close ≥$5, median 20d dollar
volume ≥$20M) → multi-lane scores (momentum, relative strength, quality
pullback, dated SEC catalyst, fundamental acceleration via filed-date
companyfacts) → frozen `candidate_pool_frozen_<session>.json` + `deep_quota=10`
deep picks. `funnel.py` (R1) freezes the immutable ex-ante per-session
funnel artifact.

### TA + synthesis — ACTIVE_PRODUCTION
`run_ta.py` → sha-stamped `case_artifacts/` (cached; a rerun is read-only).
`synthesize.py` translates TA text → intents through the bridge; numbers must
already exist in the artifact text; deterministic disposition per ticker:
`EXECUTABLE_WATCH | REANALYZE_ON_TRIGGER | RISK_PLAN_REQUIRED | RESEARCH_ONLY |
AMBIGUOUS_REJECTED | NO_ACTION | OPEN_POSITION_MANAGEMENT(unused) |
PUBLISHED_NON_EXECUTABLE`. EXECUTABLE_WATCH requires watch_mode ∈
{AUTO_ENTRY, DETERMINISTIC_CONFIRMATION} + an executable param key
(zone/zone1/zone2/pb_zone/retest_zone/bo_level/levels/kill/probe_zone/
gate_date/reclaim/hold/alt_level/veto_level) + a machine risk plan.

### Publication — ACTIVE_PRODUCTION
`publish.py` atomically rewrites `live_watchlist.json`: curated spec
(`gen_watchlist.py`) merged with publishable intents from all sessions ≤ the
published one; newer session wins per ticker; `monitor_state.watch_lifecycle`
terminal/revised watches never resurrect; `scheduler_state.published_sessions`
records the marker.

### Entry — ACTIVE_PRODUCTION
`entry_gate.authorized`: latest frozen publication for the ticker must be
EXECUTABLE_WATCH and the watch's revision must BE that latest session —
fail-closed. `monitor.do_fill`: authorization → risk-plan gate → success-plan
gate → next-open fill, 0.1% fee, exec-id dedup, `executed[]` capped at 2000.
Monitor evaluates 12 trigger primitives (see registry `entry.triggers`);
REANALYZE_ON_TRIGGER price legs only produce a "single-ticker refresh"
notification — never a fill.

### Economics — ACTIVE_PRODUCTION
`monitor_state.json` is THE authority: cash, positions, pending_open_fills,
pending_open_exits, executed[] (fill ids), outbox, watch_lifecycle.
`resolve_pending` fills queued orders at next open; `do_exit` drops matching
pending exits. `alpha_paper_ledger.jsonl`, `trigger_events.jsonl`,
`management_events.jsonl` are EVIDENCE streams.

### Deterministic management — ACTIVE_PRODUCTION
`intraday_pass`/`close_pass`: hard intraday stops and close_below rules →
next-open exits, before and independent of all inference.

### Adaptive management — ACTIVE_PRODUCTION (paper, enabled 2026-10-16)
`mgmt.py`: immutable `entry_snapshots/` (frozen success_plan + original stop =
the R basis, 1R=(entry−stop)/entry); R-triggers: APPRECIATION ≥1.0R,
PEAK_GIVEBACK (peak ≥1R surrendering ≥50%), ADVERSE_ACCELERATION ≤−1.25R,
HORIZON_REVIEW at the snapshot's parsed reeval date; no valid stop →
R_CONTEXT_UNAVAILABLE suppresses price triggers; edge-fire + 2-session
cooldown + 20% hysteresis; catalyst reserved/disabled. `mgmt_reassess.py`:
frozen context + position fingerprint staleness → bridge analysis.
`mgmt_validate.py`: never-widen, partial normalization, composite stop,
runner contract. `mgmt_exec.py`: VALID → `management_actions.json`
ENQUEUED → canonical pending exit → next-open fill; kill switch
`management_policy.json execution.enabled` cancels unfilled adaptive orders,
never reverses fills.

### Prospective evaluation (R1–R7) — RESEARCH/SHADOW only
R1 `funnel.py`, R2 `cohort_outcomes.py` (H1/H5/H20/H60 next-open outcomes vs
SPY, MFE/MAE, scheduled+flocked), R3 `ta_outcomes.py`, R4 `translator_gap.py`
(monitor-capability catalog read from the monitor.py git revision live at the
session — no retroactive relabeling), R6 `low_price_shadow.py` ($1–$5
counterfactual lane, SHADOW_ONLY, separate outcome store), R7
`postmortems.py`/`investigate.py` (incident-aware per-trade packets).
`replay.py`, `r5b_report.py`, `mgmt_time_machine.py`: as-of replay/simulation;
never write `monitor_state.json`. `tradingagents/backtest.py`: upstream grid
runner; scores the memory log, not a portfolio simulator.

### Operations — ACTIVE_PRODUCTION
`daily_scheduler.py`: sched+cycle locks, per-stage subprocess timeouts,
upstream-known-down skips, INTERRUPTED honesty, urgent-mgmt pre-pass.
`monitor.py::notify`: NOTIFICATIONS.log + libnotify desktop popups;
`ops/telegram_relay.py` (this repo, `tradingagents-telegram.service`) tails the
event streams to Telegram with severity routing, semantic dedup by transition
identity, and a circuit breaker; delivery != proof. Bridge journal = model-call evidence.
`infra_status.py` = provider-health ledger (no model calls).

## Duplication / authority

| Capability | Authoritative | Non-authoritative |
|---|---|---|
| Portfolio/fills | `monitor.py` + `monitor_state.json` | `mgmt_time_machine.py`, `replay.py`, `backtest.py` |
| Exit execution | `pending_open_exits` + `resolve_pending` | time-machine treatment fills |
| Trigger logic | `mgmt.py::evaluate` + monitor passes | replay copies (research) |
| Discovery scoring | `e17_screener.py` via `discovery.py` | `low_price_shadow.py` (shadow pop only) |
| Vendored TA library | `TradingAgents-alpha-rnd/tradingagents/` | `TradingAgents-tracks/tradingagents/` mirror, C12 frozen tree |

## State authority (summary)

AUTHORITATIVE: monitor_state.json (economics + watch_lifecycle),
management_actions.json (adaptive lifecycle), entry_snapshots/ (immutable
entry belief), management_intents/ (validated decisions),
publication_intents_<session>.json (frozen dispositions, append-only),
live_watchlist.json (watches/stops), opportunity_funnel/ + rank_cohort_
outcomes*/ (frozen evaluation evidence), trading_memory.md (decision log),
scheduler_state.json (ops markers). OBSERVABILITY_ONLY: management_state.json,
management_requests/. EVIDENCE: ledgers, event streams, bridge journal.

## Track boundaries

| Track | Worktree | Type | May mutate production | Outputs |
|---|---|---|---|---|
| ALPHA_RND | TradingAgents-alpha-rnd (`exp/alpha-rnd-v1`) | paper R&D | its own only | paper evidence |
| C12_PROSPECTIVE | TradingAgents-c12 (`exp/gate-c12-prospective`) | frozen v0.5.0 validation control | none — do not touch | clean validation evidence |
| EXPERT_RND | TradingAgents-expert-rnd | analysis R&D | no | signal evidence |
| TIME_MACHINE_RND | TradingAgents-time-machine-rnd | broad research | no | simulation only |
| narrow lifecycle research | in alpha worktree (`mgmt_time_machine.py`, `replay.py`) | research | no | simulation only |
| TRACKS | TradingAgents-tracks | docs/registry hub | n/a | docs |

## Config keys that change investment behavior

- `llm_provider`/`deep_think_llm`/`quick_think_llm`/`backend_url` — model
  routing (ALPHA: openai_compatible bridge, swe-2-medium/-high, temp 0).
- `max_debate_rounds`, `max_risk_discuss_rounds`, `max_tool_rounds`,
  `max_recur_limit` — debate/tool depth.
- `data_vendors`/`tool_vendors` — vendor chains; ALPHA pins statements to
  sec_edgar.
- `holding_period_days` (20 in ALPHA), `benchmark_ticker`/`benchmark_map` —
  memory-settlement economics.
- `checkpoint_enabled`, `news_*` limits, `global_news_queries`,
  `output_language`, `temperature`, `llm_max_retries`, `max_tokens`,
  thinking-effort keys, `memory_log_max_entries`.
- `TRADINGAGENTS_*` env overrides for all of the above; `FRED_API_KEY`,
  `SEC_EDGAR_USER_AGENT`, `TYPESAFE_API_KEY`, `ALPHA_VANTAGE_API_KEY`,
  provider `*_API_KEY`s.
- ALPHA policy: `management_policy.json` (trigger R thresholds, debounce,
  catalyst disabled, `execution.enabled` kill switch, `success_plan`
  minimums), `daily_scheduler` stage timeouts/deep quota, `gen_watchlist`
  sizing (`position_notional`, `max_positions`, `cost_bps`).

## Known documentation gaps (honest)

- Social feeds are window-trimmed, not archived: historical sentiment is
  coverage-bounded, and the model is told via coverage_gap markers.
- The `OPEN_POSITION_MANAGEMENT` disposition is UNUSED (audit label only).
- `cli/` (Typer TUI) and `main.py` (upstream demo) are not on ALPHA's path.
