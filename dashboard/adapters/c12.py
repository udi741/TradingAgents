"""C12 track adapter — frozen prospective control. Strictly isolated."""
from __future__ import annotations

from .. import config
from ..readutil import read_json, read_jsonl


def portfolio() -> tuple[list, dict]:
    return read_jsonl(config.C12_EVAL / "c12_paper_portfolio.jsonl")


def nav_series(limit: int = 500) -> tuple[list, dict]:
    rows, meta = read_jsonl(config.C12_EVAL / "c12_nav.jsonl")
    meta["total_rows"] = len(rows)
    return rows[-limit:], meta


def signal_ledger(limit: int = 200) -> tuple[list, dict]:
    rows, meta = read_jsonl(config.C12_EVAL / "c12_signal_ledger.jsonl")
    meta["total_rows"] = len(rows)
    return rows[-limit:], meta


def scheduler() -> tuple[dict | None, dict]:
    return read_json(config.C12_EVAL / "scheduler_state.json")


def summary() -> dict:
    nav, nav_meta = nav_series(1)
    pf, pf_meta = portfolio()
    sched, sched_meta = scheduler()
    latest_nav = nav[-1] if nav else None
    return {
        "meta": {"nav": nav_meta, "portfolio": pf_meta, "scheduler": sched_meta},
        "latest_nav": latest_nav,
        "open_trades": pf,
        "closed_pnl": (latest_nav or {}).get("closed_pnl"),
        "nav_rows": nav_meta.get("total_rows"),
        "scheduler_last": (sched or {}).get("last_run_utc") or (sched or {}).get("last_cycle"),
        "track": "C12_PROSPECTIVE",
        "frozen_control": True,
    }
