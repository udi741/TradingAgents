"""Root resolution for the dashboard — no hardcoded machine layout.

Resolution order for each role root (ALPHA runtime/state, C12, TRACKS/docs,
EXPERT research):

1. Explicit environment override (TA_DASH_ALPHA_ROOT, TA_DASH_C12_ROOT,
   TA_DASH_TRACKS_ROOT, TA_DASH_EXPERT_ROOT, TA_DASH_PREFIX).
2. Canonical workspace spec `ops/workspace.json` in the checkout containing
   this dashboard. PREFIX = TA_DASH_PREFIX if set, else the parent directory
   of this checkout; each role resolves to `prefix / spec.roles[ROLE].path`.
   Sibling worktree names come from the spec — they are not hardcoded here.
3. Single-checkout fallback: if this checkout itself contains
   `alpha_rnd/monitor_state.json`, it IS the ALPHA root — the canonical
   single-repo deployment needs no code change.
4. Unresolvable or content-invalid roots are reported missing; adapters
   surface `meta.state == "missing"` and never silently read a wrong tree.

Wrong-checkout guard: when the spec names an expected branch and git is
available, a branch mismatch is recorded in the resolution report
(`/api/meta`) instead of being silently accepted.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

SELF_ROOT = Path(__file__).resolve().parent.parent
WORKSPACE_SPEC = SELF_ROOT / "ops" / "workspace.json"

# content that proves a resolved root is the checkout we mean
_SENTINELS = {
    "ALPHA": "alpha_rnd",
    "C12": "evaluations/gate_c12_prospective",
    "TRACKS": "docs",
    "EXPERT": None,  # research root is optional
}

_ENV = {
    "ALPHA": "TA_DASH_ALPHA_ROOT",
    "C12": "TA_DASH_C12_ROOT",
    "TRACKS": "TA_DASH_TRACKS_ROOT",
    "EXPERT": "TA_DASH_EXPERT_ROOT",
}


def _branch(root: Path) -> str | None:
    try:
        p = subprocess.run(["git", "-C", str(root), "rev-parse",
                            "--abbrev-ref", "HEAD"],
                           capture_output=True, text=True, timeout=10)
        return p.stdout.strip() or None
    except Exception:
        return None


def _spec_roles() -> dict:
    try:
        return json.loads(WORKSPACE_SPEC.read_text()).get("roles") or {}
    except Exception:
        return {}


def _valid(role: str, root: Path) -> bool:
    s = _SENTINELS.get(role)
    return root.is_dir() and (s is None or (root / s).exists())


def _single_checkout_candidate(role: str) -> Path | None:
    """This checkout itself can be the runtime root (single-repo deploy)."""
    if role == "ALPHA" and (SELF_ROOT / "alpha_rnd" / "monitor_state.json").exists():
        return SELF_ROOT
    if role == "C12" and (SELF_ROOT / "evaluations" / "gate_c12_prospective").is_dir():
        return SELF_ROOT
    return None


def resolve(env: dict | None = None) -> dict:
    """Resolve all role roots -> {ROLE: {path, source, branch, present, ...}}."""
    env = os.environ if env is None else env
    spec = _spec_roles()
    prefix = (Path(env["TA_DASH_PREFIX"]).expanduser()
              if env.get("TA_DASH_PREFIX") else SELF_ROOT.parent)
    out = {}
    for role in _SENTINELS:
        spec_role = spec.get(role) or {}
        required = bool(spec_role.get("required_for_production",
                                      role != "EXPERT"))
        entry = {"role": role, "required": required, "present": False,
                 "path": None, "source": None, "branch": None,
                 "expected_branch": spec_role.get("branch"),
                 "branch_match": None}
        candidates = []
        if env.get(_ENV[role]):
            candidates.append((Path(env[_ENV[role]]).expanduser(),
                               "env:" + _ENV[role]))
        # docs come from this checkout first — the dashboard ships inside a
        # control-repo checkout and must read ITS OWN registry (the sibling
        # tracks worktree may be on an older branch)
        if role == "TRACKS":
            candidates.append((SELF_ROOT, "self-checkout"))
        if spec_role.get("path"):
            candidates.append((prefix / spec_role["path"], "workspace.json"))
        sc = _single_checkout_candidate(role)
        if sc:
            candidates.append((sc, "single-checkout"))
        for cand, src in candidates:
            if not _valid(role, cand):
                entry.setdefault("rejected", []).append(
                    {"path": str(cand), "source": src, "why": "sentinel"})
                continue
            br = _branch(cand)
            exp = entry["expected_branch"]
            # wrong-checkout guard: spec-derived and single-checkout
            # candidates whose git branch contradicts the spec are rejected
            # (git-tracked state files make a wrong checkout look valid).
            # Env overrides are explicit operator intent: accepted, but the
            # mismatch is still reported. TRACKS self-checkout is exempt —
            # the dashboard always reads its own docs.
            if src in ("workspace.json", "single-checkout") and \
                    br is not None and exp is not None and br != exp:
                entry.setdefault("rejected", []).append(
                    {"path": str(cand), "source": src,
                     "why": f"branch {br} != spec {exp}"})
                continue
            entry.update(path=str(cand), source=src, present=True,
                         branch=br,
                         branch_match=(None if br is None or exp is None
                                       else br == exp))
            break
        out[role] = entry
    return out


def root(role: str, env: dict | None = None) -> Path | None:
    r = resolve(env)[role]
    return Path(r["path"]) if r["path"] else None


def report(env: dict | None = None) -> dict:
    return {"self_root": str(SELF_ROOT),
            "workspace_spec": str(WORKSPACE_SPEC),
            "roles": resolve(env)}
