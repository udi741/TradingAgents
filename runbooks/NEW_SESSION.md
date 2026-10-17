# RUNBOOK: NEW_SESSION — how a fresh ChatGPT or Devin session starts

## For a new ChatGPT session

Read, in order:

1. `START_HERE.md`
2. `CURRENT_STATE.md`
3. `ai/CHATGPT_CONTEXT.md`
4. `TRACKS.md` and the relevant `tracks/<TRACK>.md` if the question is
   track-specific.

Then answer the user in plain English: what happened, what it means, what
to do next. Do NOT reconstruct history from memory — the repo is the truth.
If repo docs and your memory disagree, the repo wins; flag the discrepancy.

## For a new Devin session

1. Identify your track from the task prompt. If no track is named, stop and
   ask.
2. Read `START_HERE.md`, `docs/OPERATING_RULES.md`, `tracks/<TRACK>.md`,
   `state/<TRACK>.yaml`, `docs/DOCUMENT_OWNERSHIP.md`, and your runbook.
3. Work only in your track's worktree/branch and your own doc files.
4. When done: update your track md + yaml, your TRACKS.md/CURRENT_STATE.md
   sections, registry/decision-log entries if applicable; commit docs;
   report exact files/commits.
5. If a fact can't be verified, write `UNKNOWN`. Never guess. Never touch
   another track. Never use chat history as state.

## For the user starting a session

- C12 work → resume `kindly-nightshade`.
- EXPERT signal capture → resume `groovy-allspice`.
- ALPHA work → start/resume an ALPHA session and tell it to read its
  runbook; record its name in `state/ALPHA_RND.yaml`.
- Global doc changes → a PROJECT_CONTROL session in this worktree on
  `project/tracks`.
