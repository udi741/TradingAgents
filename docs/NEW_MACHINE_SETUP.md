# NEW MACHINE SETUP — current truthful procedure

> Capability map: `docs/TRADINGAGENTS_CAPABILITY_REFERENCE.md` (registry: `docs/TRADINGAGENTS_CAPABILITY_REGISTRY.yaml`).


Everything below is what is ACTUALLY required today. Steps marked
PORTABILITY_GAP are awkward manual work with no automation yet
(see docs/PORTABILITY_GAPS.md).

## 1. OS / machine assumptions

- Ubuntu-like Linux (developed on 6.8 kernel, systemd user sessions)
- desktop user `udi`-equivalent; systemd user lingering enabled:
  `loginctl enable-linger $USER`
- timezone: any; market logic uses exchange session dates internally
- network: outbound HTTPS to yfinance, Telegram API, Cognition/Devin
- NO local models, ever — inference goes through the SWE bridge only

## 2. System packages

```bash
sudo apt install git python3 python3-pip python3.12 python3.12-venv \
     python3-venv notify-send-bin 2>/dev/null || true
# need: python3.10+ (monitor/scheduler), python3.12 (TA inference venv),
# yfinance-capable network, notify-send (optional desktop popups)
```

## 3. Workspace — canonical spec + one command

The canonical layout is `ops/workspace.json` (machine-readable): five
checkouts of ONE repository under one parent dir. Do NOT hand-pick
folders — inspect/create with:

```bash
git clone <repo> TradingAgents                       # BASE: infra/devin-bridge
git -C TradingAgents worktree add ../TradingAgents-tracks project/tracks
cd TradingAgents-tracks
python3 -m ops.ta workspace status --prefix ..       # shows MISSING/OK per role
python3 -m ops.ta workspace setup --prefix ..        # creates required worktrees
#   (--with-optional also creates EXPERT; --dry-run shows the plan)
```

It refuses conflicting paths, wrong branches, and branches already
checked out elsewhere — it never deletes or overwrites a worktree.

Roles: BASE (runtime, bridge host), ALPHA + C12 (runtime, mutate
production state), TRACKS (control — this repo), EXPERT (optional,
parked research). Reference — the manual equivalent of workspace setup:

```bash
cd TradingAgents
git worktree add ../TradingAgents-alpha-rnd exp/alpha-rnd-v1
git worktree add ../TradingAgents-c12 exp/gate-c12-prospective
git worktree add ../TradingAgents-expert-rnd exp/expert-rnd-v2   # optional
```

(The tracks worktree must be created manually once — it is where the
tool itself lives.)

## 4. Python environments (PORTABILITY_GAP — manual)

```bash
# TA inference env (required for ALPHA deep analysis)
cd ../TradingAgents-alpha-rnd
python3.12 -m venv .venv312
.venv312/bin/pip install -e .          # pyproject.toml deps

# system-python deps for monitor/scheduler/relay
python3 -m pip install --user yfinance pandas python-telegram-bot \
     langchain-core langchain-openai langgraph requests
```

`requirements.txt` at repo root is effectively empty — dependency truth
is `pyproject.toml` + whatever the runtime modules import (GAP).

## 5. Secrets (no values committed)

```bash
mkdir -p ~/.config/tradingagents
cat > ~/.config/tradingagents/telegram.env <<'E'
TELEGRAM_BOT_TOKEN=<your bot token>
TELEGRAM_CHAT_ID=<your chat id>
E
chmod 600 ~/.config/tradingagents/telegram.env
```

Bridge auth: Devin CLI must be installed at `~/.local/bin/devin` and
authenticated (`devin` login / existing user credentials) — the bridge
execs it per call (PORTABILITY_GAP G11).

## Automated alternative (Phase 1, REAL and tested)

After cloning the worktrees, most of sections 4–7 can be done by:

```bash
cd TradingAgents-tracks
python3 -m ops.ta setup --dry-run   # shows every intended change
python3 -m ops.ta setup             # applies them (idempotent)
```

It verifies tools/python, builds .venv312, installs pinned runtime deps
(`ops/runtime_requirements.txt`), writes systemd units + the tagged cron
block from `ops/templates/`, and creates the secrets file from
`config/telegram.env.example` WITHOUT overwriting existing secrets.
Remaining manual: fill real secrets, `devin` CLI login, the initial
clone + tracks worktree (`ops.ta workspace setup` does the rest), and
python3.12 install. A `tradingagents-bootcheck.timer` unit is also
installed — it writes ~/.config/tradingagents/boot_health.json ~2min
after every boot and every 10min after; `ops.ta health` shows the
result as `boot recovery`.

## 6. Services (manual reference — the templates live in ops/templates/)

Create `~/.config/systemd/user/tradingagents-swe-bridge.service` and
`tradingagents-telegram.service` copying the units shown in
docs/SYSTEM_ARCHITECTURE.md §services (they are committed there), fixing
any differing paths, then:

```bash
systemctl --user daemon-reload
systemctl --user enable --now tradingagents-swe-bridge tradingagents-telegram
```

## 7. Cron (PORTABILITY_GAP — paste manually)

`crontab -e`, add exactly (fix the base path if different):

```
* * * * * cd .../TradingAgents-alpha-rnd && PYTHONPATH=... /usr/bin/python3 -m alpha_rnd.monitor --once >> .../monitor_cron.log 2>&1
7 * * * * ... -m alpha_rnd.daily_scheduler --check >> .../scheduler.log 2>&1
23 * * * * ... -m alpha_rnd.cohort_outcomes update >> .../cohort_outcomes.log 2>&1
0 * * * * ... -m ta_eval.c12_scheduler --check >> .../scheduler.log 2>&1
```

## 8. Health tests

```bash
curl -s http://127.0.0.1:8765/healthz        # bridge up, mappings listed
python3 -m ops.roadmap_status                 # in TradingAgents-tracks
tail -3 ../TradingAgents-alpha-rnd/alpha_rnd/monitor_cron.log
# Telegram: send /status to the bot
```

## 9. Restore state (optional)

```bash
python3 -m ops.ta restore <backup.tar.gz> --dry-run
python3 -m ops.ta restore <backup.tar.gz>
```

Restores the full authority set (see docs/STATE_AND_DATA_AUTHORITY.md).
Rules: EMPTY target only (clean checked-out baselines are fine; dirty or
untracked authority = REFUSE), runtime worktrees must be git checkouts at
the manifest SHAs (the error prints the exact commit to check out;
unverifiable code = REFUSE), staged+verified before promotion, journaled
promotion — if the machine crashes mid-restore just rerun the same
command; it resumes or safely rolls back. Secrets transfer separately.
Runtime is NOT started — run `ops.ta setup` then health after secrets are
in place.

## 10. Post-start verification

- monitor ticks appearing every minute
- bridge `/healthz` returns both model mappings
- `/status` in Telegram shows ALPHA/C12/bridge/telegram OK
- no `executed[]`/ledger drift vs the source machine
