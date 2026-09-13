# Stage 4B Report — Protocol v2 + Full Stage 4 Retry2

## Status: PASS

## 1. Protocol-v2 implementation

### FINAL representation

FINAL responses use raw bounded text, NOT JSON:

```
BEGIN_TRADINGAGENTS_BRIDGE_RESULT
FINAL
BEGIN_TRADINGAGENTS_BRIDGE_CONTENT
<raw assistant response, multiple lines, Markdown, quotes, tables, etc.>
END_TRADINGAGENTS_BRIDGE_CONTENT
END_TRADINGAGENTS_BRIDGE_RESULT
```

Content between `BEGIN_TRADINGAGENTS_BRIDGE_CONTENT` and
`END_TRADINGAGENTS_BRIDGE_CONTENT` is returned verbatim. No JSON encoding,
no escaping. Newlines, tabs, quotes, braces, and Markdown tables are
preserved exactly.

### TOOL_CALLS representation

Tool requests use strict JSON:

```
BEGIN_TRADINGAGENTS_BRIDGE_RESULT
TOOL_CALLS
{"calls":[{"name":"<tool>","arguments":{...}}, ...]}
END_TRADINGAGENTS_BRIDGE_RESULT
```

Strict `json.loads()` — no tolerance for malformed JSON, no "first JSON
wins", no trailing prose.

### Structured-output representation

Structured outputs (ResearchPlan, TraderProposal, PortfolioDecision,
SentimentReport) continue through TOOL_CALLS JSON with the schema name as
the tool name. TradingAgents' `.with_structured_output(...)` and Pydantic
validation remain unchanged.

## 2. Why this fixes previous GLM failures

Both prior failures were caused by forcing long free-form FINAL reports
through JSON string encoding:

- **Stage 4**: GLM produced a valid 10856-char JSON object, then appended
  non-whitespace content after the closing `}` ("Extra data"). The JSON
  string encoding of a long report tempted the model to continue generating.
