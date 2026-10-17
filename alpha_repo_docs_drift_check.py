#!/usr/bin/env python3
"""Lightweight doc-drift check for the TradingAgents capability registry.

Verifies:
- capability IDs unique
- statuses valid and explicit
- referenced module paths exist (alpha-rnd worktree or this repo)
- ACTIVE_PRODUCTION capabilities have modules and a purpose
- canonical docs exist and hub docs link each other
- every non-test production .py module in alpha_rnd/ and tradingagents/ is
  mapped to at least one registry capability (coverage gate)
"""
import re
import sys
from pathlib import Path

import yaml

ALPHA_ROOT = Path("/home/udi/udi_provate/TradingAgents-alpha-rnd")
DOCS = Path(__file__).resolve().parent / "docs"
VALID_STATUS = {
    "ACTIVE_PRODUCTION", "ACTIVE_PARTIAL", "SHADOW_ONLY", "RESEARCH_ONLY",
    "LEGACY", "DUPLICATED", "BROKEN", "UNUSED", "MISSING",
}
# Non-code module references that legitimately have no on-disk path.
VIRTUAL_MODULE_MARKERS = (
    "bridge", "service", "field", "DISPOSITIONS", "management_actions",
    "publication_intents", "monitor_state", "live_watchlist", "policy",
)

errs: list[str] = []
r = yaml.safe_load((DOCS / "TRADINGAGENTS_CAPABILITY_REGISTRY.yaml").read_text())
caps = r["capabilities"]
ids = [c["id"] for c in caps]
errs += [f"dup id {i}" for i in set(ids) if ids.count(i) > 1]

for c in caps:
    if c.get("status") not in VALID_STATUS:
        errs.append(f"{c.get('id')}: invalid/missing status {c.get('status')!r}")
    if c.get("status") == "ACTIVE_PRODUCTION":
        if not c.get("modules"):
            errs.append(f"{c['id']}: ACTIVE_PRODUCTION without modules")
        if not c.get("purpose"):
            errs.append(f"{c['id']}: ACTIVE_PRODUCTION without purpose")

for c in caps:
    for m in c.get("modules") or []:
        m = str(m)
        if "::" in m:
            m = m.split("::", 1)[0]
        p = m.split()[0]
        if p.startswith("http") or any(k in m for k in VIRTUAL_MODULE_MARKERS):
            continue
        if not ((ALPHA_ROOT / p).exists() or (ALPHA_ROOT / "evaluations" / p).exists()
                or (DOCS.parent / p).exists()):
            errs.append(f"missing module path: {m} (cap {c['id']})")

# Canonical docs exist and cross-link.
canonical = [
    "TRADINGAGENTS_CAPABILITY_REFERENCE.md", "ALPHA_SYSTEM_GUIDE.md",
    "STATE_AND_DATA_AUTHORITY.md", "TRADINGAGENTS_OPERATOR_MANUAL.md",
    "TROUBLESHOOTING_RUNBOOK.md", "DEVELOPER_WORKFLOW.md",
    "NEW_MACHINE_SETUP.md", "SYSTEM_ARCHITECTURE.md",
]
for d in canonical:
    if not (DOCS / d).exists():
        errs.append(f"missing canonical doc {d}")
ref = (DOCS / "TRADINGAGENTS_CAPABILITY_REFERENCE.md").read_text()
if "TRADINGAGENTS_CAPABILITY_REGISTRY" not in ref:
    errs.append("reference does not link registry")
for d in canonical[1:]:
    if (DOCS / d).exists() and "CAPABILITY_REFERENCE" not in (DOCS / d).read_text():
        errs.append(f"{d} does not link the capability reference")

# Coverage gate: every production-relevant .py module is named in the registry.
covered = set()
for c in caps:
    for m in c.get("modules") or []:
        p = str(m).split("::")[0].split()[0]
        if p.endswith(".py"):
            covered.add(p)

def _unmapped(root_sub: str) -> list[str]:
    base = ALPHA_ROOT / root_sub
    out = []
    for f in sorted(base.rglob("*.py")):
        rel = f.relative_to(ALPHA_ROOT).as_posix()
        if ("__pycache__" in rel or f.name == "__init__.py"
                or "/test_" in rel or rel.startswith("alpha_rnd/test_")):
            continue
        if rel not in covered:
            out.append(rel)
    return out

unmapped = _unmapped("alpha_rnd") + _unmapped("tradingagents") \
    + _unmapped("ta_eval_alpha") + _unmapped("cli") + _unmapped("evaluations/alpha_rnd_v1")
if unmapped:
    errs.append("unmapped production modules: " + ", ".join(unmapped))

print("drift errors:", errs or "none")
sys.exit(1 if errs else 0)
