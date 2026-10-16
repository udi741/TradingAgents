# ALPHA Post-Entry Adaptive Management — Implementation Plan

Status: PHASE B DONE (shadow trigger infrastructure live, observational
only — no model reassessment, no economic action). Phase A audit + design
lock retained below. Phases C–E require explicit phase approval; Phase E
additionally requires user approval after shadow acceptance.

## Product intent (approved, unchanged)

```
POSITION OPEN
  → deterministic safety monitor stays always active
  → meaningful change occurs
  → POST-ENTRY REASSESSMENT (compare original thesis vs current reality)
  → validated management decision:
      HOLD_UNCHANGED | HOLD_AND_TIGHTEN_RISK | PARTIAL_EXIT | FULL_EXIT | REASSESS_LATER
```

A trigger means "think again", never "automatically sell". No universal
take-profit rule (e.g. +10% → sell) exists or will exist.

## Phase A audit — what exists today

### Position authority (A)
`alpha_rnd/monitor_state.json` → `positions[<T>]`: `shares`, `fill`, `frac`,
`cost`, `invalidation` (text), `horizon` (text), `stop_rule` (typed or absent),
`entry_session`, plus mark fields. Identity = ticker (one position per
ticker). Quantity/cost-basis authority = `shares` + `cost`; seeded positions
may lack `cost` (pro-rata fallback in `do_exit`).

### Entry-thesis availability (B)
For a filled position: watch spec in `live_watchlist.json` (trigger, params,
invalidation, horizon, `artifact` filename), TA artifact
`case_artifacts/<T>_<s>.json` (full debate/reports), `publication_intents_<s>.json`
(intent, horizon, invalidation, stop_level, reevaluation text). All survive
entry — but `monitor_state.positions` itself stores only invalidation/horizon
text + stop_rule, not an artifact pointer. An **immutable entry snapshot is
necessary**: today the references exist but are scattered and revocable
(watchlist regenerates); a snapshot pins thesis/risk-plan/horizon at fill time.

### Stop authority (C)
Two sources, evaluated per minute: `live_watchlist.open_positions[t].invalidation`
(typed) takes precedence; `monitor_state.positions[t].stop_rule` is the
fallback (`intraday_pass`, monitor.py:684). Close-confirmed rules come from
`exit_rules` (`close_below`) or a `stop_rule` of type `close_below`
(`close_pass`). Stops CAN change after entry only by regenerating the
watchlist or editing state — no automated path exists. Survives restart
(state on disk).

### Time-box/horizon (D)
`horizon` and `reeval` are descriptive text only. Nothing detects horizon
expiry for positions; `watch_expiry` (EXPIRY constant) applies to watches,
not positions. **PBF's "2-3wk time-box" is descriptive, not machine-actionable.**

### Exit paths (E)
1. `intraday_stop` — immediate fill at stop level (or actual open on
   gap-through). exec_id `intraday_stop:<t>:<session>`.
2. `close_below` typed rule (position `stop_rule` or watchlist `exit_rules`)
   — close pass appends `pending_open_exits`, fills at next regular open.
3. Manual/seeded pending exits (e.g. MGMT_REVIEW orders written by operator
   tooling) — resolve via the same `pending_open_exits` queue.
4. MISSED handling — a passed target session is never retro-filled.
No model-generated exit path exists today.

### Partial exits (F)
**Machinery already works end-to-end** — proven in production by the
MGMT_REVIEW exits (TWST 4/11, SDGR 100/161): `pending_open_exits` accepts
`shares`, `do_exit` has a `shares` parameter, cost basis allocates pro-rata
(`pos["cost"]` reduced correctly), remaining shares stay open with all stops
intact, exec-id dedup applies. **Missing primitive: no producer.** No code
path creates a partial-exit order; only the plumbing exists.

### Fill/ledger/idempotency (G,H)
Intent → `pending_open_*` (order_id identity) → resolve at actual next-open
→ `do_exit`/`do_fill` (cash, realized, shares, `_exec_commit`) →
`trigger_events.jsonl` via the in-state `event_outbox` (transactional;
crash = possible duplicate durable line, never a lost event or half-fill).
`executed[]` prevents any exec_id/order_id from applying twice.

