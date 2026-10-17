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
   - **OPERATOR MANUAL:** `docs/TRADINGAGENTS_OPERATOR_MANUAL.md`
   - **New machine / fresh install:** `docs/NEW_MACHINE_SETUP.md`
   - **Architecture map:** `docs/SYSTEM_ARCHITECTURE.md`
   - **What file is authority for what:** `docs/STATE_AND_DATA_AUTHORITY.md`
   - **Something broke:** `docs/TROUBLESHOOTING_RUNBOOK.md`
   - **Development rules:** `docs/DEVELOPER_WORKFLOW.md`
2. `docs/ALPHA_SYSTEM_GUIDE.md` — how the ALPHA system works today
   (architecture, dispositions, retry semantics, authority, replay, commands)
3. `CURRENT_STATE.md` — what is happening right now, what the user should do
4. `TRACKS.md` — canonical registry of all tracks
5. `docs/ALPHA_OPPORTUNITY_COVERAGE_ROADMAP.md` — the development roadmap
6. `tracks/<TRACK>.md` — the track you care about
7. `docs/OPERATING_RULES.md` — durable project rules
8. `runbooks/<relevant>.md` — how to actually run/resume things

Incident and per-task history are evidence trails, not a starting point —
read them only when debugging a specific session.

Dashboard: `python3 -m dashboard.server` → http://127.0.0.1:8420
(read-only command center; runbook `docs/TRADINGAGENTS_DASHBOARD.md`).

Operator commands: `python3 -m ops.ta health` (deep check, exit 0/1/2),
`python3 -m ops.ta status` (quick summary),
`python3 -m ops.ta workspace status|setup` (canonical 5-worktree layout
from ops/workspace.json), `python3 -m ops.ta setup [--dry-run]`
(bootstrap a machine), `python3 -m ops.ta backup` / `restore <archive>`
(fail-closed, journaled), `python3 -m ops.ta bootcheck` (post-boot
self-test; also runs via tradingagents-bootcheck.timer).

Development roadmap / where the project stands:
`python -m ops.roadmap_status` (deterministic, no network/LLM).
Canonical roadmap: `docs/ALPHA_OPPORTUNITY_COVERAGE_ROADMAP.md` +
`state/alpha_opportunity_coverage.yaml`; task rules:
`docs/ROADMAP_OPERATING_RULES.md`, `docs/ROADMAP_TASK_TEMPLATE.md`.

Workspace layout and directory retirement rules:
`docs/WORKSPACE_INVENTORY.md` + `docs/WORKTREE_LIFECYCLE.md`.

## Source-of-truth order (when facts conflict)

For development roadmap/status specifically:
1. `state/alpha_opportunity_coverage.yaml`
2. `docs/ALPHA_OPPORTUNITY_COVERAGE_ROADMAP.md`
3. per-task committed evidence
4. `TRACKS.md` / `CURRENT_STATE.md`
5. Chat history (**last resort — never authoritative**)

General facts:
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
