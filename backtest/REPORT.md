# Historical LONG/SHORT Backtest — TradingAgents decisions Oct 2026

Reproduce: `python3 backtest/historical_backtest.py` (worktree `TradingAgents-backtest`,
branch `backtest/historical-trades`). Reads recorded artifacts read-only from
`../TradingAgents/evaluations/alpha_rnd_v1/`; prices via yfinance daily bars
(auto_adjust). No model calls. Machine output: `backtest/results/backtest_results.json`.

## Universe

- 16 production decision sessions 2026-10-01 → 2026-10-23 (`publication_intents_*.json`)
- 4 R5B replay publications (10-07/09/12 ANALYZE_ALL_CANDIDATES, 10-13 CURRENT_PRODUCTION)
- 225 recorded intent rows; signals joined from case_artifacts.

## Intent inventory (framework disposition)

| Status | Count | Meaning |
|---|---|---|
| AUTHORIZED (EXECUTABLE_WATCH, replay only) | 6 | entry_gate pass under CURRENT semantics |
| AUTH_INTENT_GATE_BLOCKED | 22 | auto_execution_authorized intent, but no EXECUTABLE_WATCH disposition -> not enterable today |
| SHORT_DESCRIPTIVE_ONLY | 29 | bearish plan; econ_contract: never executable |
| REANALYZE_ONLY | 43 | watch produces reanalysis request only |
| REJECTED_AMBIGUOUS | 70 | publication validator rejected |
| WATCH_NON_EXECUTABLE | 53 | watch with no authorized entry path |
| RESEARCH_ONLY | 2 | narrative only |

Production runs emitted **zero** EXECUTABLE_WATCH dispositions — under the
current framework, every production session authorized nothing. The 8
EXECUTABLE_WATCH names exist only in R5B replay publications (AMPL, PCVX,
KOD, TWST, P, UMAC, HESM, ETON); PCVX and HESM carry short-geometry plans —
granting them EXECUTABLE_WATCH contradicts `econ_contract` (SHORT contracts
are descriptive-only). Framework defect worth noting.

## Track A — actual recorded paper trades (prospective ledger, verified)

From `alpha_paper_ledger.jsonl` + `trigger_events.jsonl` (188 duplicate exit
events from the 10-07 incident excluded). Fills: zone-top limit, 10 bps/side.

| Ticker | Entry | Exit | Shares | Reason | P&L |
|---|---|---|---|---|---|
| PBF | 10-02 @80.00 | open (mark 76.17, 10-23) | 62 | intraday stop 74.50 never hit | -237.46 u. |
| ACN | 10-02 @205.00 | 10-07 @195.23 | 24 | close<194 -> next open | -244.09 |
| APPS | 10-02 @11.30 | 10-07 @10.302 | 442 | gap-through open < stop 10.42 | -450.66 |
| PGEN | 10-05 @8.20 | 10-06 @7.79 | 609 | corrective exit after missed stop | -259.43 |
| SDGR | 10-06 @31.00 | 10-07 @27.81 (100) + 10-13 @25.69 (61) | 161 | mgmt review Underweight exits | -652.3 |
| TWST | 10-06 @209.55 | 10-07 @158.26 (4) + 10-12 @159.74 (7) | 11 | mgmt review exits | -557.9 |

- Realized P&L: **-2,164.5**; open unrealized: **-237.5**; NAV 97,621.55 → **-2.38%**
- Closed-name win rate: **0/5**. Max drawdown ≈ -2.4% (end-point NAV).
- Benchmark SPY same window: **-0.53%** → underperformance ≈ -1.9 pp.
- Note: PBF reached +15.6% MFE (92.46 on 10-13); no mechanical profit target
  exists — appreciation only produces a model-driven mgmt review. Gains
  round-tripped.

## Track B — replay of recorded intents under current framework semantics

Entry: zone-top fill when Low <= zone top (production convention; flagged);
confirmation triggers fill next session open. Exits: intraday_stop (gap-through
at open, else at level) / close_below (next open). Watch wait <= 20 sessions,
expiry 2026-10-30. No mechanical targets. Costs 10 bps/side; shorts +2%/yr
borrow assumption (borrow availability unknown).

### Strict (EXECUTABLE_WATCH only) — what the CURRENT strategy can legally trade

| Trade | Dir | Entry | Exit | P&L |
|---|---|---|---|---|
| KOD 10-09 | LONG | 10-14 @91.00 | 10-15 @81.30 close_below | -533.10 |
| TWST 10-09 | LONG | 10-14 @145.00 | 10-16 @143.88 close_below | -47.90 |
| P 10-12 | LONG | 10-14 @145.00 | 10-19 @129.20 close_below | -546.52 |
| AMPL, UMAC, ETON | — | — | untriggered (zones never reached) | 0 |

3 filled / 3 closed / 0 open. Win rate 0%. Gross = net **-1,127.52**,
expectancy -375.8, PF 0.0.

### Gate-blocked authorized intents (AI wanted; gate refused) — counterfactual

9 fills: ACN -92.2, PGEN -129.5, PBF open -123.6, SDGR(long) open -413.5,
XP open -36.6, HAE open +3.6, MGNI -118.9, PENG -833.9, SEZL open +92.4.
Gross = **-1,652.05**, win rate 22% (open marks), PF 0.05.
**The gate prevented further losses, not profits.**

### Bearish-signal-as-SHORT experiment (clearly hypothetical, NOT strategy trades)

7 simulated: IOVA -294.1, SDGR +204.4, CDNA -35.6, ABCL -149.8,
PCVX +132.3, TWST +369.7, WDAY -8.7. Gross +218.2, win rate 43%, PF 1.45 —
but this is an invented execution path the framework explicitly refuses;
borrow availability unknown; do not read as strategy evidence.

## Missing / flagged inputs

- Intraday bar ordering unknown → conservative same-bar stop assumption; zone
  fills at zone top even on gap-through days (production convention) mildly
  favors entries.
- No mechanical profit target in the framework — all profit-taking requires
  the model-driven mgmt layer (excluded: zero-inference constraint).
- Borrow availability/costs unknown for shorts.
- Daily bars only; intraday stop precision limited.

## Contamination assessment

- Production intents/ledger: recorded forward, provenance-audited — clean.
- R5B replay intents: PIT-bounded inputs but generated by a model that may
  know later events — treated as replay evidence, not verified alpha.

## Verdict

**No credible evidence of profitable LONG or SHORT trading.** Every executed
path — actual ledger (-2.38%), strict authorized replay (-1,127.52), and the
gate-blocked counterfactual (-1,652.05) — lost money, with 0% win rate on
framework-authorized trades. The only positive cell is the hypothetical short
experiment, which the framework cannot execute.

Three main loss drivers:
1. Entries into event/earnings gaps during the Oct-14 risk-off week — buy-the-dip
   zones became falling-knife fills (KOD -10.7%, PENG -16.6%, P -10.9%).
2. No mechanical profit-taking — PBF +15.6% MFE round-tripped to -4.8%.
3. Overnight gap-throughs defeated stop geometry (PENG 74→61.69, APPS actual
   11.30→10.30), so realized losses exceeded intended risk.

First behavior to investigate: **entry gating vs. event-gap regimes** — the
pipeline repeatedly authorizes staged pullback buys into post-catalyst names
the same week the tape is repricing risk; a simple "no entry within N sessions
of a >X% gap or during market drawdown" filter would have blocked every
losing cohort while costing none of the wins.
