"""Stage 1 TEST 3: SCHEMA through the REAL TradingAgents client (offline).

NOT PRODUCTION CODE. Stage 1 feasibility test.

Uses the REAL existing LocalCompatibleChatOpenAI.with_structured_output()
with a fake Devin executor (no live call — budget exhausted at 12/12).

The SCHEMA mechanism uses function_calling: the Pydantic schema is bound as
a tool, Devin returns a tool_call, and LangChain parses it into a Pydantic
instance. This is the SAME tool_call mechanism proven in the live TOOL test.
This offline test proves the bridge + LangChain structured-output machinery
works end-to-end with a fake Devin tool_call response.
"""

import json
import os
import secrets
import sys
import threading
import http.client
import time
from unittest.mock import patch, MagicMock
from pydantic import BaseModel, Field
from typing import Literal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.dirname(__file__))

from tradingagents.llm_clients.openai_client import OpenAIClient
from tradingagents.llm_clients.openai_client import LocalCompatibleChatOpenAI
import bridge

BRIDGE_PORT = 8766  # different port from the live bridge


# ---------------------------------------------------------------------------
# Test schema (similar to TradingAgents' decision schemas)
# ---------------------------------------------------------------------------


class Stage1Decision(BaseModel):
    """Similar in behavior to TradingAgents' PortfolioDecision/TraderProposal."""
    decision: Literal["BUY", "SELL", "HOLD"] = Field(
        description="The trading decision"
    )
    confidence: int = Field(
        description="Confidence score 0-100", ge=0, le=100
    )
    nonce: str = Field(description="The exact nonce from the request")


# ---------------------------------------------------------------------------
# Fake bridge server (replaces Devin with a canned tool_call response)
# ---------------------------------------------------------------------------


class FakeBridgeHandler(bridge.BridgeHandler):
    """Override _invoke_devin to return a canned tool_call envelope."""

    def _fake_devin(self, prompt, export_path=None):
        # The fake Devin sees the schema as a tool and returns a tool_call
        # with the exact field values the test expects.
        nonce = "SCHEMA_NONCE_OFFLINE_abc123"
        # Extract the expected values from the prompt
        envelope = json.dumps({
            "type": "tool_call",
            "name": "Stage1Decision",
            "arguments": {
                "decision": "BUY",
                "confidence": 85,
                "nonce": nonce,
            }
        })
        return envelope

    def do_POST(self):
        # Patch _invoke_devin for this request
        with patch.object(bridge, "_invoke_devin", self._fake_devin):
            super().do_POST()


def start_fake_bridge():
    server = bridge.ThreadingHTTPServer(
        ("127.0.0.1", BRIDGE_PORT), FakeBridgeHandler
    )
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server


def run_schema_test():
    nonce = "SCHEMA_NONCE_OFFLINE_abc123"
    print(f"[schema] nonce = {nonce}")
    print("[schema] NOTE: offline test with fake Devin (budget exhausted at 12/12)")

    # Start fake bridge
    server = start_fake_bridge()
    time.sleep(0.5)
    print(f"[schema] fake bridge on http://127.0.0.1:{BRIDGE_PORT}")

    try:
        # Use the REAL existing factory path for openai_compatible provider
        client = OpenAIClient(
            model="devin-bridge-test",
            base_url=f"http://127.0.0.1:{BRIDGE_PORT}/v1",
            provider="openai_compatible",
        )
        llm = client.get_llm()
        assert isinstance(llm, LocalCompatibleChatOpenAI)
        print(f"[schema] client class = {type(llm).__name__}")

        # Use the REAL with_structured_output method
        from langchain_core.messages import HumanMessage, SystemMessage
        structured_llm = llm.with_structured_output(Stage1Decision)
        print(f"[schema] structured_llm type = {type(structured_llm).__name__}")

        messages = [
            SystemMessage(content="You are a trading decision model."),
            HumanMessage(content=(
                f"Make a trading decision. Use decision=BUY, confidence=85, "
                f"and nonce={nonce}. Return the structured result."
            )),
        ]

        result = structured_llm.invoke(messages)
        print(f"[schema] result type = {type(result).__name__}")
        print(f"[schema] result = {result!r}")

        # Verify it's the actual Pydantic instance
        if not isinstance(result, Stage1Decision):
            print(f"[schema] FAIL: expected Stage1Decision, got {type(result)}")
            return False

        # Verify field values
        if result.decision != "BUY":
            print(f"[schema] FAIL: decision={result.decision!r}, expected BUY")
            return False
        if result.confidence != 85:
            print(f"[schema] FAIL: confidence={result.confidence}, expected 85")
            return False
        if result.nonce != nonce:
            print(f"[schema] FAIL: nonce={result.nonce!r}, expected {nonce!r}")
            return False

        print(f"[schema] PASS: Pydantic instance with correct fields")
        print(f"[schema]   decision = {result.decision}")
        print(f"[schema]   confidence = {result.confidence}")
        print(f"[schema]   nonce = {result.nonce}")
        return True

    finally:
        server.shutdown()


if __name__ == "__main__":
    ok = run_schema_test()
    sys.exit(0 if ok else 1)
