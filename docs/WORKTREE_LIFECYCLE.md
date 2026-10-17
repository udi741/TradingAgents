# WORKTREE LIFECYCLE — how track workspaces are born and retired

The accumulation of stale worktrees is what made the workspace confusing.
This is the durable rule that prevents it.

## Lifecycle

```
CREATE        new worktree + exp/<name> branch, registered in TRACKS.md
  |
ACTIVE      work happens; artifacts committed as they are produced
  |
EXPERIMENT COMPLETE
  |
  ├─ persist all results/artifacts (committed or durably archived)
  ├─ update experiment registry + track docs + state YAML
  ├─ verify worktree clean (git status empty, nothing untracked that matters)
  ├─ verify NO live references (processes, cron, systemd, scripts, docs)
  ├─ classify per docs/WORKSPACE_INVENTORY.md
  |
  ├─ still needed?  -> document WHY the physical worktree stays
  |
  └─ not needed?    -> retire physical worktree in a SEPARATE approved
                       cleanup action; keep branch/tag history
```

## Track closure definition (definition-of-done for closing a track/gate)

A track or experiment is CLOSED only after ALL of:

1. results/artifacts persisted (committed, or archived with a manifest);
2. `docs/EXPERIMENT_REGISTRY.md` row written;
3. track status updated in `tracks/<TRACK>.md` + `state/<TRACK>.yaml` +
   TRACKS.md;
4. worktree cleanliness inspected (`git status`, incl. `--ignored` for
   bulky caches);
5. no live dependencies verified (processes, `crontab -l`, systemd units,
   hard-coded paths in active scripts/docs);
6. anything uncommitted but valuable is archived/committed first;
7. an explicit decision is recorded on whether the physical worktree stays;
8. if it does not stay, retirement happens as a separate approved cleanup
   gate — never silently inside the closing task.

## Archive convention

Permanent archives live under `/home/udi/udi_provate/archive/tradingagents/<name>/`
and must contain `MANIFEST.md` (source worktree/branch/HEAD, preserved paths,
why, exclusions) and `SHA256SUMS` covering every preserved file. Re-derivable
vendor caches are not archived; record them as intentionally excluded.
Existing archives: `c7_full_fidelity/`, `expert_mimic_m5/`, `gate_d_backup/`,
plus branch bundles `retired_worktrees_wave{1,2}_2026-10-03.bundle`.

## Hard rules

- **Active worktrees are never removed** during another track's gate.
- **Uncommitted or untracked material blocks deletion** until archived or
  explicitly judged disposable (caches, logs, `__pycache__` are usually
  disposable; results/manifests/journals are not).
- **Live references block deletion**: any process cwd/cmdline, cron entry,
  systemd unit, or hard-coded path in an active script/doc that points at
  the worktree must be reconciled first.
- Prefer `git worktree remove <path>` for registered worktrees — never a
  bare `rm -rf`, which leaves stale registry entries.
- **Branch deletion is a separate, deliberate decision.** Removing a
  worktree does not delete the branch; committed history stays reachable
  via the branch. Delete a branch only when its tip is contained in another
  retained ref or its history is otherwise preserved — and record it.
- **Never remove a worktree classified UNKNOWN.**
- Closed experiments should NOT keep a permanent physical worktree without
  a documented reason (e.g. it is the sole host of un-archived data).

## Owner checklist for `git worktree remove` (run only in an approved
cleanup gate)

```bash
# 1. confirm registry entry and branch
git -C /home/udi/udi_provate/TradingAgents worktree list
# 2. confirm clean and nothing valuable untracked/ignored
git -C <path> status --porcelain=v1 --ignored
# 3. confirm branch will remain (it always does; removal != deletion)
git -C /home/udi/udi_provate/TradingAgents branch --list 'exp/<name>'
# 4. remove the physical worktree only
git -C /home/udi/udi_provate/TradingAgents worktree remove <path>
```
