#!/usr/bin/env python3
"""TradingAgents operator CLI — setup / health / status.

    python3 -m ops.ta setup [--dry-run] [--prefix P] [--config-dir D]
    python3 -m ops.ta health      (READ ONLY)
    python3 -m ops.ta status      (READ ONLY)

setup is MUTATING except --dry-run. No internal module names needed.
"""
import argparse, json, os, re, shutil, subprocess, sys, urllib.request
from datetime import datetime, timezone
from pathlib import Path

TRACKS = Path(__file__).resolve().parents[1]
TPL = TRACKS / "ops" / "templates"
UNITS = ["tradingagents-swe-bridge.service", "tradingagents-telegram.service"]
BOOT_TIMER = "tradingagents-bootcheck.timer"
UNIT_FILES = UNITS + ["tradingagents-bootcheck.service", BOOT_TIMER]
ENABLE_UNITS = UNITS + [BOOT_TIMER]
CRON_TAG = "tradingagents"


def _layout(prefix: Path) -> dict:
    return {
        "HOME": str(Path.home()),
        "PREFIX": str(prefix),
        "BASE_DIR": str(prefix / "TradingAgents"),
        "ALPHA_DIR": str(prefix / "TradingAgents-alpha-rnd"),
        "C12_DIR": str(prefix / "TradingAgents-c12"),
        "TRACKS_DIR": str(prefix / "TradingAgents-tracks"),
        "EXPERT_DIR": str(prefix / "TradingAgents-expert-rnd"),
    }


def _fill(text: str, lay: dict) -> str:
    for k, v in lay.items():
        text = text.replace(f"@{k}@", v)
    return text


# ------------------------- setup -------------------------

def _check(cond, ok, bad, problems):
    if cond:
        print(f"  OK   {ok}")
        return True
    problems.append(bad)
    print(f"  FAIL {bad}")
    return False


def cmd_setup(a):
    """Bootstrap a fresh machine. MUTATING except --dry-run. Idempotent."""
    prefix = Path(a.prefix).resolve()
    cfg = Path(a.config_dir).expanduser()
    lay = _layout(prefix)
    dry = a.dry_run
    mut = "DRY-RUN " if dry else ""
    changes, problems, manual = [], [], []

    def apply(label, fn):
        if dry:
            changes.append(f"WOULD {label}")
            print(f"  DRY  {label}")
        else:
            fn()
            changes.append(label)
            print(f"  DONE {label}")

    print(f"{mut}SETUP TradingAgents @ {prefix}\n[environment]")
    uname = os.uname()
    _check(uname.sysname == "Linux", f"os={uname.sysname}",
           "unsupported OS (Linux required)", problems)
    for tool in ("git", "python3", "systemctl", "crontab"):
        _check(shutil.which(tool), f"{tool} present", f"{tool} missing", problems)
    py3 = sys.version_info
    _check(py3 >= (3, 10), f"system python {py3.major}.{py3.minor}",
           "system python <3.10", problems)
    py312 = next((c for c in ("python3.12",) if shutil.which(c)), None)
    if not _check(py312, "python3.12 (TA venv)",
                  "python3.12 missing — install it before setup can build the "
                  "TA environment", problems):
        manual.append("install python3.12 + python3.12-venv")
    if problems:
        print("\nABORT — fix the FAIL items above and rerun.")
        return 2

    print("[workspace]")
    ws = _ws_state(prefix)
    spec = _ws_spec()
    bad = [r for r in spec if spec[r]["required_for_production"]
           and ws[r]["status"] != "OK"]
    if bad:
        for r in bad:
            problems.append(f"workspace {r}: {ws[r]['status']}")
        problems.append(
            f"create missing worktrees: `python3 -m ops.ta workspace "
            f"setup --prefix {prefix}`")
        for p_ in problems[-len(bad) - 1:]:
            print(f"  FAIL {p_}")
        return 2
    print("  OK   required worktrees present "
          f"({', '.join(r for r in spec if spec[r]['required_for_production'])})")

    alpha = Path(lay["ALPHA_DIR"])
    venv = alpha / ".venv312"

    print("[python environments]")
    if venv.exists():
        print(f"  SKIP .venv312 exists")
    elif dry or not py312:
        print(f"  DRY  create {venv} + pip install -e ."
              if dry else "  SKIP venv deferred (no python3.12)")
    else:
        try:
            apply(f"create .venv312 (python3.12) + pip install -e .",
                  lambda: (subprocess.run([py312, "-m", "venv", str(venv)],
                                          check=1, capture_output=1),
                           subprocess.run([str(venv / "bin/pip"), "install",
                                           "-e", str(alpha)],
                                          check=1, capture_output=1)))
        except subprocess.CalledProcessError as e:
            problems.append(f".venv312 build failed: {e}")
            print(f"  FAIL venv/pip install failed — see error above")
    req = TRACKS / "ops" / "runtime_requirements.txt"
    missing = _missing_py_deps(req)
    if missing:
        apply(f"pip install --user -r ops/runtime_requirements.txt ({missing})",
              lambda: subprocess.run([sys.executable, "-m", "pip", "install",
                                      "--user", "-r", str(req)], check=1))
    else:
        print("  SKIP runtime deps satisfied")

    print("[directories]")
    for d in (cfg / "tradingagents",):
        if d.exists():
            print(f"  SKIP {d}")
        else:
            apply(f"mkdir {d}", lambda d=d: d.mkdir(parents=True))

    print("[secrets]")
    env_t = cfg / "tradingagents" / "telegram.env"
    if env_t.exists() and env_t.stat().st_size:
        print(f"  SKIP {env_t} exists — never overwriting secrets")
    else:
        def _mk(p=env_t):
            shutil.copy(TRACKS / "config" / "telegram.env.example", p)
            p.chmod(0o600)
        apply(f"create {env_t} from template (chmod 600)", _mk)
        manual.append("fill real values in ~/.config/tradingagents/telegram.env")

    print("[systemd units]")
    udir = cfg / "systemd" if a.sim else \
        Path.home() / ".config" / "systemd" / "user"
    for u in UNIT_FILES:
        tgt = udir / u
        content = _fill((TPL / u).read_text(), lay)
        if tgt.exists():
            if tgt.read_text() == content:
                print(f"  SKIP {u} identical")
            else:
                problems.append(f"{u} exists but differs — manual review "
                                f"(never silently replace customized units)")
                print(f"  FAIL {problems[-1]}")
        else:
            apply(f"write {tgt}", lambda t=tgt, c=content:
                  (t.parent.mkdir(parents=True, exist_ok=True),
                   t.write_text(c)))
    if not dry and not a.no_systemctl:
        apply("systemctl --user daemon-reload", lambda: subprocess.run(
            _sysctl() + ["daemon-reload"], check=1))
        apply("enable+start bridge, telegram & bootcheck timer",
              lambda: subprocess.run(
                  _sysctl() + ["enable", "--now"] + ENABLE_UNITS, check=1))
    else:
        manual.append("systemctl --user enable --now " +
                      " ".join(ENABLE_UNITS))

    print("[crontab]")
    block = _fill((TPL / "crontab.block").read_text(), lay)
    cur = _cron_read() or ""
    have = [j for j in ("alpha_rnd.monitor", "alpha_rnd.daily_scheduler",
                        "alpha_rnd.cohort_outcomes", "ta_eval.c12_scheduler")
            if j in cur]
    if f">>> {CRON_TAG} >>>" in cur:
        print("  SKIP tradingagents cron block already installed")
    elif len(have) == 4:
        print("  SKIP all 4 jobs present (legacy untagged) — leaving as-is; "
              "untouched rather than duplicating")
        manual.append("optional: let setup re-tag cron by removing the 4 "
                      "legacy lines first")
    elif have:
        problems.append(f"partial cron coverage ({len(have)}/4 jobs) — "
                        "manual dedup required; refusing to guess")
        print(f"  FAIL {problems[-1]}")
    elif dry:
        print("  DRY  append tradingagents cron block (4 jobs, dedup-tagged)")
        changes.append("WOULD install cron block")
    else:
        new = ((cur or "").rstrip() + "\n" + block).lstrip("\n")
        apply("install tradingagents cron block", lambda: _cron_write(new))

    print("\n[result]")
    if problems:
        for p in problems:
            print(f"  NEEDS HUMAN: {p}")
    if manual:
        for m in dict.fromkeys(manual):
            print(f"  MANUAL STEP: {m}")
    print(("DRY-RUN complete — no changes made."
           if dry else f"setup complete: {len(changes)} changes"))
    return 2 if problems else (0 if not manual else 1)


