# Track: EXPERT_RND

Status: ACTIVE
Last updated: 2026-10-02T12:40:00Z
Worktree: `/home/udi/udi_provate/TradingAgents-expert-rnd`
Branch: `exp/expert-rnd-v2` (based on freshly fetched `origin/main` @ v0.5.2;
all v0.5.0 behavior references use tag `v0.5.0` =
`2d17df8da1536c121e4d7395ac5a5dcec9e96d6f`)

## Objective

Understand the expert's decision style and determine whether any of it can
improve TradingAgents without repeating the failed M2/M4 overfitting.

## Important limitation

The expert sample is mostly/entirely successful recommendations. It is NOT a
complete record of everything the expert considered or bought. It can be used
to study decision behavior; it cannot prove the expert strategy is profitable.
Do not optimize directly to reproducing every expert winner.

## Prior history (complete)

- EXPERT_MIMIC_CHALLENGE / EXTERNAL_WATCHLIST: frozen point-in-time decisions
  for FTNT/PANW (2026-09) and IONQ (2026-09-23/24).
- EXPERT_MIMIC_BENCHMARK_V1: 12 valid expert trades, 24 frozen PIT inferences;
  `TECHNICAL_REASONING_REVIEW.md` audits all 12 entry cases verbatim. SANM
  excluded (ambiguous buy date). All 12 baseline decisions = NO_ENTRY
  (11 PM Sell, 1 PM Hold).
- M2 (CONTEXTUAL_TECHNICAL_ENTRY_RM_V1): more permissive/contextual RM.
  Frozen causal-tail replay: expert 4/12 ENTRY but loser new-entries 5/12 —
  guardrail FAIL. REJECTED.
- M3 (DISCRIMINATOR_AUDIT): good-pullback vs bad-pullback audit, read-only.
- M4 (ENTRY_LOCATION_ASYMMETRY_RM_V2): entry-quality/catalyst/location/
  asymmetry gate. Training cohort: expert 2/12, losers 0/12 (guardrail PASS).
  Fresh M5 disjoint validation (46 cases): CONTROL 7/17 strong-winner ENTRY /
  1/10 clear-loser ENTRY; M4 3/17 strong-winner ENTRY / 1/10 clear-loser
  ENTRY. M4 lost winners without reducing loser entries. REJECTED.
- M5.1 conclusion: return to untouched official v0.5.0 decision layer for
  production. Explicit invented rules failed; the reasoning difference was
  never localized — that is what this track investigates.
- Also retired: structured fundamental Lane D (fresh outcome failure); broad
  non-S&P Lane A expansion (replication failure).

## Datasets / artifacts used (all already-consumed)

- `TradingAgents-mimic/evaluations/expert_mimic_benchmark_v1/` — 12 expert
  entry artifacts + verbatim reasoning review (cohort E).
- `TradingAgents-mimic/evaluations/expert_mimic_challenge/` — FTNT/PANW
  frozen decisions (E-reference; FTNT buy accepted by baseline).
- `TradingAgents-mimic/evaluations/external_watchlist/` — IONQ diagnostics
  (E-reference).
- `TradingAgents-mimic/evaluations/gate_m5_fresh_disjoint/` — 46 fresh cases
  with control+M4 RM/Trader/risk/PM text and upstream analyst reports;
  `m5_joined.json` labels (cohorts W and L). Outcome labels were legitimately
  consumed by M5; reused here as consumed R&D data, not a new validation set.
- `TradingAgents-mimic/evaluations/gate_m2_contextual_rm/` and
  `gate_m4_entry_quality/` — M2/M4 replay outputs for failure-mechanism
  attribution.

## Explicit forbidden reserves

LOCKBOX untouched. HOLDOUT unused. No untouched reserve accessed. No new
TradingAgents inference (0 calls), no bridge calls (0), no prompt changes, no
production code changes. C12 track untouched.

## X1 gate — REASONING_DISCRIMINATOR_AUDIT

### Cohort membership

- E (expert buys, baseline decision known): UAMY, DGXX, FROG, HUT, FIVE,
  ZETA, MP, FLNC, LUNR, ASYS, BB, KEEL — all NO_ENTRY under baseline
  (11 Sell, 1 Hold). No baseline-accepted benchmark case exists.
  Reference (challenge/watchlist): FTNT buy 2026-09-04 = Overweight
  (baseline ACCEPTED — the one accepted expert case); PANW buy =
  Underweight; FTNT 09-08 = Hold; PANW 09-08 = Sell; IONQ 09-23 = Sell,
  09-24 = Overweight.
