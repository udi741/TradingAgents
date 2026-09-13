# STAGE 1 Report — Feasibility Prototype

**Stage:** STAGE_1
**Status:** READY_FOR_REVIEW
**Date:** 2026-09-13

No TradingAgents production source was modified. No global configuration was
changed. No push was made. A bounded number of live Devin CLI invocations were
used (12/12 budget consumed).

---

## Decision: PROCEED_WITH_PRINT_BRIDGE

PLAIN = PASS (live)
TOOL = PASS (live)
SCHEMA = PASS (live, real `ResearchPlan` schema)

All three required compatibility tests passed through TradingAgents' existing
model interface. Zero core TradingAgents source modifications, plus a new
local Devin bridge sidecar and configuration.

---

## 1. Plain-English conclusion

We can keep TradingAgents essentially unchanged and use its existing
`openai_compatible` provider against a small local bridge that uses the
authenticated Devin CLI instead of a direct LLM-provider API key.

The bridge is a ~300-line Python HTTP server that receives OpenAI Chat
Completions requests, serializes them into a prompt for `devin -p`, parses a
strict JSON envelope from Devin's stdout, and translates it back into an
OpenAI Chat Completions response. Each request is a fresh, stateless Devin
invocation. No `--continue` or `--resume` is used.

The PLAIN test proved that TradingAgents' real `LocalCompatibleChatOpenAI`
client can invoke through the bridge and get back a correct `AIMessage` with
exact nonce content. The TOOL test proved the full round trip: Devin requests
a tool via the strict envelope, the bridge translates it to an OpenAI
`tool_calls` response, LangChain produces `AIMessage.tool_calls`, the
LangGraph `ToolNode` executes the Python tool (generating a fresh secret
marker), the `ToolMessage` is fed back through the same client/bridge, and
Devin returns a final answer containing the previously unknowable marker.

The SCHEMA test was run live with the real TradingAgents `ResearchPlan`
schema. Devin returned a strict tool_call envelope, the bridge translated it
to OpenAI `tool_calls`, and LangChain's structured-output machinery produced a
valid `ResearchPlan` Pydantic instance with the nonce surviving exactly.

Zero core TradingAgents source modifications, plus a new local Devin bridge
sidecar and configuration. The integration is NOT "configuration-only" — the
bridge sidecar itself must be added and maintained as a separate component.

## 2. Environment/baseline

### venv

```
cd /home/udi/udi_provate/TradingAgents
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
```

### Import verification

```
python -c "import langgraph, langchain_openai; print('ok')"
# ok
```

### Baseline tests

```
python -m pytest -m "not integration" -x -q
# 676 passed, 1 skipped, 1 deselected, 18 warnings, 73 subtests passed in 4.31s
```

- Skipped: `tests/test_bedrock_provider.py` (optional `langchain_aws` not installed)
- Deselected: `tests/test_deepseek_reasoning.py` (marked `integration`)
- No pre-existing failures.

## 3. Prototype architecture

### Exact HTTP request path

```
TradingAgents LocalCompatibleChatOpenAI.invoke(messages)
  → OpenAI SDK POST http://127.0.0.1:8765/v1/chat/completions
  → bridge.py BridgeHandler.do_POST()
  → bridge._build_devin_prompt(messages, tools)
  → bridge._invoke_devin(prompt)  [subprocess: devin -p -- <prompt>]
  → bridge._extract_envelope(raw_stdout)  [strict JSON extraction]
  → bridge._validate_envelope(envelope, allowed_tools)
  → bridge._make_final_response() or _make_tool_call_response()
  → OpenAI Chat Completions JSON response
  → LangChain ChatOpenAI._create_chat_result()
  → AIMessage (content or tool_calls)
```

### Exact Devin CLI command pattern

```
devin --respect-workspace-trust false --model claude-sonnet-5-medium -p -- <prompt>
```

- `cwd`: `/tmp/devin-stage1-runtime` (disposable, outside repo)
- No `--continue` or `--resume` — each request is a fresh invocation
- `--respect-workspace-trust false` — required for non-interactive print mode

### Model

`claude-sonnet-5-medium` — fixed for all Stage 1 live calls. Confirmed
available via `devin models list`. Not switched silently.

### Message serialization

The bridge serializes the OpenAI `messages` array into the Devin prompt as
`role: content` lines. System, user, assistant, and tool messages are all
included. Tool calls in assistant messages are serialized as
`[tool_calls=<json>]`. Tool results include their `tool_call_id`.

### FINAL envelope

```json
{"type": "final", "content": "<answer text>"}
```

