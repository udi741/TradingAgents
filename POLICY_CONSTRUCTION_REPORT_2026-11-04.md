# POLICY_DERIVED Economic Construction — Mission Report (2026-11-04)

## Verdict: NO-GO for new entry authorization

The evidence-bound POLICY_DERIVED construction layer is implemented, tested,
and verified end-to-end. It produces additional complete, safe, executable
investment plans from evidence the old pipeline rejected — but the measured
delta is **+1 executable case out of 230, and that trade lost money**. The
remaining bottleneck is no longer contract-construction mechanics: it is the
scarcity of constructive judgments that survive honest ambiguity declaration,
plus the absence of economic evidence that the continuation entry style pays.
Lab implementation is complete and preserved for re-evaluation; nothing was
promoted to production.

## What was built (lab only, research/alpha-lab)

**AI judgment vs deterministic economics, now explicit:**

- `alpha_rnd/econ_policy.py` (new): versioned policy (`POLICY_VERSION=1`).
  When an intent is constructive (Buy/Overweight + constructive class or
  authored LONG contract) with no judgment-level ambiguity, but the authored
  economics are missing/unbound/incoherent, it constructs a complete
  contract: authored anchors kept verbatim when bound (SOURCE_AUTHORED);
  everything else deterministic — trigger = decision close for continuation,
  stop = entry−1.5×ATR(14), target = 2R, size = 1% risk budget (the existing
  `permissible_size` rule), gap guard 3%, confirm window 5 sessions, horizon
  ≤20 sessions. Constants reuse predeclared framework values
  (entry_shadow B_confirmed); none tuned on outcomes.
- `econ_contract.validate(..., policy_terms=)`: POLICY_DERIVED numbers are
  exempt from source binding only; every geometry/sizing/stop/success-plan
  gate is unchanged. `number_provenance` recorded on the resolved contract —
  a policy number can never masquerade as authored (tested).
- `synthesize.evaluate_intent()` (new, extracted from `run`): the single
  deterministic per-intent path used by both live synthesis and the frozen
  replay harness. Also fixed: `econ_contract.repair` was dead code for LONG
  failures (gated on `resolved is not None`, which is always None on
  failure); it now fires as designed.
- Constraint partition (`_partition_constraints` in `project_execution`):
  `no_entry_conditions`/event text is strictly machine-encoded where
  possible — "chasing above $X" → `max_entry_price` (fill refused above),
  "close below $X" → `kill_level` (watch expires); `exit on/if …` is
  post-entry management → observational only. Anything unencodable remains
  UNVERIFIED and blocks authorization at three levels: disposition
  (PUBLISHED_NON_EXECUTABLE), monitor evaluation, and `do_fill`.
- `publish.py` now carries event/provenance fields into the watch
  (previously dropped silently — the reason constraints were never
  enforced).
- `monitor.py`: `confirmed_close_above` now evaluates the last completed
  session (was `df.iloc[-2]` — a one-session lag), supports
  `confirm_within_sessions` expiry and `max_gap_pct` next-open cancellation;
  `kill_level`/`max_entry_price`/`_event_unverified` enforced.

## Measured deltas (frozen replay, 230 intents × all sessions)

| Metric | Old | New |
|---|---|---|
| EXECUTABLE_WATCH | 1 (RHI) | 2 (RHI + TEAM@10-12) |
| Complete valid contracts | ~13 authored | +3 policy-constructed |
| Correctly event-gated | 0 enforced | 3 (CDNA@11-02→PNE, REPL@10-30, CAI) |
| Invalid authorizations | 0 | 0 |
| Lost executables | — | 0 |
| Unauthorized LONG/SHORT fills | 0 | 0 |

- **TEAM@2026-10-12** (Overweight, ACTIONABLE_NOW, no authored contract):
  policy continuation → confirmed close → fill 10-14 open $206.76 →
  stopped 10-30 $195.11 → **−$36.21** (3 shares, risk-sized).
- **RHI@2026-10-28**: unchanged EXECUTABLE pullback; its contract
  constraints now machine-enforced (max_entry_price 44.98, kill 38.80)
  instead of silently dropped. Sim: open +$98.83 (matches real position).
- **CDNA@2026-11-02**: complete policy pullback contract — correctly gated
  PUBLISHED_NON_EXECUTABLE by unverifiable 10-Q/valuation prerequisites.
- **REPL@2026-10-30**: complete contract produced but intent-level
  `unsupported size_frac 0.6` + unverified filing prerequisites → stays
  rejected. Correct.

Net simulated PnL of revised executable fills: **+$62.62** (2 fills,
in-sample) vs SPY −1.8%/−1.95% in matching windows. n=2: no edge claim.

## Phase-5 bounded model validation

4 devin-deep invocations (cap 24), ~$5-8 est. Sessions 10-16, 10-19, 10-20,
10-23 — 40 held-out artifacts, fresh synthesis:

- 0 unsafe authorizations, 0 fabricated contracts, 0 policy constructions.
- Fresh intents declare judgment-level ambiguity (EVENT_OUTCOME_UNKNOWN,
  CATALYST_UNRESOLVED, SIZING_CONFLICT…) at high rates → `eligible()`
  correctly refuses construction. Sell/Hold signals → no construction.
- The mechanism is verified safe on fresh output; it simply rarely
  activates because honest research output rarely qualifies.

## Why NO-GO (failure attribution)

1. **Signal supply, not mechanics**: eligible constructive cases are ~1.3%
   of intents (3/230). The blocker upstream is the model's judgment-level
   ambiguity declarations — untyped `ambiguity:` prose and event codes —
   which correctly fail closed and cannot be policy-resolved.
2. **Economic evidence absent**: the single new opportunity filled and
   lost. A controlled rollout of continuation entries has no positive
   supporting evidence yet.
3. GO criteria ("enough supporting evidence") unmet; hard failure rule
   does not apply because a *positive* delta exists — it is just too small
   and economically unproven to justify new production authorization.

## If reconsidered later (deployment/rollback sketch)

Deploy pattern (established): `git checkout origin/research/alpha-lab --
alpha_rnd/econ_policy.py alpha_rnd/econ_contract.py alpha_rnd/synthesize.py
alpha_rnd/decision.py alpha_rnd/publish.py alpha_rnd/monitor.py` in prod,
commit, push main. Rollback: `git checkout <prev> -- <same>`. Do NOT deploy
until a bounded prospective window shows ≥1 additional *profitable-or-neutral*
safe execution and the ≥30% valid-contract gate from HANDOFF is met.

## Files

- New: `alpha_rnd/econ_policy.py`, `alpha_rnd/test_econ_policy.py` (50
  checks), `backtest/decision_reconstruction.py`,
  `backtest/policy_synthesis_check.py`, results JSONs under
  `backtest/results/`, this report.
- Modified: `econ_contract.py`, `synthesize.py`, `decision.py`,
  `publish.py`, `monitor.py`, `HANDOFF.md`.
- Production checkout: untouched. `backtest/sector_rotation_eval.py`
  (pre-existing untracked) untouched.

## Reproduce

```bash
cd ~/udi_provate/TradingAgents-contract
PYTHONPATH=. python3 alpha_rnd/test_econ_policy.py
PYTHONPATH=.:backtest python3 backtest/decision_reconstruction.py --econ
PYTHONPATH=.:backtest python3 backtest/policy_synthesis_check.py <sess...>  # costs $
```
