"""Stage 2 LIVE smoke: ResearchPlan through the PRODUCTION bridge sidecar.

NOT PRODUCTION CODE. Stage 2 verification.

Uses the REAL existing LocalCompatibleChatOpenAI.with_structured_output()
with the REAL TradingAgents ResearchPlan schema, pointed at the production
devin_bridge sidecar. One live Devin invocation occurs.
"""

import os
import secrets
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tradingagents.llm_clients.openai_client import OpenAIClient
from tradingagents.llm_clients.openai_client import LocalCompatibleChatOpenAI
from tradingagents.agents.schemas import ResearchPlan, PortfolioRating
from langchain_core.messages import HumanMessage, SystemMessage

BRIDGE_URL = "http://127.0.0.1:8765/v1"


def run_live_smoke():
    nonce = "STAGE2_LIVE_" + secrets.token_hex(8)
    print(f"[smoke] nonce = {nonce}")

    client = OpenAIClient(
        model="devin-quick",
        base_url=BRIDGE_URL,
        provider="openai_compatible",
    )
    llm = client.get_llm()
    assert isinstance(llm, LocalCompatibleChatOpenAI)
    print(f"[smoke] client class = {type(llm).__name__}")

    structured_llm = llm.with_structured_output(ResearchPlan)
    print(f"[smoke] structured_llm type = {type(structured_llm).__name__}")

    messages = [
        SystemMessage(content="You are a research manager. Produce a structured investment plan."),
        HumanMessage(content=(
            f"Produce a research plan with these exact values:\n"
            f"- recommendation: Buy\n"
            f"- rationale: The bull case is strong. Nonce: {nonce}\n"
            f"- strategic_actions: Open a 5% position and scale in over 3 tranches.\n"
            f"Return the result via the structured tool."
        )),
    ]

    print("[smoke] invoking production bridge (live Devin call)...")
    result = structured_llm.invoke(messages)

    print(f"[smoke] Python type(result) = {type(result)}")
    print(f"[smoke] isinstance ResearchPlan = {isinstance(result, ResearchPlan)}")

    if not isinstance(result, ResearchPlan):
        print(f"[smoke] FAIL: expected ResearchPlan, got {type(result)}")
        print(f"[smoke] result repr = {result!r}")
        return False

    dump = result.model_dump()
    print(f"[smoke] model_dump = {dump}")
    print(f"[smoke] recommendation = {result.recommendation}")
    print(f"[smoke] rationale = {result.rationale!r}")
    print(f"[smoke] strategic_actions = {result.strategic_actions!r}")

    if not isinstance(result.recommendation, PortfolioRating):
        print(f"[smoke] FAIL: recommendation is {type(result.recommendation)}")
        return False

    if nonce not in result.rationale:
        print(f"[smoke] FAIL: nonce {nonce!r} not in rationale")
        return False

    print(f"[smoke] PASS: ResearchPlan instance, nonce survived, no fallback")
    return True


if __name__ == "__main__":
    ok = run_live_smoke()
    sys.exit(0 if ok else 1)
