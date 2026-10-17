"""Read utilities: tolerant JSON/JSONL/YAML readers with freshness metadata.

Every read returns (value, meta) where meta carries path, mtime, age_seconds,
and state in {ok, missing, malformed, empty}. The API surfaces UNKNOWN rather
than substituting zeros.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import yaml


def _meta(path: Path, state: str, extra: dict | None = None) -> dict:
    m = {"path": str(path), "state": state}
    try:
        st = path.stat()
        m["mtime_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(st.st_mtime))
        m["age_seconds"] = round(time.time() - st.st_mtime, 1)
    except OSError:
        m["mtime_utc"] = None
        m["age_seconds"] = None
    if extra:
        m.update(extra)
    return m


def read_json(path: Path) -> tuple[Any, dict]:
    if not path.exists():
        return None, _meta(path, "missing")
    try:
        txt = path.read_text()
    except OSError as e:
        return None, _meta(path, "unreadable", {"error": str(e)})
    if not txt.strip():
        return None, _meta(path, "empty")
    try:
        return json.loads(txt), _meta(path, "ok", {"bytes": len(txt)})
    except json.JSONDecodeError as e:
        return None, _meta(path, "malformed", {"error": str(e)})


def read_jsonl(path: Path) -> tuple[list, dict]:
    if not path.exists():
        return [], _meta(path, "missing")
    rows, bad = [], 0
    try:
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                bad += 1
    except OSError as e:
        return [], _meta(path, "unreadable", {"error": str(e)})
    state = "ok" if not bad else ("malformed" if not rows else "partial")
    return rows, _meta(path, state, {"rows": len(rows), "bad_rows": bad})


def read_yaml(path: Path) -> tuple[Any, dict]:
    if not path.exists():
        return None, _meta(path, "missing")
    try:
        return yaml.safe_load(path.read_text()), _meta(path, "ok")
    except Exception as e:
        return None, _meta(path, "malformed", {"error": str(e)})


def ts_of(rec: dict, *keys: str) -> str | None:
    for k in keys:
        if isinstance(rec, dict) and rec.get(k):
            return str(rec[k])
    return None