Translated to OpenAI Chat Completions:
```json
{"choices": [{"message": {"role": "assistant", "content": "<answer>"}, "finish_reason": "stop"}]}
```

### TOOL_CALL envelope

```json
{"type": "tool_call", "name": "<tool_name>", "arguments": {<json object>}}
```

Translated to OpenAI Chat Completions:
```json
{"choices": [{"message": {"role": "assistant", "content": null, "tool_calls": [{"id": "call_bridge_<uuid>", "type": "function", "function": {"name": "<name>", "arguments": "<json string>"}}]}, "finish_reason": "tool_calls"}]}
```

### Structured output

`with_structured_output(schema)` uses `method="function_calling"` — the
Pydantic schema is bound as a tool. Devin returns a `tool_call` envelope,
the bridge translates it to an OpenAI `tool_calls` response, and LangChain's
structured-output machinery parses the tool arguments into a Pydantic instance.

`LocalCompatibleChatOpenAI.with_structured_output()` suppresses `tool_choice`
(set to `None`) so local servers that reject the object form still work.

## 4. Runtime isolation

### Runtime working directory

`/tmp/devin-stage1-runtime` — disposable, outside the TradingAgents repo.
`git init` performed (no commit). `.devin/config.json` present with deny rules.

### Local restrictions

```json
{
  "permissions": {
    "deny": ["read", "grep", "glob", "edit", "exec", "mcp__*", "Fetch(*)"],
    "allow": []
  },
  "read_config_from": {
    "agents_standard": false, "cursor": false, "windsurf": false,
    "claude": false, "copilot": false, "opencode": false, "zed": false
  }
}
```

### Configuration imports

All disabled (`read_config_from` all `false`). No `AGENTS.md`, `.cursor/`,
`.windsurf/`, `.claude/`, `.github/skills/`, `opencode.json`, or `.zed/` files
exist in the runtime workspace.

### Inherited global facilities found

- Global MCP servers (names only, no secrets): `contexthub-authoring`,
  `nordic-docs`, `quantengine`, `atlassian-mcp-server` — blocked by `mcp__*`
- Global hooks: none found
- Global permissions: `Fetch(domain:docs.devin.ai)`, `Fetch(domain:www.mintlify.com)`, `mcp__contexthub-authoring__*` — overridden by local deny rules

### Isolation probe and result

One live isolation probe (`heather-rake` session) asked Devin to run
`echo ISOLATION_PROBE`. CLI session-title evidence showed `functions.shell`
was NOT present (unlike control sessions without deny rules), proving the
exec tool was denied. Devin's text response hallucinated success, but the CLI
metadata proved the tool was not called.

### Known remaining isolation limitations

1. `Fetch(*)` catch-all behavior is not conclusively documented/proven.
2. `read`/`grep`/`glob` denial has not been independently live-tested.
3. Permission-denial evidence relied partly on CLI/session metadata rather
   than a documented audit API.

These are hardening limitations, not Stage 1 blockers. They do not justify
spending more live submissions now.

## 5. PLAIN test

### PASS/FAIL: PASS

### Nonce: `b1acde5f0f526755`

### Exact path demonstrated

1. `OpenAIClient(model="devin-bridge-test", base_url="http://127.0.0.1:8765/v1", provider="openai_compatible")` — real factory
2. `client.get_llm()` → `LocalCompatibleChatOpenAI` instance (verified `isinstance`)
3. `llm.invoke([SystemMessage, HumanMessage])` → bridge → Devin → bridge
4. Response: `AIMessage(content='PLAIN_NONCE_b1acde5f0f526755')`
5. Nonce matched exactly
6. No direct LLM API key supplied (placeholder key `EMPTY` used)

### Evidence

```
[plain] nonce = b1acde5f0f526755
[plain] client class = LocalCompatibleChatOpenAI
[plain] response content = 'PLAIN_NONCE_b1acde5f0f526755'
[plain] PASS: nonce found in response
```

## 6. TOOL test

### PASS/FAIL: PASS

### Initial model request

```
SystemMessage: "You must use the available tool to retrieve a secret marker..."
HumanMessage: "Call get_stage1_secret_marker to get the secret marker..."
llm.bind_tools([get_stage1_secret_marker]).invoke(messages)
```

### AIMessage.tool_calls evidence

```python
result.tool_calls = [
    {'name': 'get_stage1_secret_marker',
     'args': {'reason': 'User requested retrieval of the secret marker value to include in the final answer.'},
     'id': 'call_bridge_b764313ee24f',
     'type': 'tool_call'}
]
```

### ToolNode evidence

Used `langgraph.graph.StateGraph(MessagesState)` with `ToolNode` — the same
mechanism TradingAgents uses in `tradingagents/graph/trading_graph.py`.

