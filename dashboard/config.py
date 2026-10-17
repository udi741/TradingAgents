"""Dashboard configuration: authoritative state locations.

All paths read-only from the dashboard's perspective. The dashboard never
writes into these worktrees.
"""
from __future__ import annotations

import os
from pathlib import Path

# Repo/worktree roots. Overridable via env for tests.
_PREFIX = Path(os.environ.get("TA_DASH_PREFIX", str(Path.home() / "udi_provate")))

ALPHA_ROOT = Path(os.environ.get("TA_DASH_ALPHA_ROOT", _PREFIX / "TradingAgents-alpha-rnd"))
C12_ROOT = Path(os.environ.get("TA_DASH_C12_ROOT", _PREFIX / "TradingAgents-c12"))
TRACKS_ROOT = Path(os.environ.get("TA_DASH_TRACKS_ROOT", _PREFIX / "TradingAgents-tracks"))
# Dashboard worktree (holds canonical docs post-merge)
SELF_ROOT = Path(__file__).resolve().parent.parent

ALPHA_STATE = ALPHA_ROOT / "alpha_rnd"
ALPHA_EVAL = ALPHA_ROOT / "evaluations" / "alpha_rnd_v1"
C12_EVAL = C12_ROOT / "evaluations" / "gate_c12_prospective"

REGISTRY_YAML = SELF_ROOT / "docs" / "TRADINGAGENTS_CAPABILITY_REGISTRY.yaml"

HOST = os.environ.get("TA_DASH_HOST", "127.0.0.1")
PORT = int(os.environ.get("TA_DASH_PORT", "8420"))

# Files that are ECONOMIC AUTHORITY — dashboard reads, never writes.
ECONOMIC_FILES = [
    ALPHA_STATE / "monitor_state.json",
    ALPHA_EVAL / "alpha_paper_ledger.jsonl",
    C12_EVAL / "c12_paper_portfolio.jsonl",
    C12_EVAL / "c12_nav.jsonl",
    C12_EVAL / "c12_signal_ledger.jsonl",
]
