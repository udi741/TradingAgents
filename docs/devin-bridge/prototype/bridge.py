"""Stage 1 disposable prototype: local OpenAI Chat Completions bridge to Devin CLI.

NOT PRODUCTION CODE. Stage 1 feasibility prototype only.

Receives OpenAI Chat Completions requests from TradingAgents' existing
LocalCompatibleChatOpenAI client, translates each request into a single
fresh `devin -p` invocation, parses a strict JSON envelope from Devin's
stdout, and translates it back into an OpenAI Chat Completions response.

Each request is an isolated Devin invocation. No --continue/--resume.
"""

import json
import os
import re
import subprocess
import sys
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEVIN_BIN = os.environ.get("DEVIN_BIN", "/home/udi/.local/bin/devin")
DEVIN_RUNTIME_DIR = os.environ.get(
    "DEVIN_RUNTIME_DIR", "/tmp/devin-stage1-runtime"
)
DEVIN_MODEL = os.environ.get("DEVIN_MODEL", "claude-sonnet-5-medium")
BRIDGE_PORT = int(os.environ.get("BRIDGE_PORT", "8765"))
DEVIN_TIMEOUT = int(os.environ.get("DEVIN_TIMEOUT", "180"))

# ---------------------------------------------------------------------------
# Strict envelope protocol
# ---------------------------------------------------------------------------
#
# Devin MUST respond with a single JSON object on stdout. The bridge extracts
# it deterministically: it scans for the LAST balanced JSON object in the
# output (Devin may emit preamble/prose before the envelope). If no JSON
# object is found, or the object is malformed, the bridge fails closed.
#
# Envelope shapes:
#   {"type": "final", "content": "<text>"}
#   {"type": "tool_call", "name": "<tool>", "arguments": {<json object>}}
#
# The bridge NEVER infers a tool call from prose. Only a valid envelope with
# type "tool_call" and a name present in the request's tools array is accepted.

_ENVELOPE_RE = re.compile(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", re.DOTALL)


class BridgeError(Exception):
    """Explicit bridge failure. Never silently returns an empty report."""


def _extract_envelope(raw: str) -> dict:
    """Deterministically extract the last balanced JSON object from raw text.

    Finds all top-level JSON object candidates via regex, tries to parse each
    from last to first, and returns the first that parses. This is deterministic
    (not heuristic prose inference): it requires a real JSON object.
    """
    candidates = list(_ENVELOPE_RE.finditer(raw))
    for m in reversed(candidates):
        candidate = m.group(0)
        # Skip nested-inner matches by trying to parse; if it's a sub-object
        # of a larger valid object, the larger one will also be a candidate
        # and appear later in the reversed list only if it's standalone.
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict) and "type" in obj:
                return obj
        except json.JSONDecodeError:
            continue
    raise BridgeError(
        f"No valid JSON envelope with 'type' field found in Devin output. "
        f"Output length={len(raw)}; first 200 chars: {raw[:200]!r}"
    )


def _validate_envelope(envelope: dict, allowed_tools: dict[str, dict]) -> dict:
    """Strictly validate the parsed envelope against the protocol."""
    if not isinstance(envelope, dict):
        raise BridgeError(f"Envelope is not a dict: {type(envelope)}")

    etype = envelope.get("type")
    if etype == "final":
        content = envelope.get("content")
        if not isinstance(content, str):
            raise BridgeError(
                f"FINAL envelope 'content' must be string, got {type(content)}"
            )
        if not content:
            raise BridgeError("FINAL envelope 'content' is empty")
        return {"type": "final", "content": content}

    if etype == "tool_call":
        name = envelope.get("name")
        if not isinstance(name, str) or not name:
            raise BridgeError(f"TOOL_CALL envelope 'name' invalid: {name!r}")
        if name not in allowed_tools:
            raise BridgeError(
                f"TOOL_CALL name {name!r} not in advertised tools "
                f"{list(allowed_tools)}"
            )
        arguments = envelope.get("arguments", {})
        if not isinstance(arguments, dict):
            raise BridgeError(
                f"TOOL_CALL 'arguments' must be object, got {type(arguments)}"
            )
        return {"type": "tool_call", "name": name, "arguments": arguments}

    raise BridgeError(
        f"Unknown envelope type {etype!r}; expected 'final' or 'tool_call'"
    )


# ---------------------------------------------------------------------------
# Devin invocation
# ---------------------------------------------------------------------------


def _build_devin_prompt(messages: list, tools: list) -> str:
    """Serialize the OpenAI messages + tools into a single Devin prompt.

    The prompt asks Devin to format its answer as a single JSON object.
    Conversation history from the messages array is replayed so each Devin
    invocation is stateless. This is a formatting task, not an identity
    assertion — Devin is asked to *output* a JSON object, not to *become* a
    different system.
    """
    lines = []
    lines.append("Format your entire response as a single JSON object.")
    lines.append("Do not use any tools, shell commands, or file access.")
    lines.append("Do not include any text before or after the JSON object.")
    lines.append("")
    lines.append("Use one of these two JSON shapes exactly:")
    lines.append(
        '  To give a final answer: {"type": "final", "content": "<your answer text>"}'
    )
    lines.append(
        '  To request a tool: {"type": "tool_call", "name": "<tool_name>", '
        '"arguments": {<json object>}}'
    )
    lines.append("")

    if tools:
        lines.append("AVAILABLE TOOLS (you may only request these by name):")
        for t in tools:
            fn = t.get("function", t)
            name = fn.get("name", "?")
            params = fn.get("parameters", {})
            lines.append(f"  - {name}: {json.dumps(params)}")
        lines.append("")
        lines.append(
            "If the conversation needs a tool result to proceed, output a "
            "tool_call JSON. Otherwise output a final JSON with your answer. "
            "Never use a tool name not listed above."
        )
    else:
        lines.append("No tools are available. Output a final JSON.")

    lines.append("")
    lines.append("Conversation so far (role: content):")
    for msg in messages:
        role = msg.get("role", "?")
        content = msg.get("content", "")
        # Tool calls / tool results in the message
        tool_calls = msg.get("tool_calls")
        if tool_calls:
            tc_str = json.dumps(tool_calls)
            lines.append(f"  {role}: {content} [tool_calls={tc_str}]")
        elif role == "tool":
            tool_call_id = msg.get("tool_call_id", "?")
            lines.append(f"  {role} (id={tool_call_id}): {content}")
        else:
            lines.append(f"  {role}: {content}")

    lines.append("")
    lines.append("Output exactly one JSON object. Nothing else.")
    return "\n".join(lines)


