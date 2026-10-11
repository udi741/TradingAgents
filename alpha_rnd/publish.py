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
    # Merge validated PublicationIntents for every session <= this one;
    # a published watch persists until a NEWER intent for the same ticker
    # supersedes it. Latest session wins per ticker.
    ev = ROOT / "evaluations" / "alpha_rnd_v1"
    paths = sorted(p for p in ev.glob("publication_intents_*.json")
                   if p.stem.rsplit("_", 1)[-1] <= session)
    if paths:
        by_ticker = {w["ticker"]: w for w in doc["watches"]}
        for intents_path in paths:
            idoc = json.loads(intents_path.read_text())
            for t in idoc.get("validated", []):
                i = idoc["intents"][t]
                if i.get("watch_mode") in (None, "NONE"):
                    continue
                isess = intents_path.stem.rsplit("_", 1)[-1]
                # older intents never overwrite a NEWER curated revision:
                # the watch's artifact name carries its session
                cur = by_ticker.get(t, {}).get("artifact") or ""
                curs = cur.rsplit("_", 1)[-1].split(".")[0] if "_" in cur else ""
                if curs and isess <= curs:
                    continue
                by_ticker[t] = {
                    "ticker": t, "cls": i["watch_mode"], "v": "auto",
                    "trigger": i.get("trigger"),
                    "trigger_type": (i.get("params") or {}).get("type"),
                    "params": i.get("params"),
                    "entry_convention": i.get("entry_convention"),
                    "invalidation": i.get("invalidation"),
                    "horizon": i.get("horizon"),
                    "reevaluation": i.get("reevaluation"),
                    "artifact": f"{t}_{isess}.json",
                    "size_frac": i.get("size_frac") or 1.0,
                    "stop_rule": ({"type": "intraday_stop",
                                   "level": i["stop_level"],
                                   "label": i.get("invalidation")}
                                  if i.get("stop_level") else None),
                    "auto_execution_authorized": bool(
                        i.get("auto_execution_authorized")),
                    "source": "auto_synth",
                }
        doc["watches"] = list(by_ticker.values())
        doc["sha256"] = __import__("hashlib").sha256(
            json.dumps({k: v for k, v in doc.items() if k != "sha256"},
                       sort_keys=True).encode()).hexdigest()
    blob = json.dumps(doc, indent=1)
    tmp = gw.OUT.with_suffix(".tmp")
    tmp.write_text(blob)
    tmp.replace(gw.OUT)  # atomic

    import alpha_rnd.daily_scheduler as ds
    def _mut(st):
        pub = st.get("published_sessions") or {}
        pub[session] = {"published_at": datetime.now(timezone.utc).isoformat(),
                        "watch_count": len(doc["watches"]),
                        "sha256": doc["sha256"]}
        st["published_sessions"] = pub
    ds._state_txn(_mut)
    print(f"published session={session} watches={len(doc['watches'])} "
          f"sha={doc['sha256'][:16]}")
    return {"session": session, "watch_count": len(doc["watches"])}


if __name__ == "__main__":
    publish(sys.argv[1])
