# Stage 3A Report — GLM-5.2 High Protocol Tuning

## Status: PASS

## 1. Root cause assessment

GLM-5.2 High returned narration instead of the bridge protocol because the
original prompt framing was too conversational. The prompt began with
"Your task: answer the conversation below" which GLM-5.2 High interpreted
as a conversational request, responding with "I'll start by fetching the
stock data and verified market snapshot in parallel, then retrieve the
selected indicators." — a plan narration rather than a structured tool
request.

The root cause was prompt framing, not a model capability limitation.
GLM-5.2 High can produce the sentinel-bounded JSON envelope when the prompt
clearly separates the bridge contract from the conversation, explicitly
states that tools are external and cannot be executed, includes few-shot
examples, and explicitly rejects narration.

## 2. Devin CLI capability inspection

### Relevant non-inference CLI options found

- `devin rules` — manages always-on context blobs (project-level
  instructions). Rules are loaded from `.windsurf/rules/*.md` in the working
  directory.
- `--config <PATH>` — overrides the user config file.
- `--permission-mode` — controls tool permission auto-approval.

### Project/custom instruction mechanism found: YES

The Devin CLI supports project-level rules via `.windsurf/rules/*.md`
files in the working directory. When `devin -p` runs with `cwd=runtime_dir`,
it would load any `.windsurf/rules/*.md` files from that directory as
always-on context.

### Mechanism used: NO

A prompt-only fix was sufficient. All four live probes passed with the
redesigned prompt. No project-level rules were needed. The prompt-only
approach is simpler, more portable, and doesn't require additional runtime
workspace setup.

## 3. Prompt changes

The production prompt builder (`devin_bridge/executor.py build_prompt()`)
was redesigned with the following changes:

### Before (failed)

```
Your task: answer the conversation below.
Format your answer as a JSON object wrapped in these markers:
...
JSON shapes:
  Final answer: ...
  Request a tool: ...
```

### After (passed)

The new prompt has four clearly separated sections:

1. **BRIDGE RESULT PROTOCOL** (prominent, at the beginning):
   - "You are performing one deterministic next-message generation step
     for an external application."
   - "External tools listed below are NOT tools available to you directly.
     They belong to the calling application. You CANNOT execute them."
   - "If one or more of those tools are needed, do NOT execute them and do
     NOT say that you will execute them. Return a tool REQUEST through the
     result protocol below."
   - Explicit anti-narration rules: "Do NOT say 'I'll fetch', 'I'll start
     by', 'Let me', 'I need to call', or similar."

2. **FORMAT EXAMPLES** (few-shot, generic not AAPL):
   - Example A: FINAL response
   - Example B: single TOOL_CALL
   - Example C: multiple TOOL_CALLS

3. **ADVERTISED EXTERNAL TOOLS** (renamed from "ADVERTISED TOOL DEFINITIONS"):
   - "request only, do NOT execute"
   - "These tools are executed by the calling application, not by you."

4. **CONVERSATION DATA** (unchanged structure)

5. **REQUIRED OUTPUT** (repeated at the end):
   - "Respond with ONLY the result block below. No narration, no
     explanations, no markdown fences, no text before or after."
   - "If a tool is needed, return the TOOL_CALL envelope. Do NOT say
     'I'll call' or 'I'll fetch' — return the envelope."

The output contract (`protocol.py build_output_contract()`) was also
strengthened with anti-narration language.

## 4. Parser changes

**No parser changes.** The sentinel-only parser remains strict. No
fallback to loose JSON extraction. No prose interpretation. No regex
inference of tool names. If GLM outputs "I'll call get_stock_data", the
request still fails.

## 5. Offline tests

### Bridge tests

```
python -m pytest tests/test_devin_bridge.py -q
→ 96 passed, 0 failed
```

(was 89; added 7 new prompt structure tests)

### Upstream tests

```
python -m pytest -m "not integration" -q
→ 772 passed, 1 skipped, 1 deselected, 0 failures
```

(676 upstream + 96 bridge = 772 total)

## 6. GLM probe A — FINAL

