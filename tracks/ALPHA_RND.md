# Track: ALPHA_RND

# PURPOSE

Actively search for current trading/investment opportunities and improve the
discovery + decision + execution process while C12 remains the frozen
control. Paper trading only — exploratory R&D, no claim of proven alpha.

# STATUS

ACTIVE — V1 and V2 discovery gates complete; book monitoring/marking phase.

# OWNER

Devin session: UNKNOWN (not yet recorded — update this field when known).
Worktree `/home/udi/udi_provate/TradingAgents-alpha-rnd`,
branch `exp/alpha-rnd-v1`.

# WHAT THIS TRACK MAY MODIFY

- Its own worktree, paper ledger, monitor, watchlist, artifacts.
- Its own docs: this file, `state/ALPHA_RND.yaml`, `runbooks/ALPHA_RND.md`,
  ALPHA rows in `docs/EXPERIMENT_REGISTRY.md`, its own sections of
  `CURRENT_STATE.md` / `TRACKS.md`.

# WHAT THIS TRACK MUST NEVER MODIFY

- C12 worktree/ledger/epochs/config/artifacts.
- EXPERT_RND worktree or its prospective store.
- LOCKBOX; HOLDOUT unused.
- Production/promotion of anything without a separate explicit decision.
- Real-money anything. Paper only.

# CURRENT STATE

Authoritative dynamic state: `state/ALPHA_RND.yaml` and the alpha worktree
ledger (`alpha_paper_ledger.jsonl`, `alpha_rnd/`). Summary:

- Open paper positions: PBF 62sh @80.00; ACN 24sh @205.00; APPS 442sh @11.30.
- NAV $99,844.50 / cash $85,125.40 at 2026-10-02 close.
- 13 frozen watch triggers (V1: IOVA, CDNA, SDGR; V2: PGEN, SYNA, ASST, KOD,
  TXG, TWST, PAYC, XNCR, AXGN, HHH), expiry 2026-10-30.
- Per-minute cron monitor runs `alpha_rnd.monitor --once` while machine is on.

# FROZEN RULES / PROTOCOL

- Fills only from triggers frozen before the price move (prospective only).
- Intraday hard stops fill at stop level (or actual open if gapped through).
- Completed-close conditions execute at the NEXT regular-session open
  (PENDING_NEXT_OPEN); never at the confirming close.
- If a required next-open execution was missed while the machine was off:
  MISSED_EXECUTION_REVIEW_REQUIRED — never an invented later fill.
- Watch zones never trail; expiry 2026-10-30; untriggered =
  WATCH_EXPIRED_NO_ENTRY.
- REANALYZE_ON_TRIGGER never auto-buys.
- Exits follow frozen hierarchy: invalidation > event > time-box > target >
  reevaluation — never auto-sell on a research checkpoint.
- Research marks (5/20/60/120/250 sessions, vs SPY) are measurement points,
  not exits. Intended holding horizon is a different quantity.
- Events/logging append-only (`alpha_rnd/trigger_events.jsonl`).

# IMPORTANT ARTIFACTS

- `evaluations/alpha_rnd_v1/candidate_pool_frozen.json` (V1 pool)
- `evaluations/alpha_rnd_v1/case_artifacts/*_2026-10-02.json` (V2 deep-run artifacts)
- `evaluations/alpha_rnd_v1/alpha_paper_ledger.jsonl` (paper book)
- `alpha_rnd/live_watchlist.json`, `alpha_rnd/monitor.py`,
  `alpha_rnd/trigger_events.jsonl`, `alpha_rnd/NOTIFICATIONS.log`
  (event/notification logs are created lazily on first events)
- `intraday_trigger_evidence.json` (fill-timing audit)
(all inside `/home/udi/udi_provate/TradingAgents-alpha-rnd`)

# ACCEPTED RESULTS

- V1 gate COMPLETE: 0 ACTIONABLE_NOW of 10 deep runs; 3 VALID_PROSPECTIVE
  fills on frozen zones; E1 demoted to RETROSPECTIVE_SHADOW_DIAGNOSTIC for
  Oct-2 marks, ACCUMULATING prospectively.
