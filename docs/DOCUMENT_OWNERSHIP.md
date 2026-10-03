# DOCUMENT OWNERSHIP

Who is allowed to write what. If a file is not on your list, don't touch it
without explicit authorization.

## PROJECT_CONTROL owns

- `START_HERE.md`
- `docs/ARCHITECTURE.md`
- `docs/OPERATING_RULES.md`
- `docs/DOCUMENT_OWNERSHIP.md` (this file)
- `docs/GLOSSARY.md`
- `docs/WORKTREE_LIFECYCLE.md`
- `docs/WORKSPACE_INVENTORY.md`
- `ai/*` (`CHATGPT_CONTEXT.md`, `DEVIN_CONTEXT.md`, `HANDOFF_TEMPLATE.md`)
- `state/PROJECT_CONTROL.yaml`

PROJECT_CONTROL handles initial architecture and **major global
documentation changes only**. It must NOT become a bottleneck every
experiment passes through.

## C12 owns

- `tracks/C12_PROSPECTIVE.md`
- `state/C12_PROSPECTIVE.yaml`
- `runbooks/C12_PROSPECTIVE.md`
- C12 entries in `docs/EXPERIMENT_REGISTRY.md` and C12 rows in
  `docs/DECISION_LOG.md`
- its own section of `CURRENT_STATE.md` and its own block in `TRACKS.md`

## ALPHA owns

- `tracks/ALPHA_RND.md`
- `state/ALPHA_RND.yaml`
- `runbooks/ALPHA_RND.md`
- ALPHA entries in `docs/EXPERIMENT_REGISTRY.md` and ALPHA rows in
  `docs/DECISION_LOG.md`
- its own section of `CURRENT_STATE.md` and its own block in `TRACKS.md`

## EXPERT owns

- `tracks/EXPERT_RND.md`
- `state/EXPERT_RND.yaml`
- `runbooks/EXPERT_NEW_SIGNAL.md`
- `tracks/EXPERT_PROSPECTIVE_PROTOCOL.md`
- EXPERT entries in `docs/EXPERIMENT_REGISTRY.md` and EXPERT rows in
  `docs/DECISION_LOG.md`
- its own section of `CURRENT_STATE.md` and its own block in `TRACKS.md`

## Shared / aggregate files

- `CURRENT_STATE.md` — each track updates **only its own section**.
- `TRACKS.md` — each track updates **only its own block**.
- `docs/EXPERIMENT_REGISTRY.md` — append rows under your own track only;
  never edit another track's rows.
- `docs/DECISION_LOG.md` — append-only; add entries, never rewrite old ones.
- `runbooks/NEW_SESSION.md` — shared; update sparingly, PROJECT_CONTROL
  arbitrates.

## Conflict rules

1. **Append beats edit.** When in doubt, add a new dated entry rather than
   modifying an old one.
2. If two tracks need the same shared line, the second writer adds its own
   dated note and flags the conflict in its report — never silently overwrite.
3. If an aggregate file and a track file disagree, the **track file and its
   artifacts win**; flag the disagreement and correct the aggregate.
4. If `state/<TRACK>.yaml` and `tracks/<TRACK>.md` disagree, the more
   recently dated field is presumed current but the conflict must be flagged
   and fixed in the same session.
5. Multiple concurrent sessions must never edit the same file in the same
   commit window; if you hit a conflict on a shared file, rebase/reapply
   your own section only.
