# BASE REPOSITORY ROLE — audit and proposed policy

Audit: 2026-10-03, PROJECT_CONTROL_V3 (read-only; `git fetch origin` was the
only network op; no checkout/switch/reset performed). Status:
**AUDIT COMPLETE — NOT YET NORMALIZED.**

## Current observed state

- Path: `/home/udi/udi_provate/TradingAgents` (canonical repo; owns `.git`
  and all worktree registrations, branches, objects).
- Branch: `exp/gate-c6-selection-execution-split`, HEAD `d629034c`.
- Working tree: CLEAN. Untracked: none. Ignored/operational: `.venv/`
  (133M), `docs/devin-bridge/`, build/pycache/lock files.
- Local `main` = `ceabecf9` ("feat: add Devin CLI bridge"), tracking
  origin/main, ahead 1 / behind 169.
- `origin/main` (fetched 2026-10-03) = `8b22d43d`.

## Why it is on C6

The base directory was reused as the working tree for the C6 selection/
execution-split experiment (and the H1 HOLDOUT audit committed on top,
`d629034c`). When the experiment ended nobody switched it back — the same
root cause as the worktree accumulation. No current component requires the
C6 *branch* specifically; all C6/H1 results are committed.

## Dependencies — the important one

| Dependency | Type | On checked-out files? |
|---|---|---|
| All worktree registrations, branches, objects | A — `.git` metadata | NO — survives any checkout |
| **Running bridge** `python3 -m devin_bridge` (PID 2001014, `--quick-model swe-2-medium --deep-model swe-2-high`) | B — **yes** | cwd=`TradingAgents/`, `PYTHONPATH=.` → module loaded **from the C6 checkout** |
| `.venv/` (133M, ignored) | B — maybe | python env at base path; bridge currently uses `/usr/bin/python3` |
| ALPHA cron monitor | none | points at alpha-rnd only |
| systemd user units | none | — |
| track worktrees (c12/alpha/expert) | A only | they have their own checkouts; none contain `devin_bridge/` |

Critical: `devin_bridge/` exists ONLY on branches `main`,
`exp/gate-c6-…`, `feat/devin-cli-bridge` — **NOT on `origin/main` and NOT
in any active track worktree**. The running bridge already loaded its code,
so a checkout would not kill the live process — but the *next* bridge
launch from a plain `origin/main` checkout would fail with no module.

## Devin-session launch paths

Devin sessions are resumed by name (`devin -r <session>`); the starting cwd
is context, not identity — `nonchalant-citipati` currently runs correctly
from `TradingAgents-tracks`. Resuming any track session from the base path
is *harmless but confusing* (it suggests work belongs in base).

Durable operator convention (recommended, not yet enforced):

```
cd /home/udi/udi_provate/TradingAgents-c12         && devin -r kindly-nightshade
cd /home/udi/udi_provate/TradingAgents-alpha-rnd   && devin -r feather-room
cd /home/udi/udi_provate/TradingAgents-expert-rnd  && devin -r groovy-allspice
cd /home/udi/udi_provate/TradingAgents-tracks      && devin -r nonchalant-citipati
```

Rule: cd to the worktree of the session's track. Never run a track session
from the base repo.

## Recommended permanent policy

`BASE_REPOSITORY_ROLE = NEUTRAL_CANONICAL_CHECKOUT`

- Base holds `.git`, all branches, all history — the worktree factory.
- **Base is never used for experiments or operations.** A dirty base
  working tree is an integrity problem to be reported.
- Base should check out a branch that is recognizably "the clean base."
  Recommended target: **local `main`** — it is the only line containing
  `devin_bridge/` (which the current bridge launch path needs) and it
  tracks `origin/main`. Raw `origin/main` detached is NOT recommended yet
  because it would orphan the bridge launch path.
- New independent tracks: `git fetch origin` then
  `git worktree add ../TradingAgents-<name> -b exp/<name> origin/main`.
- Closing a track never moves work into base.

## Proposed normalization procedure — NOT EXECUTED

Prerequisites verified already: tree clean, C6/H1 committed (tip `d629034c`
kept by branch `exp/gate-c6-selection-execution-split`), `.venv` + docs are
ignored (survive checkout).

A future approved gate would:

```bash
cd /home/udi/udi_provate/TradingAgents
git status                     # must be clean — abort if dirty
git rev-parse HEAD             # record for rollback (d629034c)
git checkout main              # local main = bridge commit, tracks origin/main
git status                     # verify clean on main
python3 -c "import sys; sys.path.insert(0,'.'); import devin_bridge"  # bridge module present
```

Rollback: `git checkout exp/gate-c6-selection-execution-split` — zero risk,
no data moves.

Optional-but-conditional: if a future gate relocates the bridge launch path
(e.g. dedicated infra checkout or `main`-based worktree), base could then
track plain `origin/main`. Bridge architecture cleanup = FUTURE item.

Coordination: the running bridge survives checkout (code already loaded),
but the gate should be run when no in-flight bridge call is critical, and
the bridge's next launch must be verified (`python3 -m devin_bridge` from
base resolves on `main`).

## Unresolved questions

- Whether `.venv` at base is used by anything (bridge currently runs on
  system python; unverified).
- Whether local `main` should eventually fast-forward to `origin/main` —
  it is behind 169; that merge decision is a separate gate.
- `pointy-viola` and another `devin` session run from unrelated dirs —
  not project worktrees, noted only.
