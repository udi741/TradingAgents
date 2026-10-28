
### Follow-up experiments (mission3.json)

| Variant | 2024 | 2025 | 2026YTD | Verdict |
|---|---|---|---|---|
| Baseline (2.0·ATR, no gate) | +11.1 | -8.3 | +27.0 | — |
| H2 SPY>20SMA entry gate | +5.8 | -7.1 | +33.4 | REJECTED — no consistent gain |
| **H3 2.5·ATR stop** | **+19.2** | **+0.9** | **+32.3** | RETAINED — only variant positive in all 3 |

H3 improves every period (PF 2.27/1.05/4.23 vs 1.63/0.72/3.00): the
wider stop survives routine noise and keeps winners. Caveats: survivor-
biased universe, single-variant test (not a tuned grid), ordering effects
untested. Next test: seeded ordering sensitivity + 15bps costs on H3.

### H3 robustness (mission4.json — 2.5xATR, seeds x 10/15bps)

| Period | ATR25 alpha | ATR25 seeds | ATR25 15bps | Baseline alpha |
|---|---|---|---|---|
| 2024 | +19.2 | [15.2,19.2] | +18.9 | +11.1 |
| 2025 | +0.9 | [-17.5,+0.9] | +0.6 | -8.3 |
| 2026YTD | +32.3 | [29.3,32.3] | +32.0 | +27.0 |

- Cost robustness: PASS (15bps costs ~0.3pp).
- Ordering: PARTIAL FAIL — 2025 seeds swing 0.88→-17.52; 2024/2026 stay
  positive across seeds.
- Note: `closed`-list unavailable from portfolio_run (returns stats
  only) → winner-concentration metric uncomputable; recorded None.
- Verdict: **RETAIN AS UNVALIDATED** — better than baseline alphabetically
  in all periods and all cost scenarios, but not seed-robust in 2025.
  Not deployable; next step would be a shadow-variant forward test.

### Perf note
portfolio_run rebuilt a 1.7M-date union + per-position strftime scans per
call (O(36x) waste across the grid) — fixed with shared date/close caches;
runs now 0.1s after ~4s cold. mission4 completed in ~5min after fix.

### AI selection vs mechanical controls (mission5.json, Oct-2026 window)

Mechanical retest on identical rules, different universes:

| Universe | n names | Signals | P&L | PF |
|---|---|---|---|---|
| AI-researched | 50 | 27 | **-3,938** | 0.47 |
| Full discovered pool | 132 | 49 | -2,187 | 0.65 |
| Random 50-name subsets | 5 seeds | — | +138/-351/+122/-2,928/-4,438 | 1.03/0.93/1.04/0.53/0.25 |

The AI-researched set produced **worse mechanical outcomes than 4 of 5
random equal-size subsets** in October. Selection coverage did not add
value under identical execution. Caveats: one regime, ~3 weeks, the
set measures "names chosen for deep research" (discovery ranking + quota)
not authored trade decisions; AI authored contracts were only evaluated
on 6 names earlier (2 LONG, both small losses/open marks).

### Improved historical dataset + evaluation (mission6.json)

**Dataset:** CURRENT S&P500 constituents (snapshot) + `Date added`
eligibility gate. This is NOT a complete point-in-time universe:
constituents removed before the snapshot are entirely absent, so
survivorship bias REMAINS (the added-later bias is removed; the
removed-member bias is not). Removed members do NOT remain eligible —
they were never present in the source data. 503 priced names.

| Period | LONG | SHORT | SPY |
|---|---|---|---|
| 2024 | -2.6% (81t, PF 0.80) | -7.8% (72t, PF 0.85) | +25.6% |
| 2025 | -5.3% (82t, PF 0.75) | -7.7% (79t, PF 0.64) | +18.0% |
| 2026YTD | +15.5% (44t, PF 3.5) | -12.2% (59t, PF 0.90) | +13.2% |

