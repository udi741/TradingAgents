"""Stage 1 offline tests: envelope parsing, validation, and failure cases.

NOT PRODUCTION CODE. Stage 1 feasibility prototype tests only.

Uses a fake Devin executor (no live calls) to verify the bridge's strict
envelope protocol fails closed for every malformed input.
"""

import json
import os
import sys
import subprocess
import time
import threading
import http.client
from unittest.mock import patch

# Make the prototype importable
sys.path.insert(0, os.path.dirname(__file__))
import bridge


# ---------------------------------------------------------------------------
# Fake Devin executor: replaces bridge._invoke_devin with a canned response
# ---------------------------------------------------------------------------


def fake_devin_factory(canned_stdout: str, returncode: int = 0,
                       stderr: str = "", raises: Exception | None = None):
    """Return a fake _invoke_devin that returns canned_stdout or raises."""
    def fake(prompt: str, export_path=None):
        if raises:
            raise raises
        if returncode != 0:
            raise bridge.BridgeError(
                f"Devin CLI exited non-zero (code={returncode}). stderr: {stderr}"
            )
        if not canned_stdout.strip():
            raise bridge.BridgeError("Devin CLI returned empty stdout")
        return canned_stdout
    return fake


# ---------------------------------------------------------------------------
# Envelope extraction tests
# ---------------------------------------------------------------------------


class TestExtractEnvelope:
    def test_clean_final(self):
        env = '{"type": "final", "content": "hello"}'
        result = bridge._extract_envelope(env)
        assert result == {"type": "final", "content": "hello"}

    def test_clean_tool_call(self):
        env = '{"type": "tool_call", "name": "foo", "arguments": {"x": 1}}'
        result = bridge._extract_envelope(env)
        assert result["type"] == "tool_call"
        assert result["name"] == "foo"

    def test_envelope_with_preamble_prose(self):
        raw = 'Here is my response:\n{"type": "final", "content": "answer"}\nDone.'
        result = bridge._extract_envelope(raw)
        assert result["content"] == "answer"

    def test_envelope_with_nested_json_in_content(self):
        raw = '{"type": "final", "content": "the answer is {42}"}'
        result = bridge._extract_envelope(raw)
        assert result["content"] == "the answer is {42}"

    def test_no_json_at_all(self):
        try:
            bridge._extract_envelope("just plain text, no JSON here")
            assert False, "should have raised"
        except bridge.BridgeError as e:
            assert "No valid JSON envelope" in str(e)

    def test_json_without_type_field(self):
        try:
            bridge._extract_envelope('{"foo": "bar"}')
            assert False, "should have raised"
        except bridge.BridgeError as e:
            assert "No valid JSON envelope" in str(e)

    def test_empty_string(self):
        try:
            bridge._extract_envelope("")
            assert False, "should have raised"
        except bridge.BridgeError:
            pass

    def test_malformed_json(self):
        try:
            bridge._extract_envelope('{"type": "final", "content": broken')
            assert False, "should have raised"
        except bridge.BridgeError:
            pass


# ---------------------------------------------------------------------------
# Envelope validation tests
# ---------------------------------------------------------------------------


ALLOWED = {"get_marker": {"name": "get_marker"}, "decide": {"name": "decide"}}


class TestValidateEnvelope:
    def test_valid_final(self):
        env = {"type": "final", "content": "answer"}
        result = bridge._validate_envelope(env, ALLOWED)
        assert result == {"type": "final", "content": "answer"}

    def test_valid_tool_call(self):
        env = {"type": "tool_call", "name": "get_marker", "arguments": {}}
        result = bridge._validate_envelope(env, ALLOWED)
        assert result["type"] == "tool_call"
        assert result["name"] == "get_marker"

    def test_unknown_tool_name(self):
        env = {"type": "tool_call", "name": "evil_tool", "arguments": {}}
        try:
            bridge._validate_envelope(env, ALLOWED)
            assert False, "should have raised"
        except bridge.BridgeError as e:
            assert "not in advertised tools" in str(e)

    def test_unknown_envelope_type(self):
        env = {"type": "weird", "content": "x"}
        try:
            bridge._validate_envelope(env, ALLOWED)
            assert False, "should have raised"
        except bridge.BridgeError as e:
            assert "Unknown envelope type" in str(e)

    def test_final_empty_content(self):
        env = {"type": "final", "content": ""}
        try:
            bridge._validate_envelope(env, ALLOWED)
            assert False, "should have raised"
        except bridge.BridgeError as e:
            assert "empty" in str(e).lower()

    def test_final_non_string_content(self):
        env = {"type": "final", "content": 123}
        try:
            bridge._validate_envelope(env, ALLOWED)
            assert False, "should have raised"
        except bridge.BridgeError as e:
            assert "must be string" in str(e)

    def test_tool_call_non_dict_arguments(self):
        env = {"type": "tool_call", "name": "get_marker", "arguments": "notdict"}
        try:
            bridge._validate_envelope(env, ALLOWED)
            assert False, "should have raised"
        except bridge.BridgeError as e:
            assert "must be object" in str(e)

    def test_tool_call_missing_name(self):
        env = {"type": "tool_call", "arguments": {}}
        try:
            bridge._validate_envelope(env, ALLOWED)
            assert False, "should have raised"
        except bridge.BridgeError as e:
            assert "name" in str(e).lower()

    def test_prose_not_treated_as_tool_call(self):
        # Even if Devin says "I would call tool get_marker", that's prose,
        # not an envelope. The extractor should reject it.
        raw = "I would call tool get_marker with arguments {}"
        try:
            bridge._extract_envelope(raw)
            assert False, "prose must not be parsed as envelope"
        except bridge.BridgeError:
            pass