def _missing_py_deps(req: Path) -> list[str]:
    """Return list of pinned deps not satisfied in system python."""
    out = []
    for line in req.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name = re.split(r"[=<>]", line)[0].strip()
        mod = {"python-telegram-bot": "telegram", "yfinance": "yfinance",
               "python-dotenv": "dotenv"}.get(name, name.split("-")[0])
        try:
            __import__(mod)
        except ImportError:
            out.append(name)
    return out


# ------------------------- backup / restore -------------------------

FMT_VER = 1
# (worktree-key, rel-path, classification)
_BACKUP_SET = [
    ("ALPHA_DIR", "alpha_rnd/monitor_state.json", "ECONOMIC_AUTHORITY"),
    ("ALPHA_DIR", "alpha_rnd/live_watchlist.json", "OPERATIONAL"),
    ("ALPHA_DIR", "alpha_rnd/scheduler_state.json", "OPERATIONAL"),
    ("ALPHA_DIR", "alpha_rnd/trigger_events.jsonl", "ECONOMIC_EVENT_LOG"),
    ("ALPHA_DIR", "alpha_rnd/scheduler_events.jsonl", "OPERATIONAL"),
    ("ALPHA_DIR", "alpha_rnd/management_policy.json", "POLICY"),
    ("ALPHA_DIR", "alpha_rnd/management_events.jsonl", "SHADOW_LOG"),
    ("ALPHA_DIR", "evaluations/alpha_rnd_v1/alpha_paper_ledger.jsonl",
     "ECONOMIC_LEDGER"),
    ("ALPHA_DIR", "evaluations/alpha_rnd_v1/management_state.json",
     "OPERATIONAL"),
    ("ALPHA_DIR", "evaluations/alpha_rnd_v1/management_actions.json",
     "OPERATIONAL"),
    ("C12_DIR", "evaluations/gate_c12_prospective/c12_paper_portfolio.jsonl",
     "ECONOMIC_AUTHORITY"),
    ("C12_DIR", "evaluations/gate_c12_prospective/c12_nav.jsonl",
     "ECONOMIC_AUTHORITY"),
    ("C12_DIR", "evaluations/gate_c12_prospective/c12_signal_ledger.jsonl",
     "ECONOMIC_AUTHORITY"),
    ("C12_DIR", "evaluations/gate_c12_prospective/scheduler_state.json",
     "OPERATIONAL"),
    ("C12_DIR", "evaluations/gate_c12_prospective/journal.jsonl",
     "OPERATIONAL"),
]
_BACKUP_DIRS = [  # whole directories, same consistency rules
    ("ALPHA_DIR", "evaluations/alpha_rnd_v1/management_intents",
     "SHADOW_ARTIFACT"),
    ("C12_DIR", "evaluations/gate_c12_prospective/weeks", "OPERATIONAL"),
]
_LOCKS = [("ALPHA_DIR", "alpha_rnd/monitor_state.lock"),
          ("ALPHA_DIR", "alpha_rnd/scheduler_state.lock"),
          ("C12_DIR", "evaluations/gate_c12_prospective/c12_scheduler.lock")]
_REQUIRED = {"ECONOMIC_AUTHORITY", "ECONOMIC_LEDGER"}


def _sha256(b: bytes) -> str:
    import hashlib
    return hashlib.sha256(b).hexdigest()


def _git(d: Path):
    try:
        sha = subprocess.run(["git", "-C", str(d), "rev-parse", "HEAD"],
                             capture_output=1, text=1).stdout.strip()
        dirty = bool(subprocess.run(["git", "-C", str(d), "status",
                                     "--porcelain"], capture_output=1,
                                    text=1).stdout.strip())
        return {"sha": sha, "dirty": dirty}
    except Exception:
        return {}


def _alpha_summary(lay):
    try:
        st = json.loads((Path(lay["ALPHA_DIR"]) /
                         "alpha_rnd/monitor_state.json").read_text())
        pol = {}
        try:
            pol = json.loads((Path(lay["ALPHA_DIR"]) /
                              "alpha_rnd/management_policy.json").read_text())
        except Exception:
            pass
        return {"cash": st.get("cash"), "realized": st.get("realized"),
                "positions": {t: {"shares": p.get("shares"),
                                  "fill": p.get("fill"),
                                  "stop_rule": p.get("stop_rule")}
                              for t, p in
                              (st.get("positions") or {}).items()},
                "pending_in": len(st.get("pending_open_fills") or []),
                "pending_out": len(st.get("pending_open_exits") or []),
                "executed": st.get("executed") or [],
                "mark_session": (st.get("book") or {}).get("mark_session"),
                "adaptive_execution_enabled":
                    bool((pol.get("execution") or {}).get("enabled"))}
    except Exception as e:
        return {"error": repr(e)}


