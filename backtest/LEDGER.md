# Experiment ledger — research/alpha-lab

| # | Hypothesis | Data/universe | Commit | Status | Result | Verdict |
|---|---|---|---|---|---|---|
| 0 | smoke test: migrated tools work | unit tests | c57408b3 | done | 23 tests pass | baseline OK |
| 1 | 20-session exit cap beats 60d | 1,824 elig universe (survivor-biased) | e67477d8 | done | 20d: +24/+6/+5 vs 60d: +11/-8/+27 | RETAINED-H1 regime-dependent |
| 2 | mirrored retest SHORT profitable | same | e67477d8 | done | -8.7/-5.9/-6.8 all periods | REJECTED |
| 3 | deep-rank top10 > ranks11-28 | Oct pools | e67477d8 | done | top10 -3,691 vs rest -1,749 | rank not protective |
| 4 | pending | — | — | — | — | — |
| 5 | H2 SPY>20SMA entry gate improves | 1824 elig (survivor-biased) | HEAD | done | +5.8/-7.1/+33.4 vs base +11.1/-8.3/+27.0 | REJECTED (no consistent gain) |
| 6 | H3 2.5·ATR stop vs 2.0·ATR | same | HEAD | done | **+19.2/+0.9/+32.3** PF 2.27/1.05/4.23 all 3 periods vs base | RETAINED-H3 (candidate; survivor-biased) |
| 7 | H3 robustness: seeds x costs grid | 1824 elig (survivor-biased) | HEAD | done | 15bps cost: -0.3pp everywhere; seeds 2025 flip to -17.5% | RETAIN AS UNVALIDATED (see note) |
| 8 | AI-researched names beat random/mechanical controls (Oct, identical rules) | 50 researched vs 132 pool vs 5 random subsets | HEAD | done | researched -3,938 PF0.47; pool -2,187; randoms +138/-351/+122/-2,928/-4,438 | AI selection did NOT outperform; worst-quintile of random |
| 9 | S&P500 snapshot + date_added universe (NOT full PIT; removed members absent) | 503 names | HEAD | done | LONG -2.6/-5.3/+15.5; SHORT rule -7.8/-7.7/-12.2 | universe delta vs 1824 ≠ survivorship alone (different size/composition); tested SHORT RULE rejected (3 periods x 2 overlapping universes), not all shorts |
| 10 | H3 (2.5xATR) replicates on second universe (S&P500 snapshot+added-date, 503 names) | HEAD | done | ATR25>ORIG alpha all 3 periods (+1.5/-4.7/+16.7 vs -2.6/-5.3/+15.5); seed-min better 2/3 | RETAIN-VALIDATED (weak): not a survivorship artifact, but both variants lose 2025 — regime-dependent |
| 11 | TREND200 gate (fill only if close>200SMA) fixes 2025 loss regime without hurting trends | S&P500 snapshot, 503 names | HEAD | done | 2025 mean -3.6 vs -7.2 (min -6.8 vs -10.1), but 2026 mean 13.1 vs 16.9, 2024 ~flat | REJECTED — improves only the losing regime, costs winners |
| 11a | methodology: hash() seed ordering not reproducible | portfolio_sim | HEAD | fixed | md5 stable ordering; seed numbers across pre/post-fix runs not comparable | infra fix |
| 12 | SHORT_T200 gate (fill only if close<200SMA) fixes short losses | S&P500 snapshot, 503 names | HEAD | done | 2024 mean -16.0 vs -11.8 ungated; 2025/2026 ~unchanged negative | REJECTED — 3rd distinct rejection of short rule family; stop iterating |
| 13 | PROFIT exit (trim 50% +8%, trail rest -8pp) improves ATR25 economics | S&P500 snapshot, 503 names | HEAD | done | 2024 +6.8 vs +4.5; 2025 -1.7 vs -7.3; 2026 +8.6 vs +16.8 | RETAINED as defensive profile; first result had to be rerun after fixing shares-accounting + 1-share-trim bugs |
| 14 | corrections round: gate look-ahead fix + stable seeds + accounting tests | all prior | HEAD | done | 5 regression tests pass; m7 verdict holds; m8 FLIPS to RETAIN; m9 still rejected | corrected results preserved alongside originals (*_presalt/*_lookahead.json) |
| 15 | AI-authored prospective book beats naive controls? | alpha_paper_ledger, 6 fills, 10/02-10/23 | HEAD | done | AI -2.40% vs rules-only -3.15, naive-same -3.02, watchlist-naive -3.44, SPY -0.46 | AI mechanics added ~+0.6-1.0pp vs controls but underperformed SPY; selection net-negative; n=6 exploratory; zero SHORT contracts authored |
| 16 | reconciled ALPHA book + C12 first read: is AI evidence positive? | trigger_events+postmortems+C12 ledgers | HEAD | done | ALPHA -2.38% (realized -2140.99 canonical); vs naive -2.97, watchlist -3.44, SPY -0.49; C12 open: HPE -14pp excess, COP +6.6, NTAP +0.8, PLTR +0.1; C12 Sell calls 10/18 | NO profitable-selection evidence; execution mechanics +0.6-2.2pp vs naive; shorts unauthored; n=10 exploratory |
| 17 | do decision-time features/ratings separate good selections? 227 artifacts (142 ALPHA + 54 R5B + 31 C12) | HEAD | done | ACCEL label +2.8pp, rsi<70 +2.8pp (all names); bulls unrescuable (-0.9 mean); all 4 pre-registered filters failed; Sell cohort mean -3.4 but regime-flipped; coverage 10>28 wins | INSUFFICIENT evidence for a selection policy change; no manufactured profitability |
| 17a | mission13 corrections: R5B is HISTORICAL_REPLAY (retrospective); facts PIT-consistent at field level (0/797 violations); accel-preference and top-10-optimality claims removed | HEAD | done | wording/provenance only, results unchanged | corrected |
