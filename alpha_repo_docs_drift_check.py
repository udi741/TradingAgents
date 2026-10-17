#!/usr/bin/env python3
"""Lightweight doc-drift check: registry IDs unique, module paths exist,
canonical docs link to the registry/reference."""
import sys, yaml, re
from pathlib import Path
root = Path("/home/udi/udi_provate/TradingAgents-alpha-rnd")
docs = Path(__file__).resolve().parent / "docs"
r = yaml.safe_load((docs / "TRADINGAGENTS_CAPABILITY_REGISTRY.yaml").read_text())
ids = [c["id"] for c in r["capabilities"]]
errs = [f"dup id {i}" for i in set(ids) if ids.count(i) > 1]
missing = []
for c in r["capabilities"]:
    for m in c.get("modules") or []:
        p = re.split(r"::|\s", str(m))[0]
        if not p.startswith(("http", "eval")) and "/" not in p and not p.endswith(".py"):
            p = "alpha_rnd/" + p + ".py" if "::" in str(m) else p
        if "::" in str(m):
            p = re.split(r"::", str(m))[0]
            p = p if p.startswith("alpha_rnd/") or "/" in p else "alpha_rnd/" + p
        if str(m).startswith("publication_intents") or str(m).startswith("tradingagents"):
            continue
        cand = root / p
        if not cand.exists() and not (root / "evaluations" / p).exists() \
           and not Path(str(m)).is_absolute() and not (root.parent.parent / p).exists():
            if not any(x in str(m) for x in ["bridge", "service", "field", "DISPOSITIONS"]):
                missing.append(str(m))
if missing: errs.append("missing module paths: " + ", ".join(sorted(set(missing))))
for d in ["TRADINGAGENTS_CAPABILITY_REFERENCE.md"]:
    if "REGISTRY" not in (docs / d).read_text().upper():
        errs.append(f"{d} does not link registry")
print("drift errors:", errs or "none"); sys.exit(1 if errs else 0)
