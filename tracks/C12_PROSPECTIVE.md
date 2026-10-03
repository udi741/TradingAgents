# Track: C12_PROSPECTIVE

# PURPOSE

Test the frozen official TradingAgents v0.5.0 pipeline prospectively as an
honest control: S&P 500 discovery -> Lane-A screener -> top 10 -> full
official v0.5.0 decision layer -> flat PortfolioContext -> paper portfolio
external to TA. It exists to produce clean evidence, not to generate trades.

# STATUS

ACTIVE — Epoch 2 activated 2026-09-29T06:48:31Z (epoch_hash 753e3021…).
Scoreable observations: 0. First scoreable cycle (decision session
2026-10-02) is due now; deadline 2026-10-05T13:30Z.

# OWNER

Devin session `kindly-nightshade`. Worktree
`/home/udi/udi_provate/TradingAgents-c12`, branch `exp/gate-c12-prospective`.

# WHAT THIS TRACK MAY MODIFY

- Its own worktree, epochs, ledger, artifacts, config.
- SEC statement-tool provider pins (already applied, fail-closed).
- Its own docs: this file, `state/C12_PROSPECTIVE.yaml`,
  `runbooks/C12_PROSPECTIVE.md`, C12 rows in `docs/EXPERIMENT_REGISTRY.md`,
  and its own section of `CURRENT_STATE.md` / `TRACKS.md`.

# WHAT THIS TRACK MUST NEVER MODIFY

- The v0.5.0 decision layer (prompts, agents, graph) — must stay official.
- ALPHA_RND, EXPERT_RND, PROJECT_CONTROL worktrees/artifacts.
- LOCKBOX / HOLDOUT reserves.
- Any strategy idea imported from ALPHA or EXPERT experimentation.

# CURRENT STATE

See `state/C12_PROSPECTIVE.yaml`. Epoch 2 frozen; no cycle has run under it
yet. No runner/service is currently alive — the earlier armed sleeper died
with its session (never executed).

# FROZEN RULES / PROTOCOL

- Decision layer = official v0.5.0 (SHA
  `2d17df8da1536c121e4d7395ac5a5dcec9e96d6f`), unmodified prompts.
- Statement tools pinned fail-closed to SEC EDGAR (filing-date aware,
  `filed <= decision_session`): `get_balance_sheet`, `get_income_statement`,
  `get_cashflow`. No yfinance fallback for those three.
- Timing guard: decisions created after the scheduled next-session open make
  the cycle LATE_DECISION_NON_SCOREABLE — no executable paper orders, no
  retroactive fills.
- Append-only history; never rewrite an old result.

# IMPORTANT ARTIFACTS

C12 worktree internals (epochs, ledger). This control worktree holds only
documentation.

# ACCEPTED RESULTS

- Epoch 1 = operational dry run only; 0 scoreable observations.
- 2026-09-25 week = LATE_DECISION_NON_SCOREABLE; zero fills.
- Timing guard accepted and installed.
- Epoch 2 created after the SEC fail-closed pin policy change.

# REJECTED HYPOTHESES / DO NOT REPEAT

- Never count a late-decision week as scoreable or fill orders retroactively.
- Never treat C12 as a strategy playground.

# CURRENT OPEN QUESTIONS

- Does frozen v0.5.0 produce actionable prospective recommendations, and do
  they beat doing nothing? (This is what Epoch 2+ answers.)

# EXACT NEXT ACTION / TRIGGER

Run the 2026-10-02 Epoch 2 cycle before the 2026-10-05T13:30Z execution
deadline (`--prepare-week` then `--run-week 2026-10-02` in the C12 worktree;
rollover already passed 2026-10-03T05:00Z). Mark scoreable/non-scoreable;
record in ledger and update this doc + `state/C12_PROSPECTIVE.yaml`.

# HISTORY

- Epoch 1: operational dry run; timing failure on 2026-09-25 (decisions
  created after scheduled next-session open) -> LATE_DECISION_NON_SCOREABLE,
  zero fills -> timing guard added.
- Epoch 2 created 2026-10: fundamentals provider policy tightened to
  SEC-pinned fail-closed statement tools.
- EXPERT_RND session (2026-10-02) did not touch this track.

# LAST UPDATED

2026-10-03T10:24Z (kindly-nightshade — adoption/reconciliation: pending cycle
state verified against ledger; no cycle run)