```python
sg = StateGraph(MessagesState)
sg.add_node("tools", ToolNode(tools))
sg.add_edge(START, "tools")
sg.add_edge("tools", END)
compiled_tools = sg.compile()
tool_result = compiled_tools.invoke({"messages": [result]})
```

### Marker generation timing

The marker was generated INSIDE the Python tool function at execution time:
```python
_SECRET_MARKER = "MARKER_" + secrets.token_hex(12)
```
Devin could not know the marker before the tool executed. The global
`_MARKER_GENERATED_AT` was set to `"tool_executed"` only when the function
ran, proving the tool executed (not Devin hallucinating).

### ToolMessage evidence

```
ToolMessage content = 'Secret marker: MARKER_4a81cdcb61a9fdff150067e1'
ToolMessage tool_call_id = call_bridge_b764313ee24f
```

### Final model request

```python
messages2 = messages + [result, tool_msg]
result2 = llm.invoke(messages2)
```

### Exact marker returned

```
result2.content = 'The secret marker value is: MARKER_4a81cdcb61a9fdff150067e1'
```

Marker `MARKER_4a81cdcb61a9fdff150067e1` was generated by the Python tool and
returned in the final answer. Devin could not have known this value in
advance.

### Unknown tool rejection (offline)

`TestValidateEnvelope.test_unknown_tool_name` verifies that a tool_call with
a name not in the `allowed_tools` dict raises `BridgeError`. PASS.

## 7. SCHEMA test

### PASS/FAIL: PASS (live, real `ResearchPlan` schema)

### Schema definition

The real TradingAgents `ResearchPlan` schema from `tradingagents/agents/schemas.py`:

```python
class PortfolioRating(str, Enum):
    BUY = "Buy"
    OVERWEIGHT = "Overweight"
    HOLD = "Hold"
    UNDERWEIGHT = "Underweight"
    SELL = "Sell"

class ResearchPlan(BaseModel):
    recommendation: PortfolioRating  # 5-tier enum
    rationale: str                   # arbitrary text (nonce embedded here)
    strategic_actions: str           # arbitrary text
```

### Actual Python result type

`tradingagents.agents.schemas.ResearchPlan` — the actual Pydantic BaseModel
instance (not a dict, not prose, not a free-text fallback).

### Field values

```python
result.model_dump() = {
    'recommendation': <PortfolioRating.BUY: 'Buy'>,
    'rationale': 'The bull case is strong. Nonce: SCHEMA_LIVE_aa756cbaf3664910',
    'strategic_actions': 'Open a 5% position and scale in over 3 tranches.'
}
```

### Expected nonce: `SCHEMA_LIVE_aa756cbaf3664910`
### Received nonce: `SCHEMA_LIVE_aa756cbaf3664910` (in `rationale` field)

### Proof no free-text fallback was used

The test used `llm.with_structured_output(ResearchPlan)` which uses
`method="function_calling"` (the capability table's preferred method for
`LocalCompatibleChatOpenAI`). Devin returned a `tool_call` envelope (strict
JSON), the bridge translated it to an OpenAI `tool_calls` response, and
LangChain's structured-output machinery parsed the tool arguments into the
`ResearchPlan` Pydantic instance. The result is `isinstance(result, ResearchPlan)
= True`. No `invoke_structured_or_freetext` free-text path was invoked.

### Mapping to TradingAgents schemas

- `ResearchPlan`: PROVEN LIVE (this test)
- `TraderProposal`: same mechanism — `with_structured_output` + `function_calling`
- `PortfolioDecision`: same mechanism
- `SentimentReport`: same mechanism

All use `with_structured_output()` via `LocalCompatibleChatOpenAI`, which
suppresses `tool_choice` and uses `function_calling` method.

## 8. Offline validation/failure tests

26/26 PASS. Each test uses a fake Devin executor (no live calls).