- W (17 STRONG_WINNER): NEM, SNDK, TPR, HPE, LVS, GOOGL, EBAY, RCL, KMI,
  HUM, NTAP, PLTR, AVGO, MPWR, TT, APA, FICO.
  - baseline ENTRY (7): NEM, LVS, GOOGL, KMI, PLTR, TT, APA
  - baseline MISS (10): SNDK, TPR, HPE, EBAY, RCL, HUM, NTAP, AVGO, MPWR,
    FICO
- L (10 CLEAR_LOSER): GDDY, ON, NKE, SNPS, CMG, TSLA, FSLR, NRG, ABBV, CRWD.
  - correctly rejected (9): all except ON
  - incorrectly entered (1): ON (control RM/PM Overweight -> -31% abs20)

### Stage-attribution counts

First meaningful negative stage:

- E (12): analysts constructive/mixed -> **RM turned negative in all 12**
  (11 Underweight, 1 Sell). Trader Sell 12/12. PM Sell 11 / Hold 1.
  No case survived to a PM override of a positive RM.
- W-entered (7): RM Overweight -> PM Overweight in all 7. PM converted
  "don't chase" into staged limit-ladder entries rather than refusal.
- W-missed (10): RM Underweight 5 / Hold 5 -> PM Sell 5 / Hold 5.
- L-rejected (9): RM Underweight 5 / Hold 4 -> PM Sell 5 / Hold-or-
  Underweight 4.
- L-entered (1, ON): RM Overweight -> PM Overweight.

Rejection driver mix (from PM driver annotations / RM text):

- E: extension/chase 5 (DGXX, BB, KEEL severe; UAMY, LUNR moderate);
  confirmation-demanded pullback/base 6 (FROG, ZETA, MP, ASYS, FIVE, FLNC);
  substantive fundamental objection co-present in 5 (DGXX, HUT, KEEL, FLNC,
  ASYS). Reclaim/breakout gate invoked in 8/12.
- W-missed: identical shape — strong business conceded, entry rejected on
  extension + upcoming print + inverted near-term R/R (FICO, AVGO, MPWR,
  NTAP, SNDK, TPR, EBAY, RCL, HUM).
- L-rejected: same shape again (GDDY, TSLA, NKE, SNPS, CMG, FSLR, NRG,
  ABBV, CRWD). ON entered on "filed numbers + verified uptrend" despite a
  missing quarter — indistinguishable ex-ante from entered winners.

### Reasoning feature matrix (interpretable, no outcome columns)

