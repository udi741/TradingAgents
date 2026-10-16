# NEW MACHINE SETUP — current truthful procedure

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

## 3. Clone + worktree layout

Production assumes five checkouts under ONE parent dir
(PORTABILITY_GAP: paths are hard-coded — keep the layout or rewrite
every cron/unit path):

```bash
git clone <repo> TradingAgents                      # base, bridge host
cd TradingAgents
git worktree add ../TradingAgents-alpha-rnd exp/alpha-rnd-v1
git worktree add ../TradingAgents-c12 exp/gate-c12-prospective
git worktree add ../TradingAgents-expert-rnd exp/expert-rnd-v2
git worktree add ../TradingAgents-tracks project/tracks
```

Base worktree stays on `infra/devin-bridge` (bridge code lives there).

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

## 6. Services (PORTABILITY_GAP — copy by hand)

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

Copy the MUST-BACK-UP files from docs/STATE_AND_DATA_AUTHORITY.md into
the same relative paths in the matching worktrees BEFORE enabling cron,
then verify `/alpha` output matches the old machine.

## 10. Post-start verification

- monitor ticks appearing every minute
- bridge `/healthz` returns both model mappings
- `/status` in Telegram shows ALPHA/C12/bridge/telegram OK
- no `executed[]`/ledger drift vs the source machine
