#!/usr/bin/env python3
"""Canonical post-TA publication step (single implementation).

Regenerates the live watchlist from the canonical watch spec
(`alpha_rnd/gen_watchlist.py`) atomically, then records the publication
marker. This is the code tail of the accepted manual cycle; the upstream
classification/trigger synthesis (reading TA artifacts into the spec) is a
researcher step, NOT automated here.

  python3 -m alpha_rnd.publish <session>
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "alpha_rnd" / "scheduler_state.json"


def publish(session: str) -> dict:
    """Atomic, idempotent: same spec -> same live_watchlist.json (modulo
    generated_at); repeated calls overwrite, never duplicate."""
    sys.path.insert(0, str(ROOT))
    import alpha_rnd.gen_watchlist as gw

    doc = gw.build_doc()
    blob = json.dumps(doc, indent=1)
    tmp = gw.OUT.with_suffix(".tmp")
    tmp.write_text(blob)
    tmp.replace(gw.OUT)  # atomic

    st = json.loads(STATE.read_text()) if STATE.exists() else {}
    pub = st.get("published_sessions") or {}
    pub[session] = {"published_at": datetime.now(timezone.utc).isoformat(),
                    "watch_count": len(doc["watches"]),
                    "sha256": doc["sha256"]}
    st["published_sessions"] = pub
    STATE.write_text(json.dumps(st, indent=1))
    print(f"published session={session} watches={len(doc['watches'])} "
          f"sha={doc['sha256'][:16]}")
    return {"session": session, "watch_count": len(doc["watches"])}


if __name__ == "__main__":
    publish(sys.argv[1])
