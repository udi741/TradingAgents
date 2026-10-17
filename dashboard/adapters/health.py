"""System health adapter: wraps ops.ta (authoritative health), probes bridge.

ops.ta health is READ-ONLY (exit 0=HEALTHY 1=DEGRADED 2=FAILED).
"""
from __future__ import annotations

import json
import re
import subprocess
import urllib.request
from pathlib import Path

from .. import config


def _run_ta(args: list[str], timeout: int = 90) -> dict:
    try:
        p = subprocess.run(
            ["python3", "-m", "ops.ta", *args,
             "--prefix", str(config.WORKSPACE_PREFIX)],
            cwd=str(config.SELF_ROOT), capture_output=True, text=True,
            timeout=timeout)
        return {"rc": p.returncode, "stdout": p.stdout, "stderr": p.stderr[-2000:]}
    except subprocess.TimeoutExpired:
        return {"rc": None, "stdout": "", "stderr": "timeout", "timed_out": True}
    except OSError as e:
        return {"rc": None, "stdout": "", "stderr": str(e)}


_CHK = re.compile(r"\[\s*(OK|DEGRADED|FAILED)\]\s*(.*)")


def health() -> dict:
    r = _run_ta(["health"])
    checks = []
    for line in r["stdout"].splitlines():
        m = _CHK.search(line)
        if m:
            name = m.group(2).strip()
            checks.append({"status": m.group(1), "name": name})
    overall = None
    for line in r["stdout"].splitlines():
        if line.strip().startswith("OVERALL:"):
            overall = line.split(":", 1)[1].strip()
    return {"rc": r["rc"], "overall": overall,
            "checks": checks, "raw_tail": r["stdout"][-4000:],
            "error": r["stderr"] or None}


def status() -> dict:
    r = _run_ta(["status"], timeout=45)
    lines = [l for l in r["stdout"].splitlines() if l.strip()]
    return {"rc": r["rc"], "lines": lines, "error": r["stderr"] or None}


def bridge() -> dict:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8765/v1/models", timeout=5) as r:
            body = json.loads(r.read().decode()[:4000])
            models = [m.get("id") for m in body.get("data", [])] if isinstance(body, dict) else None
            return {"reachable": True, "models": models}
    except Exception as e:
        return {"reachable": False, "error": str(e)}


def systemd_units() -> list[dict]:
    out = []
    try:
        p = subprocess.run(
            ["systemctl", "--user", "list-units", "--all", "--no-legend",
             "--plain", "tradingagents*"],
            capture_output=True, text=True, timeout=15)
        for line in p.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 4:
                out.append({"unit": parts[0], "load": parts[1],
                            "active": parts[2], "sub": parts[3],
                            "desc": " ".join(parts[4:]) if len(parts) > 4 else ""})
    except (OSError, subprocess.TimeoutExpired):
        pass
    if not out:  # fallback: list unit files we ship
        sd = config.ALPHA_STATE / "systemd"
        if sd.exists():
            for f in sorted(sd.iterdir()):
                out.append({"unit": f.name, "load": "unknown", "active": "unknown",
                            "sub": "unknown", "desc": "unit file present; systemctl unavailable"})
    return out