vs the survivor-biased 1824-universe (LONG +11.1/-8.3/+27.0): returns
shrank, but the universes differ in size, sector mix and stock
characteristics — the delta cannot be attributed to survivorship alone.
The mechanical retest-with-stop SHORT rule lost in all three periods
under both universe constructions (3 periods x 2 overlapping universes);
this rejects THIS rule, not the possibility that some short strategy
could work elsewhere. 2026YTD LONG +15.5% vs SPY +13.2% is a modest
excess on differing exposure (partly-invested portfolio, not
benchmark-equivalent).

### H3 cross-universe validation (mission7.json — S&P500 snapshot universe)

Pre-registered: if the 2.5xATR edge were a 1824-universe artifact, it
would vanish on the mission6 universe (503 names, added-later bias
removed; removed-member bias remains). LONG only, 10bps, seeds
{alpha,1,7,13,42}.

| Period | ORIG alpha | ATR25 alpha | ORIG seed range | ATR25 seed range |
|---|---|---|---|---|
| 2024 | -2.6 | +1.5 | [-2.6,+4.6] | [+1.5,+9.8] |
| 2025 | -5.3 | -4.7 | [-6.5,+1.2] | [-9.1,-4.7] |
| 2026YTD | +15.5 | +16.7 | [+8.3,+19.1] | [+11.0,+16.7] |

Frozen rule outcome: ATR25 > ORIG alphabetically in all 3 periods;
ATR25 seed-min > ORIG seed-min in 2/3 (2025 fails). Verdict:
**RETAIN-VALIDATED (weak)** — the stop-width edge replicates across two
different universe constructions, so it is unlikely a pure survivorship
artifact. BUT both variants lose in the mixed 2025 regime: ATR25 widens
winners' room, it does not create regime-independent alpha. The
underlying LONG mechanics remain profitable only in trending 2026
(+16.7% vs SPY +13.2%, partly-invested NAV). Still not deployable;
next step remains a shadow-variant forward test.

### Methodology fix (mission8)

`portfolio_run` seeded orderings used Python `hash()`, which is salted
per process — the seed values reported in missions 4/7 were valid
distribution samples but not reproducible. Replaced with md5-based
stable ordering. Seed-level numbers across pre-fix and post-fix runs
are not comparable; alphabetical (seed=None) results are unaffected.

### Per-stock 200SMA trend gate (mission8.json — S&P500 snapshot universe)

Pre-registered: does requiring fill-day close > ticker's own 200-SMA
fix the 2025 mixed-regime losses without wrecking trending-period
returns? Both arms stop=2.5xATR, LONG, 10bps, stable seeds {a,1,7,13,42}.

| Period | ATR25 mean | TREND200 mean | ATR25 range | TREND200 range |
|---|---|---|---|---|
| 2024 | +4.6 | +4.0 | [+1.5,+8.2] | [-0.1,+10.5] |
| 2025 | -7.2 | -3.6 | [-10.1,-4.7] | [-6.8,-0.6] |
| 2026YTD | +16.9 | +13.1 | [+10.4,+24.6] | [+10.1,+23.0] |

Gate rejects ~7-13% of signals (67/132/91 per period). It worked as
designed in 2025 (halved the losses) but cost ~4pp mean in 2026 and
slightly hurt 2024 — entries below the 200-SMA include early base
breakouts that became big winners. Verdict: **REJECTED** as a
standalone variant (frozen rule: mean better in only 1/3 periods).
Regime-loss mitigation remains the open problem.

### Downtrend-gated SHORT retest (mission9.json — 200SMA mirror gate)

Pre-registered mirror of mission8: if anti-trend entries fail for
longs, shorting names NOT in downtrends should also fail; gating fills
to close < own 200-SMA should improve the rejected SHORT_ORIG. Both
arms 2.0xATR, 10bps + 2%/yr borrow, stable seeds.

| Period | SHORT_ORIG mean | SHORT_T200 mean | T200 range |
|---|---|---|---|
| 2024 | -11.8 | -16.0 | [-19.1,-14.4] |
| 2025 | -10.5 | -9.2 | [-13.8,-4.9] |
| 2026YTD | -9.8 | -10.3 | [-14.6,-4.9] |

