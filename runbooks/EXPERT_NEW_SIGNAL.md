# RUNBOOK: EXPERT_NEW_SIGNAL

Owner: Devin session `groovy-allspice`.
Worktree: `/home/udi/udi_provate/TradingAgents-expert-rnd`
(branch `exp/expert-rnd-v2`).
Protocol: `tracks/EXPERT_PROSPECTIVE_PROTOCOL.md`.
Store: `expert_prospective/` (append-only).

## The one rule that matters

A signal counts as PROSPECTIVE only if it is captured **before its outcome
is knowable**. Trades the expert discloses after the fact are recorded as
`historical_disclosures/` and never count toward reopen thresholds.

## What to do for each expert message type

- **New BUY/ADD**: freeze a signal record immediately — exact message text
  verbatim, timestamp received, ticker, action, stated price/zone if any,
  stated stop/target if any. Then run the same-time official v0.5.0 TA
  comparison on that ticker (decision session = capture date) and freeze the
  artifact under `ta_comparisons/`.
- **Update (raise/lower zone, thesis change)**: append an update record
  linked to the original signal id. Never edit the original record.
- **Stop change**: append a stop-update record with the exact new level and
  message text.
- **SELL/REDUCE**: append an exit record — exact text, date, price if
  stated. This is what generates "explicit exit" evidence for thresholds.
- **Exact-message capture**: always store the verbatim message. Regime
  context (which strategy path the expert says it belongs to, e.g. NORMAL vs
  RISKIER_PATH_1) gets its own field — do not infer it.

## Prospective vs historical

| | Prospective signal | Historical disclosure |
|---|---|---|
| timing | captured before outcome | told to us after outcome |
| store | `signals/` | `historical_disclosures/` |
| counts toward thresholds | YES | NO — ever |

## What to send to `groovy-allspice`

"New expert signal for capture per `runbooks/EXPERT_NEW_SIGNAL.md`:
<PASTE EXACT MESSAGE>. Capture date: <YYYY-MM-DD>."

The session freezes the record, runs the comparison, updates
`state/EXPERT_RND.yaml` counts, and reports files/commits touched.

## Reopen thresholds (reminder)

Mimic design stays closed until ≥20 prospective BUY/ADD signals AND
≥5 completed losers or ≥25% loser rate AND ≥15 explicit exits.