def _c12_summary(lay):
    d = Path(lay["C12_DIR"]) / "evaluations/gate_c12_prospective"
    out = {}
    try:
        last = json.loads(d.joinpath("c12_nav.jsonl")
                          .read_text().strip().splitlines()[-1])
        out["nav"] = last.get("nav")
        out["open_positions"] = last.get("open_positions")
    except Exception as e:
        out["error"] = repr(e)
    return out


def cmd_backup(a):
    """Create a consistent, validated backup archive. READ-ONLY vs state
    (takes the same flocks briefly; writes only the archive file)."""
    import fcntl, tarfile
    lay = _layout(Path(a.prefix).resolve())
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = Path(a.output or
               f"tradingagents-backup-{a.label or ts}.tar.gz").resolve()
    stage = {}
    manifest = {"format_version": FMT_VER, "backup_id": out.stem,
                "created_utc": ts, "hostname": os.uname().nodename,
                "os": " ".join(os.uname()[:3]), "repo_root": str(lay["BASE_DIR"]),
                "prefix": str(Path(a.prefix).resolve()),
                "python": sys.version.split()[0],
                "git": {k: _git(Path(v)) for k, v in lay.items()
                        if k.endswith("_DIR") and Path(v).exists()},
                "alpha": _alpha_summary(lay),
                "c12": _c12_summary(lay),
                "secrets_required_not_included":
                    ["~/.config/tradingagents/telegram.env",
                     "devin CLI auth (~/.local/bin/devin login state)"],
                "files": [], "captured_utc": {}}

    # consistent point-in-time: hold the same flocks the writers use
    locks = []
    try:
        for k, rel in _LOCKS:
            lp = Path(lay[k]) / rel
            lf = open(lp, "a")
            fcntl.flock(lf, fcntl.LOCK_EX)
            locks.append((lp, lf))
        manifest["captured_utc"] = {lp.name: ts for lp, _ in locks}
        for k, rel, cls in _BACKUP_SET + _BACKUP_DIRS:
            src = Path(lay[k]) / rel
            if not src.exists():
                if cls in _REQUIRED:
                    print(f"FAIL required authority missing: {src}")
                    return 2
                continue
            files = sorted(src.rglob("*")) if src.is_dir() else [src]
            for f in files:
                if not f.is_file():
                    continue
                rel = str(f.relative_to(lay[k]))
                stage[f"{k}/{rel}"] = f.read_bytes()
                manifest["files"].append(
                    {"path": f"{k}/{rel}", "class": cls,
                     "size": f.stat().st_size,
                     "sha256": _sha256(stage[f"{k}/{rel}"])})
    finally:
        for _, lf in locks:
            lf.close()

    # archive AFTER locks released — never block the monitor on gzip
    with tarfile.open(out, "w:gz") as t:
        mb = json.dumps(manifest, indent=1, sort_keys=True).encode()
        import io as _io
        ti = tarfile.TarInfo("manifest.json"); ti.size = len(mb)
        t.addfile(ti, _io.BytesIO(mb))
        for rel, data in sorted(stage.items()):
            ti = tarfile.TarInfo(f"payload/{rel}"); ti.size = len(data)
            t.addfile(ti, _io.BytesIO(data))

    # validation: reopen and verify every checksum + required classes
    ok, bad = _verify_archive(out)
    if not ok:
        print(f"FAIL backup validation: {bad}")
        out.unlink(missing_ok=True)
        return 2
    have_cls = {f["class"] for f in manifest["files"]}
    if not _REQUIRED <= have_cls:
        print("FAIL backup missing required authority classes")
        out.unlink(missing_ok=True)
        return 2
    if a.dry_run:
        out.unlink(missing_ok=True)
        print(f"DRY-RUN ok: {len(stage)} files would be archived to {out}")
        return 0
    print(f"backup OK: {out}  ({len(stage)} files, "
          f"{out.stat().st_size} bytes, validated)")
    print("secrets NOT included — transfer telegram.env + devin auth "
          "separately")
    return 0


def _verify_archive(archive: Path):
    """Reopen and verify manifest + every checksum. Returns (ok, detail)."""
    import tarfile
    try:
        with tarfile.open(archive) as t:
            names = t.getnames()
            if "manifest.json" not in names:
                return False, "no manifest"
            man = json.loads(t.extractfile("manifest.json").read())
            if man.get("format_version") != FMT_VER:
                return False, f"format_version {man.get('format_version')}"
            for f in man.get("files", []):
                pn = f"payload/{f['path']}"
                if pn not in names:
                    return False, f"missing {pn}"
                if _sha256(t.extractfile(pn).read()) != f["sha256"]:
                    return False, f"checksum {f['path']}"
            for n in names:
                if n.startswith("/") or ".." in n.split("/"):
                    return False, f"unsafe path {n}"
            return True, man
    except Exception as e:
        return False, repr(e)


JOURNAL_NAME = ".restore_in_progress"
RUNTIME_KEYS = {"ALPHA_DIR", "C12_DIR", "BASE_DIR"}


def _is_clean_tracked(repo: Path, rel: str) -> bool:
    """True iff `repo/rel` is a tracked file identical to HEAD — i.e. just
    the checkout baseline, which restore may safely overwrite. Modified,
    untracked, ignored or non-repo files are NOT clean."""
    st = subprocess.run(["git", "-C", str(repo), "status", "--porcelain",
                         "--", rel], capture_output=True, text=True)
    if st.returncode != 0 or st.stdout.strip():
        return False
    tr = subprocess.run(["git", "-C", str(repo), "ls-files",
                         "--error-unmatch", "--", rel],
                        capture_output=True)
    return tr.returncode == 0