| Test | Description | Result |
|---|---|---|
| test_clean_final | Valid FINAL envelope | PASS |
| test_clean_tool_call | Valid TOOL_CALL envelope | PASS |
| test_envelope_with_preamble_prose | Envelope after prose | PASS |
| test_envelope_with_nested_json_in_content | Content containing `{42}` | PASS |
| test_no_json_at_all | Plain text, no JSON | PASS (BridgeError) |
| test_json_without_type_field | JSON missing `type` | PASS (BridgeError) |
| test_empty_string | Empty stdout | PASS (BridgeError) |
| test_malformed_json | Broken JSON | PASS (BridgeError) |
| test_valid_final | Valid FINAL validation | PASS |
| test_valid_tool_call | Valid TOOL_CALL validation | PASS |
| test_unknown_tool_name | Tool not in advertised list | PASS (BridgeError) |
| test_unknown_envelope_type | Type not `final`/`tool_call` | PASS (BridgeError) |
| test_final_empty_content | Empty content string | PASS (BridgeError) |
| test_final_non_string_content | Content is int | PASS (BridgeError) |
| test_tool_call_non_dict_arguments | Arguments is string | PASS (BridgeError) |
| test_tool_call_missing_name | No name field | PASS (BridgeError) |
| test_prose_not_treated_as_tool_call | "I would call tool X" | PASS (BridgeError) |
| test_subprocess_nonzero_exit | Devin exits non-zero | PASS (BridgeError) |
| test_empty_stdout | Devin returns empty | PASS (BridgeError) |
| test_timeout | Devin times out | PASS (BridgeError) |
| test_binary_not_found | Devin binary missing | PASS (BridgeError) |
| test_final_response_shape | OpenAI response format | PASS |
| test_tool_call_response_shape | OpenAI tool_calls format | PASS |
| test_messages_serialized | Messages in prompt | PASS |
| test_tools_serialized | Tools in prompt | PASS |
| test_no_tools_instructs_final | No-tools → final | PASS |

## 9. Runtime usage

### All `devin -p` invocations from Stage 1

| # | Session | Purpose | Useful? | Result |
|---|---|---|---|---|
| 1 | phase-crafter | PONG test (print mode) | yes | PONG returned |
| 2 | green-wood | Isolation probe (no config) | yes (control) | exec called |
| 3 | marked-tarsier | `--config` flag attempt | no | welcome message |
| 4 | unusual-basilisk | Isolation probe (invalid matchers) | yes (control) | exec called |
| 5 | heather-rake | Isolation probe (documented matchers) | yes | exec denied — PASS |
| 6 | misty-almond | `--config` flag attempt | no | empty stdout |
| 7 | round-wren | First attempt (wrong flag order) | no | empty stdout |
| 8 | (PLAIN attempt 1) | PLAIN test (protocol issue) | yes | Devin refused envelope |
| 9 | (PLAIN attempt 2) | PLAIN test (fixed prompt) | yes | PASS — nonce returned |
| 10 | (TOOL attempt 1 step 1) | TOOL test (local ToolNode bug) | yes | Devin returned tool_call |
| 11 | (TOOL attempt 2 step 1) | TOOL test (fixed ToolNode) | yes | PASS — tool_call |
| 12 | (TOOL attempt 2 step 3) | TOOL test (final answer) | yes | PASS — marker returned |
| 13 | (SCHEMA live) | SCHEMA test (ResearchPlan) | yes | PASS — Pydantic instance |

