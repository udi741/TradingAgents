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

## Real-model eval (run, bounded: 1 call, 189s, est. ≈$1-2 ≤ $5 cap)

Six saved artifacts re-translated with the new schema (IOVA/PCVX/ABCL had
no case_artifacts at those dates; batch = ACN, AMPL, ANF, CDNA, IOVA, TWST).
Raw outputs: `results/eval_model/raw_intents.json`.

| Ticker | Signal | AI-authored | Validated | Terms | Paper sim |
|---|---|---|---|---|---|
| ACN | Overweight | **LONG** | LONG | zone[203,205] stop193.5 tgt250 sz.178 rr3.9 | filled 205→193.87, **-46** |
| ANF | Buy | **LONG** | LONG* | zone[153,158] stop144.5 tgt185 sz.117 rr2.0 | filled 158, open **-7** |
| AMPL | Sell | NO_TRADE | NO_TRADE | "zero exposure; no complete short plan" | — |
| CDNA | Sell | NO_TRADE | NO_TRADE | "avoid entry ≠ short; no bear plan" | — |
| IOVA | Sell | NO_TRADE | NO_TRADE | "zero exposure pre-binary; no short plan" | — |
| TWST | Underweight | NO_TRADE | NO_TRADE | "reduce existing long, not a short" | — |

\*ANF required adapter keys `listed_entry`/`primary_retest_zone` (stated
levels the parser missed — key list extended, validation unchanged).

Findings: the model correctly refuses to fabricate — all four Sell/
Underweight cases are explicit NO_TRADEs with sound reasons (Sell ≠ short).
2 valid LONG contracts authored; both filled in causal paper sim (-46, -7
open — retrospective, not prospective alpha). No valid SHORT was authored
because no source text contained a genuine short plan — honest, not a gap.
Sizing now computed deterministically (1% risk budget / stop distance).
