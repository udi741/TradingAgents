"""Capability registry adapter — loads canonical YAML dynamically."""
from __future__ import annotations

from .. import config
from ..readutil import read_yaml


def registry() -> tuple[dict | None, dict]:
    return read_yaml(config.REGISTRY_YAML)


def summary() -> dict:
    reg, meta = registry()
    caps = (reg or {}).get("capabilities") or []
    counts = {}
    tracks = {}
    for c in caps:
        st = c.get("status", "UNKNOWN")
        counts[st] = counts.get(st, 0) + 1
        # derive track from module paths
        tr = "unknown"
        mods = c.get("modules") or []
        blob = " ".join(str(m) for m in mods) + " " + str(c.get("id", ""))
        if "c12" in blob.lower():
            tr = "C12"
        elif "expert" in blob.lower():
            tr = "EXPERT"
        elif "time_machine" in blob or "time-machine" in blob:
            tr = "TIME_MACHINE"
        elif "ops/" in blob or "tracks/" in blob:
            tr = "CONTROL"
        else:
            tr = "ALPHA"
        tracks[tr] = tracks.get(tr, 0) + 1
    return {
        "meta": meta,
        "registry_version": (reg or {}).get("registry_version"),
        "count": len(caps),
        "by_status": counts,
        "by_track_derived": tracks,
        "capabilities": caps,
        "provider_semantics": (reg or {}).get("provider_semantics"),
        "state_authority": (reg or {}).get("state_authority"),
        "track_boundaries": (reg or {}).get("track_boundaries"),
        "limits": (reg or {}).get("limits"),
        "duplicated_implementations": (reg or {}).get("duplicated_implementations"),
    }
