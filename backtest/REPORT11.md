# AI→trade decision pipeline — vertical slice + economic results

Branch `exp/decision-contract` (worktree `TradingAgents-contract`, from
origin/main `62b99180`). Reproduce: `python3 backtest/pipeline.py`,
`python3 -m unittest backtest.test_decision_contract` (9 tests pass).

## Phase 1 — `backtest/decision_contract.py`

Contract: direction ∈ {LONG, SHORT, NO_TRADE}, entry{type, zone|level,
activation}, stop, target, horizon, size_frac, R/R, costs, provenance —
or NO_TRADE + explicit reason. Validator enforces LONG stop<entry &
target>entry; SHORT stop>entry, target<entry, `paper_only=True`,
buy-to-cover exit, ~2%/yr borrow flag; every required term must be
present and finite. Sell ≠ SHORT and Buy ≠ executable LONG: direction
comes only from `is_short_plan` (explicit short params/wording or
bearish geometry), executability still flows through production gates.

## Phase 2 — all 224 saved intents through the pipeline

| Stage | n |
|---|---|
| Researched intents | 224 |
| Valid contracts | **16** (12 LONG, 4 SHORT) |
| NO_TRADE (missing terms) | **208** |
| Filled (paper sim, causal timing) | 9 LONG, 2 SHORT |
| Untriggered | 3 LONG, 2 SHORT |

Blockers (multi-reason): MISSING_ENTRY 158, MISSING_TARGET 100,
MISSING_SIZE_FRAC 89, MISSING_STOP 27, MISSING_HORIZON 11,
geometry rejects (stop/target wrong side) 8.

**Paper-sim results (10bps/side, 2%/yr borrow):**
- LONG: 9 trades, 5W/4L, net **+61**, PF 1.12, expectancy +6.8 — vs the
  framework-authorized subset (-1,322). Gains came from intent terms the
  production gate never admitted (IOVA +66, TEAM +246, APPN +117).
- SHORT (experimental): 2 fills — **PCVX +132** (the short-shaped plan
  correctly routed SHORT, not LONG) and **TWST +370**; 2 untriggered.
  Both open at data end. Labeled experimental; n too small for claims.

Traceable examples: LONG TEAM (zone fill 10-14@206.66, open +246);
SHORT PCVX (zone [62,64] bounce-fill 10-08@64, open +132 — never routed
LONG); NO_TRADE e.g. every intent lacking a parseable entry spec.

## Phase 3 — research budget

`daily_scheduler.py`: `DEEP_QUOTA = clamp(env ALPHA_RESEARCH_BUDGET, 1, 30)`,
default 10 → production unchanged; each candidate = one bounded TA run so
cap ≈ $90/session worst case. Qualification uses the existing deterministic
deep_score ranking — extras are the next-ranked candidates, not new logic.

**Count reconciliation:** earlier "8 valid contracts / 12 executable" —
different stages. R5B-only had 12 *executable-disposition* intents
(incl. gate-blocked ones lacking full terms) but only ~7-8 *fully
specified valid contracts*. Quota expansion adds executable candidates
but mostly intents still fail contract completeness.

## Answers

1. Quota excludes real candidates (12 executable) but the excluded set
   contained October's worst losers — expand only with contract-quality
   gating, not blanket 30.
2. Research→trade blockers: intents overwhelmingly lack parseable entry
   (158/224), target (100), size (89) — authoring terms, not direction.
3. Authorized-path trades were unprofitable (-1,322); the full contract
   universe flipped slightly positive (+61 LONG, +502 SHORT-exp) — but
   that's the unauthorized superset: selection-gating value unproven.
4. Most direct improvement: **author intents with complete machine
   terms** (entry+stop+target+size) — the contract validator exists;
   research prompts should emit it. Then the AI-ranking shadow reads real
   contracts instead of prose.

**Remaining barrier to a controlled paper-only trial:** historical
intents mostly lack contract-complete terms (92%+ NO_TRADE), so the trial
requires intents to carry structured terms — a prompt/authoring change in
the research path, which is a production-code change awaiting review.
