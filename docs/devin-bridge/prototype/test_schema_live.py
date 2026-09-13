"""Stage 1 LIVE SCHEMA test: ResearchPlan through the REAL TradingAgents client.

NOT PRODUCTION CODE. Stage 1 feasibility test.

Uses the REAL existing LocalCompatibleChatOpenAI.with_structured_output()
with the REAL TradingAgents ResearchPlan schema. A live Devin CLI invocation
occurs. A fresh nonce is embedded in the rationale field.
"""

import os
import secrets
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from tradingagents.llm_clients.openai_client import OpenAIClient
from tradingagents.llm_clients.openai_client import LocalCompatibleChatOpenAI
from tradingagents.agents.schemas import ResearchPlan, PortfolioRating
from langchain_core.messages import HumanMessage, SystemMessage

BRIDGE_URL = "http://127.0.0.1:8765/v1"
MODEL = "devin-bridge-test"


def run_live_schema_test():
    nonce = "SCHEMA_LIVE_" + secrets.token_hex(8)
    print(f"[schema-live] nonce = {nonce}")

    # Use the REAL existing factory path for openai_compatible provider
    client = OpenAIClient(
        model=MODEL,
        base_url=BRIDGE_URL,
        provider="openai_compatible",
    )
    llm = client.get_llm()
    assert isinstance(llm, LocalCompatibleChatOpenAI), (
        f"Expected LocalCompatibleChatOpenAI, got {type(llm)}"
    )
    print(f"[schema-live] client class = {type(llm).__name__}")

    # Verify no real API key (openai_compatible is key-optional, placeholder used)
    print(f"[schema-live] api_key = {llm.openai_api_key!r} (placeholder, not a real key)")

    # Use the REAL with_structured_output method with the REAL ResearchPlan schema
    structured_llm = llm.with_structured_output(ResearchPlan)
    print(f"[schema-live] structured_llm type = {type(structured_llm).__name__}")

    messages = [
        SystemMessage(content=(
            "You are a research manager. Produce a structured investment plan. "
            "Use the provided tool to return your structured result."
        )),
        HumanMessage(content=(
            f"Produce a research plan with these exact values:\n"
            f"- recommendation: Buy\n"
            f"- rationale: The bull case is strong. Nonce: {nonce}\n"
            f"- strategic_actions: Open a 5% position and scale in over 3 tranches.\n"
            f"Return the result via the structured tool."
        )),
    ]

    print("[schema-live] invoking (live Devin call)...")
    result = structured_llm.invoke(messages)

    print(f"[schema-live] Python type(result) = {type(result)}")
    print(f"[schema-live] isinstance ResearchPlan = {isinstance(result, ResearchPlan)}")

    if not isinstance(result, ResearchPlan):
        print(f"[schema-live] FAIL: expected ResearchPlan, got {type(result)}")
        print(f"[schema-live] result repr = {result!r}")
        return False

    # Sanitized dump
    dump = result.model_dump()
    print(f"[schema-live] model_dump = {dump}")

    # Validate fields
    print(f"[schema-live] recommendation = {result.recommendation!r}")
    print(f"[schema-live] rationale = {result.rationale!r}")
    print(f"[schema-live] strategic_actions = {result.strategic_actions!r}")

    # Check recommendation is a valid PortfolioRating
    if not isinstance(result.recommendation, PortfolioRating):
        print(f"[schema-live] FAIL: recommendation is {type(result.recommendation)}, not PortfolioRating")
        return False

    # Check nonce survived exactly
    if nonce not in result.rationale:
        print(f"[schema-live] FAIL: nonce {nonce!r} not in rationale {result.rationale!r}")
        return False

    print(f"[schema-live] PASS: ResearchPlan instance, nonce survived, no fallback")
    print(f"[schema-live]   type = {type(result).__name__}")
    print(f"[schema-live]   recommendation = {result.recommendation}")
    print(f"[schema-live]   nonce in rationale = {nonce in result.rationale}")
    return True


if __name__ == "__main__":
    ok = run_live_schema_test()
    sys.exit(0 if ok else 1)
