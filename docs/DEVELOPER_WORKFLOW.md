# DEVELOPER WORKFLOW

**Do not depend on historical chat context for a code change.** Every
material behavior must be discoverable in repo docs, code, and tests.

## Roles

- `origin/main` (base) — upstream source; local `main` mirrors it.
- `infra/devin-bridge` — bridge package only; base worktree hosts it.
- `exp/alpha-rnd-v1` — ALPHA production paper trading (strategy frozen
  during evidence collection; integrity fixes only).
- `exp/gate-c12-prospective` — frozen control. Never modify behavior.
- `exp/expert-rnd-v2` — Expert R&D, PARKED.
- `project/tracks` — this repo: docs, roadmap, relay, project control.

One worktree per branch, layout table in docs/SYSTEM_ARCHITECTURE.md.
No track edits another track's files.

## Change discipline

- Roadmap IDs for every task (`python -m ops.roadmap_status`; rules in
  docs/ROADMAP_OPERATING_RULES.md). Bugs inside task Rn are `Rn-B#`
  subtasks — return to the parent after.
- Tests: every module has `test_*.py` runnable with stdlib unittest;
  run the affected suite before committing. Shadow/test code must never
  write to live operator logs (incident 2026-10-16).
- Economic authority files are never hand-edited (see
  docs/STATE_AND_DATA_AUTHORITY.md); fixes go through code + documented
  correction events.
- Docs-sync rule: a behavior change without a doc/test update is
  incomplete. Docs live in the tracks repo; track docs live in tracks/.
- Commits: no AI attribution trailers; smallest correct diff.

## Canary / acceptance

Production acceptance = live verification against real state (read-only)
plus the affected unit tests green. Never verify on the live book by
mutating it; use the module's test harness or tmp fixtures.
