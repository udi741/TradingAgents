"""Dashboard configuration: resolved authoritative roots.

Roots are resolved by dashboard/paths.py:
  env override -> ops/workspace.json spec (+ TA_DASH_PREFIX) ->
  single-checkout fallback -> missing (fail clearly, never a wrong tree).

No path under /home/udi or any sibling-worktree name is hardcoded here.
"""
from __future__ import annotations

import os
from pathlib import Path

from . import paths


def _unresolved(role: str) -> Path:
    """Sentinel that cannot exist: every read reports meta.state=missing."""
    return Path(f"/__unresolved_ta_dashboard_root__/{role}")


ROOTS = paths.resolve()


def _r(role: str) -> Path:
    p = ROOTS[role]["path"]
    return Path(p) if p else _unresolved(role)


# DASHBOARD CODE ROOT: the checkout containing this file (never configured).
SELF_ROOT = paths.SELF_ROOT

# ALPHA RUNTIME/STATE ROOT: env TA_DASH_ALPHA_ROOT, else workspace spec
# (prefix + roles.ALPHA.path), else this checkout if it holds alpha_rnd/.
ALPHA_ROOT = _r("ALPHA")
ALPHA_STATE = ALPHA_ROOT / "alpha_rnd"
ALPHA_EVAL = ALPHA_ROOT / "evaluations" / "alpha_rnd_v1"

# C12 ROOT: env TA_DASH_C12_ROOT, else workspace spec roles.C12.path.
C12_ROOT = _r("C12")
C12_EVAL = C12_ROOT / "evaluations" / "gate_c12_prospective"

# CAPABILITY/DOC ROOT: this checkout's docs/ (TRACKS role).
TRACKS_ROOT = _r("TRACKS")
REGISTRY_YAML = TRACKS_ROOT / "docs" / "TRADINGAGENTS_CAPABILITY_REGISTRY.yaml"

# RESEARCH ROOT: EXPERT (optional; not required for production).
EXPERT_ROOT = _r("EXPERT")

# Workspace prefix for ops.ta --prefix (role layout root).
WORKSPACE_PREFIX = Path(os.environ["TA_DASH_PREFIX"]).expanduser() \
    if os.environ.get("TA_DASH_PREFIX") else SELF_ROOT.parent

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
