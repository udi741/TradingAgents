# TROUBLESHOOTING RUNBOOK

Symptom → likely cause → first read-only check → authority → safe fix.

## Telegram message did not arrive
Usually: relay down/restarting (check after reboot) or simply no event.
Check: `systemctl --user status tradingagents-telegram`;
`tail alpha_rnd/monitor_cron.log`.
Fix: `systemctl --user restart tradingagents-telegram.service`.
Do NOT poke trading state because Telegram was quiet.

## ALPHA status looks stale
Check last `checked` line in `monitor_cron.log`. If >4 min old, read the
newest traceback in that log — do not restart blindly; a crash-looping
tick needs its error fixed first.

## Bridge unavailable / model rate-limited
`curl -s http://127.0.0.1:8765/healthz`. If down:
`systemctl --user restart tradingagents-swe-bridge.service`. Schedulers
already do this; repeated BLOCKED events mean credentials/provider issue,
not code.

## Market data failures ("possibly delisted" spam)
Transient yfinance failures; monitor retries every minute. Persistent
daily-close failure for a held ticker = real risk to marks/exits —
escalate, do not hand-edit marks.

## Computer rebooted
Everything auto-starts (linger + default.target + cron). The
`tradingagents-bootcheck.timer` writes
`~/.config/tradingagents/boot_health.json` ~2min after boot and re-checks
every 10min; `ops.ta health` shows `boot recovery`. A first relay
DNS-crash self-heals in ~15s and shows DEGRADED until the next
bootcheck — expected, not an incident. If boot recovery stays FAILED,
the component list in boot_health.json names exactly what did not come
back.

## Position mark stale / UNMARKED_SINCE_ENTRY
Normal for positions entered today (first mark at tonight's EOD). If a
mark is older than the last completed session, check
`monitor_state.json` `book.mark_session` and `processed_close_sessions`
before assuming a bug.

## Pending order seems stuck
`pending_open_fills`/`pending_open_exits` settle at the NEXT regular
open. If still pending after a session's open processed, check
`executed[]` for the order id and the monitor log around the open.

## "Trade happened" but portfolio disagrees
Notification is not authority. Check `executed[]` + ledger + positions.
Known incident pattern: test/shadow wording leaking into
NOTIFICATIONS.log (fixed 2026-10-16, commit 5f8bf828).

## Scheduler did not run
`tail alpha_rnd/scheduler.log`. Hourly `--check` ticks self-skip when up
to date ("up to date session=..."). BLOCKED_* events are durable and
retried — check `scheduler_events.jsonl` for the reason.

## Monitor lock stale
`monitor_state.lock` older than a few minutes with no active process:
verify no python monitor is running (`pgrep -f alpha_rnd.monitor`), then
the next cron tick re-acquires/clears per monitor's lock handling.
Do not delete while a monitor is alive.
