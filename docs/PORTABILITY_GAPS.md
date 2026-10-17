# PORTABILITY GAPS — register

> Capability map: `docs/TRADINGAGENTS_CAPABILITY_REFERENCE.md` (registry: `docs/TRADINGAGENTS_CAPABILITY_REGISTRY.yaml`).


What prevents "fresh machine → safe running system" today. Phase 0
records them; Phase 1+ fixes them.

| ID | Gap | Severity | Workaround today | Desired | Phase |
|---|---|---|---|---|---|
| ~~G1~~ CLOSED | No bootstrap installer — everything is manual | HIGH | follow NEW_MACHINE_SETUP.md step by step | `ops/setup` single installer | 1 |
| ~~G2~~ CLOSED | Systemd units exist in ~/.config, not installed from repo | HIGH | copy units by hand | `ops/setup` writes/enables them | 1 |
| ~~G3~~ CLOSED | Cron entries are tribal (4 lines, no installer) | HIGH | paste from NEW_MACHINE_SETUP.md | `ops/setup` installs crontab | 1 |
| ~~G4~~ CLOSED | No unified health command | MED | run ~6 commands manually | `ops/health` one-shot report | 1 |
| ~~G5~~ CLOSED | No backup command/manifest tool | HIGH | `rsync` listed paths by hand | `python3 -m ops.ta backup` + manifest | 2 |
| ~~G6~~ CLOSED | No restore procedure/tool | HIGH | manual file copy + verify | `ops.ta restore` fail-closed + integrity checks | 2 |
| ~~G7~~ CLOSED | `.venv312` (py3.12 TA env) has no creation script | HIGH | `python3.12 -m venv` + `pip install -e .` by hand | pinned env builder | 1 |
| G8 | System python deps (yfinance/pandas for monitor) not pinned per-runtime | MED | `pip install` pyproject deps for py3.10 | runtime requirements file | 1 |
| G9 | Hard-coded absolute paths `/home/udi/udi_provate/...` in cron+units | MED | rewrite paths on new machine | path-templated units/cron | 2 |
| ~~G10~~ CLOSED | Secrets have no checked-in template | MED | create `~/.config/tradingagents/telegram.env` from memory | `config/telegram.env.example` committed | 1 |
| G11 | Bridge auth depends on Devin CLI login (~/.local/bin/devin + user creds) — undocumented install | MED | install devin CLI, log in | documented minimal install path or alt auth | 2 |
| G12 | Telegram relay had no network-ready guard — RESOLVED: units carry After=+Wants=network-online.target and Restart=always; relay never gates trading | CLOSED | — | P3 |
| G13 | No `ops/start|stop|status` wrapper — operators must know module names | MED | this manual | ops wrapper CLI | 2 |
| G14 | Worktree layout implicit — RESOLVED: ops/workspace.json canonical spec + `ops.ta workspace setup/status` | CLOSED | — | P3 |
| G15 | No boot self-test — RESOLVED: `ops.ta bootcheck` + tradingagents-bootcheck.timer writing boot_health.json; health shows `boot recovery` | CLOSED | — | P3 |