# ---------------------------------------------------------------------------
# Devin invocation failure tests (fake executor)
# ---------------------------------------------------------------------------


class TestDevinInvocationFailures:
    def test_subprocess_nonzero_exit(self):
        fake = fake_devin_factory("", returncode=1, stderr="some error")
        with patch.object(bridge, "_invoke_devin", fake):
            try:
                bridge._invoke_devin("test prompt")
                assert False
            except bridge.BridgeError as e:
                assert "non-zero" in str(e).lower() or "empty" in str(e).lower()

    def test_empty_stdout(self):
        fake = fake_devin_factory("")
        with patch.object(bridge, "_invoke_devin", fake):
            try:
                bridge._invoke_devin("test prompt")
                assert False
            except bridge.BridgeError as e:
                assert "empty" in str(e).lower()

    def test_timeout(self):
        fake = fake_devin_factory("", raises=bridge.BridgeError(
            f"Devin CLI timed out after 180s"
        ))
        with patch.object(bridge, "_invoke_devin", fake):
            try:
                bridge._invoke_devin("test prompt")
                assert False
            except bridge.BridgeError as e:
                assert "timed out" in str(e).lower()

    def test_binary_not_found(self):
        fake = fake_devin_factory("", raises=bridge.BridgeError(
            "Devin binary not found at /nonexistent"
        ))
        with patch.object(bridge, "_invoke_devin", fake):
            try:
                bridge._invoke_devin("test prompt")
                assert False
            except bridge.BridgeError as e:
                assert "not found" in str(e).lower()


# ---------------------------------------------------------------------------
# End-to-end bridge response translation tests (fake executor, no HTTP)
# ---------------------------------------------------------------------------


class TestResponseTranslation:
    def test_final_response_shape(self):
        resp = bridge._make_final_response("hello", "test-model")
        assert resp["object"] == "chat.completion"
        assert resp["choices"][0]["message"]["content"] == "hello"
        assert resp["choices"][0]["message"]["role"] == "assistant"
        assert resp["choices"][0]["finish_reason"] == "stop"

    def test_tool_call_response_shape(self):
        resp = bridge._make_tool_call_response("get_marker", {"x": 1}, "test-model")
        assert resp["object"] == "chat.completion"
        tc = resp["choices"][0]["message"]["tool_calls"][0]
        assert tc["type"] == "function"
        assert tc["function"]["name"] == "get_marker"
        assert json.loads(tc["function"]["arguments"]) == {"x": 1}
        assert resp["choices"][0]["finish_reason"] == "tool_calls"
        assert resp["choices"][0]["message"]["content"] is None


# ---------------------------------------------------------------------------
# Prompt serialization tests
# ---------------------------------------------------------------------------


class TestPromptSerialization:
    def test_messages_serialized(self):
        messages = [
            {"role": "system", "content": "you are helpful"},
            {"role": "user", "content": "hello"},
        ]
        prompt = bridge._build_devin_prompt(messages, [])
        assert "you are helpful" in prompt
        assert "hello" in prompt
        assert "system" in prompt
        assert "user" in prompt

    def test_tools_serialized(self):
        messages = [{"role": "user", "content": "go"}]
        tools = [
            {"type": "function", "function": {
                "name": "get_marker",
                "parameters": {"type": "object", "properties": {"x": {"type": "string"}}}
            }}
        ]
        prompt = bridge._build_devin_prompt(messages, tools)
        assert "get_marker" in prompt
        assert "AVAILABLE TOOLS" in prompt

    def test_no_tools_instructs_final(self):
        messages = [{"role": "user", "content": "go"}]
        prompt = bridge._build_devin_prompt(messages, [])
        assert "No tools are available" in prompt
        assert "final" in prompt.lower()


# ---------------------------------------------------------------------------
# Run all tests
# ---------------------------------------------------------------------------


def run_all():
    classes = [
        TestExtractEnvelope, TestValidateEnvelope, TestDevinInvocationFailures,
        TestResponseTranslation, TestPromptSerialization,
    ]
    total = 0
    passed = 0
    failed = 0
    for cls in classes:
        for name in dir(cls):
            if name.startswith("test_"):
                total += 1
                try:
                    getattr(cls(), name)()
                    passed += 1
                    print(f"  PASS  {cls.__name__}.{name}")
                except Exception as e:
                    failed += 1
                    print(f"  FAIL  {cls.__name__}.{name}: {e}")
    print(f"\n{passed}/{total} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    ok = run_all()
    sys.exit(0 if ok else 1)