Gate rejects ~25-33% of signals. It made 2024 materially WORSE (the
200-SMA gate admits only deeply-fallen names whose bounce-retests
recover — exactly the names that mean-revert up) and did not fix the
other periods. Verdict: **REJECTED** (min/mean wins 1/3 each).
Cumulative evidence: this short rule family (breakdown + retest entry,
close_above_stop exit) is rejected under every tested configuration —
ungated on two universes and downtrend-gated. Stop iterating it.

### PROFIT exit variant + two accounting fixes (mission10.json)

Pre-registered: trim 50% at first close >= +8%, trail remainder at
peak_close-8pp; entry/stop identical to ATR25 (2.5xATR), LONG, 10bps.

Two bugs found and fixed BEFORE trusting results:
1. `sim_period` recorded `shares` AFTER the management loop — under
   PROFIT trims the recorded size was the remainder, so portfolio_run
   debited cost on N shares but credited exits on all legs -> phantom
   free shares inflated NAV ~3-10x. Per-trade `pnl` was always correct
   (computed from legs); only the NAV path and `ret_pct` denominator
   were wrong. Fix: record original size `sh0`; `ret_pct` uses `sh0`.
2. PROFIT trim on a 1-share position sold the only share and left a
   zero-size trailing position -> ZeroDivisionError. Fix: trim only
   when shares > 1.

Corrected results (stable seeds, means over {a,1,7,13,42}):

| Period | ATR25 mean | PROFIT mean | ATR25 range | PROFIT range |
|---|---|---|---|---|
| 2024 | +4.5 | +6.8 | [+1.5,+8.2] | [+4.6,+9.1] |
| 2025 | -7.3 | -1.7 | [-10.1,-4.7] | [-3.6,-0.3] |
| 2026YTD | +16.8 | +8.6 | [+10.4,+24.6] | [+3.6,+17.5] |

Verdict: **RETAINED** (mean+min better in 2/3 periods). Interpretation:
PROFIT is the DEFENSIVE profile — better in chop (2025) and flat years
(2024), costs ~8pp in trending 2026 by capping winners. Compounded
across all three periods the two profiles are roughly equal (~+13-14%)
but PROFIT has much lower dispersion. The strategy's excess return
over SPY comes from holding winners in trends; every defence that
helps the losing regime taxes the winning one. Best combined profile
so far: LONG-only, 2.5xATR stop; choose PROFIT vs plain by regime
tolerance, not by a universal winner.

## Corrections round (exp 14) — methodology fixes + corrected verdicts

### 1. Look-ahead in gate filters (FIXED)
`sim_period` fills intraday at the zone touch (`l <= zt`), but TREND200,
GAPFILT and SPYGATE all evaluated the SAME-DAY close. All three now use
the previous completed session (close/SMA at i-1; SPY at prior bar;
GAPFILT window shifted to sessions i-5..i-1). Regression test
`test_trend200_no_lookahead` locks the behavior.

### 2. Seed-ordering reproducibility (FIXED, mission7 rerun)
Builtin `hash()` is process-salted; replaced by md5-stable ordering.
Mission7 rerun under stable ordering (original preserved in
`results/mission7_presalt.json`):

| Period | ORIG alpha | ATR25 alpha | ORIG seed range | ATR25 seed range |
|---|---|---|---|---|
| 2024 | -2.6 | +1.5 | [-2.6,+7.0] | [+1.5,+8.2] |
| 2025 | -5.3 | -4.7 | [-10.6,-1.0] | [-10.1,-4.7] |
| 2026YTD | +15.5 | +16.7 | [+10.8,+16.1] | [+10.4,+24.6] |

Verdict unchanged in form (ATR25 > ORIG alpha in all 3; seed-min
better in 2/3) but RECLASSIFIED below — this is a mechanical A/B
comparison, not validated alpha.

### 3. Mission8 rerun without look-ahead — VERDICT FLIPS
Original leaked-gate result: REJECTED. Corrected prior-session gate
(original preserved in `results/mission8_v1_lookahead.json`):