| case | cohort | fund. accel. | catalyst spec. | tech regime | extension | evid. agree. | RM | PM | ENTRY |
|---|---|---|---|---|---|---|---|---|---|
| UAMY | E | weak | med | pullback/uptrend | med | mixed | Uw | Sell | N |
| DGXX | E | neg (neg GM) | med | parabolic recovery | severe | mixed | Uw | Sell | N |
| FROG | E | mod | med | pullback/uptrend | none | mixed | Uw | Sell | N |
| HUT | E | weak+dilution | high | post-crash stab. | none | conflicted | Uw | Sell | N |
| FIVE | E | mod (margin eroding) | med | base under resist. | mod | mixed | Uw | Sell | N |
| ZETA | E | mod (inflection claim) | med | stabilizing knife | none | mixed | Uw | Sell | N |
| MP | E | mod (unproven econ) | high | 200SMA reversal | mod | mixed | Uw | Hold | N |
| FLNC | E | weak (record loss) | med | damaged downtrend | oversold | mixed | Uw | Sell | N |
| LUNR | E | weak (neg equity) | med | pullback/uptrend | mod | mixed | Uw | Sell | N |
| ASYS | E | weak (59x breakeven) | low | digestion pullback | mod | mixed | Uw | Sell | N |
| BB | E | mod (turnaround) | med | steep uptrend | severe | conflicted | Uw | Sell | N |
| KEEL | E | neg (-70% GM) | med | accelerating trend | severe | mixed | Sell | Sell | N |
| FTNT | E-ref | strong | high | uptrend | — | aligned | Ow | Ow | Y |
| NEM | W-enter | strong | med | uptrend, extended | high | aligned | Ow | Ow | Y |
| LVS | W-enter | strong | med | pullback in uptrend | mod | mixed | Ow | Ow | Y |
| GOOGL | W-enter | strong | high | uptrend, extended | severe | mixed | Ow | Ow | Y |
| KMI | W-enter | strong | med | year-high | high | mixed | Ow | Ow | Y |
| PLTR | W-enter | strong | high | under ceiling | high | mixed | Ow | Ow | Y |
| TT | W-enter | strong | high | earnings breakout | high | aligned | Ow | Ow | Y |
| APA | W-enter | strong | med | range breakout | high | mixed | Ow | Ow | Y |
| SNDK | W-miss | strong (disputed run-rate) | med | parabolic | severe | mixed | Uw | Sell | N |
| TPR | W-miss | mod (EPS declining) | med | year-high | severe | mixed | Uw | Uw | N |
| HPE | W-miss | weak (deal arithmetic) | med | — | — | conflicted | Uw | Sell | N |
| EBAY | W-miss | weak (flat rev) | low | extended trend | severe | mixed | Uw | Sell | N |
| RCL | W-miss | strong | med | uptrend pullback | mod | mixed | Hold | Hold | N |
| HUM | W-miss | mod (EPS down) | med | golden-cross high | severe | conflicted | Hold | Hold | N |
| NTAP | W-miss | strong | med | under 11wk ceiling | high | mixed | Hold | Hold | N |
| AVGO | W-miss | strong | med | double-top pre-print | high | mixed | Hold | Hold | N |
| MPWR | W-miss | strong | med | MACD sell cross | high | mixed | Hold | Hold | N |
| FICO | W-miss | strong | med | gaps below | severe | mixed | Uw | Sell | N |
| ON | L-enter | mod (first growth qtr) | med | verified uptrend | mod | mixed | Ow | Ow | Y |
| GDDY | L-rej | strong | med | max extended | severe | mixed | Uw | Sell | N |
| NKE | L-rej | weak (declining) | low | rallied off low | mod | conflicted | Uw | Sell | N |
| SNPS | L-rej | stale/unseen post-deal | med | — | — | conflicted | Hold | Hold | N |
| CMG | L-rej | strong | med | band-pierce fade | severe | mixed | Hold | Hold | N |
| TSLA | L-rej | weak (credit borrow) | med | distribution tape | high | conflicted | Uw | Sell | N |
| FSLR | L-rej | strong | med | +30% 3-day spike | high | mixed | Hold | Hold | N |
| NRG | L-rej | mod (commodity windfall) | low | record high | severe | mixed | Uw | Uw | N |
| ABBV | L-rej | mod | low | extended uptrend | high | mixed | Hold | Hold | N |
| CRWD | L-rej | strong | med | extended | high | mixed | Uw | Hold | N |

### What actually separates entered from rejected cases

The only consistent discriminator in the artifacts is NOT technical setup —
it is whether the **bear conceded direction on verified/filed numbers**. In
all 7 W-entries, the bear's loss was on direction ("never disputed the
numbers"), and "don't chase" was converted by the PM into staged
limit-ladder exposure (Overweight). In all E cases the directional case was
either contested (5 with substantive fundamental objections) or the
fundamental layer simply could not verify the expert's catalyst (news/sentiment
vendor voids; thesis = narrative). In W-misses and L-rejects the directional
fight was genuinely undecided — and there the winner/loser outcomes are
ex-post luck, not reasoning separation.

### Pairwise comparisons (nearest neighbors)

- UAMY (E, +58%) vs GDDY (L, -5%) vs FICO (W-miss): all three =
  "real trend, extended, pullback zones named, confirmation demanded."
  UAMY's market report literally prescribed "buy dips near $6.16" — the
  expert's entry zone. Difference in outcome cannot be located in the
  reasoning texts; the distinguishing content (DoD antimony catalyst) was in
  the news-vendor blind spot.
- FROG (E, +35%) vs NTAP (W-miss) vs ABBV (L-rej): all "quality company,
  pullback/consolidation, armed re-entry triggers." Nearly identical decision
  text structure; different ex-post results.
- DGXX/KEEL (E severe-extension chases, +69%/+39%) vs SNDK (W-miss, +134%) vs
  GDDY (L-rej): same "RSI>75, far above 50SMA, climax volume" profile. Baseline
  rejects all such cases; some pay anyway. No reasoning feature in the
  artifacts separates DGXX from GDDY ex-ante.
- FLNC (E, +18%) vs NKE (L, -3%) — both falling knives with real fundamental
  damage; baseline rejected both correctly by its own standard.
