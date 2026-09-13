# Stage 4A Report — Offline Failure Diagnosis + Minimal Hardening

## Status: PASS

## 1. Exact failure classification

Classification: **A/B/C/D/E — cannot distinguish without raw output, but definitively one of these (non-whitespace trailing content after valid JSON)**

The error message `Invalid JSON between sentinels: Extra data: line 2 column 1 (char 10856)` is from Python's `json.loads()`. "Extra data" means:
- The parser successfully parsed one complete JSON value (10856 chars, single line)
- A newline followed
- Non-whitespace content appeared on line 2, column 1

This is NOT trailing whitespace (Python's `json.loads()` already accepts trailing whitespace — verified offline). This is GLM appending non-whitespace content after the valid JSON object, before the END sentinel.

The raw failed output was NOT captured by the bridge (observability gap — the executor does not log raw stdout, and the runtime was auto-cleaned on shutdown). However, the error structure is unambiguous: GLM produced a valid 10856-char JSON object, then appended non-whitespace content. The exact type of extra content (duplicate JSON, repeated envelope, prose, markdown fence, or duplicated report text) cannot be determined without the raw output.

## 2. Sanitized failed-output tail

The raw output was not captured by the bridge. This is an observability gap that has been fixed in this stage (see Changes Made below — raw output tail is now logged on protocol error).

From the error message alone:
- first JSON tail: (not available — raw output not captured)
- extra data beginning: (not available — raw output not captured)

The error message confirms:
- total chars between sentinels: > 10856 (first JSON) + extra content
- first JSON object: 10856 chars (single line, no internal newlines)
- extra content: starts at line 2, column 1 (non-whitespace)

## 3. Sizes

- total chars between sentinels: unknown (raw output not captured)
- first JSON chars: 10856 (from error position)
- extra chars: unknown (raw output not captured)
- final report chars: ~10856 (the JSON content field contains the market report)

## 4. Was trailing whitespace the cause?

**NO.** Verified offline: Python's `json.loads()` accepts trailing whitespace (spaces, newlines, tabs) after a valid JSON value. The "Extra data" error is only raised when non-whitespace content follows the JSON value. The error "line 2 column 1 (char 10856)" confirms non-whitespace content on line 2.

## 5. Parser behavior

- strict whole-content JSON parse: **YES** — `parse_sentinel()` extracts content between sentinels, strips it, and calls `json.loads()` on the entire content. This is correct: it rejects any non-whitespace trailing content after the first JSON value.
- parser weakened: **NO** — the parser remains strict. No "first JSON wins" logic. No regex extraction. No loose JSON fallback. No trailing-whitespace tolerance hack (unnecessary — `json.loads()` already accepts trailing whitespace).

## 6. Root-cause assessment

GLM-5.2 High produced a valid 10856-char JSON envelope (a `{"type":"final","content":"..."}` with a large market report), then appended non-whitespace content after the closing `}` and before the END sentinel. This occurred on a long-context final-report call (15 messages, all tool results replayed).

The root cause is GLM not terminating its output after the JSON object — it continued generating content (likely duplicated report text, a second JSON object, or commentary) instead of immediately emitting the END sentinel. This is a model output-fidelity issue on large final responses, not a bridge bug or a TradingAgents bug.

Contributing factor: the original prompt did not explicitly state "after the closing `}`, emit the END sentinel immediately" or "do not emit a second JSON object." The few-shot examples showed correct format but did not explicitly prohibit trailing content.

## 7. Chosen fix

**PROMPT_REINFORCEMENT**

The diagnosis clearly indicates GLM produced a correct first JSON object and then appended extra content. The prompt reinforcement approach is appropriate: explicitly state that exactly ONE JSON object must be emitted, the END sentinel must follow the closing `}` immediately, no second JSON object, no repeated content, no trailing commentary.

## 8. Changes made

### `devin_bridge/executor.py` — prompt reinforcement

Added a CRITICAL paragraph after the sentinel format specification:

```
CRITICAL: Emit exactly ONE JSON object between the sentinels.
Once you emit the closing `}` of the JSON object, immediately emit
the END sentinel (END_TRADINGAGENTS_BRIDGE_RESULT). Do NOT emit a
second JSON object. Do NOT repeat the report content outside the
JSON. Do NOT append commentary, notes, or any text after the JSON
object. The END sentinel must follow the closing `}` with no content
between them except optionally a single newline.
```

### `devin_bridge/protocol.py` — output contract reinforcement

Added to `build_output_contract()`:

```
Emit exactly ONE JSON object. After the closing `}`, emit the END
sentinel immediately. Do NOT emit a second JSON object, repeat
content, or append any text after the JSON.
```

### `devin_bridge/server.py` — raw output capture on error

Added raw output tail logging (last 500 chars) on protocol error for future debugging. This is a defensive observability improvement, not a parser change:

```python
raw_tail = raw[-500:] if len(raw) > 500 else raw
logger.error("request=%s raw tail (last 500 chars): %r", request_id, raw_tail)
```

### `tests/test_devin_bridge.py` — 7 new offline tests

1. `test_prompt_states_exactly_one_json_object` — verifies prompt says "exactly ONE JSON object"
2. `test_prompt_states_no_second_json_object` — verifies prompt says "Do NOT emit a second JSON object"
3. `test_prompt_states_no_trailing_content` — verifies prompt says "Do NOT append" and "after the JSON"
4. `test_prompt_states_end_sentinel_immediately_after_json` — verifies prompt says "immediately emit" + END sentinel
5. `test_output_contract_states_one_json_object` — verifies output contract says "exactly ONE JSON object"
6. `test_parser_rejects_extra_data_after_json` — verifies parser rejects valid JSON + non-whitespace trailing content
7. `test_parser_accepts_trailing_whitespace_after_json` — verifies parser accepts valid JSON + whitespace (json.loads behavior)

## 9. Offline tests

- bridge: **103 passed** (was 96; added 7 new tests)
- upstream: **667 passed, 1 skipped, 10 deselected, 18 warnings, 73 subtests passed**
- combined: **770 passed, 0 failures**

## 10. New live Devin inference calls

**0** — no live Devin inference was used in this stage. All diagnosis was offline.

## 11. Core source integrity

- tradingagents/ diff: **empty**
- cli/ diff: **empty**
- devin_bridge/ changes: prompt reinforcement (executor.py, protocol.py), raw output capture on error (server.py)
- tests/ changes: 7 new offline tests
- implementation changes during run: YES — but confined to `devin_bridge/` and tests, as authorized

## 12. Recommendation

**READY_FOR_STAGE4_RETRY**

The prompt reinforcement directly addresses the root cause: GLM appending non-whitespace content after the JSON object. The reinforcement explicitly tells GLM to:
1. emit exactly ONE JSON object
2. emit the END sentinel immediately after the closing `}`
3. not emit a second JSON object
4. not repeat content outside the JSON
5. not append commentary after the JSON

The parser remains strict — no weakening. The raw output capture on error ensures future failures are diagnosable.

## 13. USER ACTION REQUIRED

Authorize one Stage 4 retry with the tuned Stage 4A prompt and the same test configuration (AAPL, 2026-09-11, all four analysts, 1 debate / 1 risk round, default GLM-5.2 High).

## 14. Resume point

Next task: Stage 4 retry — run the original TradingAgents CLI end-to-end with all four analysts through the production Devin bridge with the Stage 4A prompt reinforcement and default GLM-5.2 High model. Requires new live Devin inference budget authorization.
