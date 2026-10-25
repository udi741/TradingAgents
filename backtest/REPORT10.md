# Research→execution funnel (all saved research, post-fix gates)

Reproduce: `python3 backtest/funnel.py` → `results/funnel.json`.
Uses corrected causal timing, production post-fix direction gates
(`synthesize` from merged main, read-only import), real bars 10-01..10-23.

## Funnel (prod 160 intents + R5B 84 intents, dedup where noted)

| Stage | Count | Rejection reasons |
|---|---|---|
| Discovered (pool) | ~28/session × 16 prod + 4 R5B | — |
| Researched intents | **224** | — |
| Ambiguous-rejected | 70 | no clear thesis |
| Reanalyze-only | 43 | trigger not met / watch only |
| Short-descriptive | 28 | bearish opinion, no contract |
| Non-executable watch | 53 | — |
| **Direction & contract** | LONG 37, SHORT 3, none 184 | NO_ENTRY_SPEC 124, NO_VALID_STOP 25, NON_POSITIVE_RR 12 |
| Executable LONG | **11** (6 AUTHORIZED + 5 gate-blocked) | — |
| Supportable SHORT (exp.) | **3** | 23 bearish intents lack entry spec or valid stop |
| Filled (LONG) | 6 (5 untriggered) | — |
| Filled (SHORT exp.) | 1 (2 untriggered) | — |

## Trade results (simulated, corrected timing, real bars, 10bps/side, 2%/yr borrow)

**LONG** (n=6): 1 win / 5 losses, net **-1,321.87**, expectancy -220, PF 0.07
ACN -92, PBF -124 (open), KOD -533, MGNI -119, P -547, SEZL +92 (open).
**SHORT experimental** (n=1): CDNA -36 (open). Zero valid SHORT contracts
were *authorized* historically — the 3 supportable ones are experimental
paper authoring only; none would have earned real money anyway.

## Quota analysis (WS1)

R5B researched all 28/session; production only the top-10. The 54
quota-excluded intents contained **12 executable candidates** (ETON, HESM,
KOD, TWST, XP, IESC, LW, MGNI, SEZL, UMAC) — quota DOES materially exclude
candidates. But exclusion didn't hurt returns: the excluded set held the
worst losers (KOD -533, MGNI -119; TWST -558 actual). The exclusion cost
was research coverage, not missed profit.

## What blocks research→trade (WS2)

1. `NO_ENTRY_SPEC` (124/224): intents written as prose without a parseable
   zone/level — the single largest blocker.
2. Ambiguity (70) — LLM hedge language rejected by design.
3. `NO_VALID_STOP` (25) + `NON_POSITIVE_RR` (12) — risk geometry missing
   or inverted.
4. Bearish theses almost never become contracts: 23/26 lacked an explicit
   short zone/level+stop; the framework has no SHORT contract path anyway
   (experimental `short_contract` predicate added in funnel.py —
   paper-only, requires short_zone/short level + valid stop + target below
   entry side).

## Answers

1. **Yes** — quota excludes ~60% of researched candidates incl. 12
   executable ones, but the exclusion was *protective* in this sample.
2. Prose-only intents without entry specs, missing stops, ambiguous
   language, and no SHORT contract path block research→trade.
3. **No** — the saved sample's contract-authorized LONGs lost -1,322 on
   6 trades (PF 0.07); supportable SHORTs were too few and lost marginally.
4. Minimal changes most directly improving trade generation:
   a. **Structured entry spec required at authoring** — force intents to
      carry machine-parseable zone+stop+target (removes 124/224 blocker).
   b. **Research-budget config**: DEEP_QUOTA stays 10; add an explicit
      `RESEARCH_BUDGET` env (e.g. up to 30) where extras run only when
      pool quality score justifies it — design-only, needs approval since
      each intent ≈ $1-3.
   c. SHORT contract type (paper-only) as implemented experimentally —
      gated behind a flag, never in production path.
EOF
git add backtest/funnel.py backtest/REPORT10.md backtest/results/funnel.json && git -c user.name="Devin" -c user.email="devin@localhost" commit -q -m "Research->execution funnel over prod+R5B intents; quota exclusion and contract-gap analysis" && git log --oneline -2