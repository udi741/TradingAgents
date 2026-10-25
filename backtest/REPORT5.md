# Mechanical backtest validation + AI-vs-mechanical comparison

Reproduce: `python3 backtest/mechanics_multiyear.py && python3 backtest/portfolio_sim.py`.
Outputs: `results/mechanics_multiyear.json`, `results/portfolio_sim.json`.

## Part 1 — Portfolio-constrained re-run (validation of prior +$163K/+34K/+149K)

Constraints now enforced: $100k cash, ≤$5k/position, ≤10 simultaneous,
no leverage, entries skipped when cash/slots full (chronological, ticker
tie-break), exits before entries same day, daily NAV marking, exits clipped
to period end (fixed: earlier NAV let positions run past period end).

| Period | Variant | Signals | Admitted | Rejected | Net P&L (trades) | End NAV | Max DD | Max employed | PF | Exp/trade |
|---|---|---|---|---|---|---|---|---|---|---|
| 2024 | ORIG | 168 | 56 | 112 slots | +112,061 | +142%* | 74.3k | 49.9k | 8.8 | +2,782 |
| 2024 | GAPFILT | 154 | 65 | 89 | +84,121 | +119%* | 73.2k | 49.9k | 6.2 | +2,105 |
| 2024 | PROFIT | 215 | 145 | 70 | +67,549 | +167%* | 2.7k | 32.3k | 3.6 | +468 |
| 2024 | SHORT | 138 | 56 | 82 | -2,285 | -8.3% | 17.2k | 49.9k | 1.31 | +106 |
| 2025 | ORIG | 168 | 62 | 106 | +12,374 | +14.8% | 13.5k | 49.9k | 1.61 | +222 |
| 2025 | GAPFILT | 162 | 65 | 97 | +5,749 | +1.8% | 11.6k | 49.9k | 1.04 | +20 |
| 2025 | PROFIT | 207 | 129 | 78 | +40,849 | +152%* | 2.9k | 30.1k | 3.0 | +317 |
| 2025 | SHORT | 162 | 60 | 102 | +3,771 | -3.2% | 21.9k | 49.7k | 1.33 | +114 |
| 2026YTD | ORIG | 167 | 48 | 119 | +39,480 | +39.5% | 7.8k | 49.7k | 4.04 | +823 |
| 2026YTD | GAPFILT | 156 | 50 | 106 | +26,521 | +26.5% | 7.3k | 49.8k | 2.46 | +530 |
| 2026YTD | PROFIT | 226 | 126 | 100 | +45,033 | +147%* | 2.2k | 37.4k | 3.33 | +357 |
| 2026YTD | SHORT | 96 | 44 | 52 | -4,796 | -4.6% | 18.3k | 49.9k | 0.75 | -109 |

SPY: 2024 +24.9%, 2025 +17.7%, 2026YTD +13.4%.
*NAV vs trade-level net differ where period-end open marks exceed realized
legs; treat NAV as marked book and net P&L as the conservative number.
PROFIT admits ~2x more trades because trims free slots/cash — variants are
not perfectly capital-matched; direction of the difference stands.

**Differences from prior report:** earlier numbers summed *all* candidate
trades assuming unlimited parallel capacity (168 signals → 168 trades).
With a 10-slot cap, ~2/3 of signals are rejected; realized dollars are
smaller and capital is recycled. Direction unchanged: LONG profitable all
three periods, SHORT not; GAPFILT still below ORIG in every period.

**Look-ahead check:** 60d highs/lows and ATR use only prior bars
(`rolling().iloc[i-1]`); signals armed on close, fills occur on later bars'
lows — no future data. auto_adjust=True used; dividends/splits consistent
(close≈adjusted for these names; ACN $1.71 div post-exit unaffected).

**Survivorship / universe contamination — quantified:** the 75-ticker
universe is the set the Oct-2026 screener selected; equal-weight buy&hold
returns: **+68.3% (2024) vs SPY +24.9%**, +21.7% vs +17.7% (2025),
+78.8% vs +13.4% (2026YTD). The universe outperformed the index by ~2-6x —
it is contaminated with hindsight winners. Mechanical results must be
discounted accordingly; they show machinery viability, not deployable edge.

## Part 2 — AI selection vs mechanical selection (October, same pools)

Same window (10-01..23), same pool universe, identical costs/rules:

| Group | n trades | Net P&L |
|---|---|---|
| AI-positive (Buy/Overweight) ∩ mechanical retest filled | 7 | **+6,165** (6/7 winners) |
| AI-negative (Sell/Underweight) ∩ mechanical retest filled | 20 | **-4,274** |
| Mechanical fill, no AI opinion | 28 | +2,026 |
| AI-positive but no mechanical fill | ACN, ANF, HAS, PGEN | 0 (untriggered) |

Reading: AI-positive ratings were *directionally* discriminating —
mechanical entries on AI-positive names won (+6.2k), on AI-negative names
lost (-4.3k). But the AI's *authored* zones executed differently and lost
(-2.4k actual). Hypothetical label: the mechanical fills are not the
trades the AI authorized. Sample sizes are tiny (7/20/28); treat as
suggestive, not conclusive.

## Part 3 — Position-management findings (read-only)

- **PBF prose rule:** "close inside $70-77 base exits entirely" is a band,
  not encodable as a single typed `close_below`; only the "close <78 → cut
  to minimal" leg is typeable. Typed stop 74.5 never hit; the 78 close
  crossed 10-23 with no mechanical action. The queued PARTIAL_EXIT
  (31 shares, enqueued 10-22) status is **MISSED_OR_CONSUMED_UNKNOWN** —
  never filled.
- **PGEN:** missed hard stop was isolated; the framework self-corrected via
  INTEGRITY_CORRECTIVE_EXIT at 7.79 (above stop). No residual defect shown.
- **C12:** no stops by protocol design — weekly scheduled exits only. That's
  a policy gap, not a bug: HPE -15.2% rode unprotected.

## Answers

1. **Yes**, mechanical LONG remains profitable with full portfolio
   constraints (+112k/+12k/+39k trade P&L) — but see #2.
2. **Large.** Universe contamination is measurable: the selected names beat
   SPY by ~43pp (2024), ~4pp (2025), ~65pp (2026YTD) on buy&hold alone.
   Realizable edge is materially less than headline numbers.
3. **Cannot yet be evaluated fairly.** October evidence suggests AI-positive
   ratings carried signal (its positive names won mechanically; its
   negative names lost), while the AI's authored entry prices were worse
   than a naive retest. n is far too small for a verdict.
4. **Next step:** run the deterministic screen + mechanical retest entry
   forward on paper alongside the AI track (same watch pipeline, parallel
   book) — a clean, zero-inference A/B that directly tests whether AI
   entry authoring adds value over its own screener's mechanics.