- ON (L-entered, -31%) vs APA (W-entered, +15%): both "filed turnaround +
  verified uptrend + gated tranches." Same reasoning, opposite outcomes —
  the entry criterion that passed ON is the same one that passed APA.

### Why M2 failed (mechanism)

M2 relaxed the RM's confirmation requirement — "contextual technical entry."
On frozen replays it flipped 4/12 expert cases to ENTRY but also flipped
5/12 losers (PAYC, DG, CAT, HOOD, DDOG). The veto it removed was not a
winner-blocker; it was the generic "pullback needs confirmation" rule that
fires identically on winners and losers. Relaxing a non-discriminative gate
moves both distributions together. Aggregate: false negatives fell, false
positives rose more.

### Why M4 failed (mechanism)

M4 codified entry-quality/location/asymmetry as an explicit RM gate. In the
fresh cohort the baseline's winner-entries already flow through the PM's
*implicit* staged-entry mechanism ("Overweight but don't chase; ladder into
named zones"). The M4 gate converted 5 of 7 control entries into Hold/Sell
(LVS Ow->Hold, GOOGL Ow->Hold, KMI Ow->Sell, PLTR Ow->Sell, TT Ow->Uw) while
also flipping ABBV Hold->Overweight (the one new loser entry). The explicit
rule double-counted location risk the PM already prices as sizing/timing,
and its discrete pass/fail destroyed the graded conditional acceptance the
PM produces. Loser entries did not fall because losers were already rejected
for the same extension reasons — there was nothing left to cut.

### Candidate reasoning discriminators (max 3, none implemented)

**C1 — Zone-fill counterfactual (strongest, still entangled).**
Mechanism: the baseline's NO_ENTRY verdicts routinely publish exact pullback
zones and re-entry triggers (FROG $46.6, UAMY ~$6.16, FIVE $144-145, MP
$57-58, NTAP $99.7-100.8, FICO $1,364-1,388, GDDY $197-199, ABBV $198-192,
CRWD ~$86.5...). The expert buys at or near those zones *without* waiting for
the reclaim confirmation. If the armed ladders actually discriminate, filling
them mechanically would recover expert/missed winners selectively.
Supporting cases: UAMY, FROG, MP, FIVE, ASYS, ZETA (E); NTAP, AVGO, RCL,
MPWR, HUM (W-miss) all carry named zones. Contradicting: GDDY, FSLR, ABBV,
CRWD (L) carry equally well-formed ladders that would fill into losses —
the discriminator is only as good as the case-selection filter on top
("direction conceded on verified numbers" already separates, since all
entered W cases passed it, but so did ON). Node mishandling: none — this is
an execution-layer question, not a reasoning defect. Changeable as one
variable: yes (fill rule at published zone vs at decision close). Expected
failure mode: ladders fill on the way down through broken setups (the
NKE/FLNC-type falling knives) unless the direction filter holds.

**C2 — Evidence-vacuum neutrality.**
Mechanism: in ~all E cases the news/sentiment feeds were vendor-blind; the
pipeline repeatedly counts "zero confirmed evidence" as a negative
(informational darkness = risk). The expert treats silence as non-evidence.
Supporting: ASYS, DGXX, UAMY, LUNR ("verified news vacuum" cited as bear
evidence). Contradicting: W/L cohorts share the identical vendor blackout —
darkness is universal in this dataset, so it cannot discriminate at all;
it is a constant, not a feature. Verdict: explainable but NOT actionable as
a discriminator — flagged for completeness.

**C3 — Memory/reflection conservatism loop.**
Mechanism: PM texts cite "prior lessons" (ZETA/FIVE misses) when justifying
later rejections; a miss teaches the system to demand more confirmation,
ratcheting the threshold. Supporting: FLNC PM explicitly cites ZETA/FIVE;
audit §11.F flags it. Contradicting: did not change any verdict in the audit;
direction of bias unmeasured on losers. Node mishandling: memory layer.
Changeable as one variable: yes (memory stripped vs intact replay).
Expected failure mode: effect may be near-zero; also touches validation
integrity (memory is part of the system under test).

### X1 classification

**X1-B — PLAUSIBLE BUT ENTANGLED.**

The repeatable reasoning distinction that exists (bear concedes direction on
verified numbers -> staged Overweight) already operates correctly inside the
baseline; the residual failures (E cohort, W-misses) share reasoning
signatures with correctly-rejected losers. The only untested mechanism that
could add recoveries without a permissiveness change is C1: whether the
system's own published pullback zones, filled mechanically, discriminate
better than the spot-decision ENTRY/NO_ENTRY label suggests. This is a
measurement gap, not yet an intervention.

### Exactly one recommended next gate

**EXPERT_RND_X2_LADDER_FILL_COUNTERFACTUAL** — deterministic counterfactual
scoring on already-consumed artifacts only: for every E/W/L case where the
frozen PM/RM text published explicit pullback-zone or breakout-trigger
levels, compute (from already-consumed outcome data and historical price
series already in caches) whether the zone would have filled and what the
position outcome would have been at the PM's own stop/invalidation. No new
model calls; no new cases; LOCKBOX/HOLDOUT untouched. Decision rule: if
zone-fill entries recover >= ~half of E + W-misses while filling <= ~2 of the
9 rejected losers, promote C1 to a bounded design proposal; else classify the
track's historical-mimic question X1-C (stop, wait for real-time expert
recommendations including losers).