def _git_dirty_paths(repo: Path):
    """Porcelain paths of a worktree, or None if not a git repo."""
    r = subprocess.run(["git", "-C", str(repo), "status", "--porcelain"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return None
    out = []
    for ln in r.stdout.splitlines():
        p = ln[3:].strip()
        out.append(p.split(" -> ")[-1])
    return out


def _non_authority_dirty(dirty, auth_rels):
    """Porcelain entries not explained by the backup authority set.
    Git collapses untracked dirs to `dir/` — accept them when they only
    contain authority paths."""
    out = []
    for p in dirty or []:
        if p in auth_rels:
            continue
        if p.endswith("/") and any(r.startswith(p) for r in auth_rels):
            continue
        out.append(p)
    return out


def _journal_write(jp: Path, j: dict):
    j["updated_utc"] = ts_utc()
    jp.write_text(json.dumps(j, indent=1, sort_keys=True))


def _promote(jp: Path, j: dict):
    """Move unpromoted files stage->target; journal updated after each.
    On any exception the journal on disk reflects exactly what is
    already in the target — a later restore resumes deterministically."""
    for f in j["files"]:
        if f.get("promoted"):
            continue
        tgt, sp = Path(f["target"]), Path(f["staged"])
        tgt.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(sp), str(tgt))
        f["promoted"] = True
        _journal_write(jp, j)


def _verify_promoted(j: dict, problems: list):
    for f in j["files"]:
        if not f.get("promoted"):
            continue
        tgt = Path(f["target"])
        if not tgt.exists() or _sha256(tgt.read_bytes()) != f["sha256"]:
            problems.append(f"promoted file unverifiable: {tgt}")


def _stage_from_archive(archive: Path, man: dict, lay: dict,
                        stage_root: Path):
    """Extract+checksum every manifest file under stage_root.
    Returns journal file list. Raises on any failure."""
    import tarfile
    files = []
    with tarfile.open(archive) as t:
        for ent in man.get("files", []):
            k, rel = ent["path"].split("/", 1)
            sp = stage_root / k / rel
            sp.parent.mkdir(parents=True, exist_ok=True)
            data = t.extractfile(f"payload/{ent['path']}").read()
            if _sha256(data) != ent["sha256"]:
                raise RuntimeError(f"checksum {rel}")
            sp.write_bytes(data)
            files.append({"target": str(Path(lay[k]) / rel),
                          "staged": str(sp), "sha256": ent["sha256"],
                          "promoted": False})
    return files


def _rollback_partial(jp: Path, j: dict):
    """Delete ONLY journal-listed, checksum-verified files of an
    incomplete transaction. Refuses (raises) on anything unverifiable —
    never touches foreign content."""
    prefix = jp.parent.resolve()
    for f in j["files"]:
        tgt = Path(f["target"]).resolve()
        if prefix not in tgt.parents:
            raise RuntimeError(f"journal path escapes prefix: {tgt}")
        if not tgt.exists():
            continue
        if _sha256(tgt.read_bytes()) != f["sha256"]:
            raise RuntimeError(
                f"rollback cannot verify {tgt} — content differs from the "
                "backup; refusing to delete. Inspect manually.")
        tgt.unlink()
    jp.unlink()


def cmd_restore(a):
    """Fail-closed, transactional restore into an EMPTY target.
    MUTATING (files only; never starts services or cron).
    Stages + validates everything before promotion; promotion is journaled
    so an interrupted restore resumes by simply re-running this command
    with the same archive. No overwrite mode exists."""
    import tempfile, shutil as _sh
    archive = Path(a.archive)
    ok, man = _verify_archive(archive)
    if not ok:
        print(f"FAIL archive invalid: {man}")
        return 2
    man = man if isinstance(man, dict) else {}
    prefix = Path(a.prefix).resolve()
    lay = _layout(prefix)
    dry = a.dry_run
    problems = []
    jp = prefix / JOURNAL_NAME
    journal = None
    if jp.exists():
        try:
            journal = json.loads(jp.read_text())
        except Exception as e:
            print(f"FAIL unreadable restore journal {jp}: {e}")
            return 2
        if journal.get("backup_id") != man.get("backup_id"):
            print(f"REFUSE incomplete restore belongs to backup "
                  f"{journal.get('backup_id')} — rerun "
                  f"`ops.ta restore` with THAT archive")
            return 2
        print(f"incomplete restore transaction detected "
              f"(txn {journal.get('txn_id')}) — resuming")

    # 1) eligibility: fresh target must have EMPTY authority paths; a
    #    resumed transaction legitimately has partial state. Services are
    #    only a refusal when the RUNNING unit is configured for THIS
    #    prefix — a sim restore elsewhere must not be blocked by prod.
    for u in UNITS:
        uf = Path.home() / ".config" / "systemd" / "user" / u
        bound = False
        try:
            bound = str(prefix) in uf.read_text()
        except OSError:
            pass
        if bound and _svc(u) == "active":
            problems.append(f"{u} is ACTIVE for this prefix — refusing "
                            "restore into a running installation")
    auth_rels = {k: set() for k in lay}
    for ent in man.get("files", []):
        k, rel = ent["path"].split("/", 1)
        auth_rels.setdefault(k, set()).add(rel)
    if journal is None:
        for ent in man.get("files", []):
            k, rel = ent["path"].split("/", 1)
            tgt = Path(lay[k]) / rel
            if not (tgt.exists() and tgt.stat().st_size):
                continue
            # a clean tracked file is only the git baseline — overwriting
            # it IS the restore. Dirty/untracked content = living state.
            if _is_clean_tracked(Path(lay[k]), rel):
                continue
            problems.append(f"non-empty authority exists: {tgt}")

    # 2) code compatibility: runtime worktrees must PROVE the backup SHA.
    #    unverifiable runtime code fails closed; tracks/docs warn only.
    gitman = man.get("git") or {}
    for k in sorted(RUNTIME_KEYS):
        g = gitman.get(k) or {}
        cur = _git(Path(lay[k])) if Path(lay[k]).exists() else {}
        if not g.get("sha"):
            problems.append(f"{k}: backup manifest has no code SHA — "
                            "cannot verify runtime version")
        elif not cur.get("sha"):
            problems.append(
                f"CANNOT VERIFY RUNTIME CODE VERSION: {k} is not a git "
                f"checkout at {lay[k]} — backup requires commit "
                f"{g['sha'][:8]}; `git -C {lay[k]} checkout {g['sha']}`")
        elif g["sha"] != cur["sha"]:
            problems.append(
                f"{k} code mismatch: BACKUP was created by {g['sha'][:8]} "
                f"but target runs {cur['sha'][:8]} — "
                f"`git -C {lay[k]} checkout {g['sha']}`")
        else:
            dirty = _git_dirty_paths(Path(lay[k]))
            extra = _non_authority_dirty(dirty, auth_rels.get(k, set()))
            if extra:
                more = "…" if len(extra) > 1 else ""
                problems.append(
                    f"{k} worktree has uncommitted/untracked files outside "
                    f"the authority set ({extra[0]}{more}) — effective "
                    "code version unverifiable")
    for k, g in gitman.items():
        if k in RUNTIME_KEYS or not g.get("sha"):
            continue
        cur = _git(Path(lay[k])) if Path(lay[k]).exists() else {}
        if cur.get("sha") and cur["sha"] != g["sha"]:
            print(f"  WARN {k} differs ({g['sha'][:8]} vs "
                  f"{cur['sha'][:8]}) — non-runtime; continuing")
    if problems:
        for p_ in problems:
            print(f"  REFUSE {p_}")
        print("restore aborted — fix the refusals or use an empty target "
              "with matching code")
        return 2

    # 3) resume or rollback an interrupted transaction
    if journal is not None:
        _verify_promoted(journal, problems)
        if problems:
            for p_ in problems:
                print(f"  REFUSE {p_}")
            return 2
        stage_root = Path(journal["stage_root"])
        todo = [f for f in journal["files"] if not f.get("promoted")]
        if not todo:
            # every file landed; only journal cleanup remained
            if dry:
                print("DRY-RUN ok: transaction complete, journal cleanup "
                      "only")
                return 0
            jp.unlink()
            _sh.rmtree(stage_root, ignore_errors=True)
            print(f"restore OK: {len(journal['files'])} files verified "
                  f"(recovered transaction)")
            return 0
        if stage_root.exists():
            # resume from the existing verified stage
            bad = [f["staged"] for f in todo
                   if not Path(f["staged"]).exists() or
                   _sha256(Path(f["staged"]).read_bytes()) != f["sha256"]]
            if bad:
                print(f"FAIL staged files unverifiable: {bad[0]} — "
                      "cannot safely resume")
                return 2
            if dry:
                print(f"DRY-RUN ok: would resume {len(todo)} files from "
                      "existing stage")
                return 0
            try:
                _promote(jp, journal)
                jp.unlink()
            except Exception as e:
                print(f"FAIL promotion interrupted again: {e} — journal "
                      f"{jp} kept; rerun restore with the same archive")
                return 2
            _sh.rmtree(stage_root, ignore_errors=True)
            print(f"restore OK: resumed transaction, "
                  f"{len(journal['files'])} files total")
            print("NOT auto-started: fill secrets, then `python3 -m "
                  "ops.ta setup` for units/cron, then health")
            return 0
        # stage lost -> roll back ONLY journal-verified partial files,
        # then fall through to a fresh restore of the same backup
        print("stage directory gone — rolling back verified partial "
              "files, then re-restoring from archive")
        try:
            _rollback_partial(jp, journal)
        except Exception as e:
            print(f"FAIL recovery: {e}")
            return 2
        journal = None
        if dry:
            print("DRY-RUN ok: partial state rolled back; would restore "
                  "fresh")
            return 0

    # 4) stage EVERYTHING into a sibling temp dir (same fs for atomic
    #    rename promotion)
    prefix.mkdir(parents=True, exist_ok=True)
    stage_root = Path(tempfile.mkdtemp(prefix=".restore_stage_",
                                       dir=str(prefix)))
    try:
        files = _stage_from_archive(archive, man, lay, stage_root)
        # 5) continuity on the STAGED set (not the target)
        lay_staged = {k: str(stage_root / k) for k in lay}
        for field in ("cash", "realized", "positions", "executed"):
            if (man.get("alpha") or {}).get(field) != \
                    _alpha_summary(lay_staged).get(field):
                raise RuntimeError(f"continuity {field}")
        if (man.get("c12") or {}).get("nav") != \
                _c12_summary(lay_staged).get("nav"):
            raise RuntimeError("continuity c12 nav")
        if dry:
            print(f"DRY-RUN ok: {len(files)} files staged+validated, "
                  f"backup {man.get('backup_id')}")
            _sh.rmtree(stage_root)
            return 0
        # 6) journal THEN promote — crash-safe: journal always reflects
        #    exactly which files reached the target
        journal = {"txn_id": f"restore-{ts_utc()}",
                   "backup_id": man.get("backup_id"),
                   "archive": str(archive), "stage_root": str(stage_root),
                   "files": files}
        _journal_write(jp, journal)
        try:
            _promote(jp, journal)
            jp.unlink()
        except Exception as e:
            print(f"FAIL promotion interrupted: {e} — journal kept at "
                  f"{jp}; rerun `python3 -m ops.ta restore {archive} "
                  f"--prefix {prefix}` to resume automatically")
            return 2
    except Exception as e:
        _sh.rmtree(stage_root, ignore_errors=True)
        print(f"FAIL restore: {e} — target untouched (pre-promotion)")
        return 2
    _sh.rmtree(stage_root, ignore_errors=True)

    print(f"restore OK: {len(files)} files; authority verified "
          "pre-promotion")
    print("NOT auto-started: fill secrets, then "
          "`python3 -m ops.ta setup` for units/cron, then health")
    return 0


# ------------------------- workspace -------------------------

WS_SPEC = TRACKS / "ops" / "workspace.json"


def _ws_spec():
    return json.loads(WS_SPEC.read_text())["roles"]


def _git_branch(d: Path):
    """(branch, head_sha). branch is symbolic name or 'DETACHED'."""
    b = subprocess.run(["git", "-C", str(d), "symbolic-ref", "--short",
                        "-q", "HEAD"], capture_output=True, text=True)
    sha = subprocess.run(["git", "-C", str(d), "rev-parse", "HEAD"],
                         capture_output=True, text=True)
    if sha.returncode != 0:
        return None, None
    return (b.stdout.strip() or "DETACHED", sha.stdout.strip())


def _worktree_list(repo_anchor: Path):
    """[(path, branch)] for all worktrees of the repo containing anchor."""
    r = subprocess.run(["git", "-C", str(repo_anchor), "worktree", "list",
                        "--porcelain"], capture_output=True, text=True)
    if r.returncode != 0:
        return []
    out, cur = [], {}
    for ln in r.stdout.splitlines() + [""]:
        if ln.startswith("worktree "):
            cur = {"path": ln[9:]}
        elif ln.startswith("branch "):
            cur["branch"] = ln[7:].removeprefix("refs/heads/")
        elif not ln.strip() and cur.get("path"):
            out.append(cur); cur = {}
    return out


def _ws_state(prefix: Path):
    """Per-role workspace state. Returns {role: {...}}."""
    spec = _ws_spec()
    anchor = prefix / spec["TRACKS"]["path"]
    if not anchor.exists():
        anchor = prefix / spec["BASE"]["path"]
    wt = _worktree_list(anchor) if anchor.exists() else []
    by_branch = {w.get("branch"): w["path"] for w in wt if w.get("branch")}
    state = {}
    for role, s in spec.items():
        d = prefix / s["path"]
        e = {"path": str(d), "expected_branch": s["branch"],
             "required": s["required_for_production"],
             "status": "OK", "branch": None, "head": None, "dirty": 0}
        if not d.exists():
            alt = by_branch.get(s["branch"])
            e["status"] = (f"MISSING (branch checked out at {alt})"
                           if alt else "MISSING")
        elif not (d / ".git").exists():
            e["status"] = "CONFLICT (exists but not a git worktree)"
        else:
            br, head = _git_branch(d)
            e["branch"], e["head"] = br, head
            if br != s["branch"]:
                e["status"] = (f"WRONG_BRANCH ({br or '?'} != {s['branch']})"
                               if br != "DETACHED" else "DETACHED")
            else:
                dirty = _git_dirty_paths(d)
                e["dirty"] = len(dirty or [])
        state[role] = e
    return state


def cmd_workspace(a):
    """Create/inspect the canonical multi-worktree workspace.
    `status` READ-ONLY; `setup` MUTATING (git worktree add only, never
    deletes/overwrites), --dry-run safe."""
    prefix = Path(a.prefix).resolve()
    spec = _ws_spec()
    state = _ws_state(prefix)

    if a.action == "status":
        worst = 0
        for role, s in spec.items():
            e = state[role]
            lvl = {"OK": 0, "DIRTY": 0}.get(e["status"], 2 if e["required"]
                                            else 1)
            if e["status"] == "OK" and e["dirty"]:
                lvl = 0
            worst = max(worst, lvl)
            req = "required" if e["required"] else "optional"
            print(f"{role:<7} {e['status']:<38} {e['path']}")
            if e["status"] == "OK":
                print(f"        branch {e['branch']} @ "
                      f"{(e['head'] or '?')[:8]}, dirty files: "
                      f"{e['dirty']} ({req})")
            else:
                print(f"        want branch {e['expected_branch']} ({req})")
        return worst

    # setup
    dry = a.dry_run
    problems, changes = [], []
    anchor = prefix / spec["TRACKS"]["path"]
    if not anchor.exists():
        anchor = prefix / spec["BASE"]["path"]
    if not anchor.exists():
        print("FAIL no repository found in workspace — clone the repo "
              "first, then: `git -C <clone> worktree add "
              f"{spec['TRACKS']['path']} {spec['TRACKS']['branch']}`")
        return 2
    for role, s in spec.items():
        e = state[role]
        if not s["required_for_production"] and not a.with_optional:
            print(f"  SKIP {role} (optional, --with-optional to create)")
            continue
        if e["status"] == "OK":
            print(f"  SKIP {role} exists @ {e['path']}")
        elif e["status"].startswith("MISSING"):
            d = prefix / s["path"]
            if "checked out at" in e["status"]:
                problems.append(f"{role} branch {s['branch']} already "
                                f"checked out elsewhere — {e['status']}")
                print(f"  FAIL {problems[-1]}")
                continue
            cmd = ["git", "-C", str(anchor), "worktree", "add", str(d),
                   s["branch"]]
            if dry:
                print(f"  DRY  git -C {anchor} worktree add {d} "
                      f"{s['branch']}")
                changes.append(role)
            else:
                r = subprocess.run(cmd, capture_output=True, text=True)
                if r.returncode != 0:
                    problems.append(f"{role} worktree add failed: "
                                    f"{r.stderr.strip()[:120]}")
                    print(f"  FAIL {problems[-1]}")
                else:
                    print(f"  DONE {role} -> {d} [{s['branch']}]")
                    changes.append(role)
        else:
            problems.append(f"{role}: {e['status']} — refusing to touch; "
                            "resolve manually")
            print(f"  FAIL {problems[-1]}")
    if problems:
        print("\nworkspace incomplete — fix FAIL items above")
        return 2
    print(("DRY-RUN complete — no changes" if dry else
           f"workspace ready ({len(changes)} created)"))
    return 0


# ------------------------- boot recovery self-test -------------------------

def _boot_id():
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except OSError:
        return "unknown"


def cmd_bootcheck(a):
    """Post-boot recovery verification. READ-ONLY vs trading state;
    writes only its own operational artifact boot_health.json.
    Exit 0=HEALTHY 1=DEGRADED 2=FAILED. Never trades, never calls models."""
    prefix = Path(a.prefix).resolve()
    lay = _layout(prefix)
    comps = []
    S = {"ok": "OK", "degraded": "DEGRADED", "fail": "FAILED"}

    def chk(name, ok, level="fail", note=""):
        comps.append({"name": name, "state": level if not ok else "ok",
                      "note": note})
        print(f"  [{S[level] if not ok else 'OK':>7}] {name}"
              + (f"  {note}" if note else ""))

    for d in (lay["BASE_DIR"], lay["ALPHA_DIR"], lay["C12_DIR"]):
        chk(f"worktree present {Path(d).name}", Path(d).exists())
    chk("no incomplete restore transaction",
        not (prefix / JOURNAL_NAME).exists())
    chk("bridge service active", _svc(UNITS[0]) == "active")
    chk("telegram relay active", _svc(UNITS[1]) == "active",
        level="degraded", note=_svc(UNITS[1]))
    chk("bootcheck timer active", _svc(BOOT_TIMER) == "active",
        level="degraded", note=_svc(BOOT_TIMER))
    msg, age = _fresh(Path(lay["ALPHA_DIR"]) / "alpha_rnd/monitor_cron.log",
                      240)
    chk("ALPHA monitor resumed", 0 <= age <= 240, note=msg)
    try:
        st = json.loads((Path(lay["ALPHA_DIR"]) /
                         "alpha_rnd/monitor_state.json").read_text())
        chk("ALPHA economic state readable", True,
            note=f"cash ${st['cash']:,.0f}")
        chk("ALPHA pending sane", isinstance(st.get("pending_open_fills"),
                                             list))
    except Exception as e:
        chk("ALPHA economic state readable", False, note=repr(e)[:50])
    slog = Path(lay["ALPHA_DIR"]) / "alpha_rnd/scheduler.log"
    try:
        age_s = datetime.now(timezone.utc).timestamp() - slog.stat().st_mtime
        chk("ALPHA scheduler ran <25h", age_s < 90000, level="degraded")
    except OSError:
        chk("ALPHA scheduler log exists", False, level="degraded")
    cslog = Path(lay["C12_DIR"]) / \
        "evaluations/gate_c12_prospective/scheduler.log"
    try:
        age_c = datetime.now(timezone.utc).timestamp() - cslog.stat().st_mtime
        chk("C12 scheduler ran <25h", age_c < 90000, level="degraded")
    except OSError:
        chk("C12 scheduler log exists", False, level="degraded")
    cron = _cron_read() or ""
    have = sum(1 for j in ("alpha_rnd.monitor", "alpha_rnd.daily_scheduler",
                           "ta_eval.c12_scheduler") if j in cron)
    chk("cron jobs present", have == 3, level="degraded",
        note=f"{have}/3")
    try:
        en = bool((json.loads((Path(lay["ALPHA_DIR"]) / "alpha_rnd" /
                               "management_policy.json").read_text())
                   .get("execution") or {}).get("enabled"))
        chk("adaptive execution state known", True,
            note="enabled" if en else "disabled")
    except Exception:
        chk("adaptive execution state known", False, level="degraded")
    chk("bridge /healthz recovered",
        bool(_get("http://127.0.0.1:8765/healthz")), level="degraded",
        note="local listener only — no inference call")

    worst = max(({"ok": 0, "degraded": 1, "fail": 2}[c["state"]]
                 for c in comps), default=2)
    overall = ("HEALTHY" if worst == 0 else
               "DEGRADED" if worst == 1 else "FAILED")

    state_file = Path(a.state_file).expanduser() if a.state_file else \
        Path.home() / ".config" / "tradingagents" / "boot_health.json"
    boot = _boot_id()
    rec = {"boot_id": boot, "checked_utc": ts_utc(), "overall": overall,
           "components": comps}
    try:
        prev = json.loads(state_file.read_text())
        if prev.get("boot_id") == boot:
            if prev.get("recovered_utc"):
                rec["recovered_utc"] = prev["recovered_utc"]
            elif prev.get("overall") != "HEALTHY" and overall == "HEALTHY":
                rec["recovered_utc"] = rec["checked_utc"]
    except Exception:
        pass
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(rec, indent=1))
    print(f"\nBOOT RECOVERY: {overall}  ({state_file})")
    return worst


