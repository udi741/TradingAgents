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

### Gate-1 addendum — first post-freeze session (2026-10-02)

- 3 of 6 watch triggers filled at frozen zone limits: PBF @80.00 (62sh),
  ACN @205.00 (24sh), APPS @11.30 (442sh; PM Hold — zone entry was the
  PM-authorized path: half-position only on pullback into 11.0-11.3).
- Untriggered: IOVA (low 13.95 vs 12.20-13.00), CDNA (low 65.88 vs 60-62),
  SDGR (no close>32.45, pullback zone not reached).
- Open positions mark @ 2026-10-02 close: PBF +$48.36, ACN -$146.40,
  APPS -$57.46. NAV $99,844.50; cash $85,125.40.
- E1 shadow read (one session): buying at the open cost -0.7% (PBF) and
  -5.7% (ACN); staged trigger fills gave +1.0% and -3.0%. Discipline
  delta so far: +1.66% (PBF), +2.70% (ACN) — entry staging ahead on both.
- Invalidations: ACN close 198.90 still above 194 hard exit; all positions
  remain open. Next mark at next completed session.

---

## V1 PAPER-BOOK PROTOCOL (frozen 2026-10-03)

### Provenance audit result

Market-data blindness verified in code: `yahoo/snapshot.py::_verified_rows`
filters `Date <= as_of_date` with `fill_gaps=False`; propagate decision_session
= 2026-10-01; SEC facts filed<=session. Artifact content is blind to Oct-2
prices. Wall-clock: pool frozen 13:18Z (pre-open); ACN artifact 13:27Z
(pre-open); PBF 13:35Z / APPS 13:41Z (minutes post-open but data-blind);
artifacts committed `307fc24b` 14:33Z; fills recorded 2026-10-03 post-close
from frozen rules.

- PBF: VALID_PROSPECTIVE_FILL @80.00
- ACN: VALID_PROSPECTIVE_FILL @205.00
- APPS: VALID_PROSPECTIVE_FILL @11.30 — **APPS-A EXPLICIT_CONDITIONAL_ENTRY**:
  PM text "Deploy a half-position ... only on a pullback into the $11.0–$11.3
  zone ... with a hard stop below $10.42" explicitly authorizes the zone entry.
  Sizing divergence noted ($5k standard vs PM ~2% risk).

### E1 provenance

E1 shadow rule ("buy at 2026-10-02 open") first frozen in commit `60de5909` at
14:33Z Oct-2 — AFTER the open. Oct-2 open marks are
`RETROSPECTIVE_SHADOW_DIAGNOSTIC` — not prospective evidence. E1 remains frozen
prospectively for future pairs. E1 STATUS = ACCUMULATING (needs ≥10 pairs,
each ≥20 sessions matured).

### Frozen exit policy

- A: execute explicit frozen TA invalidation verbatim (PBF close<78/stop 74.50;
  ACN close<194; APPS stop<10.42).
- B: no explicit invalidation → no invented stop; hold to horizon.
- C: max horizon = 60 trading sessions from fill (~2026-12-30); 20-session
  secondary marks. No discretionary profit-taking in V1.

### Watch policy

max_wait = 20 trading sessions from recommendation freeze (2026-10-02) →
expiry 2026-10-30; zones never trail; untriggered = WATCH_EXPIRED_NO_ENTRY.
Active watches: IOVA (12.20–13.00 or wkly close>15.30), CDNA (60–62 declining
vol), SDGR (close>32.45→retest 30–31 or orderly 24–26).

### Metrics

Per position: abs ret, ret vs SPY, 5/20/60-session marks, MFE, MAE,
invalidation hit, days held. Portfolio: NAV, cash, invested, realized,
unrealized, maxDD, SPY comparison. No strategy conclusions from daily moves.

### Current authoritative book (post-audit)

3 valid prospective fills; NAV $99,844.50 @ 2026-10-02 close; cash $85,125.40;
invested $14,874.60; unrealized −$155.50. Next action: mark at each completed
session; check watch zones and invalidations; no new inference.

### Intraday fill-timing audit (2026-10-03)

1-minute evidence (`intraday_trigger_evidence.json`): rule must exist before
market first satisfied it. PBF: frozen ~13:35Z, first zone touch 14:02Z →
VALID. APPS: frozen ~13:41Z, first touch 17:26Z → VALID. ACN: frozen 13:27Z
pre-open, first touch 13:52Z → VALID (resting order could have existed at
open). All three fills confirmed VALID_PROSPECTIVE_FILL. Book unchanged.

---

## Gate 2 — ALPHA_RND_V2_CURRENT_OPPORTUNITY_DISCOVERY (COMPLETE 2026-10-03)

Session: **2026-10-02**. Universe 4,767 raw / 1,865 eligible (same frozen
hygiene). Fresh pool: 28 names; EXISTING_BOOK_CONFIRMATION: IOVA, CDNA, SDGR,
ACN (screened high again — reported, not re-decided). PRIOR_CYCLE_ANALYZED:
QMCO, MRNA. New candidates: 22.

Deep-10 (same frozen score rule): PGEN SYNA ASST KOD TXG TWST PAYC XNCR AXGN
HHH — artifacts in `case_artifacts/*_2026-10-02.json`.

