# ARCHITECTURE — how the TradingAgents project is put together

## Plain-English version

The project runs one research codebase — **TradingAgents**, an LLM-driven
multi-agent trading-decision system — in several **parallel copies** (git
worktrees), each owned by a separate Devin session so experiments don't
contaminate each other:

- One copy is a **frozen control** (C12): it runs the official released
  pipeline unchanged, prospectively, to honestly measure whether the
  system's recommendations work.
- One copy is **active R&D** (ALPHA): it searches for current opportunities
  and paper-trades them under frozen, pre-committed rules.
- One copy is **analysis only** (EXPERT): it studies an external human
  expert's trades to learn whether anything reproducible exists.
- This worktree is **documentation only** (PROJECT_CONTROL): no code runs
  here.

No models run locally. All LLM calls go through a bridge:
`devin-quick -> swe-2-medium`, `devin-deep -> swe-2-high`. **NO LOCAL MODELS.**

Everything is paper trading. Nothing touches real money without a separate,
explicit promotion decision.

## Technical version

```
                        upstream TradingAgents repo
                        official ref: v0.5.0
                        SHA 2d17df8da1536c121e4d7395ac5a5dcec9e96d6f
                                    |
        +---------------------------+---------------------------+
        |              git worktrees (parallel copies)            |
+-------v--------+   +--------------v----+   +-----------------v--+
| TradingAgents- |   | TradingAgents-    |   | TradingAgents-      |
| c12            |   | alpha-rnd         |   | expert-rnd          |
| exp/gate-c12-  |   | exp/alpha-rnd-v1  |   | exp/expert-rnd-v2   |
|  prospective   |   |                   |   |                     |
| FROZEN CONTROL |   | ACTIVE R&D        |   | ANALYSIS ONLY       |
| session:       |   | paper book + cron |   | session:            |
| kindly-        |   | monitor           |   | groovy-allspice     |
| nightshade     |   | session: UNKNOWN  |   |                     |
+-------+--------+   +---------+---------+   +----------+----------+
        |                      |                        |
        +----------+-----------+-----------+------------+
                   |                       |
            LLM bridge              paper monitor
            devin-quick ->          alpha_rnd.monitor
            swe-2-medium            (cron, 1-min, market
            devin-deep  ->          data only, no LLM,
            swe-2-high              fills only on frozen
                                    pre-committed rules)

        +--------------------------------------------+
        | TradingAgents-tracks  (branch project/tracks)|
        | documentation only: START_HERE / TRACKS /     |
        | tracks/ state/ docs/ runbooks/ ai/            |
        +--------------------------------------------+
```

### Components

- **Upstream TradingAgents**: the real codebase (interactive CLI, agent
  graph, tools). Official production reference is tag `v0.5.0`, SHA
  `2d17df8da1536c121e4d7395ac5a5dcec9e96d6f`.
- **Devin coding-agent CLI**: each track is operated by a named Devin
  session inside its own worktree; sessions resume by session name.
- **Official interactive TA CLI / evaluation harness**: how decisions are
  produced inside a worktree; C12 uses it frozen, ALPHA/EXPERT may build
  evaluation tooling around it.
- **SWE-2 bridge**: remote model calls only; `devin-quick` (swe-2-medium)
  and `devin-deep` (swe-2-high). No local models, ever.
- **Track worktrees**: isolation boundary. A track may only modify its own
  worktree and its own docs.
- **Paper monitor** (`alpha_rnd/monitor.py` in the alpha worktree): pure
  market-data cron job; executes paper entries/exits strictly from
  pre-frozen trigger rules; append-only event log; `notify-send` desktop
  alerts; flags missed executions instead of faking fills.
- **Control/documentation worktree** (this repo): holds no implementation
  code of record; holds all canonical docs and state YAMLs.
- **Base repository role**: neutral canonical checkout / worktree factory —
  never used for experiments. See `docs/BASE_REPOSITORY_ROLE.md`
  (audit done; normalization pending a separate gate).

### Data integrity

- SEC fundamentals are filing-date aware (`filed <= decision_session`) and
  the three statement tools are pinned fail-closed to SEC EDGAR.
- Market data is point-in-time filtered (`Date <= as_of_date`) so artifacts
  cannot see future prices.
- Reserves: LOCKBOX untouched, HOLDOUT unused — always.
