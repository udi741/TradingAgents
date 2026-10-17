# DEVIN CONTEXT — durable rules for every Devin session on this project

## Before touching anything

1. **Identify your track.** If the prompt doesn't name one, stop and ask.
2. Read: `START_HERE.md`, `docs/OPERATING_RULES.md`, your
   `tracks/<TRACK>.md`, `state/<TRACK>.yaml`, `docs/DOCUMENT_OWNERSHIP.md`,
   and your track's runbook.
3. Obey document ownership — never modify another track's worktree,
   artifacts, or doc files without explicit authorization.

## Global constraints

- NO LOCAL MODELS. Bridge: devin-quick -> swe-2-medium,
  devin-deep -> swe-2-high.
- Production reference: v0.5.0, SHA `2d17df8da1536c121e4d7395ac5a5dcec9e96d6f`.
- C12 decision layer is frozen; EXPERT is analysis-only; ALPHA is
  paper-only.
- No retroactive fake fills; close-confirmed -> next regular-session open;
  machine-off misses -> MISSED_EXECUTION_REVIEW_REQUIRED, never invented
  fills.
- Append-only history. Never silently rewrite old results.
- LOCKBOX untouched, HOLDOUT unused.
- Use `UNKNOWN` for unverifiable facts. Never invent missing state.
- Chat history is not authoritative; the repo is.

## Definition of done — a task is NOT COMPLETE until:

1. requested work finished;
2. artifacts/results persisted;
3. `tracks/<TRACK>.md` updated;
4. `state/<TRACK>.yaml` updated;
5. your sections of `TRACKS.md` / `CURRENT_STATE.md` updated when materially
   changed;
6. `docs/EXPERIMENT_REGISTRY.md` row added when an experiment completed;
7. `docs/DECISION_LOG.md` entry appended when a durable protocol/architecture
   decision changed;
8. docs committed;
9. your report states exactly which documentation was updated, with file
   paths and commit hashes.

## Working style

- Stop when the requested gate is finished. Do NOT silently begin another
   experiment or gate.
- Report exact files and commits.
- Include a plain-English user summary for important operational outputs
  (fills, exits, gate results): what happened, what it means, what next.
- Prefer the smallest change that satisfies the gate; no speculative
  abstractions.
