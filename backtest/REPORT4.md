# Part A — Actual position-management audit (recorded trades)

| Position | Recorded risk rule | What happened | Diagnosis |
|---|---|---|---|
| PBF 62@80 | prose: "close<78 = failed breakout, cut to minimal"; typed stop 74.5 intraday; horizon time-box Oct 16 | close 10-23 = 76.17 (<78) — prose rule demanded action; only the typed 74.5 rule existed mechanically (low never hit). Mgmt PARTIAL_EXIT queued 10-22 → status MISSED_OR_CONSUMED_UNKNOWN | protection gap: prose invalidation never compiled to a rule; mgmt exit missed |
| ACN 24@205 | close_below 194 | fired 10-06, exited 10-07 open 195.23 | rules executed correctly; bad decision |
| APPS 442@11.30 | hard stop 10.42 | gapped through, exited at open 10.302 | execution correct; gap loss exceeded stop geometry |
| PGEN 609@8.20 | hard stop 7.75 | stop MISSED, then INTEGRITY_CORRECTIVE_EXIT at 7.79 | execution miss, self-corrected (exit above stop) |
| SDGR 161@31 | breakout watch; risk via mgmt reviews | mgmt Underweight review sold 100@27.81; tightened stop → 61@25.69 | mgmt layer worked; bad decision (bought a Sell-rated name) |
| TWST 11@209.55 | breakout watch; mgmt exits | sold 4@158.26 + 7@159.74 via mgmt | mgmt layer worked; bad decision |
| HPE/NTAP/PLTR (C12) | **none exist — C12 protocol is entry + scheduled-exit only** | all open; HPE -15.2% | missing protection by design |

Verdict on Part A: the losses are dominated by **decision quality** (entries
into post-event names), secondarily by **protection gaps** (PBF prose-vs-typed
rule, PGEN missed stop, C12 no stops at all). Mechanical exits that existed
mostly executed correctly.

# Part B — Multi-year mechanics experiment (NOT AI performance)

`backtest/mechanics_multiyear.py`. Faithful candidate-selection replay is
impossible (the screener + AI authored the zones/stops historically). So the
entry signal is a FIXED deterministic proxy matching the recorded pattern:
LONG = retest of a fresh 60-day high (fill at high*0.97, the recorded
zone-top convention), stop = fill − 2·ATR14, close_below → next open,
60-session cap. SHORT = mirrored retest of a fresh 60-day low.
Universe = the 75 tickers the system analyzed Oct-2026 (survivorship caveat).

Frozen variants: ORIG / GAPFILT (the Oct-proposed ≥8%-move-or-SPY<20SMA
filter) / PROFIT (trim 50% @+8%, trail peak−8pp) / SHORT_ORIG.

Results ($5k per trade, 10bps/side, 2%/yr short borrow):

| Period | Variant | n | win% | net P&L | exp/trade | PF | max DD |
|---|---|---|---|---|---|---|---|
| 2024 | ORIG | 168 | 36.9 | +163,382 | +972 | 3.68 | 9.8k |
| 2024 | GAPFILT | 154 | 29.2 | +77,602 | +504 | 2.16 | 22.9k |
| 2024 | PROFIT | 215 | 61.9 | +71,074 | +331 | 2.62 | 5.6k |
| 2024 | SHORT | 138 | 35.5 | -12,006 | -87 | 0.78 | 20.7k |
| 2025 | ORIG | 168 | 32.1 | +34,364 | +205 | 1.48 | 13.0k |
| 2025 | GAPFILT | 162 | 27.8 | -2,027 | -13 | 0.97 | 18.7k |
| 2025 | PROFIT | 207 | 63.8 | +43,463 | +210 | 2.08 | 4.2k |
| 2025 | SHORT | 162 | 36.4 | -3,794 | -23 | 0.95 | 32.5k |
| 2026YTD | ORIG | 167 | 56.3 | +148,749 | +891 | 4.15 | 3.7k |
| 2026YTD | GAPFILT | 156 | 46.8 | +75,866 | +486 | 2.29 | 6.6k |
| 2026YTD | PROFIT | 226 | 72.6 | +87,838 | +389 | 3.61 | 3.5k |
| 2026YTD | SHORT | 96 | 32.3 | -15,851 | -165 | 0.65 | 29.8k |

## Findings

1. **Loss cause (recorded book):** decision quality — entries into
   event/volatility names in a drawdown week — plus protection gaps
   (PBF prose rule, C12 no-stop design). The *mechanics* are not the
   problem: the same fill/stop/exit machinery on a fixed retest signal is
   profitable in all three untouched periods.
2. **The gap filter FAILS outside its inspiring sample.** In all three
   untouched periods it reduces net P&L by ~50% (2024: 163k→78k;
   2025: 34k→-2k; 2026: 149k→76k). October's +2,364 improvement was
   sample-specific. Do not deploy it.
3. **Profit protection** raises win rate dramatically (62-73%) but trades
   expectancy away in trending periods (2024: 972→331/trade). Net effect:
   mixed, mildly negative vs ORIG. Worth keeping only as a "protect open
   profit" tool for held winners (the PBF failure mode), not as an
   expectancy booster.
4. **SHORT mechanics lose in every regime** (PF 0.65-0.95, negative
   expectancy). No support for short trading.
5. Robustness caveats: universe is hindsight-selected (Oct-2026 analyzed
   names that survived to be screened → long-bias survivorship);
   zone-top fills on gap days flatter entries; daily bars only.

# Part C — What is supported for prospective testing

- These results test **mechanics only** — no AI decision was replayed for
  the multi-year periods (none exist).
- Supported takeaway: the framework's execution machinery is viable; the
  losing component is entry selection. A prospective paper test of
  "stricter entry gating" is justified — but the specific gap filter as
  frozen is NOT supported (it loses out-of-sample). If anything, the
  mechanics result favors *more selective* constructive-setup entries
  (retest-after-high type) rather than blanket dip-buying — exactly the
  distinction the AI was supposed to make but didn't.
- Worth carrying to prospective test: (a) per-position mechanical floor —
  every position must carry a typed stop (C12 lacks any); (b) compile
  prose invalidations into typed rules (the PBF gap); (c) a *max-holding
  review* discipline. Not supported: short trading, the gap filter,
  mandatory profit-trimming.