def ts_utc():
    return datetime.now(timezone.utc).isoformat()


def _sysctl():
    env = os.environ.copy()
    env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    env.setdefault("DBUS_SESSION_BUS_ADDRESS",
                   f"unix:path={env['XDG_RUNTIME_DIR']}/bus")
    return ["env", *[f"{k}={v}" for k, v in env.items()
                     if k.startswith(("XDG_", "DBUS_"))],
            "systemctl", "--user"]


def _cron_read():
    r = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ""


def _cron_write(text):
    subprocess.run(["crontab", "-"], input=text, text=True, check=1)


# ------------------------- health -------------------------

def _fresh(path: Path, max_age_s: int, pat: str = r"checked") -> tuple[str, int]:
    """Newest matching-log timestamp age in seconds."""
    try:
        lines = path.read_bytes()[-20000:].decode(errors="replace").splitlines()
    except OSError:
        return "log missing", -1
    ts = [re.search(r"(202\d-\d\d-\d\dT\d\d:\d\d:\d\d)", l)
          for l in lines if pat in l]
    ts = [t.group(1) for t in ts if t]
    if not ts:
        return "no recent ticks in log", -1
    last = datetime.fromisoformat(ts[-1]).replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - last).total_seconds()
    return (f"last tick {int(age)}s ago", age)


