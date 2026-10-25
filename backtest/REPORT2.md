# Backtest Follow-up — Verification + Improvement Experiments

Reproduce: `python3 backtest/historical_backtest.py && python3 backtest/experiments.py`
(worktree `TradingAgents-backtest`, branch `backtest/historical-trades`).
Machine output: `backtest/results/backtest_results.json`, `backtest/results/experiments.json`.

## Part 1 — Baseline validation

### Reconciled actual ledger (Track A)

| Ticker | Entry | Exits (deduped; 188 duplicate events excluded) | Realized | Open |
|---|---|---|---|---|
| PBF | 10-02 @80.00 ×62 | — open, mark 76.17 (10-23 close) | 0 | -237.46 u. |
| ACN | 10-02 @205.00 ×24 | 10-07 @195.23 (close<194 → next open) | -244.09 | — |
| APPS | 10-02 @11.30 ×442 | 10-07 @10.302 (gap-through open <10.42) | -450.66 | — |
| PGEN | 10-05 @8.20 ×609 | 10-06 @7.79 (corrective exit, missed hard stop) | -259.43 | — |
| SDGR | 10-06 @31.00 ×161 | 10-07 @27.81 ×100; 10-13 @25.69 ×61 (mgmt) | -652.25 | — |
| TWST | 10-06 @209.55 ×11 | 10-07 @158.26 ×4; 10-12 @159.74 ×7 (mgmt) | -557.89 | — |

Realized **-2,164.32**, unrealized **-237.46** → **-2,401.8 (-2.40%)**. Ledger
NAV implies -2,378; the ~$24 residual is exit-fee convention on the PBF mark.
PBF's recorded PARTIAL_EXIT (31 sh, enqueued 10-22) has status
`MISSED_OR_CONSUMED_UNKNOWN` — treated as not executed; conservative.

### Relation of actual fills to the intent population — verified distinct

The 6 actual entries came from production watches created **before the
entry-gate existed** (RISK_GUARDRAIL_FROM = 2026-10-07): zone fills recorded
under the 10-02 protocol freeze. None of their sessions produced an
EXECUTABLE_WATCH disposition — production emitted zero across all 16
sessions. So: actual fills ∩ R5B-authorized set = **∅**. The Track-B strict
trades (KOD, TWST, P) are a different, replay-only population.

Timestamps verified: 10-01 intents synthesized 10-02 ~05:00Z → fills eligible
10-02 ✓ (matches recorded fills). Zone fills at zone top even on gap days
(production convention; flagged — e.g., PENG sim filled 74 on a day it
closed 67.6). Same-bar ordering: conservative stop-first. Corporate actions:
CTVA 6.665 split 10-01 (untraded — the artifact anomaly); ACN $1.71 div
10-13 (post-exit). auto_adjust=True used throughout; no traded ticker had a
split in-window.

### Exposure-matched SPY benchmark (same dollars, same dates)

Every trade underperformed SPY on its own window: total **-2,618.5 vs SPY**
on ~$28k deployed (worst: SDGR -848, TWST -545, APPS -490). Losses are
idiosyncratic, not market beta.

### PCVX/HESM defect — CONFIRMED

