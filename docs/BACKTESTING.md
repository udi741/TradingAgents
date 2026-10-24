# Backtesting & Evaluation Guide

**Start here: `python -m alpha_rnd.backtest --help`**

"Backtesting" in TradingAgents is not one thing. Four different questions
need four different tools — conflating them produces false confidence:

1. "Does the *pipeline* work?" — engineering regression
2. "Does the *AI reasoning* work?" — model behavior on historical inputs
3. "Would the *strategy* have made money?" — historical economic evaluation
4. "Does the *deployed system* have alpha?" — prospective evidence

Only #4 is real alpha evidence. #1 is regression. #2 evaluates AI behavior.
#3 is a caveated historical estimate.

## Decision table

| I want to know... | Use |
|---|---|
| Did my publication/trigger/gate/order change behave correctly? | `targeted` |
| Did a safety rule still block correctly? | `targeted` |
| Can the AI turn PIT inputs into the intended structured decision? | `research-replay` |
| How would the full ALPHA process have performed on a sample? | `strategy-backtest` |
| Score core-lib decisions over a ticker×date grid? | `grid-backtest` / `tradingagents backtest` |
| Is the live/paper system working on post-freeze data? | `prospective` |

## Mode reference

### targeted — pipeline replay (default dev tool)

Replays an explicit scenario manifest through the real validate →
contract → disposition → trigger → entry-gate → pending-order chain on
persisted artifacts and cached bars.

- AI calls: **NONE**. Provider calls: **NONE**. Cost: LOW (seconds).
- Hindsight selection: allowed — *engineering regression only*.
- Model contamination: none (no model).
- Production mutation: none — in-memory state + tmp dir.
- Alpha evidence: **none.**
- Command:
  `python -m alpha_rnd.backtest targeted evaluations/alpha_rnd_v1/scenario_packs/initial.json`
- Output: per-scenario trace + PASS/FAIL summary on stdout.

### research-replay — PIT AI replay

Re-runs the research pipeline as though a historical session were today:
frozen universe/market data → selection → TA via `graph.propagate` →
synthesis → shadow publication, in an isolated `evaluations/.../replays/`
namespace.

- AI calls: **YES** (devin-deep via bridge). Providers: possible. Cost: MEDIUM/HIGH.
- PIT integrity: hard-fails if any market bar postdates the session;
  news post-check scans artifact text for dates > session.
- **MODEL_KNOWLEDGE_CONTAMINATION_RISK**: the current model may already
  "know" events after the as-of date. Results evaluate *AI behavior*,
  not clean alpha.
- Commands:
  `python -m alpha_rnd.backtest research-replay audit --as-of 2026-10-21`
  `python -m alpha_rnd.backtest research-replay run --as-of 2026-10-21 --policy CURRENT_PRODUCTION [--max-ta N]`
- Output: `evaluations/alpha_rnd_v1/replays/<session>/<policy>/`.

### grid-backtest — core-library decision sweep

`tradingagents/backtest.py` runs `TradingAgentsGraph` over a user-chosen
ticker × date grid and scores each decision's realized/alpha return vs
the instrument's regional benchmark, written to its own memory log.

- AI calls: **YES** (full graph per cell). Providers: **YES**. Cost: HIGH.
- PIT: date-window bounded inputs.
- MODEL_KNOWLEDGE_CONTAMINATION_RISK applies.
- Not a portfolio simulator by design (no quantities, fills, cash).
- Command: `tradingagents backtest NVDA,AAPL --start ... --end ... --every 7`
  or the `run_backtest` Python API. The front door routes to the same
  implementation: `python -m alpha_rnd.backtest grid-backtest NVDA,AAPL
  --start ... --end ... --every 7` (arguments pass through to the existing
  typer `backtest` command; the contamination warning prints first).

### strategy-backtest — composite, not a dedicated engine

No single module does a full strategy backtest. The composite is:

1. `research-replay run --policy ANALYZE_ALL_CANDIDATES` (TA over pool)
2. `python -m alpha_rnd.backtest strategy-backtest --report <sessions>` →
   `alpha_rnd/r5b_report.py` paired-outcome report (next-open fills,
   H1/H5/H20, SPY excess, MFE/MAE)
3. `python -m alpha_rnd.cohort_outcomes update` → R2 rank-cohort
   forward outcomes (append-only, ex-ante cohort membership)

Caveats: PIT-bounded inputs; next-open fill assumption; model
contamination via the TA call; a hindsight-selected scenario pack is
**not** strategy evidence.

### prospective — strongest evidence

Live/paper forward record on data that arrived after the design froze.
`python -m alpha_rnd.backtest prospective` prints read-only status:
cohort-outcome tracker, TA accept/reject outcomes, ledger location.
There is no "run" command — evidence accumulates from the deployed
system; don't force it.

## Scenario manifests

Each scenario: `{id, class, ticker, session, reason, intent{overlay},
watch{trigger_type,params,stop_rule,invalidation}, grant_authorization,
expected{disposition,trigger,order,risk_blocked,not_authorized}}`.

- `intent` overlays the *persisted* intent for that ticker/session; in
  the contract era it models what the new translator emits (typed
  `ambiguities`, `economic_authority`). Contract numbers must appear
  verbatim in the artifact text (evidence binding is enforced).
- Positive-path scenarios assert the framework *can* progress; negative/
  safety scenarios assert it stays blocked. Expected values assert
  **behavior, never profit** — "must buy because it rallied" is wrong.
- Caps: ≤12 scenarios, ≤10 sessions each; exceeded → hard stop.

## Legacy/internal entry points

| Module | Status | Invoke directly? |
|---|---|---|
| `tradingagents.backtest` | grid evaluator (`grid-backtest`) | yes, documented CLI/API |
| `alpha_rnd.scenario_replay` | engine for `targeted` | works; prefer front door |
| `alpha_rnd.replay` | engine for `research-replay` | works; prefer front door |
| `cohort_outcomes`, `ta_outcomes` | prospective measurement CLIs | yes, read-only |
| `r5b_report` | strategy-backtest reporting | via front door `--report` |
| `mgmt_time_machine` | frozen-manager eval | specialized, run directly |
| `reuse_engine`, `reuse_shadow`, `delta_probe` | reuse validation | specialized internals |
| `postmortems`, `investigate`, `funnel_status` | diagnosis CLIs | specialized, direct ok |
| `daily_scheduler`, `monitor`, `publish`, `synthesize`, `gen_watchlist` | production pipeline | **never run ad hoc** |

## Examples

```bash
# regression after changing gate/trigger code
python -m alpha_rnd.backtest targeted \
  evaluations/alpha_rnd_v1/scenario_packs/initial.json

# is a session replayable at all?
python -m alpha_rnd.backtest research-replay audit --as-of 2026-10-21

# forward evidence so far
python -m alpha_rnd.backtest prospective
```

## Safety

Evaluation commands must not mutate production trading state
(`live_watchlist.json`, `monitor_state.json`, `scheduler_state.json`,
`alpha_paper_ledger.jsonl`, management state/actions). `targeted`,
`research-replay`, `strategy-backtest --report`, and `prospective` are
all read-only or tmp-namespaced by design. If a command writes outside
its replay/tmp namespace, that is a bug — stop and fix it.
