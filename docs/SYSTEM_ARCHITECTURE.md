# SYSTEM ARCHITECTURE — newcomer map

> Capability map: `docs/TRADINGAGENTS_CAPABILITY_REFERENCE.md` (registry: `docs/TRADINGAGENTS_CAPABILITY_REGISTRY.yaml`).


## Pipeline

```
raw ticker universe
→ eligibility filters            [deterministic, ALPHA]
→ multi-lane scoring + ranks     [deterministic]
→ candidate pool (frozen ~28)    [deterministic]
→ deep-quota selection (10)      [deterministic]
→ TradingAgents LLM analysis     [MODEL via devin_bridge]
→ publication dispositions       [deterministic, fail-closed]
→ live watchlist (triggers/rules)[deterministic]
→ per-minute monitor             [deterministic]
→ pending → next-open execution  [deterministic]
→ paper economics + ledger       [ECONOMIC AUTHORITY]
→ shadow post-entry management   [research only, execution DISABLED]
→ events → Telegram relay        [NOTIFICATION, not authority]
→ cohort/outcome evaluation      [R&D evidence]
```

C12 is a separate frozen pipeline: weekly TradingAgents run → scoreable
signals → simulated regular-open fills → 20/60-session relative-return
maturity. It is the control; do not modify.

## Runtime processes

| Process | Started by | Module | State |
|---|---|---|---|
| ALPHA monitor | cron * * * * * | `alpha_rnd.monitor --once` | monitor_state.json |
| ALPHA scheduler | cron 7 * * * * | `alpha_rnd.daily_scheduler --check` | scheduler_state.json |
| ALPHA outcomes | cron 23 * * * * | `alpha_rnd.cohort_outcomes update` | cohort_outcomes_state.json |
| C12 scheduler | cron 0 * * * * | `ta_eval.c12_scheduler --check` | c12 scheduler_state.json |
| SWE bridge | systemd | `python -m devin_bridge` on :8765 | none (stateless proxy) |
| Telegram relay | systemd | `ops.telegram_relay --serve` | telegram_state.json (cursors) |

## Inference (NO LOCAL MODELS — hard invariant)

`devin_bridge` binds 127.0.0.1:8765, maps `devin-quick → swe-2-medium`,
`devin-deep → swe-2-high`, and delegates to the Devin CLI binary. Single
owner: `tradingagents-swe-bridge.service` (Restart=always/15s, after
network-online). Schedulers only consume; on failure they ask systemd
for a restart (with `XDG_RUNTIME_DIR=/run/user/$UID` derived — cron has
no session bus), poll `/healthz`, and emit durable BLOCKED events rather
than fabricate output. TA runs under `.venv312` (python 3.12).

## systemd units (canonical, as deployed)

tradingagents-swe-bridge.service:
```
WorkingDirectory=<base>/TradingAgents ; PYTHONPATH=. 
ExecStart=/usr/bin/python3 -u -m devin_bridge --quick-model swe-2-medium \
  --deep-model swe-2-high --timeout 1200
Restart=always RestartSec=15 ; After/Wants=network-online.target ; WantedBy=default.target
```
tradingagents-telegram.service: same pattern, `ops.telegram_relay --serve`
from the tracks repo.

## Failure semantics

- Scheduler tick: bounded retry, durable BLOCKED event, next tick resumes.
- Monitor tick: one-shot per minute; a crash loses only that tick.
- Bridge down: LLM phases BLOCK, deterministic phases unaffected.
- Relay down: events queue in jsonl; cursors resume delivery on restart.
- Shadow management: writes intents/reassessments only; `mgmt_exec` is a
  no-op while `management_policy.json -> execution.enabled == false`.

## Worktrees

| Path | Branch | Role |
|---|---|---|
| `TradingAgents/` | infra/devin-bridge | base + bridge host |
| `TradingAgents-alpha-rnd/` | exp/alpha-rnd-v1 | ALPHA production paper |
| `TradingAgents-c12/` | exp/gate-c12-prospective | C12 control |
| `TradingAgents-expert-rnd/` | exp/expert-rnd-v2 | Expert R&D (parked) |
| `TradingAgents-tracks/` | project/tracks | docs/control (this repo) |