| Period | ATR25 mean | TREND200 mean | TREND200 range |
|---|---|---|---|
| 2024 | +4.5 | +4.6 | [-1.7,+8.1] |
| 2025 | -7.3 | -1.8 | [-3.4,+0.5] |
| 2026YTD | +16.8 | +14.5 | [+10.4,+23.7] |

Corrected gate admits fewer signals (48/92/70 rejected) and beats
ATR25 on mean in 2024 AND 2025; 2025 seed-min -3.4 vs -10.1.
Frozen rule -> **RETAINED**. Prior-session gating is stricter and
more effective than the (leaked) same-day version. This remains a
mechanical result, not deployable alpha.

### 4. Mission9 rerun without look-ahead — still REJECTED
Original preserved in `results/mission9_v1_lookahead.json`. Corrected:
2024 mean -13.8 vs -11.8 ungated; 2025 mean -7.2 vs -10.5; 2026 mean
-11.5 vs -9.8. min_wins=2 but mean_wins=1 -> REJECTED. Conclusion
strengthened: gate helps the losing regime only; the short rule family
stays closed (this rule's rejection does not preclude other short
designs).

### 5. Accounting verification (test_mech_regressions.py — 5 tests)
All PASS: gate uses prior session; PROFIT leg shares sum to recorded
shares; 1-share positions never trim and exit cleanly; portfolio cash/
NAV reconciles to the cent on a known trade; all exit legs execute
after their signal close. The earlier phantom-share defect (NAV
inflation under PROFIT) is confirmed fixed — mission10's published
numbers were already computed post-fix and are unchanged.

### 6. Corrected economic conclusions (supersede earlier wording)
- H3/ATR25 is an experimental improvement over a WEAK mechanical
  baseline on biased data — not validated trading alpha.
- Both universes carry survivorship bias (1824-name worse; the 503
  snapshot still lacks removed members). Relative A/B conclusions can
  also shift with universe choice; only the replicated direction of
  the ATR25 effect is trustworthy, not its magnitude.
- 2024/2025/2026YTD are design-adjacent periods, not untouched
  out-of-sample validation.
- Nothing in missions 6-10 demonstrates that TradingAgents' AI
  research selects profitable investments.
- The tested SHORT rule family's rejection is specific, not a claim
  about short strategies in general.
- MECHANICAL INVESTIGATION IS CLOSED: no further ATR/MA/profit-taking
  parameter searches. None of these mechanical variants is deployable.

## AI-authored decisions: first prospective score (mission11.json)

The `alpha_paper_ledger` (frozen 2026-10-02/03, before outcomes) is
the first causally-valid AI evidence: authored zones, invalidations
and triggers — not a mechanical proxy. Six fills, all LONG, window
2026-10-02 -> 2026-10-23, 10bps costs, $100k book:

| Variant/control | net % | reading |
|---|---|---|
| AI as-recorded | -2.40 | realized -2,141 on 5 closed + PBF mark |
| AI rules-only (no mgmt exits) | -3.15 | discretionary exits helped +0.75pp |
| Same-names naive hold | -3.02 | AI mechanics added ~+0.6pp vs holding its picks |
| Watchlist-naive (all 10 V2 names @ open 10/5) | -3.44 | selective triggers added ~+1.0pp vs buying all researched names |
| SPY matched deployment | -0.46 | market beat every AI variant by ~2-3pp |

Honest reading: AI-authored entry zones, invalidations and selective
triggering added measurable value RELATIVE to naive controls on the
same names, but the underlying selections were net-negative and the
book underperformed SPY. Zero SHORT contracts were authored — no short
evidence exists. n=6 over one 3-week window: exploratory evidence of
execution value, no evidence yet of profitable selection. PBF was the
only profitable thesis (+14% MFE) and closed under its authored stop
(78) on 10/23, ending negative.

## Consolidated AI-decision evidence (mission12.json) — FINAL

### Reconciliation of the ALPHA paper book (supersedes mission11 v1)