Results: PGEN PM=**Buy** but staged limit zone 8.00-8.20 below price →
WATCH_FOR_ENTRY. All 9 Sells published explicit conditional re-entry triggers →
WATCH_FOR_ENTRY each. ACTIONABLE_NOW: 0. REJECT: 0 (no name was left
thesis-free AND trigger-free). No new orders; no fills. Watch expiry
2026-10-30; zones frozen before future price observation.

Book unchanged: PBF/ACN/APPS open under frozen rules; V1 watches IOVA/CDNA/SDGR
untriggered, expiry 2026-10-30. NAV $99,844.50; cash $85,125.40; 7 open slots.

Next action: session marking; monitor 13 active watch triggers; fill only on
triggers occurring after freeze; E1 ACCUMULATING.

### Holding-horizon audit (extraction only, 2026-10-03)

All 16 frozen artifacts carry explicit horizon language — see ledger
HOLDING_HORIZON_AUDIT record. Key distinction: EXPECTED_HOLDING_PERIOD is the
TA-published intent (mostly 1-3 months / event-driven); RESEARCH_EVALUATION_
HORIZON stays 60 sessions for measurement — they are different quantities.

Protocol addition (reporting layer only, no prompt change): every future
full-TA artifact MUST be reported with trade_style, expected_hold,
thesis_realization_window, reevaluation_event, invalidation, target —
`NOT_STATED` when absent.

### Horizon policy alignment (2026-10-03)

Conflict found: ACN's frozen 6–12mo intended hold vs the universal 60-session
max. Corrected: 60 sessions = standardized RESEARCH measurement point only.
Exits follow frozen exit hierarchy (invalidation > event > time-box > target >
reevaluation — never auto-sell). PBF: tactical, reevaluate at ~Oct-16 time-box.
ACN: medium-term, 60s = checkpoint not exit. APPS: event-driven to ~Nov-3
earnings. Change driven by frozen recommendation-time info, not returns.
Historical V1 protocol text preserved above.

---

## FAST_TRIGGER_MONITOR_V1 (built 2026-10-03)

### What runs

`alpha_rnd/monitor.py` in the alpha worktree — pure market-data, no LLM/TA.

- Cron (installed, user `udi`): every minute runs `--once`
  `cd TradingAgents-alpha-rnd && PYTHONPATH=. python3 -m alpha_rnd.monitor --once`
  → intraday-zone checks during US session (13:30-20:00Z weekdays),
  close-pass once per newly completed session. Pre-freeze sessions
  (<=2026-10-03) are never evaluated.
- Start: already running via cron. Manual: `python3 -m alpha_rnd.monitor --loop`
  or `--once`. Status: `python3 -m alpha_rnd.monitor --status`. Stop:
  remove the cron line (`crontab -e`) or kill the --loop process.
- Reboot: cron resumes automatically. Machine asleep/off: nothing runs and
  nothing is claimed — missed close-passes are caught up on next run since
  completed sessions are processed once via `processed_close_sessions`.
- systemd user unit provided (`alpha_rnd/systemd/alpha-rnd-monitor.service`)
  as an alternative; requires `loginctl enable-linger` (sudo) to survive logout.

### Watch classes (live_watchlist.json, sha 01d2be80...)

- AUTO_ENTRY: PGEN (limit 8.20).
- DETERMINISTIC_CONFIRMATION: IOVA, CDNA, SDGR, ASST, TXG, TWST, PAYC, XNCR,
  AXGN — mechanical close/volume/multi-session rules; fill = next-session open
  (or zone-top limit where stated).
- REANALYZE_ON_TRIGGER: SYNA (~112/<106/2nd bidder), KOD (priced offering
  55-80 event — manual/event detection only), HHH (pullback needs catalyst
  check; >74.88 leg flagged for review).
- AMBIGUOUS: none.

### Safeguards

Fill only if: trigger after freeze, watch ACTIVE & unexpired (expiry
2026-10-30), not already open, slot free, cash sufficient, no duplicate.
$5k notional x size_frac, 10bps costs. Events immutable in
`alpha_rnd/trigger_events.jsonl`; notifications in `alpha_rnd/NOTIFICATIONS.log`.

### Single-ticker refresh (prepared, NOT run)

`ALPHA_RND_SINGLE_TICKER_REFRESH`: inputs = ticker + frozen artifact + trigger
event; refreshes that one ticker's market/filing/catalyst state; returns
BUY_NOW / KEEP_WATCHING / REJECT with horizon + execution instruction. To be
invoked manually or by a later session when a REANALYSIS_REQUIRED event exists.

### Monitor operational completion (2026-10-03)

Verified: exits AUTO-EXECUTE as paper exits (not just alerts). PBF: intraday
Low<=74.50 -> exit @74.50 (stop); close<78 -> exit @ close. ACN: close<194 ->
exit @ close. APPS: intraday Low<=10.42 -> exit @10.42. Costs 10bps; position
removed on exit (no duplicates; watch_status TRIGGERED prevents re-entry).
Bug fixed: ACN exit_rules missing `label` would have crashed the exit path.
Notifications now also fire `notify-send` desktop alerts (cron-safe env) for
triggers, exits, and REANALYSIS_REQUIRED. No buys without frozen rules.
