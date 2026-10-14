"""Deterministic read-only roadmap status. `python -m ops.roadmap_status`."""
import re, sys
from pathlib import Path

S = Path(__file__).parent.parent / "state" / "alpha_opportunity_coverage.yaml"

def load():
    items, cur = {}, None
    for l in S.read_text().splitlines():
        m = re.match(r"^  (R\d+):", l)
        if m: cur = m.group(1); items[cur] = {}; continue
        if cur:
            for k in ("title", "status", "next_action"):
                mm = re.match(rf"^    {k}: (.+)$", l)
                if mm: items[cur][k] = mm.group(1).strip('"')
    hdr = dict(re.findall(r"^(current_task|next_task): (\S+)", S.read_text(), re.M))
    blk = re.findall(r"^    blockers: \[(.+)\]", S.read_text(), re.M)
    return items, hdr, blk

if __name__ == "__main__":
    items, hdr, blk = load()
    print("TRADINGAGENTS ROADMAP\n")
    for k in sorted(items, key=lambda x: int(x[1:])):
        print(f"{k} {items[k].get('status','?')}")
    print(f"\nCURRENT: {hdr.get('current_task','?')}\nNEXT: {hdr.get('next_task','?')}")
    print(f"BLOCKERS: {'; '.join(b for b in blk if b) or 'none'}")
