# TRACKS.md — TradingAgents project track registry

Canonical master registry of all tracks. Update a track's row whenever its
gate, result, or next action changes. Per-track detail lives in
`tracks/<TRACK>.md` and `state/<TRACK>.yaml`; this file is the index.

Last updated: 2026-10-03T10:13:19Z

---

## ACTIVE

### C12_PROSPECTIVE

- Status: ACTIVE (frozen validation — owned by a different session)
- Type: VALIDATION_CONTROL
- Objective: Test the frozen official TradingAgents v0.5.0 system on
  genuinely prospective weekly recommendations and paper trades.
- Worktree: `/home/udi/udi_provate/TradingAgents-c12`
- Branch: `exp/gate-c12-prospective`
- Devin session: `kindly-nightshade`
- Current gate: Epoch 2 prospective paper trading
- Last accepted result: Epoch 1 = operational dry run, 0 scoreable
  observations; 2026-09-25 week LATE_DECISION_NON_SCOREABLE, zero fills;
  timing guard added; Lane A -> top10 -> full TA; SEC statement tools pinned
  fail-closed.
- Next trigger/action: run the due 2026-10-02 cycle before its 2026-10-05
  13:30 UTC deadline; resume `kindly-nightshade` (no runner is alive)
- Blockers: none internal; calendar/market-week driven
- Production modification permission: SEC statement-tool pins only; decision
  layer must remain untouched v0.5.0
- Other sessions: DO NOT modify the C12 worktree, ledger, epochs, config, or
  artifacts.
- Detail: `tracks/C12_PROSPECTIVE.md`, `state/C12_PROSPECTIVE.yaml`
- Last-updated: 2026-10-03T10:13:19Z

### ALPHA_RND

- Status: ACTIVE
- Type: OPPORTUNITY_RND (paper only — no profitability claim)
- Objective: Continuously search for stocks/trades worth acting on now;
  improve discovery + decision + execution; build live/paper evidence.
- Worktree: `/home/udi/udi_provate/TradingAgents-alpha-rnd`
- Branch: `exp/alpha-rnd-v1` (from freshly fetched `origin/main`)
- Devin session: UNKNOWN (not yet recorded)
- Current gate: V1+V2 discovery complete; monitoring/marking phase
- Last accepted result: V1 (2026-10-01 session) 28-name pool, 10 deep runs,
  0 ACTIONABLE_NOW, 6 watches; 3 VALID_PROSPECTIVE fills 2026-10-02 (PBF,
  ACN, APPS). V2 (2026-10-02 session) 22 new candidates, 10 deep runs,
  0 ACTIONABLE_NOW, 10 new watches; paper-book protocol frozen;
  close-confirmed -> next-open execution fix.
- Next trigger/action: session marking; cron monitor on 13 watch triggers
  (expiry 2026-10-30); E1 ACCUMULATING
- Blockers: none
- Production modification permission: none without explicit promotion
- Detail: `tracks/ALPHA_RND.md`, `state/ALPHA_RND.yaml`
- Last-updated: 2026-10-03T10:13:19Z

### EXPERT_RND

- Status: WAITING_FOR_PROSPECTIVE_EXPERT_SIGNALS (historical mimic CLOSED)
- Type: ANALYSIS_ONLY_RND
- Objective: Understand the expert's decision style; determine whether any of
  it can improve TradingAgents without repeating M2/M4 overfitting.
- Worktree: `/home/udi/udi_provate/TradingAgents-expert-rnd`
- Branch: `exp/expert-rnd-v2`
- Devin session: `groovy-allspice`
- Current gate: EXPERT_PROSPECTIVE_CAPTURE (X3-B closed historical mimic)
- Last accepted result: X3-B — published invalidation non-discriminative;
  HISTORICAL_EXPERT_MIMIC = CLOSED; prospective capture protocol frozen,
  append-only store `expert_prospective/`; addendum 1 recorded 4
  retrospective disclosures (all NOT_PROSPECTIVE).
- Next trigger/action: on next expert message — freeze signal record
  pre-outcome, run same-time v0.5.0 comparison, freeze artifact
  (`runbooks/EXPERT_NEW_SIGNAL.md`)
- Blockers: waits on future expert messages
- Reopen threshold: >=20 prospective BUY/ADD, >=5 losers or >=25% loser rate,
  >=15 explicit exits
- Production modification permission: none — analysis only
- Detail: `tracks/EXPERT_RND.md`, `state/EXPERT_RND.yaml`,
  `tracks/EXPERT_PROSPECTIVE_PROTOCOL.md`
- Last-updated: 2026-10-03T10:13:19Z

### PROJECT_CONTROL

- Status: ACTIVE
- Type: DOCUMENTATION_CONTROL
- Objective: Own the knowledge architecture and major global documentation;
  NOT a per-experiment gatekeeper.
- Worktree: `/home/udi/udi_provate/TradingAgents-tracks`
- Branch: `project/tracks`
- Devin session: whichever session is running a control task
- Current gate: V1 knowledge architecture initialized 2026-10-03
- Next trigger/action: only when global doc structure needs changing
- Detail: `state/PROJECT_CONTROL.yaml`, `docs/DOCUMENT_OWNERSHIP.md`
- Last-updated: 2026-10-03T10:13:19Z

---

## PAUSED

(none)

## CLOSED / REJECTED (summary — full detail in `docs/EXPERIMENT_REGISTRY.md`)

- **M2** CONTEXTUAL_TECHNICAL_ENTRY_RM_V1 — REJECTED (non-discriminative
  relaxation; recovered 4/12 expert entries, admitted 5/12 losers).
- **M4** ENTRY_LOCATION_ASYMMETRY_RM_V2 — REJECTED (fresh disjoint validation:
  lost winners, loser entries unchanged).
- **X2** ladder-fill counterfactual — X2-B zones non-discriminative.
- **X3** published invalidation — X3-B non-discriminative.
- **Structured fundamental Lane D** — RETIRED (fresh outcome failure).
- **Broad non-S&P Lane A expansion** — RETIRED (replication failure).

Do not silently resurrect any closed/retired line; reopening requires a new
explicit gate.

## ARCHIVED

(none)
