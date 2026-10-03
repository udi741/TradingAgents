# TELEGRAM NOTIFICATIONS — shared alert relay

Purpose: important ALPHA and C12 events reach the user's phone via Telegram.
Telegram is a **delivery channel only**. Trading monitoring, paper
execution, and C12 automation are fully independent of it — if Telegram or
this relay fails, everything keeps working and unsent events are retried.
Local durable logs remain authoritative.

## Architecture

```
ALPHA monitor ──appends──> alpha_rnd/trigger_events.jsonl ─┐
                                                          ├─> ops.telegram_relay
C12 scheduler ──appends──> c12_notifications.jsonl ───────┘   (tails sources,
        |                                                    normalizes,
        |                                                    dedups, sends)
        └─> ~/.config/tradingagents/telegram_state.json  (cursors, delivered
            ids, pending retry queue — survives restarts)
Secrets: ~/.config/tradingagents/telegram.env (chmod 600, NEVER in git)
```

- Implementation: `ops/telegram_relay.py` in this worktree; library =
  `python-telegram-bot` (pip user-site).
- It **reads** the two authoritative jsonl logs via byte-offset cursors and
  never writes to track files.
- At-least-once: events queue in `pending` until Telegram accepts them;
  `delivered` ids deduplicate.

## Event priorities

| Source event | Severity | Sent? |
|---|---|---|
| ALPHA PAPER_ENTRY / PAPER_EXIT | SUCCESS | yes |
| ALPHA CONFIRMED_PENDING_NEXT_OPEN_(ENTRY\|EXIT) | INFO | yes |
| ALPHA REANALYSIS_REQUIRED | ACTION_REQUIRED | yes (+resume instructions) |
| ALPHA MISSED_EXECUTION_REVIEW_REQUIRED | ACTION_REQUIRED | yes |
| ALPHA monitor_error | ERROR | yes |
| ALPHA NO_ACTION / CONFIRMED / WATCH_EXPIRED | — | no (noise) |
| C12_CYCLE_STARTED | INFO | yes |
| C12_CYCLE_SCOREABLE_COMPLETE | SUCCESS | yes |
| C12_CYCLE_NON_SCOREABLE | WARNING | yes |
| C12_AUTOMATION_BLOCKED_BRIDGE | ACTION_REQUIRED | yes |
| C12_EXECUTION_SETTLED | SUCCESS | yes |
| C12_EXECUTION_MISSED | ACTION_REQUIRED | yes |
| C12_AUTOMATION_ERROR | ERROR | yes |

ACTION_REQUIRED/ERROR messages always include: what happened, what to do,
which session to resume (`cd <worktree> && devin -r <session>`), and the
source log path.

## Running modes

**Installed — systemd user service** `tradingagents-telegram.service`
(delivers events every 60s AND answers read-only bot commands; starts
automatically at boot — user lingering is enabled, so no login or terminal
is required; `Restart=always` recovers crashes):

```bash
systemctl --user status tradingagents-telegram.service
systemctl --user restart tradingagents-telegram.service
systemctl --user stop tradingagents-telegram.service    # disable alerts
systemctl --user disable tradingagents-telegram.service # survive reboot too
```

Unit: `~/.config/systemd/user/tradingagents-telegram.service`
(interpreter `/usr/bin/python3`, `WorkingDirectory=TradingAgents-tracks`,
no secrets inside). Manual equivalent:
`PYTHONPATH=. python3 -m ops.telegram_relay --serve`

**Alternative — cron `--once`** (delivery only, no /commands):

```
* * * * * cd /home/udi/udi_provate/TradingAgents-tracks && PYTHONPATH=. python3 -m ops.telegram_relay --once >> /tmp/telegram_relay.log 2>&1
```

**Disable:** kill the `--serve` process / remove the cron line. Nothing
else is affected. Re-enable later and queued events resume delivery.

**Machine-off limitation:** like the monitor, nothing runs while the
computer is off/asleep. On return, unsent durable events are picked up by
the next delivery pass — stale alerts may arrive late; timestamps are in
each message.

## Configuration (local, interactive — user does this)

```bash
cd /home/udi/udi_provate/TradingAgents-tracks
PYTHONPATH=. python3 -m ops.telegram_relay --configure
```

1. In Telegram, message **@BotFather** → `/newbot` → copy the token.
2. Run `--configure`, paste the token into the hidden prompt.
3. Send any message to your new bot, press Enter — the script lists chats.
4. Pick your chat ID. A test message is sent. Done.

The token is stored in `~/.config/tradingagents/telegram.env` (chmod 600),
never echoed in full, never committed, never needed in any prompt.

Other commands: `--test` (send test), `--status` (config/cursors/queues),
`--heartbeat on|off`.

## Security model

- Only the configured `TELEGRAM_CHAT_ID` is answered; every other
  user/chat is silently ignored.
- Commands are read-only: `/status`, `/alpha`, `/c12`, `/help`. No
  buy/sell, no TA runs, no watchlist/stop changes, no shell.
- No secrets in messages, logs, or documentation.

## Heartbeat

Optional ~daily "systems alive" message (`--heartbeat on`): reports ALPHA
monitor freshness (cron log <3min), C12 scheduler freshness (<2h), relay
OK. Silence then means "nothing happened", not "everything died". Off by
default.

## Troubleshooting

- `--status` shows config presence, cursor offsets, delivered/pending counts.
- Failed sends stay in `pending` and retry every pass — check
  `~/.config/tradingagents/telegram_state.json` and `/tmp/telegram_relay.log`.
- If a source file doesn't exist yet (e.g. ALPHA has had no trigger
  events), the relay simply waits — `absent` in `--status` is normal.
- Wrong chat authorized? Re-run `--configure` and pick the right ID.

## Fallback

If Telegram is down or unwanted: local sources remain authoritative —
`alpha_rnd/NOTIFICATIONS.log`, `alpha_rnd/trigger_events.jsonl`,
`c12_notifications.jsonl`, plus `notify-send` desktop popups.
