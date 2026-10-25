
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