### OPEN_POSITION_MANAGEMENT (I)
Defined in `synthesize.DISPOSITIONS`; produced when a ticker is in `held`
(current open positions) AND the intent has validation errors. **Dead end
today:** not in PUBLISHABLE, consumed by nothing — an audit label only.
Reusing it as the management namespace would conflate "entry-side intent that
failed validation on a held ticker" with "post-entry management decision" —
different objects. Decision: management decisions get their own artifact
namespace (below); `OPEN_POSITION_MANAGEMENT` stays as the entry-side label.

### Post-entry model capability (J)
**None exists.** `run_ta.py` runs pre-entry per-ticker analysis; the
translator prompt translates fresh TA into entry intents. No path feeds a
position + original thesis to a model, nothing emits exits, nothing is wired
into the scheduler. Entirely greenfield — but the bridge routes
(devin-quick/devin-deep) and the translator's structured-output +
fail-closed-validation pattern are directly reusable.

### Scheduler/locking (K)
- Per-minute `monitor --once` (cron) — deterministic, owns economics under
  `locked_state`.
- Hourly `daily_scheduler --check` → `run_cycle` under `CYCLE_LOCK` (flock):
  monitor book pass → discovery → TA → synthesize → publish → observational
  freezers. Current session first; background retries bounded (2 tickers,
  fair order, 7-day lifetime).
- Integration point for reassessment: **trigger detection belongs inside
  `monitor --once` close pass** (cheap, deterministic, uses daily bars it
  already fetches). **Model reassessment must be a separate bounded stage**
  in `run_cycle` (after publish, before observational freezers) or its own
  session — never inside the minute monitor, never blocking the current
  session, and subject to the same starvation/fairness rules.

### Fresh-data sources for reassessment (L)
Reusable without new provider architecture: `e17.fetch_batch_ohlcv` daily
bars (all position context, MFE/MAE), `fetch_intraday` 1m bars, SPY benchmark
(same fetch), `discovery.sec_catalyst_events` + `fetch_sec` companyfacts/
filings (PIT-bounded), TA vendors' news inside a model call. Positions'
`mark`/EOD marks give canonical close values.

### Telegram (M)
Management events fit the existing severity map: reassessment completed →
INFO/summary; stop tightened / partial exit scheduled → INFO (like
CONFIRMED_PENDING_*); management infrastructure degradation → one bounded
WARNING per session/status (same dedup signature pattern as analysis
alerts); fills → existing PAPER_EXIT SUCCESS. New kinds go in ALPHA_MAP /
ALPHA_SCHED_MAP with `notify` flags — no new machinery.

### Restart/crash (N)
Pending orders, positions, exec IDs, outbox all live in `monitor_state.json`
(flock + atomic write) — restarts are safe today. Management needs the same
treatment: durable per-position management record + management action IDs
that map into `executed[]`/order_id space so a crash cannot double-execute.

## PBF read-only reconstruction (2026-10-16)

| Field | Value | Source |
|---|---|---|
| Entry | 2026-10-02 @ $80.00, 62 shares | ledger/postmortem |
| Original TA | `PBF_2026-10-01.json`, signal Overweight | case_artifacts |
| Intent | ACTIONABLE_NOW, staged limit 78–80 | publication_intents_2026-10-01 |
| Invalidation | close < $78 failed breakout; close in $70–77 base exits | intent |
| Active stop | intraday_stop $74.50 (watchlist `invalidation`, typed) | live_watchlist |
| Close rule | close_below $78.00 "failed breakout" | exit_rules |
| Horizon | "1-3 months, hard 2-3wk time-box ~Oct-16 options expiry"; reeval = next completed session after 2026-10-16 — **descriptive, arrives today** | intent/watchlist |
| Current mark | $86.99 (2026-10-15 close), +8.74% unrealized | monitor_state |
| Peak since entry | $91.53 high → +14.41% MFE; drawdown from peak ≈ −5% | postmortem ex_post + daily bars |
| Sessions held | ~10 | — |

**Reassessment-context verdict:** everything needed exists — thesis,
invalidation, stop, horizon, price path, mark. PBF would plausibly trigger a
reassessment today on the time-box arrival alone. No model call was made;
no action recommended.

## Historical trade-management audit (R7 postmortems + ledger)

