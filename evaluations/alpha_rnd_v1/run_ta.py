#!/usr/bin/env python3
"""ALPHA_RND Gate-1: full TradingAgents run on deep-analysis candidates.

Official TA graph (Market, Sentiment/social, News, Fundamentals analysts +
Bull/Bear debate + Research Manager + Trader + risk debate + Portfolio
Manager). Model bridge: devin-quick=swe-2-medium, devin-deep=swe-2-high,
temperature=0. Statement tools pinned to sec_edgar (filing-date safe).
Flat PortfolioContext for entry analysis. Prompts unmodified.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

D = ROOT / "evaluations" / "alpha_rnd_v1"
BRIDGE_URL = "http://127.0.0.1:8765/v1"
TEMPERATURE = 0
STATEMENT_VENDOR_PINS = {
    "get_balance_sheet": "sec_edgar",
    "get_income_statement": "sec_edgar",
    "get_cashflow": "sec_edgar",
}

_RM = re.compile(r"\*\*Recommendation\*\*:\s*(Buy|Overweight|Hold|Underweight|Sell)", re.I)
_TR = re.compile(r"(?:\*\*Action\*\*:|FINAL TRANSACTION PROPOSAL:\s*\*\*)\s*(BUY|HOLD|SELL)", re.I)
_PM = re.compile(r"\*\*Rating\*\*:\s*(Buy|Overweight|Hold|Underweight|Sell)", re.I)


def cfg() -> dict:
    from tradingagents.default_config import DEFAULT_CONFIG

    c = dict(DEFAULT_CONFIG)
    c.update(
        {
            "llm_provider": "openai_compatible",
            "backend_url": BRIDGE_URL,
            "deep_think_llm": "devin-deep",
            "quick_think_llm": "devin-quick",
            "temperature": TEMPERATURE,
            "checkpoint_enabled": True,
            "data_vendors": {
                **DEFAULT_CONFIG["data_vendors"],
                "fundamental_data": "sec_edgar,yfinance",
            },
            "tool_vendors": STATEMENT_VENDOR_PINS,
            "holding_period_days": 20,
            "results_dir": str(D / "results"),
            "data_cache_dir": str(D / "cache"),
            "memory_log_path": str(D / "memory" / "trading_memory.md"),
        }
    )
    return c


def pick(pat, txt, default):
    m = pat.search(txt or "")
    return m.group(1).capitalize() if m else default


def run_one(ticker: str, date: str,
            position: tuple[float, float] | None = None,
            out_name: str | None = None) -> dict:
    from tradingagents.graph.trading_graph import TradingAgentsGraph
    from tradingagents.portfolio import PortfolioContext, Position

    art_path = D / "case_artifacts" / (out_name or f"{ticker}_{date}.json")
    if art_path.exists():
        return json.loads(art_path.read_text())

    graph = TradingAgentsGraph(
        selected_analysts=("market", "social", "news", "fundamentals"), config=cfg()
    )
    port = PortfolioContext(
        cash=100000, currency="USD",
        positions=[Position(ticker=ticker, quantity=position[0],
                            average_price=position[1])] if position else [])
    t0 = time.monotonic()
    st, signal = graph.propagate(ticker, date, asset_type="stock", portfolio=port)
    dur = time.monotonic() - t0
    inv, risk = st["investment_debate_state"], st["risk_debate_state"]
    a = {
        "ticker": ticker,
        "decision_session": date,
        "signal": signal,
        "rm_rating": pick(_RM, st.get("investment_plan", ""), "REVIEW"),
        "trader_action": pick(_TR, st.get("trader_investment_plan", ""), "REVIEW"),
        "pm_rating": pick(_PM, st.get("final_trade_decision", ""), signal),
        "market_report": st.get("market_report", ""),
        "sentiment_report": st.get("sentiment_report", ""),
        "news_report": st.get("news_report", ""),
        "fundamentals_report": st.get("fundamentals_report", ""),
        "bull_history": inv.get("bull_history", ""),
        "bear_history": inv.get("bear_history", ""),
        "judge_decision": inv.get("judge_decision", ""),
        "investment_plan": st.get("investment_plan", ""),
        "trader_investment_plan": st.get("trader_investment_plan", ""),
        "risk_judge_decision": risk.get("judge_decision", ""),
        "final_trade_decision": st.get("final_trade_decision", ""),
        "portfolio_context_rendered": port.render(ticker),
        "model_routing": {"quick": "swe-2-medium", "deep": "swe-2-high"},
        "temperature": TEMPERATURE,
        "duration_s": round(dur, 1),
    }
    a["final_state_hash"] = hashlib.sha256(
        json.dumps({k: v for k, v in a.items() if k != "final_state_hash"},
                   sort_keys=True, default=str).encode()
    ).hexdigest()
    art_path.parent.mkdir(parents=True, exist_ok=True)
    art_path.write_text(json.dumps(a, indent=1, default=str))
    return a


def main() -> None:
    session = sys.argv[1]
    tickers = sys.argv[2:]
    for t in tickers:
        print(f"=== {t} {session} ===", flush=True)
        try:
            a = run_one(t, session)
            print(f"{t}: signal={a['signal']} rm={a['rm_rating']} "
                  f"trader={a['trader_action']} pm={a['pm_rating']} "
                  f"dur={a['duration_s']}s", flush=True)
        except Exception as e:
            print(f"{t}: FAILED {e!r}", flush=True)
            from alpha_rnd import infra_status as inf
            up = inf.status_report()
            rec = inf.failure_record(session, t, "ta", repr(e), exc_name=type(e).__name__,
                                     upstream=up["upstream"], bridge=up["bridge_process"])
            rec["error"] = rec["raw_error"]  # legacy key kept for existing readers
            (D / "case_artifacts").mkdir(parents=True, exist_ok=True)
            (D / "case_artifacts" / f"{t}_{session}.error.json").write_text(json.dumps(rec, indent=1))


if __name__ == "__main__":
    main()