v1 errors: PGEN fill was $8.20 not $8.21; PBF was reported as exited
under its $78 rule — it is OPEN (the close<78 trigger only CONFIRMED on
10/23; exit executes at the next open — unexecuted as of 10/23 close);
exit legs needed the postmortem `non_economic` flags to exclude
duplicate-incident rows (ACN @195.00, SDGR @25.69); V1 entry bases are
feeless, V2 `PAPER_ENTRY` costs include the fee. Reconciled book now
reproduces canonical r7b1 to the cent: realized **-2,140.99**, cash
92,899.01, NAV(10/23) **97,621.55 (-2.38%)**.

Population (only ACTUAL executions): 6 fills, all LONG —
PBF 62@80 open; ACN 24@205->195.23 (authored close<194);
APPS 442@11.30->10.30 (gap through 10.42 stop);
PGEN 609@8.20->7.79 (corrective exit after monitor MISSED the 7.75
stop); SDGR 161@31.00->27.81/25.91 (discretionary mgmt reviews);
TWST 11@209.55->158.26/159.74 (mgmt reviews).
Excluded: ASST trigger 10/14 blocked by RISK_PLAN_REQUIRED (unexecuted);
PBF 10/16 partial-exit intents were shadow_only (unexecuted);
E1 shadow marks are counterfactual diagnostics (not trades).

| Book/control (10/02-10/23, identical 10bps costs) | net % |
|---|---|
| AI as-recorded | -2.38 |
| Same-names naive hold | -2.97 |
| V2 watchlist-naive (10 names, 10/05 open) | -3.44 |
| SPY matched | -0.49 |
| per $ deployed: AI -8.75% vs naive -10.93% | |

### C12_PROSPECTIVE (read-only, its own 20-session hold policy)

Scoreable cycles 10/02-10/23: 4 ENTRY fills, all OPEN (exits mature
10/30-11/18, none closed yet): HPE -15.2% vs SPY -1.3% (excess -14.0pp);
NTAP -0.4% (+0.8pp); PLTR -2.4% (+0.1pp); COP +5.7% (+6.6pp).
0 completed lifecycles. 2026-09-25 entries non-scoreable (late) —
excluded. 18 scoreable Sell/Underweight NO_ENTRY calls: 10/18 (56%)
underperformed SPY forward — coin-flip accuracy with large variance
(correct: TER -31%, LITE -30%, HPE -23% avoided on 10/9; wrong: MPC
+16%, VLO +8%, RVTY +5% called Sell). C12 NAV 99,383 (-0.62%, 10/25).

### Answers to the five questions

1. Stock selection: CONTRADICTED so far — 6/6 ALPHA picks underwater at
   horizon; C12 2/4 entries beat SPY (HPE dominates negatively); C12
   avoid calls 56% correct ≈ chance.
2. LONG/SHORT direction: UNSUPPORTED — zero authored shorts in either
   book; all executed risk was long into a falling tape.
3. Entry timing: WEAK POSITIVE — zone-limit discipline beat holding the
   same names (+0.6pp book, +2.2pp per $ deployed) and beat buying the
   whole watchlist (+1.1pp); E1 shadow marks showed +1.7/+2.8pp day-1
   discipline deltas.
4. Management/exits: MIXED — mgmt reviews (SDGR/TWST) cut losses
   (+0.75pp vs rules-only); but ACN's authored close<194 stop exited at
   195 and the stock sits at 249 (+21%) — the invalidation was
   structurally wrong. PGEN's stop was correct but the monitor missed
   it (operational bug, not judgment).
5. Portfolio economics after costs: NEGATIVE — ALPHA -2.38%, C12
   -0.62%, both behind SPY-matched (-0.49% / flat windows).

### Verdict

NO credible evidence of profitable AI investment decisions yet. What is
supported: authored execution mechanics (zone entries, selective
triggering vs blanket watchlist buys, discretionary management reviews)
add small positive value RELATIVE to naive alternatives — roughly
+0.6-2.2pp. What is contradicted: profitable selection — every
concrete long pick in the only prospective window lost money or
underperformed SPY. What is unsupported: short-side ability (never
authored), and any claim of alpha (n=10 executions, one regime,
~3 weeks).