| Item | Value |
|---|---|
| PASS/FAIL | PASS |
| Nonce | STAGE3A_PROBE_A_abc123 |
| Protocol output type | FINAL |
| Content | "2+2 equals 4. STAGE3A_PROBE_A_abc123" |
| Nonce present | YES |
| Live call # | 1 |
| Duration | 1.8s |
| Model | glm-5-2 |
| Alias | devin-quick |

## 7. GLM probe B — TOOL

| Item | Value |
|---|---|
| PASS/FAIL | PASS |
| Requested tool | get_secret_value |
| Arguments | {"key": "treasure"} |
| AIMessage.tool_calls evidence | YES — `[{'name': 'get_secret_value', 'args': {'key': 'treasure'}, ...}]` |
| Narration present | NO — content was empty |
| Live call # | 2 |
| Duration | 1.7s |
| Model | glm-5-2 |
| Alias | devin-quick |

## 8. GLM probe C — STRUCTURED OUTPUT

| Item | Value |
|---|---|
| PASS/FAIL | PASS |
| Schema | ResearchPlan |
| Actual Python type | `tradingagents.agents.schemas.ResearchPlan` |
| Recommendation | PortfolioRating.BUY |
| Nonce | STAGE3A_PROBE_C_def456 |
| Nonce present | YES — in rationale field |
| Strategic actions | "Open a 5% position to establish initial exposure consistent with a Buy rating." |
| Free-text fallback | NO |
| Live call # | 3 |
| Duration | 2.3s |
| Model | glm-5-2 |
| Alias | devin-deep |

## 9. Optional Market Analyst-like reproduction

| Item | Value |
|---|---|
| RUN/NOT RUN | RUN |
| Result | PASS |
| Output type | TOOL_CALLS |
| Tool requested | get_stock_data |
| Arguments | {"symbol": "AAPL", "start_date": "2026-08-11", "end_date": "2026-09-11"} |
| Narration | NO — content was empty |
| Live call # | 4 |
| Duration | 1.9s |
| Model | glm-5-2 |
| Alias | devin-quick |

This reproduction used the actual TradingAgents market tools
(`get_stock_data`, `get_indicators`, `get_verified_market_snapshot`) and a
Market Analyst-like system instruction. GLM-5.2 High correctly returned a
`get_stock_data` TOOL_CALL instead of narrating "I'll start by fetching..."
— exactly the scenario that failed in Stage 3.

## 10. Total Stage 3A Devin inference calls

| Item | Value |
|---|---|
| Count | 4 |
| Ceiling | 6 |
| All model IDs | glm-5-2 |

## 11. Model-neutrality

| Item | Value |
|---|---|
| Same prompt used for all models | YES |
| Model-specific branch added | NO |

The prompt redesign is model-neutral. No `if model == "glm-5-2"` branches.
The same prompt is used for all Devin models.

## 12. Core source integrity

```
git diff --stat tradingagents/ cli/ → empty
git diff --stat devin_bridge/ → empty (all untracked)
```

### devin_bridge/ files changed

- `devin_bridge/executor.py` — redesigned `build_prompt()` with bridge
  contract, few-shot examples, anti-narration rules, external tool
  distinction
- `devin_bridge/protocol.py` — strengthened `build_output_contract()`
  with anti-narration language
- `tests/test_devin_bridge.py` — 7 new prompt structure tests

## 13. Remaining limitations

1. No live full TradingAgents analysis run yet (Stage 3 retry needed)
2. No streaming (`stream=true` rejected)
3. No token usage tracking (reports 0)
4. Isolation hardening (`Fetch(*)` unproven; read/grep/glob not
   live-tested)
5. No multi-turn tool chaining tested live through the full graph
6. The prompt is longer due to few-shot examples, which may increase
   token usage per request

## 14. Recommendation

READY_TO_RETRY_STAGE_3_WITH_GLM

## 15. USER ACTION REQUIRED

Authorize one clean Stage 3 retry: run the original `tradingagents` CLI
end-to-end through the production bridge with the default GLM-5.2 High
model, using the same test configuration (AAPL, 2026-09-11, Market
Analyst only, 1 debate / 1 risk round).

## 16. Resume point

Next task: Stage 3 retry — run the original TradingAgents CLI end-to-end
through the production bridge with the tuned prompt and default GLM-5.2
High model. Requires new live Devin inference budget authorization.
