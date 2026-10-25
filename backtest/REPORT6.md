# Broad-universe mechanical LONG + admission-order sensitivity

## Universe & provenance
- Universe: 1,823 tickers from `candidate_pool_frozen_2026-10-23.json`
  `eligible_features` (≥252d history, ≥$5, ≥$20M median dv20 at Oct-2026),
  re-gated per entry date by the same rules (`elig_mask` in universe_pt.py).
- Residual bias: names must have existed through Oct-2026 — no delisted
  stocks (paid delisting data would be needed; disclosed dependency).
- Cache: `backtest/results/eligible_bars.pkl` (67MB, NOT committed);
  md5 `b25fe6abe3c115e65670ba2eedc01c79`; regenerate with
  `python3 backtest/universe_pt.py` (re-downloads yfinance bars 2023-01→2026-09).

## Completed run (backtest/results/universe_pt.json), $100k/$5k/10-slot

| Period | Signals | Admitted | Rejected | Net P&L | End NAV | Max DD | PF | SPY |
|---|---|---|---|---|---|---|---|---|
| 2024 | 3,684 | 80 | ~98% | +6,220 | +5.8% | 10.7k | 1.33 | +25.6% |
| 2024 GAPFILT | 3,472 | 84 | ~98% | +9,628 | +9.6% | 5.6k | 1.41 | +25.6% |
| 2025 | 3,605 | 74 | ~98% | +11,583 | +10.7% | 15.5k | 1.54 | +18.0% |
| 2025 GAPFILT | 3,353 | 80 | ~98% | -17,638 | -18.0% | 20.2k | 0.40 | +18.0% |
| 2026YTD | 3,437 | 66 | ~98% | +20,891 | +20.9% | 8.4k | 2.38 | +13.2% |
| 2026YTD GAPFILT | 3,216 | 60 | ~98% | +12,325 | +12.4% | 8.4k | 1.93 | +13.2% |

NAV reconciliation: `end_nav - start` ≈ trade P&L + open marks at period
end + cash effects; NAV% reported is marked-book; net_pnl is the
conservative realized+period-mark figure. Matched-exposure vs SPY: max
capital employed ≈ $49.7k (≈50% of NAV), so the matched-exposure SPY
return is roughly half the full-investment figure — the strategy still
lags SPY in 2024/2025 and leads modestly in 2026YTD.

## Signal admission (Task 3)
- Same-day competing entries admitted **alphabetically by ticker** — a
  fixed arbitrary ordering using zero future information.
- Rejections split: `dup_ticker` (same ticker already held) vs `no_slot`
  (10 positions full). ~98% of signals rejected — most are dup/slot
  competition, not disqualification.
- Fixed-seed sensitivity (seeds 1,7,13,42,99): `admission_sensitivity.py`
  reran identical rules/caps/costs; results in
  `results/admission_sensitivity.json`.

## Verdict
- Broad-universe LONG is modestly positive but NOT robustly attractive:
  +5.8/+10.7/+20.9% vs SPY +25.6/+18.0/+13.2% — lags in two of three
  periods on matched exposure. The 75-name universe was most of the story.
- Gap filter remains unreliable (great 2024, terrible 2025).
- AI-ratings-as-priority test remains the sensible next experiment:
  run the mechanical strategy forward on paper where admission order is
  prioritized by the live AI rating — tests whether AI ranking adds value
  to entry selection, without claiming it is profitable.

## Admission-order sensitivity — final results

Setup verified: five shuffled runs reused the identical candidate set from
`sim_period` (same signals, fills, stops, costs, $100k/$5k/10-slot caps,
dates); only the same-day admission order changed (deterministic
hash-shuffle on fixed seeds 1/7/13/42/99). No future information in either
ordering.

| Period | Alphabetical | Seeds (1,7,13,42,99) | Median | Range |
|---|---|---|---|---|
| 2024 | +5.83% | +17.8, +0.9, +8.4, +8.2, +12.7 | **+8.43%** | +0.9 → +17.8 |
| 2025 | +10.68% | +1.5, +0.5, -7.5, -7.4, +0.3 | **+0.29%** | -7.5 → +1.5 |
| 2026YTD | +20.94% | +18.7, +25.3, +15.8, +21.4, +9.0 | **+18.70%** | +9.0 → +25.3 |

All rejections were `no_slot` (capacity), not `dup_ticker` — a held
ticker's watch is consumed on fill, so ~98% rejection = pure
capital-capacity competition.

**2025 alphabetical advantage is luck, not signal.** Alphabetical order
picked a favorable subset (+10.7%); every shuffled ordering landed between
-7.5% and +1.5% (median +0.3%). With ~70-80 admitted of ~3,600 signals,
which trades fill the 10 slots is close to a lottery: per-period outcomes
swing by ±10-17pp on ordering alone.

**Robustness verdict:** the mechanical LONG is NOT robust to admission
ordering. Ordering alone shifts results by ~17pp (2024), ~9pp (2025),
~16pp (2026YTD). Median-seed performance vs SPY: +8.4 vs +25.6 (2024),
+0.3 vs +18.0 (2025), +18.7 vs +13.2 (2026YTD) — attractive only in
2026YTD. No deployable edge survives unbiased universe + arbitrary
admission.

**Recommended next experiment:** prospective paper run of this exact
strategy with AI ratings used ONLY to prioritize same-day admissions
(highest-rated first). Everything else identical. Tests whether AI ranking
has informational value for selection — the one lever the sensitivity shows
actually matters — with zero inference cost and no hindsight.
