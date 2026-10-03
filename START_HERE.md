# START HERE — TradingAgents project

**Read this file first. Chat history is not authoritative project state.**

## Project objective

Find stocks worth buying, improve TradingAgents' ability to identify/trade
them, and accumulate honest evidence about whether the recommendations work.

Validation is deliberately separated from R&D: a frozen control pipeline
produces clean evidence while parallel research tracks search for
opportunities and improvements.

## The tracks

| Track | Type | What it does |
|---|---|---|
| **C12_PROSPECTIVE** | Validation / control | Frozen official TradingAgents v0.5.0 run prospectively, honestly, paper-only |
| **ALPHA_RND** | Active R&D | Searches for current opportunities, paper trades them, improves process |
| **EXPERT_RND** | Analysis R&D | Studies an external expert's decisions; historical mimic CLOSED; now capturing prospective signals |
| **PROJECT_CONTROL** | Documentation | Owns global docs/architecture only — not a per-experiment gatekeeper |

Tracks run in **parallel** in separate git worktrees and separate Devin
sessions. No track may modify another track's worktree, ledger, config, or
artifacts.

## Reading order

1. `START_HERE.md` (this file)
2. `CURRENT_STATE.md` — what is happening right now, what the user should do
3. `TRACKS.md` — canonical registry of all tracks
4. `tracks/<TRACK>.md` — the track you care about
5. `docs/OPERATING_RULES.md` — durable project rules
6. `runbooks/<relevant>.md` — how to actually run/resume things

Workspace layout and directory retirement rules:
`docs/WORKSPACE_INVENTORY.md` + `docs/WORKTREE_LIFECYCLE.md`.

## Source-of-truth order (when facts conflict)

1. Immutable artifact / ledger / committed experiment result
2. Per-track canonical Markdown + `state/<TRACK>.yaml`
3. `TRACKS.md`
4. `CURRENT_STATE.md`
5. `ai/*` context summaries
6. Chat history (**last resort — never treat it as state**)

Conflicts are never silently resolved — they are flagged and recorded.

## Key facts every session must know

- **NO LOCAL MODELS.** Model bridge: `devin-quick -> swe-2-medium`,
  `devin-deep -> swe-2-high`.
- Production reference: TradingAgents **v0.5.0**, SHA
  `2d17df8da1536c121e4d7395ac5a5dcec9e96d6f`.
- Everything is **paper trading only**. Paper results are not proof of
  profitability. No real-money deployment without a separate explicit
  promotion decision.
- New research starts from freshly fetched `origin/main`; existing track work
  continues in that track's existing worktree/branch.
- Use `UNKNOWN` rather than guessing a fact.
