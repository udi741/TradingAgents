# Structured LONG/SHORT authoring — live-path integration

Branch `exp/decision-contract` (`TradingAgents-contract`, origin/main
`62b99180`). No production changes deployed.

## 1. Live authoring path changed

- `alpha_rnd/synthesize.py::SCHEMA_HINT` — translator output now REQUIRES
  `"decision":{"direction":"LONG"|"SHORT"|"NO_TRADE","no_trade_reason"}`
  per ticker (Buy≠executable LONG, Sell≠executable SHORT).
- `run()` — after econ-contract resolution, each intent gets
  `i["decision"] = decision.from_intent(...)` (persisted with intents).
- New `alpha_rnd/decision.py` — canonical validator + adapters
  (`from_economic_authority`, `from_intent`). LONG contracts still flow
  through `econ_contract`/`_machine_executable`; SHORTs are paper-only
  objects (buy-to-cover, ~2%/yr borrow flag, stop-above-entry enforced).
- AI authors thesis fields (entry/stop/target/invalidation); the
  validator does geometry, R/R, sizing, borrow — no silent repair.
- `backtest/decision_contract.py` remains the legacy prose adapter.

## 2-4. Regression examples (`alpha_rnd/test_decision.py`, 6 tests pass;
`backtest/test_decision_contract.py`, 9 pass; test_synthesize green)

- LONG: EA contract zone [60,62]/stop55/target70 → valid, R/R>0 →
  synthetic bars → LIMIT_ZONE fill → close_below stop → next-open exit,
  realized P&L — full authoring→validation→eligibility→sim→outcome path.
- SHORT: EA SHORT contract → valid paper contract, paper_only,
  buy_to_cover; a stop-below-entry variant → NO_TRADE with
  `STOP_NOT_ABOVE_ENTRY`.
- NO_TRADE: missing sizing → `MISSING_SIZE_FRAC`; prose intents without
  terms → explicit reason, nothing fabricated.

## 5. Phase-4 real-model eval proposal (NOT run)

- Scope: rerun `synthesize.synthesize()` on 6–10 saved case_artifacts
  (mixed Buy/Sell/ambiguous, e.g. IOVA, PCVX, TWST, ACN, ABCL, AMPL).
- Cost: one bounded bridge call per session batch (~$0.5–2 total; the
  translator call is a single batch, not per-ticker).
- Ceiling: **$5**. Command: `python3 -m alpha_rnd.synthesize <session>`
  in the contract worktree with artifacts copied to a temp EV dir.
- Evaluation: each emitted decision → `decision.from_intent` →
  validity + geometry + rejection reasons + paper sim on real bars;
  success = ≥1 valid LONG or SHORT contract + correct NO_TRADEs,
  zero fabricated levels (validate() already cross-checks numbers vs
  source text).
- Requires approval before any model call.

## Remaining integration blockers

1. Historical intents lack contract terms — only affects old data, fixed
   going forward by the required `decision` field + contract emission.
2. `decision` field lands in persisted intents but publish()/monitor are
   untouched — deliberately; executability still flows through
   `_machine_executable`.
3. SHORT path is data-model only — no monitor/watch semantics exist for
   it (paper sim objects only).