- V2 gate COMPLETE: 0 ACTIONABLE_NOW, 10 new watches, 0 REJECT.
- Fast trigger monitor built and verified; close-confirmation execution fix
  applied (close -> next open).

# REJECTED HYPOTHESES / DO NOT REPEAT

- E1 Oct-2 marks must not be cited as prospective evidence (frozen post-open).
- Never take discretionary profit outside frozen rules in V1.
- Never invent stops for positions whose artifacts lack explicit invalidation.

# CURRENT OPEN QUESTIONS

- Does entry-zone staging add or cost vs buying at decision-time (E1)?
- H1–H5 hypotheses under observation (see detailed record below).

# EXACT NEXT ACTION / TRIGGER

Mark book each completed session; let the cron monitor process triggers;
act on REANALYSIS_REQUIRED / MISSED_EXECUTION_REVIEW_REQUIRED events per
`runbooks/ALPHA_RND.md`. Run another discovery cycle only when justified
(book slots, watchlist decay, or user request).

# HISTORY

Full pre-normalization detail is preserved verbatim below — it contains the
complete gate-by-gate record and is authoritative for anything not summarized
above.

---

# LAST UPDATED

2026-10-03T10:13:19Z (normalized by PROJECT_CONTROL; see per-section dates in
the detailed record)

---

## DETAILED RECORD (pre-normalization, verbatim)

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

### Close-confirmation execution fix (2026-10-03)

A close-confirmed condition can no longer fill at the confirming close.
Exits: PBF close<78 and ACN close<194 now emit
`CONFIRMED_PENDING_NEXT_OPEN_EXIT` and fill at the next regular-session open
(actual open incl. gaps). All DETERMINISTIC_CONFIRMATION entries already used
PENDING_NEXT_OPEN — unchanged. Intraday stops (PBF 74.50, APPS 10.42) fill at
stop level, or at the actual open if the session gaps through the stop.
Pending orders whose target open fully passed while machine was off are marked
`MISSED_EXECUTION_REVIEW_REQUIRED` — no retroactive/later-price substitution.
Notifications: ENTRY/EXIT CONFIRMED — PENDING NEXT OPEN, then ENTRY/EXIT
EXECUTED.

### PROJECT_CONTROL_ADOPTION (2026-10-03)

Session identity `feather-room` recorded in state/ALPHA_RND.yaml,
runbooks/ALPHA_RND.md, CURRENT_STATE.md. Authoritative state reconciled
against alpha worktree ledger + monitor_state.json — no conflicts found
(3 positions, 13 watches, 0 pending executions, 0 reanalysis events, cron
monitor live). Documentation definition-of-done adopted for all future
ALPHA gates (artifacts -> track md -> yaml -> aggregates -> registry ->
decision log -> runbook -> commit -> report).

---

## EXPERT_DISCOVERY_COVERAGE_V1 (RETROSPECTIVE DIAGNOSTIC — NOT_PROSPECTIVE, NOT_PROFITABILITY_VALIDATION)

Question: on the exact dates the expert bought, would current ALPHA discovery
have noticed? Replay of the FROZEN pipeline at each decision date (PIT data
only; universe membership = today's list — survivorship caveat; UAMY absent
from current universe but evaluated via data).

