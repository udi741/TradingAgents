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
CRON_TAG = "tradingagents"


def _layout(prefix: Path) -> dict:
    return {
        "HOME": str(Path.home()),
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

    alpha = Path(lay["ALPHA_DIR"])
    venv = alpha / ".venv312"
    if not alpha.exists():
        problems.append(f"ALPHA worktree missing: {alpha} — clone + "
                        "`git worktree add` first (see NEW_MACHINE_SETUP.md)")
        print(f"\n  FAIL {problems[-1]}")
        return 2

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
    for u in UNITS:
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
        apply("enable+start bridge & telegram services",
              lambda: subprocess.run(_sysctl() + ["enable", "--now"] + UNITS,
                                     check=1))
    else:
        manual.append("systemctl --user enable --now " + " ".join(UNITS))

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

    pol = Path(lay["ALPHA_DIR"]) / "alpha_rnd/management_policy.json"
    try:
        en = bool((json.loads(pol.read_text()).get("execution") or {})
                  .get("enabled"))
        chk("adaptive execution DISABLED (expected)", not en,
            note="enabled" if en else "disabled")
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
    for c in ("setup", "health", "status"):
        p = sub.add_parser(c,
                           help={"setup": "MUTATING bootstrap (--dry-run safe)",
                                 "health": "READ-ONLY deep check (0/1/2)",
                                 "status": "READ-ONLY short summary"}[c])
        p.add_argument("--prefix", default=str(TRACKS.parent),
                       help="parent dir holding the worktrees")
        if c == "setup":
            p.add_argument("--dry-run", action="store_true")
            p.add_argument("--config-dir",
                           default=str(Path.home() / ".config"))
            p.add_argument("--no-systemctl", action="store_true")
            p.add_argument("--sim", action="store_true",
                           help="write units under config-dir (simulation)")
    a = ap.parse_args()
    return {"setup": cmd_setup, "health": cmd_health,
            "status": cmd_status}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
