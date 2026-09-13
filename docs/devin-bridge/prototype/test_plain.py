"""Stage 1 TEST 1: PLAIN response through the REAL TradingAgents client.

NOT PRODUCTION CODE. Stage 1 feasibility test.

Instantiates TradingAgents' existing LocalCompatibleChatOpenAI via the
existing OpenAIClient factory, pointed at the local bridge. Calls .invoke()
with a fresh nonce and requires the response to contain it exactly.
"""

import os
import secrets
import sys

# Use the repo venv
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from tradingagents.llm_clients.openai_client import OpenAIClient
from langchain_core.messages import HumanMessage, SystemMessage

BRIDGE_URL = "http://127.0.0.1:8765/v1"
MODEL = "devin-bridge-test"

def run_plain_test():
    nonce = secrets.token_hex(8)
    print(f"[plain] nonce = {nonce}")

    # Use the REAL existing factory path for openai_compatible provider
    client = OpenAIClient(
        model=MODEL,
        base_url=BRIDGE_URL,
        provider="openai_compatible",
    )
    llm = client.get_llm()

    # Verify it's the real LocalCompatibleChatOpenAI class
    from tradingagents.llm_clients.openai_client import LocalCompatibleChatOpenAI
    assert isinstance(llm, LocalCompatibleChatOpenAI), (
        f"Expected LocalCompatibleChatOpenAI, got {type(llm)}"
    )
    print(f"[plain] client class = {type(llm).__name__}")

    # Verify no real API key was supplied (openai_compatible is key-optional)
    # The factory sends placeholder_key="EMPTY" when no key is set
    print(f"[plain] api_key = {llm.openai_api_key!r} (should be placeholder)")

    messages = [
        SystemMessage(content="You are a test echo. Follow instructions exactly."),
        HumanMessage(content=(
            f"Respond with exactly this text and nothing else: "
            f"PLAIN_NONCE_{nonce}"
        )),
    ]

    result = llm.invoke(messages)
    content = result.content if hasattr(result, "content") else str(result)
    print(f"[plain] response content = {content!r}")

    expected = f"PLAIN_NONCE_{nonce}"
    if expected in content:
        print(f"[plain] PASS: nonce found in response")
        return True
    else:
        print(f"[plain] FAIL: nonce {expected!r} not in response {content!r}")
        return False


if __name__ == "__main__":
    ok = run_plain_test()
    sys.exit(0 if ok else 1)
