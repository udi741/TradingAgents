# Track: C12_PROSPECTIVE

# PURPOSE

Test the frozen official TradingAgents v0.5.0 pipeline prospectively as an
honest control: S&P 500 discovery -> Lane-A screener -> top 10 -> full
official v0.5.0 decision layer -> flat PortfolioContext -> paper portfolio
external to TA. It exists to produce clean evidence, not to generate trades.

# WHY C12 EXISTS

Historical evaluation is useful: it explains the framework, generates
hypotheses, backtests, finds bugs, and tells us whether a strategy *looks*
promising. But it cannot fully answer the narrower question C12 exists for:

> "After the baseline is frozen and the future is genuinely unknown, do its
> ENTRY decisions outperform its NO_ENTRY decisions?"

No historical dataset can settle that cleanly: LLMs carry post-date knowledge;
company facts and news are served at today's revised vintage; survivorship and
selection effects bend the sample; and we ourselves have already seen the
historical outcomes, so any selection tuned on them is contaminated. The
future is the only dataset guaranteed never to have been observed.

C12 being slow does NOT mean the project waits on it. It is a background
control; ALPHA_RND runs its own active opportunity research independently.

# OPERATION

C12 weekly cycles are **background-automated** (hourly cron checker
`ta_eval/c12_scheduler.py`), not manually fired from a chat prompt. The
checker decides due/late/missed deterministically and invokes the frozen
prepare/run/settle commands; it also settles pending orders at their real
next-session opens and scores matured outcomes. If the machine is off,
nothing runs and nothing is fabricated; a due cycle whose execution deadline
passed is recorded LATE_DECISION_NON_SCOREABLE. See the runbook for the
schedule, logs, and how to disable it.

# STATUS

ACTIVE — Epoch 2. First scoreable cycle COMPLETE: 2026-10-02 session,
SCOREABLE (screen 10:29Z + freeze 11:16Z, both before 10-05 13:30Z
deadline). 10 decisions: ENTRY = HPE (Buy), NTAP (Buy) — pending Monday
open; 8 NO_ENTRY. Scoreable observations so far: 10 signals, 0 fills yet.

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

See `state/C12_PROSPECTIVE.yaml`. First Epoch-2 cycle completed
2026-10-03, SCOREABLE. Two ENTRY orders await the real 2026-10-05 open;
no fills exist yet.

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

After the 2026-10-05 session completes, run `--settle-pending-fills` to
fill HPE/NTAP at the real open, then `--score-matured` and
`--update-marks`. Next weekly cycle becomes due after 2026-10-09
finalizes.

# HISTORY

- Epoch 1: operational dry run; timing failure on 2026-09-25 (decisions
  created after scheduled next-session open) -> LATE_DECISION_NON_SCOREABLE,
  zero fills -> timing guard added.
- Epoch 2 created 2026-10: fundamentals provider policy tightened to
  SEC-pinned fail-closed statement tools.
- EXPERT_RND session (2026-10-02) did not touch this track.
- 2026-10-03: first Epoch-2 cycle (session 2026-10-02) ran and froze
  SCOREABLE — 2 ENTRY (HPE, NTAP) pending the real 10-05 open.
  One transient: v0.5.0 SEC cache tmp-rename race on parallel statement
  fetches caused 6 TERMINAL_INVALID on pass 1; warm-cache retries under the
  frozen checkpoint policy resolved all 10 cases. Adoption-added armed
  launcher was reverted before the run (runtime == c559dbfe).

# LAST UPDATED

2026-10-03T11:30Z (kindly-nightshade — first scoreable Epoch-2 cycle)
