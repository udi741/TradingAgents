# OPERATING RULES — durable project rules

These rules bind every session and every track. When a rule and a convenient
shortcut conflict, the rule wins.

## Models and reference

1. **NO LOCAL MODELS.** All model calls go through the bridge:
   `devin-quick -> swe-2-medium`, `devin-deep -> swe-2-high`.
2. Official production reference: TradingAgents **v0.5.0**, SHA
   `2d17df8da1536c121e4d7395ac5a5dcec9e96d6f`.

## Track isolation

3. Each track works only in its own worktree/branch and updates only its own
   documentation (see `docs/DOCUMENT_OWNERSHIP.md`).
4. C12 is **validation/control, not a strategy playground**. Never import
   ALPHA or EXPERT experimentation into C12.
5. EXPERT findings must not contaminate C12.
6. New independent research starts from freshly fetched `origin/main`
   (never from the `infra/devin-bridge` base checkout); existing track work
   continues in that track's existing branch/worktree. The base worktree is
   `BASE_INFRASTRUCTURE_HOST` — see `docs/BASE_REPOSITORY_ROLE.md`.

## Prospective integrity

7. No retrospective fake fills. Ever.
8. A completed-close condition executes at the **next regular-session open**
   (at the actual open price, including gaps) — never at the confirming
   close.
9. If a required execution opportunity passed while the machine was off, do
   NOT invent a fill at a later or better price. Record
   MISSED_EXECUTION_REVIEW_REQUIRED and flag it.
10. Preserve **append-only history**. Never silently rewrite an old result
    to make the current story cleaner. Corrections are new records.
11. A signal/trigger must exist before the price move it acts on, or the
    fill is invalid.

## Evidence and claims

12. **Intended holding horizon ≠ research evaluation horizon.** Research
    marks (5/20/60/120/250 sessions, vs SPY) are measurement points, not
    exits. Exits follow the frozen per-position rules.
13. Paper results are **not** proof of profitability.
14. No real-money deployment without a separate explicit promotion decision.
15. Do not optimize indefinitely on historical data — prefer narrow causal
    experiments and prospective evidence.
16. LOCKBOX and HOLDOUT protections must be preserved: LOCKBOX untouched,
    HOLDOUT unused.

## Documentation definition of done

A track task is **NOT COMPLETE** until:

1. the requested work is finished;
2. artifacts/results are persisted;
3. the track Markdown (`tracks/<TRACK>.md`) is updated;
4. the track YAML (`state/<TRACK>.yaml`) is updated;
5. `TRACKS.md` and `CURRENT_STATE.md` are updated when the change is
   material;
6. `docs/EXPERIMENT_REGISTRY.md` is updated when an experiment completed;
7. `docs/DECISION_LOG.md` is updated when a durable protocol/architecture
   decision changed;
8. docs are committed;
9. the returned report states exactly which documentation was updated.

## Workspaces

17. Worktree lifecycle and track-closure requirements are defined in
    `docs/WORKTREE_LIFECYCLE.md`; the durable directory audit record is
    `docs/WORKSPACE_INVENTORY.md`. Retiring a physical worktree is always a
    separate approved cleanup gate, never part of closing an experiment.

## Background infrastructure

17. **BACKGROUND SERVICES MUST BE REBOOT-RECOVERABLE.** After an ordinary
    reboot, routine infrastructure resumes automatically: cron daemon
    (enabled) runs the ALPHA per-minute monitor and C12 hourly scheduler;
    systemd user service `tradingagents-telegram.service` (enabled,
    `Restart=always`) runs the Telegram relay — user lingering is enabled
    (`loginctl show-user udi` → Linger=yes) so it starts without a login.
    The model bridge is intentionally on-demand: the C12 scheduler starts
    it when a cycle needs it. Anything that fundamentally requires
    login/unlock must be documented explicitly rather than assumed.

## Honesty

18. Do not invent missing facts. Use `UNKNOWN` when a fact cannot be
    verified.
19. Conflicts between sources are flagged, never silently resolved
    (see source-of-truth order in `START_HERE.md`).