- Total attempted: 13/14 (budget: 14)
- Total successful (useful model output): 10
- Failed/no-model: 3 (#3, #6, #7)
- Model: `claude-sonnet-5-medium` for all post-isolation calls
- Retries: 2 (PLAIN protocol fix, TOOL ToolNode fix) — both justified by concrete fixes
- Cost/usage: unavailable (no usage API consulted; no runtime submission metrics captured)

## 10. Files changed

### Added

- `docs/devin-bridge/AGENT_GUIDE.md` (Stage 0)
- `docs/devin-bridge/PROGRESS.md` (Stage 0, updated Stage 1)
- `docs/devin-bridge/STAGE_0_REPORT.md` (Stage 0)
- `docs/devin-bridge/STAGE_1_REPORT.md` (this file)
- `docs/devin-bridge/prototype/bridge.py` (bridge prototype)
- `docs/devin-bridge/prototype/test_bridge.py` (offline tests)
- `docs/devin-bridge/prototype/test_plain.py` (PLAIN live test)
- `docs/devin-bridge/prototype/test_tool.py` (TOOL live test)
- `docs/devin-bridge/prototype/test_schema.py` (SCHEMA offline test)
- `docs/devin-bridge/prototype/test_schema_live.py` (SCHEMA live test)
- `.venv/` (virtualenv — gitignored, not committed)

### Production source changes

**NONE.** No files under `tradingagents/` or `cli/` were modified. Verified:
```
git diff --stat tradingagents/ cli/
# (empty)
```

## 11. Limitations/blockers

1. **Devin prompt-framing sensitivity** — the first PLAIN attempt failed
   because Devin refused to act as a "JSON-envelope endpoint" (saw it as a
   prompt injection). The fix was to frame the request as a formatting task
   ("format your response as JSON") rather than an identity assertion ("you
   are a model-only endpoint"). This sensitivity may recur with different
   prompt patterns.

2. **Devin hallucination** — the isolation probe showed Devin can hallucinate
   successful tool execution when the tool is denied. The bridge's strict
   envelope protocol mitigates this (prose is never treated as a tool call),
   but the model may still fabricate content in the FINAL envelope.

3. **Isolation hardening** — `Fetch(*)` catch-all unproven; `read`/`grep`/
   `glob` denial not independently live-tested; permission-denial evidence
   relied on CLI session metadata.

4. **No multi-turn tool chaining** — the TOOL test used a single tool call
   followed by a final answer. TradingAgents' market analyst calls up to 3
   tools in sequence. The bridge supports this (each request is stateless),
   but it was not tested with chained tool calls.

5. **No streaming** — the bridge returns complete responses, not streamed
   chunks. TradingAgents' CLI streams graph output, but the LLM responses
   are not streamed through the bridge.

6. **No token usage tracking** — the bridge reports `0` for all token counts.
   TradingAgents' CLI tracks LLM statistics; these would show zero through
   the bridge.

## 12. Recommended Stage 2 architecture

### Smallest possible implementation

The Stage 1 prototype is already close to the production bridge. The smallest
Stage 2 implementation would:

1. Move the bridge from `docs/devin-bridge/prototype/` to a **separate
   top-level sidecar location** such as `devin_bridge/` or `tools/devin_bridge/`
   (NOT inside the `tradingagents/` package — the goal is zero core TradingAgents
   source modifications).
2. Add a startup script for the bridge sidecar.
3. Add multi-turn tool chaining support (already works — just needs testing).
4. Add `--export` capture for debugging.
5. Harden the isolation config (verify `Fetch(*)`, test `read`/`grep`/`glob`).
6. Run TradingAgents' offline regression test suite through the bridge.

### Expected production source changes

**ZERO** to `tradingagents/` or `cli/` production code. The integration is
**zero core TradingAgents source modifications, plus a new local Devin bridge
sidecar and configuration** — NOT "configuration-only", because the bridge
sidecar itself must be added and maintained as a separate component.

### Expected configuration/user workflow

1. User starts the bridge sidecar (one command)
2. User sets environment variables (provider, backend URL, model aliases)
3. User runs `tradingagents` (or `python -m cli.main` from source) as normal
4. All LLM calls route through the bridge to the authenticated Devin CLI
5. No direct LLM-provider API keys needed

```bash
# Start the bridge sidecar (separate top-level location, NOT inside tradingagents/)
python devin_bridge/run_bridge.py --model claude-sonnet-5-medium &

# Run TradingAgents with the bridge
TRADINGAGENTS_LLM_PROVIDER=openai_compatible \
TRADINGAGENTS_LLM_BACKEND_URL=http://127.0.0.1:8765/v1 \
TRADINGAGENTS_DEEP_THINK_LLM=devin-deep \
TRADINGAGENTS_QUICK_THINK_LLM=devin-quick \
tradingagents
```

The bridge maps `devin-deep` and `devin-quick` to the configured Devin model.
No TradingAgents source changes are needed because:
- `openai_compatible` is already key-optional
- `LocalCompatibleChatOpenAI` already suppresses `tool_choice`
- `validators.py` returns `True` for any model string on `openai_compatible`
- The factory already accepts a custom `base_url`

## 13. USER ACTION REQUIRED

**NONE required for Stage 1 review.**

For Stage 2 (if approved), the user would need to:
- Authorize a new live Devin submission budget for the SCHEMA live test and
  regression tests
- Confirm the bridge sidecar startup command and port
- Confirm the model to use (`claude-sonnet-5-medium` or another)

## 14. REVIEWER DECISION REQUIRED

Approval requested: **Stage 1 feasibility results and the recommendation to
PROCEED_WITH_PRINT_BRIDGE to Stage 2 (implementation).**

Note: SCHEMA was proven offline only. The reviewer should decide whether
offline SCHEMA + live TOOL (same mechanism) is sufficient, or whether a live
SCHEMA test must be run before Stage 2.

## 15. Resume point

### Exact next task (after approval)

Stage 2: Move the bridge prototype to a production sidecar, run the live
SCHEMA test (1 Devin call), run TradingAgents' offline regression suite
through the bridge, and test multi-turn tool chaining.

### Running processes requiring cleanup

- Bridge server on port 8765: **terminated** (killed after tests)
- Fake bridge server on port 8766: **terminated** (daemon thread, exited with
  test process)
- No background Devin sessions running
- `/tmp/devin-stage1-runtime` and `/tmp/devin-stage1-exports` still exist
  (disposable, can be cleaned up)