Weaknesses found in the AI decisions (evidence-based):
- Long-only bias in a falling window; no hedge/short capability used.
- Some authored stops sat at levels the market immediately broke
  (ACN 194 vs 200-SMA rationale — exited at 195, stock +21% later);
  invalidations need structure-level justification, not round numbers.
- Operational integrity: missed stop (PGEN), duplicate exits, missed
  exit review (PBF 10/16-19) — monitor bugs cost real P&L.
- Trigger-without-exit-plan existed (ASST) — correctly blocked by the
  new RISK_PLAN_REQUIRED gate; validates that control.
- C12 Sell calls have coin-flip accuracy; strong Sell calls caught
  TER/LITE crashes but sold winners MPC/VLO/RVTY.

Concrete improvements justified:
- Enforce (already-gated) machine-actionable exit plans pre-entry; add
  monitor self-tests for stop evaluation coverage (PGEN-class bug).
- For close<level invalidations, require the authored level to reference
  a named structure (SMA/shelf) and a scheduled re-evaluation —
  ACN's stop lacked both.
- Keep selective-trigger vs watchlist-buy discipline: measured +1pp.
- Next evidence milestone: C12 exits mature 10/30-11/18 (4 positions);
  ALPHA PBF pending exit at next open; rescore this table then.

## Selection research (mission13.json + mission13_dataset.json)

Population: 227 timestamped deep analyses — 142 ALPHA production
artifacts (10/session, 10/01-10/23), 54 R5B full-pool replays
(deduped), 31 C12 weekly decisions — joined to decision-time-only
features (PM/trader/RM ratings, pool labels, rsi, fundamental_facts
YoY growth — see provenance notes in the corrections block) and
next-open outcomes (H1/H5, SPY excess; H20 not yet mature for any
October session).

### What separated winners from losers (descriptive, all analyzed names)

| Feature split | better group | gap (mean H5 excess) |
|---|---|---|
| FUNDAMENTAL_ACCELERATION label | labeled | -2.37 vs -5.15 (+2.8pp) |
| rsi_14 < 70 vs >= 70 | < 70 | -1.97 vs -4.75 (+2.8pp) |
| fund_support (rev+NI yoy >0) | supported | -2.46 vs -3.51 (+1.1pp) |
| consensus (pm+trader bull, rm not bear) | consensus | -1.19 vs -3.23 (+2.0pp) |
| production top-10 vs ranks 11-28 | top-10 | +0.6 vs -3.2 (10/07); -10.3 vs -5.5 (10/09); -6.9 vs -5.2 (10/12) |

PM "Overweight" on production-selected names: +3.7 mean excess (n=7,
71% positive) — the only rating bucket with positive selection value,
but too small to rely on. PM "Buy" on the same names: -2.3 (n=3).

### Pre-registered rules FAILED (bull cohort, n~20)

| Rule | n | mean H5 excess |
|---|---|---|
| BASELINE all bull signals | 20 | -0.91 |
| R_FUND (rev+NI yoy >0) | 13 | -1.98 |
| R_CONS (full consensus) | 19 | -1.19 |
| R_ACCEL (accel label) | 16 | -1.84 |
| R_FUND+CONS | 12 | -2.50 |

No fundamental/consensus/label filter rescued the bull cohort — every
subset was flat-to-worse. The October tape discounted all signal-level
screening; bull picks were noise (-0.9 mean, 35% positive).

### LONG vs bearish separately

Sell-rated cohort (n=109, ALPHA+R5B): mean -3.37, median -1.96,
39% fell >5% — real left skew on average. BUT per-session means flip
positive in rebound weeks (+7.4 on 10/14, +4.7 on 10/16): the bearish
signal is regime-dependent and cannot be used as a standalone short
signal without a timing layer the framework does not have. C12
Sell/Underweight calls: 56% correct — coin flip. No authored short
contract has ever existed; "Sell" remains a no-entry vote, not a short
recommendation. Evidence for a profitable short policy: INSUFFICIENT.

