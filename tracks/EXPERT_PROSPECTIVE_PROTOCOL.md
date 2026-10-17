# EXPERT_PROSPECTIVE_PROTOCOL

Status: ACTIVE — waiting for first signal
Created: 2026-10-02T11:54:02Z
Track: EXPERT_RND (state: WAITING_FOR_PROSPECTIVE_EXPERT_SIGNALS)

Purpose: capture future expert recommendations *before* outcomes are known,
paired with a same-time frozen TradingAgents v0.5.0 decision, so that
expert-vs-system comparison can never again be contaminated by hindsight.

## A / B / C separation

- **A — what the expert said** (`expert_prospective/signals/<signal_id>/signal.json`
  + `raw_message.txt`). Frozen at receipt. Immutable except append-only
  clerical corrections.
- **B — what TradingAgents said at the same time**
  (`expert_prospective/ta_comparisons/<signal_id>/`). Frozen at run time.
  Immutable.
- **C — what subsequently happened** (`expert_prospective/signals/<signal_id>/events.jsonl`
  and `outcome.json` when computed). NEVER modifies A or B.

## Signal record schema (`signal.json`)

```json
{
  "signal_id": "SIG-YYYYMMDD-NNN",
  "received_utc": "ISO-8601",
  "raw_text_file": "raw_message.txt",
  "ticker": "XXXX",
  "action": "BUY|ADD|HOLD|REDUCE|SELL|WATCH|OTHER_VERBATIM",
  "action_verbatim": "exact phrase from message",
  "expert_entry_price_or_range": "number, 'lo-hi', or null",
  "expert_stop_or_invalidation": "number/text or null",
  "expert_target": "number/text or null",
  "expert_thesis_catalyst": "verbatim summary or null",
  "stated_horizon": "text or null",
  "source_id": "channel/message id or null",
  "strategy_regime": "NORMAL|RISKIER_PATH_1|<exact user/expert-supplied name>|NOT_STATED",
  "explicit_or_inferred": "EXPLICIT|INFERRED",
  "captured_by": "operator/devin",
  "frozen_at_utc": "ISO-8601"
}
```

Rules: never infer missing values — use `null` / `NOT_STATED`. The exact
original message goes verbatim into `raw_message.txt`.

## Update/exit events (`events.jsonl`, append-only)

```json
{"ts_utc":"...","type":"SELL|REDUCE|ADD|STOP_CHANGE|TARGET_CHANGE|THESIS_INVALIDATION|POSITION_CLOSED|OTHER","linked_signal_id":"SIG-...","price_or_range":"...or null","reason_stated":"verbatim or null","raw_text":"exact message"}
```

Later expert messages are linked via `linked_signal_id`. The original
`signal.json` is never altered; corrections append a
`{"type":"CLERICAL_CORRECTION","field":"...","note":"..."}` event.

## Losers are mandatory

Do NOT filter the sample. Every captured signal stays: losers, stopped
trades, abandoned ideas, never-triggered recommendations, still-open
positions. Deleting any captured signal invalidates the dataset.

## Same-time TA comparison (prepare — do NOT run now)

For each EXPLICIT BUY/ADD signal: run the frozen official v0.5.0 pipeline as
close to signal time as feasible, in the EXPERT_RND worktree
(`exp/expert-rnd-v2`), using a flat native PortfolioContext (entry
comparison only). Save the full decision state verbatim to
`ta_comparisons/<signal_id>/` including run timestamp, exact data cutoff,
all analyst reports, bull/bear, RM, Trader, risk debate, PM, final
ENTRY/NO_ENTRY. This is R&D — separate from C12. Do not modify TA to match
the expert.

## No-hindsight rule

Once signal + TA comparison are frozen: do not change interpretation,
classification, entry condition, horizon, or success definition after seeing
future prices. Clerical corrections are append-only and documented.

## Strategy regimes and historical disclosures

Each signal records `strategy_regime` when stated by the user/expert; never
infer it. Regimes are never pooled automatically. "Riskier strategy/path"
is the user's characterization, not ours; `RISKIER_PATH_1` is our neutral
internal identifier for it.

Retrospectively disclosed trades (outcomes already known when told to us)
live in `expert_prospective/historical_disclosures/`, carry
`"NOT_PROSPECTIVE": true` and `entry_known_before_outcome: false`, and count
**0** toward the prospective minimum-sample thresholds. They may be used
later only as clearly labeled diagnostics.

Captured so far (addendum 1, 2026-10-02):
- HD-001 IREN — NORMAL — buy 2026-08-14 $45, sell 2026-08-28, LOSS (sell
  price not supplied; not inferred). First disclosed normal-strategy loser.
- HD-002 PANW — RISKIER_PATH_1 — buy 2026-09-08 $329, sell 2026-09-22 $329,
  FLAT_BEFORE_COSTS.
- HD-003 FTNT — RISKIER_PATH_1 — buy 2026-09-08 $153, sell 2026-09-22 $153,
  FLAT_BEFORE_COSTS.
- HD-004 AMAT — RISKIER_PATH_1 — buy 2026-09-08 $462, sell 2026-10-01 $524,
  WIN.

## Outcome fields (`outcome.json`, define now — compute later)

`expert_realized_return` (only when an explicit expert exit exists — primary
measure of expert trade management), `ret20`, `ret60`, `rel20_spy`,
`rel60_spy`, `max_favorable_excursion`, `max_adverse_excursion`,
`expert_stop_hit`, `ta_published_zone_hit`, `ta_published_invalidation_hit`.
All diagnostics; TA fields compare against the frozen TA artifact.

## Comparison questions the dataset must answer

1. How often does the expert BUY when TA says NO_ENTRY?
2. How often is the expert right in those disagreements?
3. How often does TA avoid expert losers?
4. Does the expert enter earlier than TA confirmation?
5. Does the expert exit into strength materially earlier than TA's
   fixed-horizon deterioration?
6. Are expert losses managed differently from winners?
7. Is there a reproducible rule generalizing across winners AND losers?

No mimic strategy is defined until the sample threshold is met.

## Minimum sample before any new mimic work

Reopen expert-mimic strategy design only when ALL hold:

- >= 20 prospective explicit BUY/ADD signals;
- >= 5 completed losing expert trades OR >= 25% of completed trades are
  losers, whichever occurs first;
- >= 15 trades with explicit expert exits or objective closed-position
  evidence.

Below threshold: keep collecting. No tuning.

## WHEN THE EXPERT SENDS A NEW PICK

1. Paste the expert's exact message to Devin immediately (verbatim — do not
   paraphrase; include timestamp if the source has one), and say which
   strategy regime it belongs to when known (NORMAL / RISKIER_PATH_1 / exact
   name). If unstated, regime stays NOT_STATED — never inferred.
2. Devin creates `expert_prospective/signals/SIG-<date>-<seq>/`, writes
   `raw_message.txt` + `signal.json`, commits (append-only).
3. Devin runs the frozen v0.5.0 TA comparison on that ticker with a flat
   book, saves the full state to `ta_comparisons/<signal_id>/`, commits.
4. Nothing else happens. No judgment, no trade action required.
5. When the expert later updates/exits, paste that message verbatim; Devin
   appends an `events.jsonl` entry linked to the signal.
6. Outcomes are scored later in batch — never used to edit A or B.