| Ticker | Entry | Exit(s) | Realized | MFE | MAE | Final | Giveback | Class |
|---|---|---|---|---|---|---|---|---|
| PBF | 10-02 @80.00 ×62 | open | 0 | +14.4% | −3.5% | +8.7% (open) | ~6pp so far | open |
| ACN | 10-02 @205.00 ×24 | 195.23 ×24 | −239 | +3.2% | −6.8% | −4.8% | ~8pp | B* |
| APPS | 10-02 @11.30 ×442 | 10.30 ×442 | −446 | +5.9% | −9.0% | −8.8% | ~15pp | B |
| PGEN | 10-05 @8.20 ×609 | 7.79 ×609 | −259 | +4.9% | −8.7% | −5.0% | ~10pp | B* |
| TWST | 10-06 @209.55 ×11 | 158.26 ×4, 159.74 ×7 | −558 | +4.9% | −31.0% | −24.0% | ~29pp | B |
| SDGR | 10-06 @31.00 ×161 | 27.81 ×100, 25.69/25.91 ×61 | −639 | +9.0% | −18.0% | −13.9% | ~23pp | B |

Every closed trade gave back its entire peak move and finished negative.
TWST and SDGR in particular spent days underwater far beyond their small
peaks — **a "think again" trigger would have had something to evaluate in
all five closed cases.** (R7 caveat stands: these were not clean
same-session TA evidence; this audit measures management-path behavior
only.) No claim about what a model "would have done".

## Design lock

1. **Management state location:** new durable file
   `evaluations/alpha_rnd_v1/management_state.json` + per-position records;
   economics stay in `monitor_state.json`. Trigger/peak tracking is derived
   per minute from daily bars + marks — no new hot-path state needed beyond a
   persisted `trigger_registry`.
2. **Entry snapshot:** written at `do_fill` (and backfilled for seeded
   positions): ticker, entry_session, price, shares, watch revision/artifact,
   intent classification, invalidation text+typed rules, stop_rule,
   horizon/reeval text, catalysts named in intent. Immutable.
   `evaluations/alpha_rnd_v1/entry_snapshots/<T>_<entry_session>.json`.
3. **Trigger state:** `management_state.json.trigger_registry[<T>]`
   = {family, first_seen, last_fired, cooldown_until, debounce_count,
   last_decision_id}.
4. **Peak tracking:** `peak` (max high since entry), `peak_session`,
   `trough`, `unrealized_peak_pct`, `drawdown_from_peak_pct` — recomputed
   deterministically in close pass from daily bars + entry snapshot, no
   inference.
5. **V1 trigger families:** (a) HORIZON_ARRIVAL — reeval/time-box date
   machine-parsed at snapshot time when expressible as a date (PBF's
   "after 2026-10-16" is exactly this); (b) THESIS_INVALIDATION_ZONE —
   price near/violating the stated invalidation without a hard-rule hit;
   (c) PROFIT_EROSION — drawdown from peak beyond configured tolerance;
   (d) ADVERSE_EXTENSION — MAE beyond configured tolerance (deep underwater,
   e.g. TWST −31%); (e) CATALYST_MATERIALIZATION — a named catalyst date
   passed. Configuration, not magic numbers (item 6).
6. **Trigger configuration:** `alpha_rnd/management_policy.json` — per-family
   enable + parameters. Numeric thresholds derived from the position's own
   artifact (stop distance, ATR) where possible; global defaults documented
   with derivation notes, tunable per family. No value is silently invented.
7. **Debounce/cooldown:** per-ticker per-family cooldown in sessions
   (default: 1 reassessment per position per session max, regardless of
   families); repeated firing only records state.
8. **Urgency classes:** URGENT (thesis invalidation confirmed / hard-rule
   adjacent) evaluated at next close pass; NORMAL evaluated in the next
   bounded management stage. Hard deterministic exits never wait.
9. **Context package:** entry snapshot + position + price-path stats
   (peak/drawdown/MFE/MAE/sessions) + fresh daily bars + fresh SEC catalysts
   + SPY window + original artifact text. PIT-bounded to evaluation date.
10. **Route:** existing bridge, `devin-deep` for the management analyst
    (position decisions are low-frequency/high-value), `devin-quick` for the
    translator — same pattern as entry side.
11. **Output schema:** `{action: HOLD_UNCHANGED|HOLD_AND_TIGHTEN_RISK|
    PARTIAL_EXIT|FULL_EXIT|REASSESS_LATER, rationale_ref, tighten?: {type,
    level, label}, partial?: {shares|frac}, horizon_update?, confidence,
    valid_until}`.
12. **Action vocabulary:** exactly the five actions above; terminal economic
    effects only through PARTIAL_EXIT → pending order and
    HOLD_AND_TIGHTEN_RISK → stop_rule update.