def _svc(name):
    r = subprocess.run(["systemctl", "--user", "is-active", name],
                       capture_output=True, text=True,
                       env={**os.environ,
                            "XDG_RUNTIME_DIR": f"/run/user/{os.getuid()}"})
    return r.stdout.strip()


def _get(url, t=4):
    try:
        with urllib.request.urlopen(url, timeout=t) as r:
            return json.loads(r.read())
    except Exception:
        return None


def cmd_health(a):
    """Comprehensive READ-ONLY health report.
    Exit 0=HEALTHY 1=DEGRADED 2=FAILED."""
    lay = _layout(Path(a.prefix).resolve())
    checks = []
    S = {"ok": "HEALTHY", "degraded": "DEGRADED", "fail": "FAILED"}

    jp = Path(a.prefix).resolve() / JOURNAL_NAME
    if jp.exists():
        checks.append(("restore transaction", "fail", ""))
        print("  [  FAILED] INCOMPLETE RESTORE TRANSACTION — "
              f"{jp} present; rerun `ops.ta restore` with the same "
              "archive")

    boot = {}
    try:
        boot = json.loads((Path.home() / ".config" / "tradingagents" /
                           "boot_health.json").read_text())
    except Exception:
        pass
    if boot.get("boot_id") == _boot_id():
        bs = boot.get("overall")
        lvl = {"HEALTHY": None, "DEGRADED": "degraded"}.get(bs, "fail")
        notes = "; ".join(c["name"] for c in boot.get("components", [])
                          if c.get("state") != "ok")
        checks.append(("boot recovery", lvl or "ok", notes[:80]))
        print(f"  [{'OK' if not lvl else S[lvl].upper():>7}] boot "
              f"recovery: {bs}" + (f"  {notes[:80]}" if notes else ""))
    else:
        checks.append(("boot recovery", "degraded", ""))
        print("  [DEGRADED] boot recovery: no bootcheck record for this "
              "boot (timer runs it ~2min after boot)")

    def chk(name, ok, level="fail", note=""):
        checks.append((name, level if not ok else "ok", note))
        print(f"  [{'OK' if ok else S[level].upper():>7}] {name}"
              + (f"  {note}" if note else ""))

    mlog = Path(lay["ALPHA_DIR"]) / "alpha_rnd/monitor_cron.log"
    msg, age = _fresh(mlog, 240)
    chk("ALPHA monitor ticking", 0 <= age <= 240, note=msg)

    mstate = Path(lay["ALPHA_DIR"]) / "alpha_rnd/monitor_state.json"
    st = None
    try:
        st = json.loads(mstate.read_text())
        chk("ALPHA economic state readable", True,
            note=f"cash ${st['cash']:,.0f}, {len(st['positions'])} open")
    except Exception as e:
        chk("ALPHA economic state readable", False, note=repr(e)[:60])
    if st:
        chk("ALPHA pending orders sane",
            isinstance(st.get("pending_open_fills"), list) and
            isinstance(st.get("pending_open_exits"), list),
            level="degraded",
            note=f"{len(st.get('pending_open_fills', []))} in / "
                 f"{len(st.get('pending_open_exits', []))} out")
    slog = Path(lay["ALPHA_DIR"]) / "alpha_rnd/scheduler.log"
    try:
        age_s = (datetime.now(timezone.utc).timestamp()
                 - slog.stat().st_mtime)
        chk("ALPHA scheduler ran <25h", age_s < 90000, level="degraded",
            note=f"{int(age_s/3600)}h ago")
    except OSError:
        chk("ALPHA scheduler log exists", False, level="degraded")

    cslog = Path(lay["C12_DIR"]) / "evaluations/gate_c12_prospective/scheduler.log"
    try:
        age_c = (datetime.now(timezone.utc).timestamp()
                 - cslog.stat().st_mtime)
        chk("C12 scheduler ran <25h", age_c < 90000, level="degraded",
            note=f"{int(age_c/3600)}h ago")
    except OSError:
        chk("C12 scheduler log exists", False, level="degraded")
    cnav = Path(lay["C12_DIR"]) / "evaluations/gate_c12_prospective/c12_nav.jsonl"
    chk("C12 state readable", cnav.exists() and cnav.stat().st_size > 0,
        level="degraded")

    h = _get("http://127.0.0.1:8765/healthz")
    chk("SWE bridge /healthz", bool(h and h.get("runtime_ready")),
        note=("devin-quick→" + str((h or {}).get("models", {})
              .get("devin-quick") or "?")) if h else "no listener")
    chk("bridge unit active", _svc(UNITS[0]) == "active", level="degraded",
        note=_svc(UNITS[0]))
    chk("telegram relay active", _svc(UNITS[1]) == "active", level="degraded",
        note=_svc(UNITS[1]))
    chk("telegram config present",
        (Path.home() / ".config/tradingagents/telegram.env").exists(),
        level="degraded")
    chk("devin CLI present (bridge auth)",
        (Path.home() / ".local/bin/devin").exists() or
        bool(shutil.which("devin")), level="degraded",
        note="bridge delegates auth to it")
    cron = _cron_read() or ""
    _jobs = ("alpha_rnd.monitor", "alpha_rnd.daily_scheduler",
             "alpha_rnd.cohort_outcomes", "ta_eval.c12_scheduler")
    have = sum(1 for j in _jobs if j in cron)
    chk("cron jobs installed (4)", have == 4, level="degraded",
        note="tagged block" if f">>> {CRON_TAG} >>>" in cron else
             f"{have}/4 legacy entries — untagged, rerunnable anyway")

    # Adaptive execution is legitimately ENABLED for paper since 2026-10-16
    # (E1 acceptance). The invariant is provenance, not the flag value:
    # enabled requires activation provenance (activated_at/for); a bare
    # enabled flag is suspicious. Disabled is the conservative default.
    pol = Path(lay["ALPHA_DIR"]) / "alpha_rnd/management_policy.json"
    try:
        ex = (json.loads(pol.read_text()).get("execution") or {})
        en = ex.get("enabled")
        if not isinstance(en, bool):
            chk("adaptive execution policy well-formed", False,
                note="execution.enabled missing/not boolean")
        elif en:
            prov = bool(ex.get("activated_at") and ex.get("activated_for"))
            chk("adaptive execution ENABLED with provenance", prov,
                level="degraded",
                note=(f"activated {ex.get('activated_at')} for "
                      f"{ex.get('activated_for')}" if prov else
                      "enabled without activated_at/activated_for"))
        else:
            chk("adaptive execution disabled (conservative)", True,
                note="disabled")
    except Exception:
        chk("management policy readable", False, level="degraded")

    for d in (Path(lay["ALPHA_DIR"]) / "alpha_rnd",
              Path(lay["C12_DIR"]) / "evaluations/gate_c12_prospective"):
        chk(f"{d.name} writable", os.access(d, os.W_OK), level="degraded")

    worst = max(({"ok": 0, "degraded": 1, "fail": 2}[c[1]] for c in checks),
                default=2)
    verdict = ("HEALTHY" if worst == 0 else
               "DEGRADED" if worst == 1 else "FAILED")
    print(f"\nOVERALL: {verdict}")
    return worst