Authoritative cases: 16 (12 E-cohort frozen case_ids + IREN + 3
RISKIER_PATH_1 disclosures). Excluded: SANM (ambiguous date), IONQ (two
candidate dates). Result: ELIGIBLE 13/16 — DGXX ($4.53) and KEEL ($4.81)
failed price>=$5; ASYS failed liquidity ($2.8M medDV20). DISCOVERY_HIT 12/13
eligible (MP triggered nothing). CANDIDATE_POOL 1/16 (UAMY: LaneA #7, RS #6,
CAT, FA). DEEP_ALLOCATION 1/16 (UAMY). All other family hits ranked far below
frozen quotas (FROG B#28, BB A#95/RS#44, LUNR A#143, FTNT B#161).
FINAL_TA_DECISION = NOT_TESTED everywhere — no historical LLM inference.

FUTURE_HYPOTHESIS (record only, no tuning): the expert systematically buys
sub-$5/low-liquidity small caps outside ALPHA's eligibility band (3/16 cases)
and enters names ALPHA sees via catalyst/FA but ranks below quota (11/16).
A single deep-hit (UAMY) is too thin to conclude overlap.

Artifacts: `evaluations/alpha_rnd_v1/expert_coverage/` (per-date evals,
coverage_results.json, coverage_summary.json).

### UAMY deep-rank verification (2026-10-03)

Methodology flaw found in coverage gate: FA bonus was applied to UAMY without
computing it for pool rivals. Corrected symmetrically (all 25 pool members,
companyfacts filed<=2025-09-29): UAMY deep score 44.628, rank **3 of 25**,
inside the 10-slot quota — **DEEP_ALLOCATION_CONFIRMED** (would have been
rank 3 even without FA). Prior aggregate unchanged otherwise.

### Automatic daily discovery (2026-10-03)

Routine ALPHA operation no longer requires resuming Devin after market close.
`alpha_rnd/daily_scheduler.py` runs hourly via cron (`7 * * * *`). When the
latest completed session is unprocessed it launches one full frozen cycle:
monitor bookkeeping -> discovery.py -> deep-10 -> run_ta.py. Idempotent via
completed_sessions markers + kernel flock; bridge-foreign busy ->
ALPHA_DISCOVERY_BLOCKED_BRIDGE and retry. Per-minute monitor remains
authoritative for intraday/pending-open execution. First real unattended run:
session 2026-10-05 (AWAITING_FIRST_UNATTENDED_DISCOVERY_VERIFICATION).
Disable: remove the daily_scheduler crontab line.

### Scheduler hardening V1.1 (2026-10-03)

- Telegram relay now tails `scheduler_events.jsonl`: STARTED=INFO,
  COMPLETE=SUCCESS, ERROR=ACTION_REQUIRED (resume feather-room),
  BLOCKED_BRIDGE=WARNING (auto-retry noted).
- Deep selection canonicalized: `discovery.select_deep_candidates()` is the
  single implementation; scheduler delegates. Verified identical on the frozen
  2026-10-02 pool (IOVA QMCO MRNA CDNA SDGR PGEN SYNA ASST KOD TXG).
- Crash idempotence: TA per-ticker artifacts are the resume checkpoint —
  retries pass only missing tickers (no duplicate model calls); completed
  marker written only after full success. Scheduler writes no orders/watches,
  so a retry cannot duplicate economic side effects.

### Publication audit V1.2 (2026-10-03)

Audit verdict: PUBLICATION_PARTIAL. The accepted V2 path after TA was a
researcher synthesis step (read case_artifacts -> author watch specs in
gen_watchlist.py -> regenerate live_watchlist.json) — never captured in code,
and NOT automatable without inventing classification logic. Fixed boundary:

- Scheduler: discovery -> canonical deep-10 -> resumable TA -> emits
  ALPHA_DISCOVERY_TA_COMPLETE + ALPHA_PUBLICATION_REQUIRED (ACTION_REQUIRED,
  resume feather-room). Session stays open (not done).
- Canonical publish: `python3 -m alpha_rnd.publish <session>` regenerates the
  live watchlist atomically via gen_watchlist.build_doc() and records a
  published_sessions marker. Idempotent overwrite; never duplicates.
- Next hourly tick sees publish marker -> ALPHA_DISCOVERY_COMPLETE + done.
- Monitor remains sole execution owner throughout.

Equivalent to manual V2 path verified: build_doc() output identical to
current live_watchlist.json modulo generated_at/sha256.

### Automatic publication synthesis V1 (2026-10-03)

`alpha_rnd/synthesize.py` translates frozen TA artifacts into strict
PublicationIntent JSON via one bounded devin-deep call (temp 0), then a
deterministic fail-closed validator (evidence binding: every number must
appear in artifact text; scaled words 1.5M/million; word fractions
quarter/third/half; news/catalyst/deal-gated triggers must be
REANALYZE_ON_TRIGGER; auto-entry requires Buy/Overweight signal + explicit
params + stop). Validated intents merge into live_watchlist via
`alpha_rnd.publish` (atomic, idempotent). Ambiguous/unsupported cases emit
ALPHA_PUBLICATION_REVIEW_REQUIRED (ACTION_REQUIRED, resume feather-room);
the session still completes — validated watches publish, ambiguous stay
pending review (tracked in last_cycle.pending_review).

V2 equivalence run (frozen artifacts, no TA rerun): 4 SEMANTIC_MATCH
(AXGN/PAYC/TWST/TXG — identical mode + levels), 6 REVIEW (ASST/KOD/PGEN
genuine artifact-internal conflicts; HHH/SYNA wrong-mode output correctly
refused; XNCR over-claimed AUTO_ENTRY vs Sell refused). V1 out-of-sample:
1 validated (QMCO), 9 review — artifacts contain real sizing/stop
contradictions Devin had resolved by judgment.

### PGEN stop-integrity incident (2026-10-06)

Classification: STOP_BREACHED_MONITOR_BUG. PGEN entered 10:39 ET @ $8.20
(AUTO_ENTRY); its frozen intraday hard stop $7.75 was breached post-entry at
13:40 ET (low 7.55, close 7.74) but never executed: intraday_pass iterated
only watchlist `open_positions` (V1 seeds) and watch-fill positions stored
`invalidation` as raw text. Fix: all open positions stop-checked; typed
stop_rule derived at fill/migration from frozen invalidation text.
No retroactive fill invented — MISSED_EXECUTION_REVIEW_REQUIRED recorded;
PGEN remains open with stop armed (gap-through exits at actual open).

### PGEN integrity resolution + typed stops (2026-10-06)

- PGEN: MISSED_EXECUTION_REVIEW_REQUIRED stands; corrective exit queued —
  next regular-session open at ACTUAL open price
  (INTEGRITY_CORRECTIVE_EXIT_AFTER_MISSED_HARD_STOP). No retroactive $7.75.
- Typed stops canonicalized: watch spec `stop_rule` field (publish.py emits
  it from validated intent stop_level) -> do_fill consumes it; prose regex is
  legacy fallback only; suspended/reviewed positions are never re-armed.
- TWST verified for next open: entry close>200.31 confirmed, veto_level
  183.39 typed; post-entry stop explicitly "not provided" by TA artifact —
  accepted frozen spec, nothing invented. (Earlier "$73.8" was HHH's, a
  mislabel in the audit prose.)

### State concurrency hardening (2026-10-06)

Race classification: REAL_PRODUCTION_WRITER_RACE (B) — any two overlapping
monitor ticks, or a tick vs an ops write, could lose read-modify-write
updates; that is how the corrective-exit write was first clobbered.
Fix: monitor_state.json mutations now go through `locked_state()` — kernel
flock over load->mutate->save with atomic tmp+replace; scheduler_state.json
mutations via `_state_txn` (flock + atomic replace) used by check/run_cycle/
publish. Ledgers/events remain append-only. Tests patched to redirect
canonical paths; a stray-stub leak in test_monitor fixed.

### Monitor crash + open-order recovery (2026-10-06)

KeyError('type') crashed every tick: a position with suspended/no typed rule
yielded inv={} in the intraday stop loop. Fixed: schema-safe dispatch (typed
intraday stops only; everything else skips cleanly, malformed schema emits
warning), per-ticker isolation, stale-list guard. Second gap: pending
next-open orders couldn't see today's open because fetch_daily's end is
exclusive — resolve_pending now takes the live session's open from the
intraday frame. Delayed accounting of precommitted orders settled:
TWST entry 11@209.55; PGEN corrective exit 609@7.79 (realized -$259.42).
Monitor health now reflects last successful tick / latest traceback, not
cron writes.

### Temporal mark integrity (2026-10-06)

eod_marks never marks a position at a session earlier than entry_session —
such positions get mark_status=UNMARKED_SINCE_ENTRY and are excluded from
canonical marks/NAV; book carries provisional_nav_incl_unmarked_at_cost.
Realized P&L accumulates in state (PGEN corrective: -$259.42). Telegram
positions now show typed post-entry stop only; a pre-entry veto is never
labeled a stop.

### RISK_GUARDRAIL_V1 (2026-10-07, prospective)

Invariant: no automatic entry unless the frozen plan has a machine-actionable
post-entry risk rule (typed stop / typed close exit). Enforced at do_fill:
missing plan -> watch_status=RISK_PLAN_REQUIRED, NOT BOUGHT, Telegram INFO.
Boundary recorded in state (PRE/POST_RISK_GUARDRAIL); no historical fills
altered.

Root cause of no-plan entries: published watch specs never required typed
post-entry rules — invalidation prose wasn't machine-enforceable.
Watch audit: every current entry-capable watch except none has a typed rule;
all classify INTERESTING_BUT_RISK_PLAN_REQUIRED on next trigger (fail closed).
Positions: PBF/APPS typed stops valid; ACN pending exit undisturbed.

Fresh management reviews (position-context TA, 2026-10-06, new decisions):
TWST Underweight -> sell 4/11 next open, residual close<164; SDGR
Underweight -> sell 100/161 next open, residual close<27.29. Also fixed:
unattended 10-05 cycle TA step had failed silently (py3.10 ImportError);
scheduler now uses .venv312 and treats empty signals as
ALPHA_DISCOVERY_ERROR stage=ta_empty.

### TA provenance + exit-session audit (2026-10-07, pre-open)

- 2026-10-05 AND 2026-10-06 unattended cycles: TA stage failed for ALL deep
  tickers (py3.10 ImportError; 0 SWE-2 calls; 0 artifacts) yet both were
  marked ALPHA_DISCOVERY_COMPLETE — FALSE. Both now marked
  INVALID_TA_RUNTIME_FAILURE in scheduler_state (history preserved, no
  backfill, no rerun). Scheduler now errors on zero-signal TA (ta_empty) and
  uses .venv312 explicitly (verified cron-equivalent: py3.12.15, TA+langchain
  imports OK, bridge aliases resolve).
- Provenance: TWST/SDGR entries authorized by the VALID manual V2 TA
  artifacts (TWST/SDGR_2026-10-02.json, published 2026-10-03); the broken
  cycles changed no rules (validated=[] in both publication_intents).
  PBF/APPS/ACN provenance likewise from valid 10-01 artifacts.
- Timing: TWST/SDGR mgmt decisions frozen 10:18/10:31 UTC, before the
  13:30 UTC open; confirm_session corrected to decision session 2026-10-06
  -> eligible open = TODAY 2026-10-07 (same as ACN). General rule: eligible
  open = first regular-session open after the decision timestamp.

### SEV-1 duplicate-exit incident (2026-10-07)

Root cause: main() re-seeded exited V1 positions from watchlist
open_positions every tick — exited ACN/APPS resurrected and their rules
re-fired each minute (188 duplicate PAPER_EXITs, cash corrupted to $952,810).
Fix: exactly-once execution identity (`executed` ids, check/commit split,
order_id on pending orders) + retired_seeds anti-resurrection. Book
reconciled: cash $90,203.02, realized -$1,485.68, positions PBF 62 / SDGR 61
/ TWST 7; ACN/APPS/PGEN closed; pending 0/0. Incident evidence preserved in
ledger + evaluations/alpha_rnd_v1/incident_2026-10-07/. Automation remains
STOPPED pending user review.

### Incident final review (2026-10-07)

- Mark continuity restored from forensic snapshot: PBF 82.88 / SDGR 28.90 /
  TWST 166.97 @ 2026-10-06 close (reconciliation had wrongly stripped them;
  partial exits never invalidated residual marks — the repair did).
- Book: cash $90,203.02, realized -$1,485.68, NAV $98,273.27 (labeled
  MIXED-TIME: Oct-7 cash + Oct-6 marks; comparable EOD NAV at tonight's mark).
- Seeding: one-time explicit init (initialized flag) + fail-closed on missing
  canonical state; retired_seeds defense-in-depth only.
- Crash-safety: economic truth = canonical state (atomic replace); ledger/
  events are receipts; crash windows proven by test (single execution total).
- PBF downtime audit: session low 83.91 > 74.50 stop — no missed action.
- Telegram: cursors advanced, zero suppressed C12 bytes, one summary queued;
  relay STOPPED.

### wl NameError hotfix (2026-10-07)

Final-review edit left a broken inline seed block in main() referencing an
unloaded `wl` — every cron tick crashed BEFORE any mutation/save: zero
economic impact (verified: cash/positions/marks/pending/events unchanged).
main() now loads the watchlist and calls _seed_once; anti-resurrection
invariants intact. New production-main entrypoint test (isolated paths)
covers the class of failure helper tests missed.

### Stale-research + pending-entry audit (2026-10-08)

Oct-7 cycle STARTED 05:07Z, suspended mid-run, resumed on wake — process alive
and producing TA artifacts (verified live, not inferred). Gaps found and fixed:
run_cycle had no terminal-on-exception semantics (silent STARTED forever) and
no progress tracking -> added current_run {session,run_id,pid,stage,
last_progress_at,ta counts} to scheduler_state, terminal COMPLETE/ERROR/
BLOCKED/INTERRUPTED on every path, dead-pid reaping in check() with
resume-safe relaunch (discovery inputs are session-frozen, run_ta skips
existing artifacts), per-stage staleness bound = subprocess timeout + 15m.
Monitor now records data_health (PROCESS_ALIVE vs MARKET_DATA_HEALTHY) and
confirmation-time risk guardrail blocks "ENTRY CONFIRMED" for unplanned
entries. IOVA/TXG pending entries retired (prose-only invalidations, not
machine-actionable): RISK_PLAN_REQUIRED, watch evidence preserved, would have
self-blocked at fill anyway. TWST residual exit valid (155.65<164). SDGR
exactly 27.29 -> strict < -> correctly no exit.

### Oct-7 publication review + discovery stickiness audit (2026-10-08)

Oct-7 cycle COMPLETE: 10/10 TA artifacts, all Sell. Publication fail-closed
for all 10; root cause of most violations was a synthesizer evidence-binding
normalization bug (% literals, lowercase k, scaled ranges not normalized).
Fixed _nums_in_text; re-validated (no model calls). Verdicts: PGEN published
as inert REANALYZE_ON_TRIGGER watch; AMPL/ASST/PTC RESEARCH_ONLY; CDNA/MRNA/
QMCO/TEAM AMBIGUOUS; IOVA RISK_PLAN_REQUIRED (block stands); SDGR NO_ACTION
(open-position mgmt, existing 27.29 rule unchanged). Resolutions doc:
publication_resolutions_2026-10-07.json. Discovery stickiness proven
legitimate: session-keyed market caches, fresh universe+scoring per session,
real turnover, no stale reuse. Relay footer/severity consistency fixed.

### Offline catch-up + Oct-9 review (2026-10-11)

Machine off Oct-8..10. Catch-up integrity verified: TWST order (confirm 10-07,
target 10-08 open) recorded MISSED_EXECUTION — no fabricated fill; distinct
new prospective order close_below:TWST:2026-10-09 (10-09 close 159.78<164).
SDGR new order close_below:SDGR:2026-10-09 (27.28<27.29 strict). Both target
the 10-12 open. 10-08 EOD mark skipped by latest-session design (10-09 MARK
recorded, NAV 98210.30). Oct-9 cycle valid: 10/10 artifacts, COMPLETE; all 10
publication violations were genuine frozen-text ambiguity -> 0 new watches;
resolutions doc written. Defect found+fixed: publish.py only merged current-
session intents, silently dropping prior published watches (PGEN 10-07) —
now carries forward all sessions<=current with newer-wins precedence.

### Missed-execution provenance + watch lifecycle hardening (2026-10-11)

SDGR: 10-08 close 26.39 breached close<27.29 while machine offline; the
resulting 10-09 open opportunity is now durably recorded as a non-economic
MISSED_EXECUTION_REVIEW_REQUIRED (trigger_session 10-08, eligible 10-09,
retro_provenance) — no fill fabricated. The live order
close_below:SDGR:2026-10-09 (10-12 open) is the separate prospective
instruction. Watch lifecycle: _set_watch_status records terminal revisions
{status,rev,session}; publish carry-forward now consults monitor_state
watch_lifecycle + structured session fields (artifact filename is fallback
only), so RETIRED/EXPIRED/TRIGGERED/RISK_PLAN_REQUIRED revisions can never
resurrect while genuinely newer intents still supersede.

### Third flood: crash-replay loop + global event idempotency (2026-10-13)

Root cause: carry-forward publish introduced trigger_type:null watches ->
close_pass raised TypeError EVERY tick AFTER popping/re-queueing the SDGR
exit (MISSED+CONFIRMED emitted) but BEFORE save_state -> each cron tick
replayed the same transition (184+183 events, file grew to 152KB; all
consumed/delivered by relay). Economics clean: TWST filled once at Mon open,
SDGR order legitimately re-pending for 10-13 open. Fixes: (1) trigger_type
None-safe in both eval loops; (2) emit_once semantic event-id registry in
canonical state for every user-visible transition class; (3) relay
second-layer: delivered_semantic dedup (utc-free identity) + per-scan
circuit breaker (cap 25 + one summary + persisted breaker_log).
Acceptance: real main() x500 -> exactly 1 MISSED + 1 CONFIRMED, restart 0.

### Autonomous publication dispositions (2026-10-13)

Publication review no longer escalates normal TA ambiguity. synthesize now
assigns every analyzed ticker a deterministic disposition
(EXECUTABLE_WATCH / REANALYZE_ON_TRIGGER / RISK_PLAN_REQUIRED /
RESEARCH_ONLY / AMBIGUOUS_REJECTED / NO_ACTION / OPEN_POSITION_MANAGEMENT)
recorded durably in the intents doc. Scheduler emits one
ALPHA_PUBLICATION_SUMMARY (info) instead of ACTION_REQUIRED review events;
COMPLETE always carries user_action_required=none + disposition counts.
publish.py merges EXECUTABLE+REANALYZE dispositions (reanalysis published
inert). Oct-12 outcome: 4 exec (CDNA/IOVA/PGEN/TEAM), 2 reanalyze
(FRO/QMCO), 4 ambiguous-rejected. USER ACTION REQUIRED now reserved for
integrity failures only.

### Executable-disposition semantics correction (2026-10-13)

EXECUTABLE_WATCH now requires production-evaluability (watch_mode +
recognized trigger param key + machine-actionable risk plan). Validated but
inert intents -> PUBLISHED_NON_EXECUTABLE; REANALYZE_ON_TRIGGER intents keep
their own class. Oct-12 corrected: 0 truly executable; CDNA/IOVA/TEAM
published-non-executable; PGEN/FRO/QMCO reanalysis; 4 ambiguous-rejected.
IOVA effective state: new 10-12 revision legitimately superseded the 10-01
risk block (history preserved in watch_lifecycle) but is NON-EXECUTABLE.
Fixed latent intraday_pass crash: AUTO_ENTRY watch without params.zone.

### R2 rank-cohort outcome tracking (2026-10-14)

Ex-post observational layer: alpha_rnd/cohort_outcomes.py joins frozen R1
funnel artifacts to forward market data. Entry ref = next regular open;
horizons H1/H5/H20/H60 trading sessions; MFE/MAE; SPY excess; append-only
per (session,ticker,horizon). Stage cohorts DEEP/POOL-NOT-DEEP/NOT-POOL and
primary_rank cohorts preserved — no fabricated global rank. 10-12 backfill
(labeled) matured H1. R2 status WAITING_FOR_DATA; first clean session =
2026-10-14 funnel (schema v2). Standalone evaluator; not wired into trading
paths.
