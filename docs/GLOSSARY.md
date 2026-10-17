# GLOSSARY — plain-English project terms

Written for the project owner, not for engineers.

**TradingAgents (TA)** — the open-source multi-agent LLM trading system this
project researches. Several AI "agents" debate and decide buy/sell/hold.

**v0.5.0** — the specific official release we treat as the production
reference. SHA `2d17df8da1536c121e4d7395ac5a5dcec9e96d6f`.

**Track** — one independent line of work with its own code copy, owner
session, and docs. Tracks: C12, ALPHA_RND, EXPERT_RND, PROJECT_CONTROL.

**Worktree** — a separate checked-out copy of the same repository so tracks
don't interfere. Each track has its own directory under
`/home/udi/udi_provate/`.

**C12 / C12_PROSPECTIVE** — the frozen control track. Runs the official
pipeline unchanged, forward in time, on paper, to honestly measure whether
recommendations work.

**Epoch** — one defined scoring period of C12 (roughly "a generation of
weekly cycles"). Epoch 1 was a dry run; Epoch 2 is the current one.

**Lane A** — the stock-screening step that picks candidate tickers (e.g.
S&P 500 momentum/technical screens) before the full AI pipeline runs.
"Broad non-S&P Lane A" was a retired expansion of that screen.

**Lane D** — a retired structured-fundamentals screening lane. Failed
out-of-sample; do not resurrect automatically.

**ENTRY / NO_ENTRY** — the pipeline's final verdict on whether it would buy
a stock at all (in historical replay tests).

**ACTIONABLE_NOW** — a recommendation strong enough to act on immediately
(no waiting for a better price).

**WATCH_FOR_ENTRY** — the pipeline likes the stock but only below/at a
named price zone; we wait and let the trigger system handle it.

**AUTO_ENTRY** — a watch trigger the monitor may paper-execute automatically
when its frozen limit is touched.

**DETERMINISTIC_CONFIRMATION** — a watch that needs a mechanical condition
(like a completed close above a level); on confirmation it fills at the next
session's open.

**REANALYZE_ON_TRIGGER** — a watch that, when its price/event trigger fires,
requires a fresh analysis session before any decision. It never auto-buys.

**MISSED_EXECUTION_REVIEW_REQUIRED** — the machine was off when an execution
should have happened. We record it and ask for review; we never invent the
fill.

**PortfolioContext** — the account summary (cash, positions) fed into the AI
so decisions account for what's already held. "Flat" means evaluated as if
starting empty.

**Prospective** — decided/recorded before the outcome is knowable. The only
kind of evidence that counts.

**Retrospective** — looked at after the fact. Useful for debugging, never
proof.

**Scoreable** — a C12 cycle that ran correctly and on time, so its results
count toward the honest score. Late or broken cycles are NON_SCOREABLE.

**LATE_DECISION_NON_SCOREABLE** — the cycle's decisions were created after
the market open they were supposed to precede; thrown out of scoring.

**Decision session** — the market date the analysis is supposed to be as-of.
All data used must be knowable by that date (filing-date aware).

**Execution deadline** — the next regular-session open at which a decision
must be executable to count as prospective.

**VALID_PROSPECTIVE_FILL** — a paper fill whose trigger existed before the
price move that triggered it.

**Paper trading / paper book / ledger** — simulated trading with fake money,
recorded in append-only files. Not proof of real profitability.

**Frozen / freeze** — writing a rule, trigger, or protocol down and
committing it before outcomes are known, so it can't be tuned to the result.

**NAV** — net asset value: cash + value of open paper positions.

**MFE / MAE** — max favorable / adverse excursion: how far a trade went in
your favor / against you at its best/worst point.

**Intended holding horizon** — how long the original recommendation planned
to hold (e.g. "6–12 months" for ACN). Decides management style.

**Research evaluation horizon** — standardized checkpoints (5/20/60/120/250
sessions, vs SPY) where we measure performance for science. A checkpoint is
NOT an automatic exit.

**E1 (staging counterfactual)** — ALPHA experiment comparing "buy at the
open" vs the disciplined staged-entry path, to measure whether patience
helps or hurts.

**LOCKBOX** — a sealed dataset nobody is allowed to touch. Keeps at least
one clean test set safe from accidental peeking/overfitting.

**HOLDOUT** — reserved data not used in research. Currently unused and must
stay that way.

**Prospective capture (expert)** — recording the expert's recommendation at
the moment it arrives, before anyone can know the outcome.

**Gate** — a named, bounded unit of work with acceptance criteria
(e.g. "X2 gate"). Tracks advance gate by gate.

**RM / Trader / PM** — roles inside TradingAgents: Research Manager
(structures the debate verdict), Trader (execution plan), Portfolio Manager
(final decision + sizing).

**Bridge / model bridge** — the remote LLM route. `devin-quick` maps to
swe-2-medium, `devin-deep` to swe-2-high. There are no local models.

**RISKIER_PATH_1** — label for a separate, more aggressive expert strategy
the disclosed PANW/FTNT/AMAT trades belonged to.

**Session (Devin session)** — a named Devin conversation that owns a track
(e.g. `kindly-nightshade` owns C12). Resuming the name resumes the context.
