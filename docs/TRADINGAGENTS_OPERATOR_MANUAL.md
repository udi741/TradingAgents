# TRADINGAGENTS OPERATOR MANUAL

Plain-language guide to running the paper-trading system day to day.
Everything here is read-only unless marked otherwise.

## What runs normally

| Component | How it runs | Cadence |
|---|---|---|
| ALPHA monitor | cron, `python -m alpha_rnd.monitor --once` | every minute |
| ALPHA scheduler | cron, `python -m alpha_rnd.daily_scheduler --check` | hourly at :07 |
| ALPHA cohort outcomes | cron, `python -m alpha_rnd.cohort_outcomes update` | hourly at :23 |
| C12 scheduler | cron, `python -m ta_eval.c12_scheduler --check` | hourly at :00 |
| SWE model bridge | systemd `tradingagents-swe-bridge.service` | always |
| Telegram relay | systemd `tradingagents-telegram.service` | always |

Interactive Devin sessions are development agents — they are NOT part of
runtime and never auto-start.

## Is the system running?

```bash
systemctl --user status tradingagents-swe-bridge tradingagents-telegram
tail -3 /home/udi/udi_provate/TradingAgents-alpha-rnd/alpha_rnd/monitor_cron.log
tail -3 /home/udi/udi_provate/TradingAgents-alpha-rnd/alpha_rnd/scheduler.log
tail -3 /home/udi/udi_provate/TradingAgents-c12/evaluations/gate_c12_prospective/scheduler.log
crontab -l
```

Monitor healthy = last `checked ... data=ok` within ~4 minutes.

## Portfolio status (Telegram)

Send `/alpha`, `/c12`, or `/status` to the bot. Telegram is a VIEW, never
the authority — the files in `docs/STATE_AND_DATA_AUTHORITY.md` are.

## How do I know a trade really happened?

Only if BOTH hold:
1. `monitor_state.json` `executed[]` contains the order id, and
2. `positions`/`cash`/`realized` changed and the ledger
   `alpha_paper_ledger.jsonl` has the matching record.

A Telegram message, desktop popup, or NOTIFICATIONS.log line alone is NOT
proof. Shadow management output is labeled SHADOW and never executes.

## Restart safely

```bash
systemctl --user restart tradingagents-telegram.service     # relay only
systemctl --user restart tradingagents-swe-bridge.service   # model bridge
```

Do NOT "restart" the cron monitor/scheduler — they are one-shot jobs;
fix the cause and the next tick recovers.

## Telegram silent?

Relay down does not mean trading stopped. Check the monitor log first.
After a machine reboot the relay may crash once on DNS before the network
is up; systemd restarts it ~15s later (observed 2026-10-16).

## Model bridge down?

```bash
curl -s http://127.0.0.1:8765/healthz
systemctl --user restart tradingagents-swe-bridge.service
```

Schedulers retry automatically; LLM-dependent cycles emit BLOCKED events
and never fabricate results. Deterministic trading is unaffected.

## Market data failed?

yfinance misses are retried next tick and logged `data=degraded_intraday`
or `possibly delisted` spam — usually transient. Only act if failures
persist for hours AND marks/exits would be affected.

## After a reboot

Lingering + `default.target` start the bridge and relay automatically;
cron jobs resume on their own. Verify with the status commands above.
Nothing needs a manual start.

## Never edit manually while the system runs

`monitor_state.json`, `live_watchlist.json`, `scheduler_state.json`, any
ledger, any management artifact. These are economic authority; edits
become truth.

## Shadow vs real

Shadow management reassessment can say "PARTIAL_EXIT recommendation —
NOT EXECUTED". Real fills say "PAPER EXIT EXECUTED" AND move economics.
If wording ever conflates the two, it is a bug (see 2026-10-16 incident
in git history).

## Shut down safely

```bash
systemctl --user stop tradingagents-telegram.service tradingagents-swe-bridge.service
crontab -r   # DANGEROUS: removes ALL automation; prefer commenting out
```

Prefer `crontab -e` and comment the lines. Stopping services mid-pending-
order is safe — state is durable; the next tick continues.

## Call a developer when

- `executed[]` and the ledger disagree with positions (integrity bug)
- a stop/close rule exists in docs but not in `monitor_state.json`
- marks are stale >1 completed session during market days
- any shadow artifact claims to be executed