def cmd_status(a):
    """Short READ-ONLY operator summary."""
    lay = _layout(Path(a.prefix).resolve())
    st = {}
    try:
        st = json.loads((Path(lay["ALPHA_DIR"]) /
                         "alpha_rnd/monitor_state.json").read_text())
    except Exception:
        pass
    msg, age = _fresh(Path(lay["ALPHA_DIR"]) / "alpha_rnd/monitor_cron.log", 1e9)
    pol = {}
    try:
        pol = json.loads((Path(lay["ALPHA_DIR"]) /
                          "alpha_rnd/management_policy.json").read_text())
    except Exception:
        pass
    pend_in = len(st.get("pending_open_fills", []) or [])
    pend_out = len(st.get("pending_open_exits", []) or [])
    print(f"""TRADINGAGENTS STATUS (read-only)

ALPHA monitor : {msg}
ALPHA cash    : ${st.get('cash', 0):,.2f}   realized ${st.get('realized', 0):,.2f}
ALPHA positions: {', '.join(f"{t} {p['shares']}sh" for t, p in
                (st.get('positions') or {}).items()) or 'none'}
ALPHA pending : {pend_in} entries / {pend_out} exits
C12 scheduler : see `ops/ta health` (hourly)
SWE bridge    : {_svc(UNITS[0])}
Telegram      : {_svc(UNITS[1])}
Adaptive exec : {'ENABLED' if (pol.get('execution') or {}).get('enabled')
                 else 'DISABLED'}""")
    return 0


