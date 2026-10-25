# TradingAgents — Autonomous Profitability Mission: Final Report

Branch `exp/final-review` (worktree `TradingAgents-final`, origin/main `aa57ea86`).
All numbers reproduce from committed scripts under `backtest/` and results
under `backtest/results/`. Production untouched; no merges.

## A. Executive conclusion

**LONG: INSUFFICIENT EVIDENCE / NOT VALIDATED.**
**SHORT: INSUFFICIENT EVIDENCE / NOT VALIDATED.**

No TradingAgents LONG or SHORT strategy has credible evidence of
post-cost profitability. The honest forward collector — the deployed
decision portfolio + 3-book ranking shadow — is the only uncontaminated
evidence path and is already running.

## B. Consolidated results

| Result | n | P&L | Basis |
|---|---|---|---|
| Recorded ALPHA paper book | 5 closed +1 open | **-2,402** | real (validated ledger) |
| C12 paper (HPE/NTAP/PLTR) | 3 open | ~-930 | real |
| Strict authorized LONG replay | 3 | -1,127 | retrospective replay |
| Contract-authorized LONG (post-fix) | 6 | -1,322 | retrospective replay |
| Gate-blocked counterfactual LONG | 9 | -1,652 | counterfactual |
| All contract-valid intents (pipeline) | 9L/2S | +61 / +502 | retrospective, unauthorized superset |
| Mechanical LONG, 75-name hindsight universe | ~500 | +112k/+12k/+39k | **contaminated universe** |
| Mechanical LONG, 1,823-name universe | ~220 | +11.1%/-8.3%/+27.0% | residual survivorship bias |
| Same, seed-shuffled admission | — | ±9-17pp swings | ordering = dominant factor |
| Real-model authoring eval | 6 | ACN -46, ANF -7 (open) | genuine authored output |

SPY refs: 2024 +25.6%, 2025 +18.0%, 2026YTD +13.2%, Oct-window -1.5%.

## C. Does AI research add value?

Partial evidence: AI-positive names coincided with mechanical winners
(+6.2k vs -4.3k on AI-negative, Oct cross-tab, n=7/20 — too small).
Authored decisions were honest (4/6 NO_TRADE, zero fabricated levels).
What AI demonstrably adds is *discrimination honesty*, not yet provable
alpha: its authored entry prices were no better than mechanical baselines.
Unknown: whether ratings-as-priority beats random admission — the shadow
experiment answers exactly this, prospectively.

## D. Research quota recommendation

**Keep 10, with quality-driven expansion as a conditional option.**
Evidence: the 54 quota-excluded R5B intents contained 12 executable
candidates but held October's worst losers (KOD -533, TWST -558,
MGNI -119). Expanding to 20/30 costs ~$20-90/session extra; the excluded
cohort produced negative incremental returns. Change only if forward data
show top-10 saturation — the machinery (`ALPHA_RESEARCH_BUDGET`, capped
30) is already merged.

## E. Recommended trading policy

No evidence supports replacing the current ruleset. If anything changes,
the best-supported hypotheses (untested out-of-sample, in priority order):
1. **Contract-complete authoring** (already live) — biggest funnel fix;
   92% of intents were NO_TRADE on missing terms, not bad direction.
2. **Typed stops on every position** (fixes PBF prose-rule gap; C12 has
   no stops at all — its protocol needs a policy decision, not code).
3. Constructive-setup preference over dip-buying (mechanics evidence,
   universe-biased).

The frozen gap filter is rejected (failed every untouched period).
Mandatory profit-trimming rejected (expectancy-negative in trending
periods). SHORT trading rejected (mechanics lose in all regimes;
contract-level shorts had n=2 retrospective only).

## F. Implementation

- Branch `exp/final-review`; prior work on `exp/decision-contract`
  (deployed `aa57ea86`), `backtest/historical-trades`, `fix/direction-safety`.
- 23 focused tests pass (contracts, decision, portfolio, lifecycle).
- Reproduce: `python3 backtest/pipeline.py`, `funnel.py`,
  `universe_pt.py`, `admission_sensitivity.py`, `eval_real_model.py`.
