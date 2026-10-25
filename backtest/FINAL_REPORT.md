
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