## Next action

X2 gate as specified above.

## Blockers

None for X2. Long-run blocker: the expert sample contains no losers, so no
historical analysis can fully answer "is the expert's edge real" — that
requires prospective expert recommendations including failures.

## X2 gate — LADDER_FILL_COUNTERFACTUAL (complete)

Protocol: frozen extraction `x2_frozen_entry_conditions.json`
(sha256 90a65958696e221dd27e52207c39c6aceaa34b42faada1d7b36a77e68c5fa10f),
committed in `TradingAgents-expert-rnd` (exp/expert-rnd-v2) under
`evaluations/expert_rnd_x2/` before any outcome computation. Engine:
`x2_engine.py`; results: `x2_results.json` (sha256 8462c00a...). 20-session
trigger window; 20/60-session horizons; SPY-relative via consumed
b1_2_2 adjusted SPY cache. No new inference, no bridge, no production change.

### Results

| cohort | n | eligible | filled | trigger% | med days | rel20 med | rel60 med | rel60 pos |
|---|---|---|---|---|---|---|---|---|
| E (expert, rejected) | 12 | 10 | 7 | 70% | 5 | +6.9% | -15.3% | 43% |
| W missed | 10 | 9 | 6 | 67% | 8 | +11.2% | +10.4% | 100% |
| L rejected | 9 | 8 | 6 | 75% | 6 | -6.7% | -9.0% | 17% |
| RECOVERABLE_WINNERS (E+W-miss) | 22 | 19 | 13 | 68% | 5 | +7.6% | +8.4% | 67% |
| W entered (reference) | 7 | 7 | 6 | 86% | 6.5 | +4.1% | +16.5% | 83% |

Ineligible: ASYS (PM disarmed tape reclaim — catalyst required),
KEEL (dip-buy explicitly forbidden; non-price re-eval), HPE (levels deferred
to post-print), NKE (filed-fundamentals gate only).

### Promotion criteria

1. >=8 RW eligible: PASS (19)
2. RW trigger >=50%: PASS (68.4%)
3. triggered RW median rel60 >0 AND pos-rate >=55%: PASS (+8.4%, 66.7%)
4. L trigger <=25%: FAIL (75%)
5. triggered losers <=2: FAIL (6)
6. winner-minus-loser trigger gap >=25pp: FAIL (-6.6pp)

### Classification: X2-B — ENTRY ZONES NON-DISCRIMINATIVE

Published zones trigger on losers at the same rate as winners. However the
conditional outcomes diverge sharply (triggered winners rel60 med +8-10%,
triggered losers -9%) — the zone is not the discriminator; what happens
AFTER the fill is. Two further honest findings:

- Expert entries sit at or below the published conditions in 9/10 eligible E
  cases (e.g., UAMY expert $6.65 vs momentum-reclaim fill $7.64; ZETA $17.7
  vs $18.81-reclaim fill $20.42). The expert buys earlier and cheaper than
  the system's own confirmation triggers; executing the system's triggers
  pays a confirmation premium.
- E-cohort rel60 is negative (-15.3% median) despite expert realized gains:
  the expert exits into strength within ~2-4 weeks; a fixed 60-session
  horizon rides through the post-spike collapse (DGXX +69% realized but
  -26% rel60 from trigger fill). X2 measures delayed-entry quality, not
  expert round-trip replication.

### Does X2 solve the M2/M4 problem?

