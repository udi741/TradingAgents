# ROADMAP OPERATING RULES

## Bug subtask rule
If roadmap task Rn discovers a bug, create subtasks `Rn-B1`, `Rn-B2`, ...
The bug is a SUBTASK of Rn, never a new parent item:

    Rn IN_PROGRESS -> Rn-B1 discovered -> fix/test -> Rn-B1 DONE -> RETURN TO Rn

Only a genuine safety/integrity emergency may interrupt the active item.
After the emergency: RETURN TO THE INTERRUPTED ROADMAP ITEM.

## Development order
A. ALPHA V1 strategy is FROZEN during evidence collection.
   Allowed: correctness bugs, data-integrity bugs, operational-safety bugs,
   observability/instrumentation that does not alter decisions.
   Not allowed without R8/R9: screener tuning, ranking-weight changes,
   deep-quota changes, new trading triggers, strategy/risk loosening,
   universe-policy changes.
B. C12 remains frozen prospective control.
C. EXPERT remains PARKED unless explicitly reopened by roadmap decision.
D. New ideas found during development go to BACKLOG / FUTURE CANDIDATES;
   they never replace `current_task`.

## Evidence discipline
Every task updates state/alpha_opportunity_coverage.yaml: status, evidence,
commits, blockers, next_action. Chat history is LAST in the source hierarchy.

## Documentation synchronization rule
`docs/ALPHA_SYSTEM_GUIDE.md` is the canonical current-system description.
Any change that alters any of the following MUST update that guide in the
same task/commit set:

- publication disposition meanings or vocabulary
- entry authorization / entry-gate semantics
- economic state authority
- scheduler lifecycle or priority semantics
- inference-failure classification or semantics
- retry behavior or retry lifecycle
- replay engine behavior or policies
- operator commands

A guide edit that disagrees with current code is a defect, not documentation.