def main():
    ap = argparse.ArgumentParser(prog="ops/ta",
                                 description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for c in ("setup", "health", "status", "backup", "restore",
              "workspace", "bootcheck"):
        p = sub.add_parser(c,
                           help={"setup": "MUTATING bootstrap (--dry-run safe)",
                                 "health": "READ-ONLY deep check (0/1/2)",
                                 "status": "READ-ONLY short summary",
                                 "backup": "read-only consistent archive",
                                 "restore": "MUTATING, fail-closed, empty target",
                                 "workspace": "workspace status/setup",
                                 "bootcheck": "boot recovery self-test"
                                 }[c])
        p.add_argument("--prefix", default=str(TRACKS.parent),
                       help="parent dir holding the worktrees")
        if c == "setup":
            p.add_argument("--dry-run", action="store_true")
            p.add_argument("--config-dir",
                           default=str(Path.home() / ".config"))
            p.add_argument("--no-systemctl", action="store_true")
            p.add_argument("--sim", action="store_true",
                           help="write units under config-dir (simulation)")
        if c == "backup":
            p.add_argument("--output")
            p.add_argument("--label")
            p.add_argument("--dry-run", action="store_true")
        if c == "restore":
            p.add_argument("archive")
            p.add_argument("--dry-run", action="store_true")
        if c == "workspace":
            p.add_argument("action", nargs="?", default="status",
                           choices=["status", "setup"])
            p.add_argument("--dry-run", action="store_true")
            p.add_argument("--with-optional", action="store_true",
                           help="also create optional dev worktrees")
        if c == "bootcheck":
            p.add_argument("--state-file",
                           help="boot_health.json location "
                                "(default ~/.config/tradingagents/)")

    a = ap.parse_args()
    return {"setup": cmd_setup, "health": cmd_health, "status": cmd_status,
            "backup": cmd_backup, "restore": cmd_restore,
            "workspace": cmd_workspace, "bootcheck": cmd_bootcheck}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
