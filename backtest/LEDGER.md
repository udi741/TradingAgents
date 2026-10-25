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