13. **Publication namespace:** `evaluations/alpha_rnd_v1/management_intents/
    <session>/<T>.json` + `management_decisions_<session>.json` — separate
    from entry-side `publication_intents_*`; `OPEN_POSITION_MANAGEMENT`
    disposition left untouched.
14. **Validation:** deterministic fail-closed validator (same style as
    `synthesize.validate`): tighten must raise protection, never widen
    (level must move toward price vs current stop, never below the existing
    max authorized downside); partial must be 0 < shares < position; full =
    all shares; unknown/malformed → REASSESS_LATER/no-op + audit.
15. **Partial-exit architecture:** validated decision →
    `pending_open_exits` entry with `shares` + `order_id`
    `mgmt_partial:<t>:<decision_id>` — reuses proven plumbing; fills at next
    regular open with pro-rata cost basis.
16. **Tightened-stop architecture:** decision → atomic update of
    `positions[t].stop_rule` (raise level for longs) AND a new typed rule in
    the position's effective rule set; the old rule is superseded, never
    weakened; update is itself an `executed[]` action id
    `mgmt_tighten:<t>:<decision_id>` so it applies exactly once.
17. **Stale-decision protection:** a decision is valid only while
    `valid_until` ≥ evaluation session and the position/shares match the
    snapshot it was computed on; any earlier exit or manual change voids it.
18. **Action IDs:** `mgmt_<verb>:<t>:<decision_id>` entering `executed[]`;
    `decision_id` = sha of (ticker, trigger, context snapshot hash) —
    idempotent across restarts.
19. **Scheduler integration:** trigger detection in close pass; reassessment
    stage in `run_cycle` after publish (bounded, e.g. ≤2 positions per run,
    least-recently-assessed first — same starvation contract as TA retry).
20. **Retry semantics:** reuse the analysis retry state machine —
    retryable reasons → `RETRY_PENDING` with the same ledger/lifetime
    pattern; management inference failures never produce economic action.
21. **Telegram:** new ALPHA_SCHED_MAP kinds `ALPHA_MGMT_REASSESS_*`
    (INFO), `ALPHA_MGMT_ACTION` (INFO for tighten/partial; existing
    PAPER_EXIT SUCCESS covers fills), `ALPHA_MGMT_INFRA_*` (bounded WARNING).
    One message per distinct state — same dedup contract.
22. **Operator command:** `python -m alpha_rnd.mgmt status [--ticker T]` —
    shows triggers, last decision, pending actions, shadow-vs-active mode.
23. **Shadow isolation:** `management_policy.json.mode = "shadow"` —
    triggers detect and record, reassessment produces artifacts, validation
    runs, and the result is written to `management_decisions` with
    `applied: false, would_have: <order/rule delta>`; zero economic writes.
24. **Rollback:** mode flag `disabled` bypasses detection entirely; economic
    activation is a separate flag (`mode: "live"`) checked at the pending-
    order write — flipping to shadow stops new actions without touching
    existing pending orders/stops.
25. **Replay compatibility:** management state is namespaced per session and
    pure-function of (snapshot, bars, decisions); the replay engine can drive
    it offline for evaluation without touching live files.

## Phase plans

- **Phase B (shadow):** entry-snapshot writer (fill-time + backfill),
  `management_state.json`, trigger families (a)–(e), policy file, cooldown
  registry, `mgmt status` CLI. Tests: trigger fire/no-fire per family,
  debounce, snapshot immutability, monitor untouched.
- **Phase C (shadow):** management prompt + bridge call + structured
  artifact + fail-closed validation + context-package builder + infra
  failure semantics. Tests: schema validation, no-result→no-action,
  malformed→no-op, bounded stage scheduling.
- **Phase D (non-economic):** tighten/partial/full → `pending_open_exits`
  and stop_rule update machinery + staleness checks + idempotent action IDs
  + validator hard limits (never widen, never add). Tests: every validator
  rule, restart replay, duplicate suppression, ordering vs hard stops.
- **Phase E:** paper activation — explicit user approval after shadow
  acceptance; `mode: "live"`, first management-derived order.
- **Phase F:** prospective evaluation — management decisions joined to
  subsequent outcomes (same H1/H5 semantics), reported like R3.

## Guide updates required when behavior lands

`ALPHA_SYSTEM_GUIDE.md` sections 7 (dispositions — new namespace), 9
(position management — new exit paths), 10 (authority — new state files),
11 (Telegram kinds), 17 (failure scenarios), 18 (invariants), 16 (commands),
19 (file map). Phase A changes none of them.