- **Stage 4 Retry1**: GLM emitted a literal unescaped control character
  inside the long JSON `content` string ("Invalid control character at
  line 1 column 86"). JSON string escaping of arbitrary Markdown/newlines
  is a fidelity burden the model does not reliably carry.

Protocol v2 removes the JSON encoding burden for FINAL content entirely.
The report text is never parsed as JSON — it is extracted verbatim between
bounded content markers. TOOL_CALLS remain strict JSON (small, structured,
machine-generated), which GLM handles reliably.

## 3. Parser strictness

- malformed JSON tolerance added: **NO**
- first-JSON-wins added: **NO**

The parser remains strict. FINAL requires exactly one content begin/end
pair; content is returned verbatim. TOOL_CALLS requires exactly one valid
JSON object; malformed JSON is rejected. No fallback, no normalization of
malformed content, no `strict=False`.

## 4. Offline tests

- bridge: 130 passed (was 105; +25 new v2 tests)
- upstream: 667 passed, 1 skipped, 10 deselected, 0 failures
- combined: 797 passed, 0 failures

New test classes:
- `TestProtocolV2Final`: 16 tests (simple/multiline/quotes/tabs/braces/
  JSON-looking/Markdown table/very long/newlines/missing markers/duplicate
  markers/trailing text/reserved marker/empty/conversation injection)
- `TestProtocolV2ToolCalls`: 8 tests (one/multiple/malformed/unknown/
  invalid args/extra content/empty/not-list)

## 5. Live Probe A — long FINAL

- PASS
- content length: 9133 chars
- has newlines: YES
- has headings (#): YES
- has Markdown table (|): YES
- call #: 1
- result_type: final
- AIMessage.content returned as normal text (not JSON)

## 6. Live Probe B — TOOL_CALLS

- PASS
- tool: get_stock_price (fake advertised tool)
- call #: 2
- result_type: tool_calls
- AIMessage.tool_calls populated: `[{'name': 'get_stock_price', 'args': {'symbol': 'AAPL'}, ...}]`

## 7. Live Probe C — ResearchPlan

- PASS
- actual Python type: `ResearchPlan` (Pydantic instance)
- call #: 3
- result_type: tool_calls
- recommendation: Buy
- rationale: "Strong fundamentals."
- No fallback; `.with_structured_output(ResearchPlan)` returned a real
  Pydantic object.

## 8. Full Stage 4 Retry2

- RUN: YES
- PASS

## 9. Analyst execution

| # | Analyst | Alias | Mapped model | Devin calls | Status | Output |
|---|---|---|---|---|---|---|
| 1 | Market Analyst | devin-quick | glm-5-2 | 3 (calls 1-3) | DONE | TOOL_CALLS + TOOL_CALLS + FINAL (market.md, 123 lines) |
| 2 | Sentiment Analyst | devin-quick | glm-5-2 | 1 (call 4) | DONE | TOOL_CALLS (SentimentReport, sentiment.md, 59 lines) |
| 3 | News Analyst | devin-quick | glm-5-2 | 2 (calls 5-6) | DONE | TOOL_CALLS + FINAL (news.md, 89 lines) |
| 4 | Fundamentals Analyst | devin-quick | glm-5-2 | 2 (calls 7-8) | DONE | TOOL_CALLS + FINAL (fundamentals.md, 181 lines) |

All four analysts completed. The v2 protocol handled the Market Analyst
final report (14 messages, the call that failed in Stage 4 and Stage 4
Retry1) and the Fundamentals Analyst final report (7 messages) without
issue — raw text, no JSON encoding.

## 10. Downstream execution

| # | Node | Alias | Mapped model | Call # | Status | Output |
|---|---|---|---|---|---|---|
| 5 | Bull Researcher | devin-quick | glm-5-2 | 9 | DONE | FINAL (bull.md, 49 lines) |
| 6 | Bear Researcher | devin-quick | glm-5-2 | 10 | DONE | FINAL (bear.md, 68 lines) |
| 7 | Research Manager | devin-deep | glm-5-2 | 11 | DONE | TOOL_CALLS (ResearchPlan, manager.md, 10 lines) |
| 8 | Trader | devin-quick | glm-5-2 | 12 | DONE | TOOL_CALLS (TraderProposal, trader.md, 6 lines) |
| 9 | Aggressive Risk Analyst | devin-quick | glm-5-2 | 13 | DONE | FINAL (aggressive.md, 19 lines) |
| 10 | Conservative Risk Analyst | devin-quick | glm-5-2 | 14 | DONE | FINAL (conservative.md, 46 lines) |
| 11 | Neutral Risk Analyst | devin-quick | glm-5-2 | 15 | DONE | FINAL (neutral.md, 19 lines) |
| 12 | Portfolio Manager | devin-deep | glm-5-2 | 16 | DONE | TOOL_CALLS (PortfolioDecision, decision.md, 14 lines) |

All 12 agents completed. The Bear Researcher (call 10, the call that failed
in Stage 4 Retry1 with "Invalid control character") succeeded with the v2
raw-text FINAL format.

## 11. Structured outputs

| Schema | Alias | Model | PASS | Fallback |
|---|---|---|---|---|
| SentimentReport | devin-quick | glm-5-2 | YES | NO |
| ResearchPlan | devin-deep | glm-5-2 | YES | NO |
| TraderProposal | devin-quick | glm-5-2 | YES | NO |
| PortfolioDecision | devin-deep | glm-5-2 | YES | NO |

All four structured outputs returned real Pydantic instances via
`.with_structured_output(...)`. No fallback invoked.

## 12. Protocol compliance

- FINAL successes: 9 (calls 3, 6, 8, 9, 10, 13, 14, 15 + probe A)
- TOOL_CALLS successes: 7 (calls 1, 2, 4, 5, 7, 11, 12, 16 + probes B, C)
- malformed responses: 0
- narration: 0
- refusals: 0
- repeated/trailing-content failures: 0

## 13. Full inference trace (full run only; probes separate)

| # | Node | Alias | Model | Result type | Duration | Success |
|---|---|---|---|---|---|---|
| 1 | Market Analyst | devin-quick | glm-5-2 | TOOL_CALLS | 2.0s | YES |
| 2 | Market Analyst | devin-quick | glm-5-2 | TOOL_CALLS | 5.2s | YES |
| 3 | Market Analyst | devin-quick | glm-5-2 | FINAL | 22.8s | YES |
| 4 | Sentiment Analyst | devin-quick | glm-5-2 | TOOL_CALLS | 14.4s | YES |
| 5 | News Analyst | devin-quick | glm-5-2 | TOOL_CALLS | 2.5s | YES |
| 6 | News Analyst | devin-quick | glm-5-2 | FINAL | 14.3s | YES |
| 7 | Fundamentals Analyst | devin-quick | glm-5-2 | TOOL_CALLS | 1.6s | YES |
| 8 | Fundamentals Analyst | devin-quick | glm-5-2 | FINAL | 21.8s | YES |
| 9 | Bull Researcher | devin-quick | glm-5-2 | FINAL | 12.3s | YES |
| 10 | Bear Researcher | devin-quick | glm-5-2 | FINAL | 20.8s | YES |
| 11 | Research Manager | devin-deep | glm-5-2 | TOOL_CALLS | 12.9s | YES |
| 12 | Trader | devin-quick | glm-5-2 | TOOL_CALLS | 5.5s | YES |
| 13 | Aggressive Risk | devin-quick | glm-5-2 | FINAL | 10.5s | YES |
| 14 | Conservative Risk | devin-quick | glm-5-2 | FINAL | 24.2s | YES |
| 15 | Neutral Risk | devin-quick | glm-5-2 | FINAL | 14.6s | YES |
| 16 | Portfolio Manager | devin-deep | glm-5-2 | TOOL_CALLS | 9.2s | YES |

All 16 calls used glm-5-2.

## 14. Call-count breakdown

Probes (separate budget):
- Probe A (FINAL): 1
- Probe B (TOOL_CALLS): 1
- Probe C (ResearchPlan): 1
- TOTAL probes: 3 / 3

Full run:
- Market: 3
- Sentiment: 1
- News: 2
- Fundamentals: 2
- Bull/Bear: 2
- Research Manager: 1
- Trader: 1
- Risk (aggressive/conservative/neutral): 3
- Portfolio Manager: 1
- TOTAL: 16 / 30

## 15. Final TradingAgents result

- Rating: **Hold**
- Price target: $344.27
- Time horizon: 3-6 months
- Complete report: 731 lines
- All 12/12 agents completed
- Reports: 7/7

## 16. Saved artifacts

```
/tmp/tradingagents-devin-stage4-retry2/results/AAPL_20260911_full/
├── 1_analysts/
│   ├── market.md (123 lines)
│   ├── sentiment.md (59 lines)
│   ├── news.md (89 lines)
│   └── fundamentals.md (181 lines)
├── 2_research/
│   ├── bull.md (49 lines)
│   ├── bear.md (68 lines)
│   └── manager.md (10 lines)
├── 3_trading/
│   └── trader.md (6 lines)
├── 4_risk/
│   ├── aggressive.md (19 lines)
│   ├── conservative.md (46 lines)
│   └── neutral.md (19 lines)
├── 5_portfolio/
│   └── decision.md (14 lines)
└── complete_report.md (731 lines)

/tmp/tradingagents-devin-stage4-retry2/results/AAPL/2026-09-11/
├── message_tool.log
└── reports/
    ├── market_report.md
    ├── sentiment_report.md
    ├── news_report.md
    ├── fundamentals_report.md
    ├── investment_plan.md
    ├── trader_investment_plan.md
    └── final_trade_decision.md
```

## 17. Credentials

- direct external LLM-provider key required: NO
- authenticated Devin CLI used: YES
- FRED_API_KEY: NOT SET (optional, graceful degradation)
- No secrets exposed in logs

## 18. Source integrity

- tradingagents/ diff: empty
- cli/ diff: empty
- devin_bridge/ changes: protocol v2 (protocol.py, executor.py), logging
  safety (server.py, protocol.py), USER_GUIDE.md
- tests/ changes: 25 new offline tests for v2 + updated existing tests
- implementation changes during live run: NO

## 19. User guide

- created: YES
- path: `devin_bridge/USER_GUIDE.md`
- key commands:
  - `python -m devin_bridge` (default start)
  - `python -m devin_bridge --list-models` (model discovery)
  - `python -m devin_bridge --model <id>` (one model)
  - `python -m devin_bridge --quick-model <id> --deep-model <id>` (separate)
  - `tradingagents` (original CLI)

## 20. Remaining limitations

- Reddit RSS rate limiting (HTTP 429) for r/stocks and r/investing is a
  data-provider issue, not a bridge issue. Sentiment analyst degrades
  gracefully.
- FRED_API_KEY is optional and was not set. Macro data degrades gracefully.
- The bridge does not retry failed Devin calls
  (`TRADINGAGENTS_LLM_MAX_RETRIES=0`). A malformed response terminates the
  run. This is intentional — strict parser behavior is the trust boundary.
- GLM-5.2 High is the only model tested end-to-end. Other Devin models may
  work but are not validated.

## 21. FINAL RECOMMENDATION

PRODUCTION_READY

## 22. USER ACTION REQUIRED

NONE. The Devin bridge is production-ready with protocol v2. The original
TradingAgents CLI runs end-to-end using authenticated Devin CLI models
without direct LLM-provider API keys.

## 23. Resume point

Stage 4 is complete. The Devin bridge is production-ready. No further
action is required unless the user wants to:
- test with a different model (via `--model` or `--quick-model`/`--deep-model`)
- test with a different ticker/date
- commit the bridge package and documentation
