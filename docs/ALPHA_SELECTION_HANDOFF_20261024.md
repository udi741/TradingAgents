# TradingAgents — Selection Research Reconciliation

Date: 2026-10-24
Status: Historical investigation complete; production policy unchanged.

## 1. Canonical repositories

Canonical GitHub:
git@github.com:udi741/TradingAgents.git

Verified GitHub main: 545157da
Verified Linux local main: e363ea2d

On 2026-10-24, Git reported:
- Linux-only commits: 0
- GitHub-only commits: 4
- Common ancestor: e363ea2d

The four newer GitHub commits are:
- e02e7c11 — Contract authoring
- 4d327add — Deterministic execution projection
- 76107e55 — do_fill notification fix
- 545157da — Cross-platform locking

Linux and GitHub share one continuous commit history.

Linux main was deliberately NOT fast-forwarded during this
investigation because its working tree contains operational
paper-trading state.

Windows source development must begin from a freshly fetched
GitHub origin/main, not an assumed local checkout.

## 2. The 10-stock research limitation

Production contains:

alpha_rnd/daily_scheduler.py:
DEEP_QUOTA = 10

evaluations/alpha_rnd_v1/discovery.py:
select_deep_candidates(..., quota=10)
Selection returns scored[:quota].

The scheduler therefore analyzes at most ten candidates
per normal research session.

Historical Git examination found the same behavior in the
current branch, other checked branch tips, October 18-19
saved snapshots, and the canonical-selection commit 3378b394.

No dynamic production allocation fix was recovered.

## 3. Existing full-pool solution

On October 14-15, R5A/R5B implemented an isolated replay
framework with two selection policies:

CURRENT_PRODUCTION
ANALYZE_ALL_CANDIDATES

Key implementation:
alpha_rnd/replay.py

Important commit:
2e6ad883 — 84/84 full-pool TA artifacts frozen.

Three historical sessions were analyzed:
2026-10-07
2026-10-09
2026-10-12

Each contained 28 candidates; 84/84 research artifacts
were completed in the full-pool experimental policy.

The experiment is part of GitHub main history.

This was a retrospective experimental capability,
not an approved change to live daily research allocation.

## 4. Why production remained unchanged

docs/ALPHA_SYSTEM_GUIDE.md records:
R5B_ACCEPTED_PRELIMINARY
"No live strategy change has been approved from R5B."

The roadmap state described R5 as shadow-only deep
coverage expansion, blocked on sufficient prospective evidence.

The October 15 documentation noted maturity limitations,
session-selection caveats, and substantial inference costs.

Those historical maturity statements must be rechecked
against current evidence, not treated as permanently pending.

Therefore the repository evidence supports:
Full-pool capability implemented; production promotion
not approved in the recorded roadmap.

We have NOT located the exact ChatGPT conversation in
which the earlier 10-stock fix was discussed. Do not
claim that the conversation or intended fix was disproved.

## 5. Other research already conducted

Windows evaluation work examined:
- Frozen candidate pools and deep_score rankings
- Selected versus unselected future outcomes
- Production-generated AI decisions
- Constructive contract objectives and paper-trade lifecycle

Those evaluations should be reconciled with R5B's
existing full-pool AI artifacts before designing a new
allocation policy.

Neither the small R5B sample nor the recent ranking
diagnostics prove an optimal research count.

## 6. Product intent — pending design review

The desired system should be able to research more than
ten stocks when decision-time opportunity evidence and
explicit resource authorization justify doing so.

It should not replace 10 with another arbitrary quota,
silently analyze all candidates, or optimize thresholds
using hindsight returns.

Candidate eligibility, research priority, batch size,
and total model budget are separate concepts.

No new production allocation policy has yet been
approved or implemented.

## 7. Development and deployment workflow

1. Preserve this document in shared Git history.
2. Windows fetches GitHub and inspects this handoff.
3. Windows development uses a new isolated branch based
   on the latest origin/main.
4. Reuse and review existing R5A/R5B research before
   implementing anything new.
5. Complete tests and review before merging changes
   to GitHub main.
6. Return to Linux and explicitly verify the new remote
   commit history.
7. Update/deploy Linux only through a controlled
   procedure that preserves tracked operational data,
   running services, paper positions, and schedules.

Never automatically reset Linux main, discard dirty state,
or deploy research-selection changes without review.