### Coverage question (10 vs 20-30 deep runs)

R5B ran the full 28-name pool on 3 sessions. Ranks 11-28 produced only
2-5 additional bull-rated names per session at aggregate NEGATIVE
outcomes; production top-10 beat them in 1/3 sessions and was roughly
equal in the other 2. Marginal cost ~+2h inference/session (mean run
417s) for coin-flip-quality extra picks. Verdict: expand coverage
NO — the top-10 gate is not the binding constraint.

### Selection weaknesses identified (evidence)

1. Bull-rated picks have no demonstrated edge in the only window with
   full coverage (mean excess -0.9, ~35% positive).
2. The PM rating ladder is inverted vs intuition: Overweight > Buy
   — conviction labels are not calibrated.
3. Strongest negative-outcome names shared: pre-profit story stocks
   + dissent or binary setups — but filters built on that intuition
   did not validate on the larger sample.
4. Sell ratings identify laggards only in falling weeks — not a
   short signal.
5. Operational: STALE_TA_AT_ENTRY recurs in postmortems — decisions
   were issued on analysis older than the entry session.

### Conclusion (explicit, per mission)

Evidence is INSUFFICIENT to justify a new selection policy: every
pre-registered improvement failed on the largest timestamped sample
available, and no defensible rule emerges without outcome-fitting.
The honest supported claims: (a) the production top-10 quota remains
a reasonable COST-CONSERVATIVE DEFAULT — the evidence says deeper
coverage did not add positive picks in 3 sessions, not that 10 is
economically optimal; (b) no feature preference is an established
improvement — the accel-label separation was descriptive only and the
corresponding selection rule FAILED; (c) do NOT expand to shorts or
looser entry rules on this evidence.
Next real evidence arrives with C12 maturities (10/30-11/18) and each
new weekly cycle; until n of scored bull decisions grows, selection
quality cannot be measured better than this.

### Mission 13 corrections (provenance + wording)

1. **R5B replays are RETROSPECTIVE, not contemporaneous.** Manifests
   declare `mode: HISTORICAL_REPLAY`, `EMPTY_REPLAY_MEMORY`; they were
   computed 2026-10-14/15 (git history), 1-8 days AFTER their nominal
   decision sessions. The 54 R5B analyses measure how the same pipeline
   re-judged pool members under a declared information cutoff
   (20:00Z) — counterfactual research, never prospective evidence, and
   must not be merged with the production paper book. One PIT flag
   exists: WDAY on the 10/12 replay had `max_date_seen=2026-10-13`.
   The R5B-derived numbers are therefore treated as "same-pipeline
   rerating" diagnostics, not genuine ex-ante decisions.
2. **fundamental_facts provenance is field-level, not file-level.**
   The facts files were generated by the 10/14 funnel-instrumentation
   commit — later than some decision sessions they describe. What
   makes the join usable: every metric carries its own `last_filed`
   SEC filing date, and the join picks the nearest facts file <=
   session. Verified: 797 metrics scored, **zero** `last_filed >
   decision_session` violations. So the underlying FACTS were public
   before each decision; the ARTIFACT packaging them was built later.
   Called "PIT-consistent," not casually "PIT-safe."
3. **Accel-label preference REMOVED** as a recommendation. The
   +2.8pp separation is descriptive on all analyzed names; the
   selection rule built on it (R_ACCEL) performed WORSE than baseline
   (-1.84 vs -0.91). A descriptive split is not an improvement.
4. **Top-10 quota reframed**: cost-conservative default only.
   Evidence = 3 sessions where ranks 11-28 added few bull picks at
   negative aggregate outcomes; this does not prove 10 optimal —
   only that expansion was not rewarded in this sample.
5. **H5 outcome correlations are not portfolio economics.** All
   mission13 numbers are per-name forward-return statistics at a
   fixed horizon with SPY excess — no entry costs, sizing, capacity
   constraints, or exit mechanics. They identify signal quality, not
   executable after-cost portfolio performance (which only missions
   11-12 measured, on the real paper book).

