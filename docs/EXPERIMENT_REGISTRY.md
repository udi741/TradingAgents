# EXPERIMENT REGISTRY

Purpose: answer "did we already try this?" in one search. Each track appends
its own rows. Fields: gate | status | result | meaning | artifact | revisit
policy.

Statuses: COMPLETE / REJECTED / RETIRED / CLOSED / ACTIVE / ACCUMULATING /
WAITING.

## EXPERT_RND

| Gate | Status | Result | Meaning | Artifact | Revisit policy |
|---|---|---|---|---|---|
| EXPERT_MIMIC_BENCHMARK_V1 | COMPLETE | 12 valid expert trades, all baseline NO_ENTRY | Historical sample exists but winner-biased | `TradingAgents-mimic/evaluations/expert_mimic_benchmark_v1/` | consumed data only |
| M2 CONTEXTUAL_TECHNICAL_ENTRY_RM_V1 | REJECTED | expert 4/12 ENTRY but 5/12 loser entries | Relaxing a non-discriminative gate moves both distributions | `gate_m2_contextual_rm/` | do not retry permissive RM variants |
| M3 DISCRIMINATOR_AUDIT | COMPLETE | read-only audit | informed M4 | — | — |
| M4 ENTRY_LOCATION_ASYMMETRY_RM_V2 | REJECTED | CONTROL 7/17 winners / 1/10 losers; M4 3/17 / 1/10 | Lost winners without cutting losers; PM already prices location | `gate_m4_entry_quality/`, `gate_m5_fresh_disjoint/` | do not retry explicit entry gates |
| M5 / M5.1 | ACCEPTED | fresh disjoint validation run | Production decision layer = untouched official v0.5.0 | `gate_m5_fresh_disjoint/` | — |
| X1 REASONING_DISCRIMINATOR_AUDIT | COMPLETE | X1-B plausible but entangled | Real discriminator already operates in baseline; residuals inseparable | tracks/EXPERT_RND.md X1 section | consumed |
| X2 LADDER_FILL_COUNTERFACTUAL | REJECTED | X2-B zones non-discriminative | Winners ~68% vs losers ~75% zone trigger | `x2_frozen_entry_conditions.json` | do not retry zone-fill as filter |
| X3 PUBLISHED_INVALIDATION | REJECTED | X3-B non-discriminative | Stops hit losers more but destroy winner economics | tracks/EXPERT_RND.md X3 section | do not retry published stops |
| HISTORICAL_EXPERT_MIMIC | CLOSED | all historical lines exhausted | Exit-into-strength hypothesis untestable without losers | — | needs prospective sample with losers |
| EXPERT_PROSPECTIVE_CAPTURE | ACTIVE | protocol frozen, store live, count = 0 | Capture before outcome; thresholds ≥20 signals / ≥5 losers or 25% / ≥15 exits | `expert_prospective/` | reopen only at thresholds |
| Historical disclosures addendum 1 | RECORDED | IREN LOSS; PANW/FTNT flat; AMAT win (RISKIER_PATH_1) | All NOT_PROSPECTIVE | `expert_prospective/historical_disclosures/` | never counts toward thresholds |

## C12_PROSPECTIVE

| Gate | Status | Result | Meaning | Artifact | Revisit policy |
|---|---|---|---|---|---|
| C12 Epoch 1 | COMPLETE (dry run) | 0 scoreable observations; 2026-09-25 week LATE_DECISION_NON_SCOREABLE | Timing failure -> timing guard | C12 worktree epochs/ledger | never count late weeks |
| Timing guard | ACCEPTED | late cycles non-scoreable, no executable orders | Prospective integrity enforcement | C12 worktree | permanent |
| C12 Epoch 2 | ACTIVE | activated 2026-09-29; first cycle 2026-10-02 SCOREABLE (2 ENTRY pending 10-05 open) | Prospective scoring under SEC fail-closed pins | C12 worktree | — |
| H1/HOLDOUT integrity issue | CLOSED | reserve protections reaffirmed | LOCKBOX untouched, HOLDOUT unused | project record | permanent rule |

## ALPHA_RND

| Gate | Status | Result | Meaning | Artifact | Revisit policy |
|---|---|---|---|---|---|
| ALPHA_RND_V1_DISCOVERY | COMPLETE | 0 ACTIONABLE_NOW of 10; 6 watches; 3 VALID_PROSPECTIVE fills | Discipline produces staged entries not instant buys | `evaluations/alpha_rnd_v1/` | — |
| V1_PAPER_BOOK_PROTOCOL_FREEZE | COMPLETE | fills audited VALID_PROSPECTIVE; E1 Oct-2 demoted to RETROSPECTIVE_SHADOW | Provenance verified | alpha worktree ledger | permanent |
| ALPHA_RND_V2_DISCOVERY | COMPLETE | 22 new candidates, 0 ACTIONABLE_NOW, 10 watches | Second cycle consistent | `evaluations/alpha_rnd_v1/case_artifacts/*_2026-10-02.json` | — |
| Holding-horizon audit/alignment | COMPLETE | 60 sessions = measurement not exit; exits per frozen hierarchy | Horizon concepts separated | ledger HOLDING_HORIZON_AUDIT | permanent rule |
| Fast trigger monitor V1 | COMPLETE | cron monitor live; AUTO_ENTRY / DETERMINISTIC / REANALYZE classes | Local execution without live session | `alpha_rnd/monitor.py` | — |
| Close-confirmation execution fix | COMPLETE | close-confirmed -> next open; missed -> REVIEW_REQUIRED | Removes same-close fills | `alpha_rnd/` | permanent |
| E1 staging counterfactual | ACCUMULATING | needs ≥10 pairs, ≥20 sessions matured | Does entry staging add or cost? | ledger | read when matured |

## Retired research lines (project-wide)

| Line | Status | Result | Meaning | Artifact | Revisit policy |
|---|---|---|---|---|---|
| Structured fundamental Lane D | RETIRED | fresh outcome-quality failure | Did not hold up out of sample | project record | do not resurrect automatically |
| Broad non-S&P Lane-A expansion | RETIRED | positive period failed replication in immediately preceding period | Apparent edge was period-specific | project record | do not resurrect automatically |