`synthesize._machine_executable` checks direction only when a resolved
`economic_authority` contract exists. Legacy path: watch_mode ∈
{AUTO_ENTRY, DETERMINISTIC_CONFIRMATION} + any executable param key +
any stop_level ⇒ EXECUTABLE_WATCH. PCVX (reentry_zone + stop 73.8 = the
*rejected short's* stop, per its own ambiguity note) and HESM (short_zone)
both pass → `publish()` builds a LONG watch with `stop_rule` above the
entry zone — a malformed watch that can trigger LONG fills on a Sell-signal
name and whose "stop" fires as an accidental take-profit.

Smallest safe fix: in `_machine_executable`'s legacy path, return False when
entry geometry is bearish — `stop_level` above the entry reference (zone hi
or trigger level), or `params` containing `short_zone`/explicit short
wording in `entry_convention`. Regression test: disposition of a PCVX-like
fixture intent must be PUBLISHED_NON_EXECUTABLE. Report only — no production
change made.

## Part 2 — Experiments (pre-registered rules, same sample → exploratory)

### A — Original rules (from first run)

Strict LONG: 3 fills, 0% win, -1,127.52. Gate-blocked counterfactual:
9 fills, -1,652.05. Actual ledger: -2,401.8.

### B — Hypothetical short strategy (labeled; Sell ≠ SHORT)

Rules: explicit short-geometry plans only (short wording/`short_zone`/
stop-above-entry + target-below); sell bounce into zone at zone bottom
(bar must intersect zone); stop above (close_above→next open or intraday);
borrow assumed 2%/yr, availability unknown; 10 bps/side.
7 fills: IOVA -294, SDGR +204, CDNA -36, ABCL -150, PCVX +132,
TWST +370, WDAY -9 → **+218 net, 43% win, PF 1.45.** Hypothesis only.

### C — Event-gap / risk-regime filter (pre-registered, not tuned)

Block LONG fill if (a) any |daily move| ≥8% in fill day or prior 5 sessions,
or (b) SPY < its 20-session SMA.

| Result | Count | P&L impact |
|---|---|---|
| Trades blocked | 7 of 12 long fills (ACN, PGEN, SDGR, KOD, P, PENG, SEZL) | **-2,456 avoided** |
| Winners missed | SEZL only (+92) | -92 |
| Trades kept | TWST, XP, HAE, MGNI (+ marks) | — |

Net effect on simulated longs: **+2,364** — converts -2,780 to ≈ -415.
Note: the +8% ACN gap on 10-01 is exactly the event type every large loss
shared. Mechanistically coherent, but the rule was defined *on* this sample.

### D — Profit protection (pre-registered)

Trim 50% at first close ≥+8%; trail remainder at peak-8pp vs original
stop-only: only PBF (+264.9 → turns -123.6 into +141.3) and SEZL (+48)
benefit; all other trades never reached +8%. Net **+313** across 12 longs.

## Limitations / leakage

- Single 16-session window; no untouched test period exists — the only
  out-of-sample evidence is the live forward ledger itself (now -2.40%).
- Exp C/D rules were motivated by this sample's failure modes; reported as
  exploratory, not validated alpha.
- R5B replay intents carry model-knowledge contamination; production
  intents/ledger are provenance-audited and clean.
- Zone-top fills on gap days flatter entries; intraday ordering unknown
  (conservative assumptions stated).

## Verdict

Evidence supports **one candidate improvement worth testing forward**:
the event-gap/risk-regime entry filter (Exp C) — it removes 58% of fills
and ~88% of simulated losses while missing a single +$92 winner, and its
mechanism (blocking entries into violent repricings) matches the observed
loss signature in all three tracks. It is not validated: the same
observations suggested it. Profit protection (D) is mildly positive but
only matters when a position reaches +8% — fixes the PBF round-trip
failure mode but not the dominant loss driver. Short trading shows small
positive hypothetical P&L but remains unsupported by the framework and
lacks borrow/feasibility evidence.

What's missing before any claim of edge: (1) a second, untouched sample
period with the filter applied identically; (2) forward-tracked paper
outcomes with the filter active; (3) intraday data to resolve same-bar
entry/stop ordering; (4) short-borrow feasibility/cost data. Until those
exist, the honest statement is: the strategy loses money by buying event
gaps, and the highest-value change to test next is restricting entries in
post-gap regimes — not more analysis capacity.

---

## Follow-up (commit after bec93a54): sensitivity + independence check

### Sensitivity (same trades, repriced)

| Variant | LONG 12 fills | SHORT 7 fills |
|---|---|---|
| V1 base (10bps, stop at level) | -2,779.6 | +218.2 |
| V2 25bps/side | -2,888.8 | +165.9 |
| V3 worst-case stop fills (stop = min/max with session open) | -2,779.6 | +218.2 |
| V4 = V2+V3 | -2,888.8 | +165.9 |

Conclusions insensitive to cost/stop-fill assumptions: LONG loses under every
variant; hypothetical shorts stay marginally positive.

### Per-decision-session P&L (all simulated trades, same sample)

| Session | Trades | Net P&L |
|---|---|---|
| 10-01 | 4 | -305.5 |
| 10-02 | 1 | -129.5 |
| 10-07 | 3 (shorts) | +352.2 |
| 10-09 | 4 | -1,031.0 |
| 10-12 | 6 | -1,412.0 |
| 10-13 | 1 | -35.6 |

### Independence disclosure — NO untouched holdout exists

All recorded decision artifacts span 2026-10-01..10-23 and every outcome in
that window was already observed when the gap-filter and profit-protection
rules were defined. There is no genuinely independent historical decision
period: Oct-24 was a Saturday, no newer sessions exist, and no pre-October
ALPHA_RND artifacts exist. Sessions 10-19..10-23 produced intents but their
fills were still simulated inside the inspiring sample. Therefore: Exp C/D
results are exploratory same-sample evidence, NOT validation. The only
clean test available is forward: run the frozen rules on new sessions as
they are recorded.