Partially, for entry timing only: it mechanically recovers 13/19
recoverable-winner setups without any reasoning-layer change (the M2/M4
prompt modifications were unnecessary for this dimension). But it fails the
false-positive side by itself: 6/8 eligible losers also triggered, and their
fills went on to lose (ABBV -14% rel60, CRWD -12.6%, CMG -21%). The zones
are honest levels — losers simply reach them too, and what separates the
cohorts is post-fill behavior relative to the PM's own published
invalidations, not the trigger.

## Next action (exactly one)

EXPERT_RND_X3_PUBLISHED_STOP_DISCIPLINE — deterministic second-stage
counterfactual on the SAME frozen extraction and caches: for each X2 fill,
apply the PM's own published stop/invalidation level (already present in the
frozen texts) and re-score outcomes at stop-exit or horizon. Hypothesis:
loser fills hit their published invalidations quickly while winner fills do
not — i.e., the discriminator may live in published-invalidations adherence
rather than in the entry zone. If triggered-loser outcomes after
stop-discipline are cut to <=2 adverse entries while winner returns hold,
that would isolate an execution-layer discriminator; otherwise the
historical expert-mimic question is closed (X1-C conclusion path).

## X3 gate — PUBLISHED_STOP_DISCIPLINE (complete)

Protocol: frozen invalidation extraction
`evaluations/expert_rnd_x3/x3_frozen_invalidation_conditions.json`
(sha256 251ec31b7c34987510972465c8bd46647c56b464d55309c1c8bbd115f15c996a),
committed on exp/expert-rnd-v2 before stop-outcome computation. Engine:
`x3_engine.py`; results `x3_results.json` (sha256 ec0e745d...). Same
consumed caches and SPY convention as X2.

### Survival results

| cohort | triggered | scoreable | stopped | stop rate | med sess | surv20 | surv60 |
|---|---|---|---|---|---|---|---|
| E | 7 | 6 | 4 | 67% | 19 | 4 | 2 |
| W-missed | 6 | 6 | 3 | 50% | 2 | 4 | 3 |
| L-rejected | 6 | 6 | 6 | 100% | 6 | 0 | 0 |
| RECOVERABLE_WINNERS | 13 | 12 | 7 | 58% | 16 | 8 | 5 |
| W-entered ref | 6 | 6 | 2 | 33% | 2.5 | 4 | 4 |

SAME_DAY_ORDER_AMBIGUOUS: 0. UAMY had NO_EXPLICIT_INVALIDATION (unscoreable).

### Promotion criteria

1. >=8 RW scoreable: PASS (12)
2. >=5 L scoreable: PASS (6)
3. L stop rate >=60%: PASS (100%)
4. RW stop rate <=35%: FAIL (58.3%)
5. stop-rate gap >=30pp: PASS (41.7pp)
6. RW median policy return >0 AND pos >=55%: FAIL (med -0.9% abs, pos 50%)
7. improves L median without RW median <0: FAIL (L improved -7.0% vs -9.0%
   rel60, but RW policy median went below zero)

### Classification: X3-B — PUBLISHED INVALIDATION NON-DISCRIMINATIVE

Stops separate on RATE (losers stopped 100%, winners 58%, entered-ref 33%)
but fail on selective removal: published invalidations were calibrated to the
spot-price entry and bite too early on cheaper zone fills — FIVE stopped at
+0.8% at session 3 vs +33% at fixed-60; MPWR/FICO stopped at ~-3% vs +1% /
+21% held. Applying them converts more winner fills into scratches/small
losses than it removes losers. Net STOP_POLICY_RETURN for recoverable
winners is ~flat/negative, worse than the X2 fixed-60 result.

## HISTORICAL_EXPERT_MIMIC = CLOSED

X1-B -> X2-B -> X3-B exhausts the executable discriminations recoverable
from consumed artifacts:

- Reasoning-layer permissiveness (M2) and explicit entry gates (M4): rejected.
- Published delayed-entry zones: trigger non-discriminatively (X2-B).
- Published invalidations: discriminate on stop rate but destroy winner
  economics when enforced (X3-B).

What X1-X3 did establish: the expert buys earlier than the system's
confirmation triggers (9/10 eligible cases at/below the zone), realizes
gains inside ~2-4 weeks, and exits before the 60-session deterioration the
frozen labels measure. The residual untested hypothesis is profit-taking /
exit-into-strength (exit policy), which cannot be validated on consumed
data — the expert sample contains no losers, so no negative examples exist
to test it against.

## Next action

None on historical artifacts. Future expert research requires prospective
real-time expert recommendations including losing trades. If pursued, open a
new gate only when a prospective expert sample with both winners AND losers
exists.