- Data: publication_intents ×16 sessions, R5B replays ×4, C12 ledgers,
  alpha_paper_ledger, frozen pools, yfinance bars (10bps/side, 2%/yr
  borrow, gaps at open).
- Inference spent: 1 bounded translator call (~$1-2). No other calls.

## G. Final decision

**INSUFFICIENT HISTORICAL EVIDENCE** — with a live path to resolution.

The missing evidence is chronological, not technical: all AI decisions
span one month/one regime; any larger universe is contaminated; any
retrospective model run is knowledge-tainted. The correct instrument —
the deployed decision portfolio + ranking shadow — is already collecting
untainted forward data. Re-evaluate in ~8-12 weeks with real contested
days and authored contracts.

## H. Independent critique

- Survivorship: the 1,823-name universe still requires names to exist in
  Oct-2026; delisted losers absent → LONG results overstated.
- Mechanical "edge" was mostly universe selection (+43-65pp buy&hold vs
  SPY); corrected baseline still lags SPY in 2/3 periods.
- Admission ordering swings results ±9-17pp — any small-sample result is
  noise-dominated.
- October AI positives winning mechanically could be luck (n=7) or
  screener overlap, not AI skill.
- The live paper portfolio is young; treating its future data as
  validation must be pre-committed (rules frozen today).
- Falsifiers: forward AI-priority book underperforming alphabetical by
  >5pp over ~40 contested days; authorized LONGs losing >2% NAV/quarter;
  authored-contract win rate below ~40%.

## NEW WORK COMPLETED DURING THIS MISSION

Three new experiments executed on the corrected timing engine +
1,824-ticker eligible universe (residual survivorship bias disclosed;
cache md5 b25fe6abe3c115e65670ba2eedc01c79). Results:
`backtest/results/mission2.json`, runner `backtest/mission2.py`.

### A — LONG holding-period discipline (60d vs 20d cap)

| Period | 60-session | 20-session |
|---|---|---|
| 2024 | +11.1% (77t, PF 1.63) | **+24.1% (162t, PF 1.91)** |
| 2025 | -8.3% (89t, PF 0.72) | **+5.8% (163t, PF 1.21)** |
| 2026YTD | +27.0% (57t, PF 3.00) | +4.8% (125t, PF 1.19) |

20d cap trades ~2x more often (frees capital faster → more admitted
signals). It improves 2024/2025 substantially but gives back 2026's
trend-driven gains — a time-decay discipline helps in choppy years,
hurts in trending ones. Not a free win; regime-dependent. Retained as
candidate hypothesis H1 (needs forward test, not deployable).

### B — SHORT on full eligible universe (corrected timing, first run
of the SHORT mechanics on the unbiased-ish universe)

| Period | NAV% | PF | Net P&L |
|---|---|---|---|
| 2024 | -8.7% | 0.75 | -5,595 |
| 2025 | -5.9% | 0.92 | -1,758 |
| 2026YTD | -6.8% | 0.68 | -6,597 |

SHORT mechanics lose in every regime on the broad universe — confirms
the biased-universe result. **Rejected definitively.**

### C — Quota economics (deep-rank split, Oct window)

| Pool | Signals | Admitted | Net P&L | PF |
|---|---|---|---|---|
| Top-10 (deep-ranked) | 26 | 17 | -3,691 | 0.40 |
| Rank 11-28 (quota-excluded) | 34 | 20 | -1,749 | 0.75 |
| All | 49 | 19 | -2,187 | 0.65 |

Quota-excluded candidates performed *better* than the top-10 in Oct
(mechanically) — the deep-score ranking is not protective, merely
arbitrary within this window. Mechanical ≠ AI value: these are
deterministic retest fills, not AI-authored decisions; it measures
what additional research *could* cover, not what it would earn.

### Verdicts

- A (horizon): mixed, regime-dependent → hypothesis retained for
  forward test only, not deployable.
- B (shorts): **NO-GO** — loses across all three regimes.
- C (quota): rank beyond 10 is not worse → quota expansion is
  defensible mechanically, but mechanical ≠ AI value; recommend
  keeping 10 with conditional quality-driven expansion (already
  configurable via ALPHA_RESEARCH_BUDGET).
