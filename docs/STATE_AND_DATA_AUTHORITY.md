# STATE AND DATA AUTHORITY

The single source-of-truth map for TradingAgents state. If a display,
log, or notification disagrees with a file listed as AUTHORITY here,
the file wins. Do not "fix" the authority to match the display.

Legend: ECONOMIC AUTHORITY (money/shares truth) | OPERATIONAL STATE |
DERIVED STATE | RESEARCH/SHADOW ARTIFACT | NOTIFICATION ONLY

## ALPHA — worktree /home/udi/udi_provate/TradingAgents-alpha-rnd

| Path | Class | Authority? | Safe to edit | Backup |
|---|---|---|---|---|
| `alpha_rnd/monitor_state.json` | ECONOMIC AUTHORITY | YES — positions, cash, realized, pending orders, executed IDs | NO (monitor owns it, file-locked) | MUST |
| `evaluations/alpha_rnd_v1/alpha_paper_ledger.jsonl` | ECONOMIC AUTHORITY (append-only ledger) | YES — historical record of fills/marks | NO | MUST |
| `alpha_rnd/live_watchlist.json` | OPERATIONAL STATE | YES — active watches + open-position rules | NO | MUST |
| `alpha_rnd/monitor_state.lock` | OPERATIONAL | lock file, not state | NO | no |
| `alpha_rnd/scheduler_state.json` | OPERATIONAL STATE | YES — completed/invalid sessions, published digests | NO | MUST |
| `alpha_rnd/scheduler_state.lock` | OPERATIONAL | lock file | NO | no |
| `evaluations/alpha_rnd_v1/management_state.json` | OPERATIONAL/SHADOW | latest prices + mgmt shadow bookkeeping | NO | MUST |
| `evaluations/alpha_rnd_v1/management_actions.json` | OPERATIONAL REGISTRY | adaptive-execution lifecycle (VALIDATED→ENQUEUED→FILLED→EXECUTED); EMPTY while execution disabled | NO | MUST |
| `evaluations/alpha_rnd_v1/management_intents/<TICKER>/*.json` | SHADOW ARTIFACT | validated shadow intents — NOT economic | NO | MUST |
| `alpha_rnd/management_events.jsonl` | SHADOW/OPERATIONAL log | reassessment triggers/results; never proof of a trade | NO | yes |
| `alpha_rnd/trigger_events.jsonl` | ECONOMIC EVENT LOG | durable entry/exit/stop events; relay cursor feeds on it | NO | MUST |
| `alpha_rnd/scheduler_events.jsonl` | OPERATIONAL EVENT LOG | discovery/publication events | NO | yes |
| `alpha_rnd/NOTIFICATIONS.log` | NOTIFICATION ONLY | human-facing text; NOT proof of a trade (tests once leaked into it) | safe to read, do not trust as economics | no |
| `alpha_rnd/monitor_cron.log` | NOTIFICATION/log | tick + error log | — | no |
| `alpha_rnd/cohort_outcomes_state.json`, `evaluations/alpha_rnd_v1/cohorts*/` | RESEARCH | R2 outcome tracking | NO | yes |
| `evaluations/alpha_rnd_v1/replays/`, `low_price_shadow/` | RESEARCH/SHADOW | replay & shadow lanes — never economic | NO | no |

**How to prove a real paper trade:** `monitor_state.json` → `executed[]`
contains the order id AND `positions`/`cash`/`realized` moved, with the
matching append in `alpha_paper_ledger.jsonl`. A line in NOTIFICATIONS.log
or a Telegram message alone proves nothing.

## C12 — worktree /home/udi/udi_provate/TradingAgents-c12

| Path | Class | Authority? | Safe to edit | Backup |
|---|---|---|---|---|
| `evaluations/gate_c12_prospective/c12_paper_portfolio.jsonl` | ECONOMIC AUTHORITY | YES — open/closed paper trades | NO | MUST |
| `evaluations/gate_c12_prospective/c12_nav.jsonl` | ECONOMIC AUTHORITY | YES — canonical NAV series | NO | MUST |
| `evaluations/gate_c12_prospective/c12_signal_ledger.jsonl` | ECONOMIC AUTHORITY | YES — scoreable signals, maturity | NO | MUST |
| `evaluations/gate_c12_prospective/scheduler_state.json` | OPERATIONAL | session dispositions, done markers | NO | MUST |
| `evaluations/gate_c12_prospective/c12_notifications.jsonl` | NOTIFICATION ONLY | what the relay sends; not economics | — | no |
| `evaluations/gate_c12_prospective/weeks/<s>/state.json` | OPERATIONAL | per-week cycle state/resume | NO | MUST |

## Tracks repo — /home/udi/udi_provate/TradingAgents-tracks

`state/*.yaml`, `docs/*`, `TRACKS.md`, `CURRENT_STATE.md` — CONTROL
documents, not economic authority. `ops/telegram_relay.py` reads the
files above read-only; `~/.config/tradingagents/telegram_state.json` is
the relay's own dedup/cursor state (regenerable).

## Base repo — /home/udi/udi_provate/TradingAgents

`infra/devin-bridge` worktree; owns only the bridge package
(`devin_bridge/`). No economic state lives here.

## Rules

- Never hand-edit a file marked NO while its owner runs; corrupt edits
  become economic truth.
- SHADOW artifacts may never be presented as executed trades.
- Chat history, Telegram text, and cron logs are never authority.
