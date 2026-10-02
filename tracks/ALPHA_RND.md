# Track: ALPHA_RND

Status: ACTIVE
Created: 2026-10-02
Worktree: `/home/udi/udi_provate/TradingAgents-alpha-rnd`
Branch: `exp/alpha-rnd-v1` (based on freshly fetched `origin/main`; all v0.5.0
behavior references use tag `v0.5.0` = `2d17df8da1536c121e4d7395ac5a5dcec9e96d6f`)

## Registration

```text
track: ALPHA_RND
status: ACTIVE
purpose: current opportunity discovery + strategy improvement
production impact: NONE until separately promoted
C12 isolation: mandatory
EXPERT_RND isolation: mandatory
```

## Objective

Continuously search for stocks/trades worth acting on now, improve the
discovery + decision + execution process, and build evidence from live/paper
results. This is an exploratory R&D track — no claim of proven alpha. C12
remains the frozen control.

## Isolation

- Do NOT modify the C12 worktree, ledger, epochs, config, or artifacts.
- Do NOT modify EXPERT_RND worktree or its prospective store.
- Do NOT touch LOCKBOX; HOLDOUT unused.
- Separate ALPHA_RND paper ledger only.

## Gate 1 — CURRENT_OPPORTUNITY_DISCOVERY (in progress)

Details populated on gate completion.

---

## Gate 1 — ALPHA_RND_V1_CURRENT_OPPORTUNITY_DISCOVERY (COMPLETE 2026-10-02)

Decision session: **2026-10-01** (latest completed U.S. session at run time).

### Universe

Raw: 4,770 tickers = Wikipedia S&P 500 (503) + S&P 400 MidCap (400) +
nasdaqtrader `nasdaqlisted.txt` non-ETF/non-test/common-name filter (2,772) +
`otherlisted.txt` NYSE/AMEX/Arca same filter (1,979).
Hygiene: >=252 sessions history, close >= $5, median 20d dollar volume >= $20M.
Eligible: **1,856**. Exclusions: fetch_failed 14, insufficient_history 296,
illiquid 1,420, price<$5 1,184. Filters not tuned on returns.

### Discovery sources (independent)

- MOMENTUM: frozen Lane-A (242 eligible) + Lane-C breakout (54).
- RELATIVE_STRENGTH: rs_60 >= 97th pctile vs SPY, rs_20>0, close>sma50 (46).
- QUALITY_PULLBACK: Lane-B pullback in uptrend (207).
- CATALYST: dated SEC 8-K/10-Q/10-K within 10 business days (EDGAR daily
  master index) AND market signature (|ret_5|>=3% or vol_ratio>=1.3) (23).
- FUNDAMENTAL_ACCELERATION: SEC companyfacts, filed<=session, last-two-quarter
  YoY acceleration in revenue/op-income/net-income/OCF (131 flagged of 160
  checked on pre-pool).

### Frozen candidate pool: 28 tickers

`evaluations/alpha_rnd_v1/candidate_pool_frozen.json` (in alpha worktree).
Balanced quotas: LaneA top-8, RS top-6, LaneB top-5, LaneC top-3, catalyst
top-8 (multi-signal then signature strength), FA-only top-4; deduped.

### Deep-analysis selection (10)

score = 10*n_distinct_labels + 2*clip(rs_60,0,2) + 1(CATALYST); top-10:
PBF APPS IOVA QMCO MRNA CDNA ACN SDGR BMNR AVTR.

### Full TA results (official v0.5.x graph, swe-2-medium quick / swe-2-high deep,
temp 0, SEC-pinned statements, flat PortfolioContext, unmodified prompts)

| ticker | RM | Trader | PM | class |
|---|---|---|---|---|
| PBF | Overweight | Buy | Overweight | WATCH_FOR_ENTRY 78-80 |
| ACN | Overweight | Buy | Overweight | WATCH_FOR_ENTRY 203-205 |
| APPS | Hold | Hold | Hold | WATCH_FOR_ENTRY 11.0-11.3 |
| IOVA | Underweight | Sell | Sell | WATCH_FOR_ENTRY 12.20-13.00 |
| CDNA | Underweight | Sell | Sell | WATCH_FOR_ENTRY 60-62 |
| SDGR | Underweight | Sell | Sell | WATCH_FOR_ENTRY (see ledger) |
| QMCO | Sell | Sell | Sell | REJECT |
| MRNA | Underweight | Sell | Sell | REJECT |
| BMNR | Underweight | Sell | Sell | REJECT |
| AVTR | Underweight | Sell | Sell | REJECT |

ACTIONABLE_NOW: **0** (no PM Buy/Overweight with unconditional entry).

### Paper book

`alpha_paper_ledger.jsonl`: $100k, $5k/position, max 10. Zero proposed orders
this gate; six frozen watch triggers recorded. No fills.

### Hypotheses generated (Part 9)

- H1 continuation-as-overextension: all 6 pure momentum/RS leaders rejected on
  extension metrics; IOVA/CDNA explicitly "good fundamentals, bad entry".
- H2 staging-cost: PBF/ACN Overweight but conditional entries — if price runs,
  trigger never fills; opportunity cost unmeasured.
- H3 evidence-vacuum-as-negative: BMNR (NAV unverifiable), SDGR (retail-channel
  catalysts), CDNA (withheld Form 4) penalized for missing evidence.
- H4 FA-flag base distortion: QMCO acceleration flag mechanical on negative
  equity — filter quality issue, not TA error.
- H5 PM-correct-protection: MRNA/AVTR/QMCO bear cases rest on verifiable
  fundamentals; rejection likely correct.

### Exact next action

Monitor the six frozen watch triggers session-by-session; if a zone fills,
record paper entry at that session's fill price. Experiment E1: shadow
counterfactual — mark-to-market "buy at 2026-10-02 open" for PBF+ACN vs the
staged trigger path to measure whether entry discipline adds or costs.
