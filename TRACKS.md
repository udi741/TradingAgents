# TRACKS.md — TradingAgents project track index

Durable source of truth for all research/validation tracks. Update this file
whenever a track's gate, result, or next action changes.

Last updated: 2026-10-02T11:54:02Z

---

## ACTIVE

### C12_PROSPECTIVE

- Status: ACTIVE (frozen — owned by a different session)
- Objective: Test the frozen v0.5.0 TradingAgents system on genuinely
  prospective weekly recommendations and paper trades. Validation track, not a
  strategy-research track.
- Worktree/branch: `/home/udi/udi_provate/TradingAgents-c12` /
  `exp/gate-c12-prospective`
- Owning session: separate Devin session (not this one)
- Production impact: SEC statement tools pinned fail-closed
  (get_balance_sheet / get_income_statement / get_cashflow -> sec_edgar);
  decision layer otherwise official v0.5.0
- Current gate: Epoch 2 prospective paper trading
- Last accepted result: Epoch 1 = operational dry run only, 0 scoreable
  observations; 2026-09-25 week LATE_DECISION_NON_SCOREABLE; zero fills;
  timing guard prevents retroactive execution; Lane A -> top10 -> full TA
- Next action: run Epoch 2 weekly recommendations under the timing guard
- Blockers: none internal; gated by calendar/market weeks
- Other sessions: DO NOT modify the C12 worktree, ledger, epochs, config, or
  artifacts.

### EXPERT_RND

- Status: WAITING_FOR_PROSPECTIVE_EXPERT_SIGNALS (historical mimic CLOSED)
- Objective: Understand the expert's decision style and determine whether any
  of it can improve TradingAgents without repeating the failed M2/M4
  overfitting.
- Worktree/branch: `/home/udi/udi_provate/TradingAgents-expert-rnd` /
  `exp/expert-rnd-v2`
- Owning session: this session (EXPERT_RND)
- Production impact: none — analysis-only track
- Protocol: `tracks/EXPERT_PROSPECTIVE_PROTOCOL.md`; append-only store
  `expert_prospective/`
- Current gate: `EXPERT_PROSPECTIVE_CAPTURE_SETUP` (complete); X3-B closed
- Last accepted result: X3-B — published invalidations stop out 100% of
  losers but also 58% of recoverable winners; execution-layer policies
  tested on consumed artifacts are non-discriminative; HISTORICAL_EXPERT_MIMIC
  = CLOSED; see `tracks/EXPERT_RND.md`
- Next action: on next expert message — freeze signal record, run same-time
  v0.5.0 TA comparison, freeze artifact (see operator procedure);
  minimum reopen threshold: 20 BUY/ADD signals, >=5 losers or >=25% loser
  rate, >=15 explicit exits
- Blockers: none
- Reference baseline for all v0.5.0 behavior questions: tag `v0.5.0`,
  SHA `2d17df8da1536c121e4d7395ac5a5dcec9e96d6f`

---

## PAUSED

(none)

## CLOSED / REJECTED

### M2 (CONTEXTUAL_TECHNICAL_ENTRY_RM_V1)

- Status: REJECTED
- Summary: Made the Research Manager more permissive/contextual about
  pullbacks. Recovered 4/12 expert entries on frozen causal-tail replays but
  produced 5/12 new entries into known clear losers (PAYC, DG, CAT, HOOD,
  DDOG). Non-discriminative relaxation.
- Artifacts: `TradingAgents-mimic/evaluations/gate_m2_contextual_rm/`

### M4 (ENTRY_LOCATION_ASYMMETRY_RM_V2)

- Status: REJECTED
- Summary: Entry-quality/catalyst/location/asymmetry gate appended to M2.
  Passed its training guardrail (expert 2/12, losers 0/12) but on fresh M5
  disjoint validation: untouched CONTROL 7/17 strong-winner ENTRY, 1/10
  clear-loser ENTRY; M4 3/17 strong-winner ENTRY, 1/10 clear-loser ENTRY.
  Lost winners without reducing loser entries.
- Artifacts: `TradingAgents-mimic/evaluations/gate_m4_entry_quality/`,
  `gate_m5_fresh_disjoint/`

### Structured fundamental Lane D

- Status: RETIRED — fresh outcome failure.

### Broad non-S&P Lane A expansion

- Status: RETIRED — replication failure.

Do not silently resurrect any closed/retired track; reopening requires a new
explicit gate.

---

## ARCHIVED

(none)
