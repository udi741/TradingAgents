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
