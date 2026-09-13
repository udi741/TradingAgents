"""Stage 1 TEST 2: TOOL round trip through the REAL TradingAgents client.

NOT PRODUCTION CODE. Stage 1 feasibility test.

Uses the same @tool decorator and LangGraph ToolNode that TradingAgents uses.
The secret marker is generated ONLY when the Python tool executes — Devin
cannot know it in advance. PASS requires the full chain:

  client → bridge → Devin → tool_call → AIMessage.tool_calls →
  ToolNode → Python tool (generates marker) → ToolMessage →
  bridge → Devin → final answer containing the marker.
"""

import os
import secrets
import sys
import json
from typing import Annotated

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from langchain_core.tools import tool
from langchain_core.messages import (
    HumanMessage, SystemMessage, AIMessage, ToolMessage,
)
from langgraph.prebuilt import ToolNode
from langgraph.graph import StateGraph, MessagesState, START, END

from tradingagents.llm_clients.openai_client import OpenAIClient
from tradingagents.llm_clients.openai_client import LocalCompatibleChatOpenAI

BRIDGE_URL = "http://127.0.0.1:8765/v1"
MODEL = "devin-bridge-test"

# Global to track when the marker is generated (proves timing)
_MARKER_GENERATED_AT = None
_SECRET_MARKER = None


@tool
def get_stage1_secret_marker(
    reason: Annotated[str, "why you need the secret marker"],
) -> str:
    """Retrieve a secret marker that is generated at call time.

    Returns a fresh random marker. The marker does not exist until this
    function is called.
    """
    global _MARKER_GENERATED_AT, _SECRET_MARKER
    _MARKER_GENERATED_AT = "tool_executed"
    _SECRET_MARKER = "MARKER_" + secrets.token_hex(12)
    return f"Secret marker: {_SECRET_MARKER}"


def run_tool_test():
    print("[tool] === STAGE 1 TOOL ROUND TRIP TEST ===")

    # Use the REAL existing factory path for openai_compatible provider
    client = OpenAIClient(
        model=MODEL,
        base_url=BRIDGE_URL,
        provider="openai_compatible",
    )
    llm = client.get_llm()
    assert isinstance(llm, LocalCompatibleChatOpenAI)
    print(f"[tool] client class = {type(llm).__name__}")

    tools = [get_stage1_secret_marker]
    llm_with_tools = llm.bind_tools(tools)
    print(f"[tool] bound {len(tools)} tool(s): {[t.name for t in tools]}")

    # --- Step 1: initial request ---
    messages = [
        SystemMessage(content=(
            "You must use the available tool to retrieve a secret marker, "
            "then include the exact marker value in your final answer."
        )),
        HumanMessage(content=(
            "Call get_stage1_secret_marker to get the secret marker. "
            "Then tell me what the marker value is."
        )),
    ]

    print("[tool] step 1: invoking client with tools (live call)...")
    result = llm_with_tools.invoke(messages)
    print(f"[tool] step 1 result type = {type(result).__name__}")
    print(f"[tool] step 1 content = {result.content!r}")
    print(f"[tool] step 1 tool_calls = {result.tool_calls}")

    if not result.tool_calls:
        print("[tool] FAIL: no tool_calls in initial response")
        return False

    # Verify tool call structure
    tc = result.tool_calls[0]
    print(f"[tool] tool name = {tc['name']}")
    print(f"[tool] tool args = {tc['args']}")
    assert tc["name"] == "get_stage1_secret_marker", (
        f"Expected get_stage1_secret_marker, got {tc['name']}"
    )

    # --- Step 2: execute via LangGraph ToolNode (same as TradingAgents) ---
    print("[tool] step 2: executing via LangGraph ToolNode (compiled graph)...")
    tool_node = ToolNode(tools)
    # Use a minimal StateGraph — same mechanism TradingAgents uses, just
    # minimal. The compiled graph provides the runtime the ToolNode needs.
    sg = StateGraph(MessagesState)
    sg.add_node("tools", tool_node)
    sg.add_edge(START, "tools")
    sg.add_edge("tools", END)
    compiled_tools = sg.compile()
    tool_result = compiled_tools.invoke({"messages": [result]})
    tool_messages = tool_result["messages"]
    print(f"[tool] step 2: ToolNode produced {len(tool_messages)} message(s)")

    # Verify the Python tool actually executed (marker generated)
    assert _MARKER_GENERATED_AT == "tool_executed", (
        "Marker was NOT generated — tool did not execute"
    )
    print(f"[tool] step 2: marker generated at tool execution time: {_SECRET_MARKER}")

    # Get the ToolMessage (last message — ToolNode passes through the AIMessage)
    tool_msg = tool_messages[-1]
    assert isinstance(tool_msg, ToolMessage), (
        f"Expected ToolMessage, got {type(tool_msg)}"
    )
    print(f"[tool] step 2: ToolMessage content = {tool_msg.content!r}")
    print(f"[tool] step 2: ToolMessage tool_call_id = {tool_msg.tool_call_id}")

    # --- Step 3: feed ToolMessage back through the SAME client/bridge ---
    print("[tool] step 3: feeding ToolMessage back (live call)...")
    messages2 = messages + [result, tool_msg]
    result2 = llm.invoke(messages2)
    print(f"[tool] step 3 result type = {type(result2).__name__}")
    print(f"[tool] step 3 content = {result2.content!r}")

    # --- Step 4: verify the final answer contains the marker ---
    if _SECRET_MARKER in result2.content:
        print(f"[tool] PASS: final answer contains marker {_SECRET_MARKER}")
        return True
    else:
        print(f"[tool] FAIL: marker {_SECRET_MARKER!r} not in {result2.content!r}")
        return False


if __name__ == "__main__":
    ok = run_tool_test()
    sys.exit(0 if ok else 1)
