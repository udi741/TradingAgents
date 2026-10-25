# AI ratings as admission priority — smoke test + shadow design

Reproduce: `python3 backtest/ai_priority_test.py` →
`results/ai_priority.json`.

## Setup (frozen rules)

- Universe: per-session frozen candidate pools — the ~10 names actually
  researched each session (132 unique across 15 sessions). Ratings apply
  only to researched names — the 1,824-stock universe is untouched.
- Candidates: identical mechanical retest signals (60d-high close → zone
  fill at high*0.97, 2·ATR stop, close_below→next open, 60-session cap,
  10bps/side, $5k/$100k/10-slot).
- Ratings: latest published rating per ticker as of the fill date only
  (`rating_at` uses pub_date ≤ fill_date — no look-ahead).
  Rank: Buy > Overweight > Neutral > Underweight > Sell; unrated last.
- Sell/Underweight never became entries; LONG mechanics only.

## Historical smoke test (Oct 1–23, 2026)

- 55 mechanical candidate fills across **16 days; 15 days were contested**
  (multiple candidates competing for slots) — a genuine ranking contest
  exists; the experiment is not vacuous.
- Outcomes (18 admitted trades each variant):

| Priority | NAV% | P&L | PF |
|---|---|---|---|
| Alphabetical (mechanical) | +2.40% | +2,384 | 1.53 |
| **AI rating rank** | **+2.54%** | +2,525 | 1.54 |
| Shuffle seed 1 | +0.23% | +210 | 1.04 |
| Shuffle seed 7 | +3.38% | +3,363 | 1.82 |

- AI-priority marginally beat alphabetical and seed 1, lost to seed 7 —
  **inside noise; underpowered at n=18 trades in one 16-day window.** No
  edge demonstrated; no negative evidence either. One month can never
  answer this question — the answer must be prospective.

## Prospective shadow design (zero additional inference)

Frozen before observing future outcomes:

- On each production session date, take that day's frozen candidate pool
  (already published — no change to screener or quota).
- For each pool ticker, arm the existing mechanical retest watch
  (60d-high close → 0.97·high zone → fill at zone top, 2·ATR stop,
  close_below → next open, 60-session cap, 10bps/side).
- Maintain THREE paper sub-books of $100k each, identical rules, differing
  only in same-day admission order: (a) alphabetical, (b) AI rating rank
  using the rating as of that fill date, (c) a fixed-seed shuffle
  (seed fixed today, e.g. 42).
- Storage: separate JSONL under `evaluations/shadow/` — NOT the live
  watchlist, paper ledger, or positions. No orders. No cron change: the
  shadow engine can run inside the existing nightly research job or a
  separate daily script reading published intents + bars.
- PBF/C12/quota untouched; no SHORTs; no new exit rules.
- Readout after ~8–12 weeks (~40 contested days est.): per-book NAV, PF,
  and — the actual question — rank correlation between AI rating and
  per-trade return on contested days only.

## Verdict

- A meaningful ranking contest does occur in the AI-covered subset
  (15/16 days contested). The comparison is feasible.
- October alone is underpowered; results (±3pp between priorities) are
  consistent with luck.
- **Worth activating prospectively** — it's cheap, uses ratings the
  scheduler already publishes, and measures the exact lever the
  sensitivity analysis identified (admission ordering).
