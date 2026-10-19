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


def cfg(overrides: dict | None = None) -> dict:
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
    if overrides:
        c.update(overrides)
    return c


def pick(pat, txt, default):
    m = pat.search(txt or "")
    return m.group(1).capitalize() if m else default


def run_one(ticker: str, date: str,
            position: tuple[float, float] | None = None,
            out_name: str | None = None,
            config_overrides: dict | None = None) -> dict:
    from tradingagents.graph.trading_graph import TradingAgentsGraph
    from tradingagents.portfolio import PortfolioContext, Position
    from alpha_rnd.analysis_metrics import ModelCallMetrics, provider_call_metrics
    from alpha_rnd.case_integrity import seal_case

    art_path = D / "case_artifacts" / (out_name or f"{ticker}_{date}.json")
    if art_path.exists():
        return json.loads(art_path.read_text())

    config = cfg(config_overrides)
    model_metrics = ModelCallMetrics({
        "quick": config.get("quick_think_llm"), "deep": config.get("deep_think_llm"),
    })
    graph = TradingAgentsGraph(
        selected_analysts=("market", "social", "news", "fundamentals"), config=config,
        callbacks=[model_metrics],
    )
    from tradingagents.dataflows import provenance
    provenance.begin(ticker, date)
    port = PortfolioContext(
        cash=100000, currency="USD",
        positions=[Position(ticker=ticker, quantity=position[0],
                            average_price=position[1])] if position else [])
    started_at = datetime.now(timezone.utc).isoformat()
    t0 = time.monotonic()
    st, signal = graph.propagate(ticker, date, asset_type="stock", portfolio=port)
    dur = time.monotonic() - t0
    finished_at = datetime.now(timezone.utc).isoformat()
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
        json.dumps(a, sort_keys=True, default=str).encode()
    ).hexdigest()
    try:
        provider_metadata = provenance.finish()
    except Exception as e:
        provider_metadata = {
            "schema_version": 1,
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "coverage": {},
            "instrumentation_errors": [f"{type(e).__name__}: {e}"],
        }
    try:
        observed = model_metrics.snapshot()
        calls = provider_metadata.get("calls", [])
        a["analysis_metrics"] = {
            "schema_version": 1,
            "wall_clock": {
                "started_at": started_at, "finished_at": finished_at,
                "elapsed_ms": round(dur * 1000, 3),
            },
            "provider_calls": provider_call_metrics(calls),
            **observed,
            "stages": {},
        }
    except Exception:
        a["analysis_metrics"] = {
            "schema_version": 1,
            "wall_clock": {
                "started_at": started_at, "finished_at": finished_at,
                "elapsed_ms": round(dur * 1000, 3),
            },
            "provider_calls": {"logical_data_calls": None},
            "model_calls": {"total": None},
            "tokens": {
                "availability": "UNAVAILABLE", "input_tokens": None,
                "output_tokens": None, "total_tokens": None,
            },
            "stages": {},
        }
    a["provider_metadata"] = provider_metadata
    seal_case(a)
    art_path.parent.mkdir(parents=True, exist_ok=True)
    art_path.write_text(json.dumps(a, indent=1, default=str))
    return a


def _record_shadow_case(ticker: str, session: str) -> None:
    try:
        from alpha_rnd.reuse_shadow import record_for_session

        record = record_for_session(ticker, session)
        if record is not None:
            print(
                f"{ticker}: reuse shadow={record['shadow_mode']['classification']}",
                flush=True,
            )
    except Exception as e:
        print(f"{ticker}: reuse shadow instrumentation failed {e!r}", flush=True)


def _pairs_done(session: str) -> int:
    from alpha_rnd.reuse_engine import VALIDATION_DIR

    try:
        return sum(1 for p in VALIDATION_DIR.glob(f"*_{session}.json"))
    except Exception:
        return 0


def _engine_dispatch(t: str, session: str):
    """ALPHA_REUSE_ENGINE dispatch.

    OFF (default): identical to before — plain run_one.
    VALIDATE: paired controlled run for repeated tickers, capped by
      ALPHA_REUSE_MAX_PAIRS (default 2) per session; the canonical artifact is
      always the full-refresh baseline — economic/publication authority is
      never switched here.
    ENABLED: optimized reuse path writes the canonical artifact.
    """
    from alpha_rnd import reuse_engine

    def _full(ticker, date, out_name=None, config_overrides=None):
        return run_one(ticker, date, out_name=out_name,
                       config_overrides=config_overrides)

    mode = reuse_engine.engine_mode()
    if mode == "OFF":
        return run_one(t, session), mode
    if mode == "VALIDATE":
        has_prior = bool(list((D / "case_artifacts").glob(f"{t}_*.json")))
        if has_prior and _pairs_done(session) < reuse_engine.max_validation_pairs():
            try:
                a = reuse_engine.run_validated_pair(
                    t, session, full_run=_full)
                print(f"{t}: reuse VALIDATE pair recorded "
                      f"(authority=baseline)", flush=True)
                return a, mode
            except Exception as exc:
                # Optimization must never lose an analysis: plain full run.
                print(f"{t}: reuse VALIDATE failed {exc!r}; full run", flush=True)
                return run_one(t, session), mode
        return run_one(t, session), mode
    # ENABLED — optimized authority (operator-enabled only)
    try:
        return reuse_engine.run_optimized(
            t, session, full_run=_full,
            artifact_path=D / "case_artifacts" / f"{t}_{session}.json"), mode
    except Exception as exc:
        print(f"{t}: reuse engine failed {exc!r}; full run", flush=True)
        return run_one(t, session), mode


def main() -> None:
    session = sys.argv[1]
    tickers = sys.argv[2:]
    try:
        from alpha_rnd import reuse_engine as _re  # noqa: F401
        engine = _re.engine_mode()
    except Exception:
        engine = "OFF"
    for t in tickers:
        print(f"=== {t} {session} ===", flush=True)
        try:
            a, used = _engine_dispatch(t, session) if engine != "OFF" else (
                run_one(t, session), "OFF")
            print(f"{t}: signal={a['signal']} rm={a['rm_rating']} "
                  f"trader={a['trader_action']} pm={a['pm_rating']} "
                  f"dur={a.get('duration_s', 'n/a')}s", flush=True)
            _record_shadow_case(t, session)
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
