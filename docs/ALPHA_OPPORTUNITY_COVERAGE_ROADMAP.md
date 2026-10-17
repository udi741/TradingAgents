# ALPHA OPPORTUNITY COVERAGE ROADMAP

> Capability map: `docs/TRADINGAGENTS_CAPABILITY_REFERENCE.md` (registry: `docs/TRADINGAGENTS_CAPABILITY_REGISTRY.yaml`).


Canonical development roadmap for TradingAgents. Survives conversations.
Machine-readable state: `state/alpha_opportunity_coverage.yaml`.
Task discipline: `docs/ROADMAP_OPERATING_RULES.md`, `docs/ROADMAP_TASK_TEMPLATE.md`.

Status values: NOT_STARTED | IN_PROGRESS | BLOCKED | WAITING_FOR_DATA | DONE | PARKED

## R0 — ROADMAP CONTROL
Create durable roadmap/state/task tracking so development cannot lose direction.

## R1 — OPPORTUNITY FUNNEL INSTRUMENTATION
Persist exactly where stocks disappear from:
raw universe → eligibility → ranking → deep TA → TA decision →
publication disposition → machine executability → trigger → paper trade.

## R2 — RANK COHORT OUTCOME TRACKING
Prospectively track ranks 1-10, 11-25, 26-50, 51-100, 101+ with future
returns, benchmark-relative returns, MFE and MAE at defined horizons.

## R3 — TA ACCEPT/REJECT OUTCOME TRACKING
Compare future performance of TA Buy/Overweight, TA Hold, TA Sell/Underweight,
Research-only, Ambiguous-rejected, Risk-plan-required and other publication
dispositions.

## R4 — TRANSLATOR GAP MEASUREMENT
Measure why valid TA research becomes PUBLISHED_NON_EXECUTABLE and identify
recurring machine-trigger translation patterns.

## R5 — SHADOW DEEP-QUOTA EXPANSION
Prospectively test additional deep analysis beyond current top-10, initially
shadow-only/no trading (e.g. ranks 11-25 or 11-30).

## R6 — LOW-PRICE OPPORTUNITY SHADOW LANE
Separately investigate sub-$5 opportunities under stricter liquidity/dilution/
listing/risk constraints without contaminating ALPHA V1.

## R7 — EXISTING TRADE POSTMORTEMS
Standardized case packets for PBF, ACN, APPS, PGEN, TWST, SDGR separating:
selection, entry timing, risk-plan quality, execution/infrastructure,
thesis outcome.

## R8 — EVIDENCE REVIEW
Use R1-R7 evidence to determine which bottlenecks actually cost good
opportunities and which changes are justified.

## R9 — ALPHA V2
Implement only evidence-supported improvements as a separate prospective
challenger, while preserving ALPHA V1 as baseline.

## R10 — REAL-MONEY READINESS
Formal gate requiring operational stability, adequate prospective sample size,
mature outcomes, drawdown/expectancy analysis, benchmark/control comparison,
and only then consideration of a small supervised real-money pilot.

### R10 minimum evaluation policy (direction, not final thresholds)
- approximately >=30 clean trading sessions operationally
- preferably >=20-30 genuinely executable prospective decisions
- meaningful 20-session outcomes
- substantial cohort reaching 60 trading sessions
- no unresolved economic-integrity defect
- known expectancy/drawdown/MAE/MFE
- comparison with C12 and simple benchmark
- real-money step, if justified, is SMALL SUPERVISED PILOT first

## SYSTEM ROLE SNAPSHOT (2026-10-14)

| System | Role | Rule |
|---|---|---|
| ALPHA V1 | ACTIVE candidate/opportunity system | strategy frozen except integrity fixes; collecting prospective evidence |
| C12 | ACTIVE frozen prospective control | do not modify |
| EXPERT | PARKED | no current development |