Final verdict stands: no validated profitable AI selection policy;
nothing deployable.

## Oct-27 production diagnosis + pipeline fix (this commit)

### Why 10/10 were AMBIGUOUS_REJECTED

Root cause in `synthesize.disposition()`: any validation error
containing "ambiguous"/"unsupported" mapped to AMBIGUOUS_REJECTED —
including `REANALYZE_ON_TRIGGER` intents, where model-declared
ambiguity (pending earnings/FDA, unverified catalyst) IS the
legitimate class. The ambiguity declarations are real content
contradictions inside the TA reports, not parse failures.

| Ticker | signal | model declared | corrected disposition | was it a defect? |
|---|---|---|---|---|
| AMPL | Sell | ENTRY_ZONE_CONFLICT (Q3 binary) | REANALYZE_ON_TRIGGER | mislabeled, economically justified wait |
| BRZE | Sell | sizing 5-6% vs 5-8%, catalyst, unsupported frac | AMBIGUOUS_REJECTED | genuine NO_TRADE (contradictions) |
| XNCR | Overweight | stop discrepancy 24.95 vs 25.20; LONG decision authored | AMBIGUOUS_REJECTED | genuine NO_TRADE (conflicting stops) |
| IOVA | Sell | catalyst unverified | REANALYZE_ON_TRIGGER | mislabeled |
| MRNA | Sell | sizing conflict; SHORT econ contract authored | PUBLISHED_NON_EXECUTABLE (paper-short) | mislabeled; SHORT has no production path |
| HTFL | Sell | sizing 1.25% vs 2.5%, event | AMBIGUOUS_REJECTED | genuine NO_TRADE |
| GRAL | Sell | FDA+earnings binary | REANALYZE_ON_TRIGGER | mislabeled |
| TEAM | Sell | entry zone 196-200 vs 208-210, target<=entry | AMBIGUOUS_REJECTED | genuine NO_TRADE |
| CAI | Hold | earnings binary | REANALYZE_ON_TRIGGER | mislabeled |
| NTSK | Sell | sizing conflict | AMBIGUOUS_REJECTED | genuine NO_TRADE |

Fixes in `synthesize.py`: (a) REANALYZE class ignores declared-ambiguity
errors (hard structural errors still fail closed); (b) a resolved
SHORT contract -> PUBLISHED_NON_EXECUTABLE paper-research instead of
ambiguous. In `daily_scheduler.py`: publication summary now carries
`session_health=AUTHORING_FAILED` when every output fails — a fully
failed scan can no longer masquerade as a green run.
Regression test `alpha_rnd/test_oct27_dispositions.py` replays all 10
real artifacts: 4 REANALYZE, 1 paper-short, 5 justified rejects,
plus a fabricated-number fail-closed check. All PASS.

### The 10-stock limit

`DEEP_QUOTA = clamp(ALPHA_RESEARCH_BUDGET, 1, 30)`, default 10;
the cron job does not set it. Oct-27 pool = 28 candidates ranked by
deep_score; top-10 selected. Cost model: 1 TA run/candidate,
~417s mean duration, worst-case ~$3/run.

| Quota | added runs | worst-case $/session | wallclock @4-way |
|---|---|---|---|
| 10 (current) | — | $30 | ~17min |
| 20 | +10 | $60 | ~35min |
| 30 (hard cap) | +18* | $84 | ~49min |
*pool had only 28. Tool: `python -m alpha_rnd.research_budget [pool]`
selects by the EXISTING deep_score rule — merit-ranked, not slot-fill.

Deployment (needs approval, not done): set `ALPHA_RESEARCH_BUDGET=20`
in the alpha_rnd.daily_scheduler cron line; keep the built-in
<=30 cap as the daily spending ceiling (~$84 worst case). Verify
next session: summary event should show session_health=OK and
dispositions split across REANALYZE/EXECUTABLE/NO_TRADE — zero or
few AMBIGUOUS_REJECTED; any all-failed scan emits AUTHORING_FAILED.