def _invoke_devin(prompt: str, export_path: str | None = None) -> str:
    """Run a single fresh `devin -p` invocation. Returns stdout text."""
    cmd = [
        DEVIN_BIN,
        "--respect-workspace-trust", "false",
        "--model", DEVIN_MODEL,
        "-p",
        "--",
        prompt,
    ]
    if export_path:
        cmd = [
            DEVIN_BIN,
            "--respect-workspace-trust", "false",
            "--model", DEVIN_MODEL,
            "--export", export_path,
            "-p",
            "--",
            prompt,
        ]

    try:
        proc = subprocess.run(
            cmd,
            cwd=DEVIN_RUNTIME_DIR,
            capture_output=True,
            text=True,
            timeout=DEVIN_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        raise BridgeError(
            f"Devin CLI timed out after {DEVIN_TIMEOUT}s"
        )
    except FileNotFoundError:
        raise BridgeError(f"Devin binary not found at {DEVIN_BIN}")

    if proc.returncode != 0:
        raise BridgeError(
            f"Devin CLI exited non-zero (code={proc.returncode}). "
            f"stderr: {proc.stderr[:500]}"
        )

    raw = proc.stdout
    if not raw.strip():
        raise BridgeError("Devin CLI returned empty stdout")
    return raw


# ---------------------------------------------------------------------------
# OpenAI Chat Completions response translation
# ---------------------------------------------------------------------------


def _make_final_response(content: str, model: str) -> dict:
    """Build an OpenAI Chat Completions response for a final text answer."""
    return {
        "id": f"chatcmpl-bridge-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


def _make_tool_call_response(
    tool_name: str, arguments: dict, model: str
) -> dict:
    """Build an OpenAI Chat Completions response for a tool call."""
    call_id = f"call_bridge_{uuid.uuid4().hex[:12]}"
    return {
        "id": f"chatcmpl-bridge-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": tool_name,
                                "arguments": json.dumps(arguments),
                            },
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


# ---------------------------------------------------------------------------
# HTTP server
# ---------------------------------------------------------------------------


class BridgeHandler(BaseHTTPRequestHandler):
    def _send_json(self, code: int, body: dict):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_error(self, code: int, message: str):
        self._send_json(code, {"error": {"message": message, "type": "bridge_error"}})

    def do_POST(self):
        path = self.path
        if path != "/v1/chat/completions":
            self._send_error(404, f"Unknown path: {path}")
            return

        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length).decode())
        except Exception as e:
            self._send_error(400, f"Invalid JSON body: {e}")
            return

        messages = body.get("messages", [])
        tools = body.get("tools", [])
        model = body.get("model", DEVIN_MODEL)

        allowed_tools: dict[str, dict] = {}
        for t in tools:
            fn = t.get("function", t)
            allowed_tools[fn.get("name")] = fn

        prompt = _build_devin_prompt(messages, tools)

        export_path = None
        if os.environ.get("BRIDGE_EXPORT_DIR"):
            export_path = os.path.join(
                os.environ["BRIDGE_EXPORT_DIR"],
                f"devin-export-{uuid.uuid4().hex[:8]}.json",
            )

        try:
            raw = _invoke_devin(prompt, export_path)
            envelope = _extract_envelope(raw)
            validated = _validate_envelope(envelope, allowed_tools)
        except BridgeError as e:
            self._send_error(502, str(e))
            return

        if validated["type"] == "final":
            resp = _make_final_response(validated["content"], model)
        else:
            resp = _make_tool_call_response(
                validated["name"], validated["arguments"], model
            )
        self._send_json(200, resp)

    def do_GET(self):
        # Health check
        if self.path == "/v1/models":
            self._send_json(200, {
                "object": "list",
                "data": [{"id": DEVIN_MODEL, "object": "model"}],
            })
        elif self.path == "/health":
            self._send_json(200, {"status": "ok"})
        else:
            self._send_error(404, f"Unknown path: {self.path}")

    def log_message(self, fmt, *args):
        sys.stderr.write(
            f"[bridge] {self.address_string()} - {fmt % args}\n"
        )


def main():
    server = ThreadingHTTPServer(("127.0.0.1", BRIDGE_PORT), BridgeHandler)
    print(f"[bridge] listening on http://127.0.0.1:{BRIDGE_PORT}", file=sys.stderr)
    print(f"[bridge] devin={DEVIN_BIN} model={DEVIN_MODEL}", file=sys.stderr)
    print(f"[bridge] runtime_dir={DEVIN_RUNTIME_DIR}", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
