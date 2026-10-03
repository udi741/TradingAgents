# BASE REPOSITORY ROLE — final architecture (normalized 2026-10-03)

Status: **NORMALIZED** (PROJECT_CONTROL_V3A). This document supersedes the
V3 audit's provisional "neutral checkout" recommendation.

## The three distinct concepts

| Concept | Identity | Meaning |
|---|---|---|
| `origin/main` | `8b22d43d` (fetched 2026-10-03) | canonical upstream source for NEW independent work — always fetch first |
| local `main` | `8b22d43d` == `origin/main` | plain mirror of fetched upstream; NO private overlay |
| base worktree `TradingAgents/` | branch `infra/devin-bridge` @ `ceabecf9` | **BASE_INFRASTRUCTURE_HOST** — Git root + Devin bridge host + worktree management point |

## Base worktree = BASE_INFRASTRUCTURE_HOST

It IS: common Git repository/root, the host of the running model bridge
(`python3 -m devin_bridge`, cwd=base, `PYTHONPATH=.`), and the safe place
for `git worktree` management.

It is NOT: an experiment, C12, ALPHA, EXPERT, PROJECT_CONTROL, or the
source branch for independent research. A dirty base is an integrity
problem — report it.

## Why `infra/devin-bridge` and not `main`/`origin/main`

`devin_bridge/` (the private bridge package) exists only on the bridge
commit `ceabecf9` — upstream `origin/main` does not contain it. Checking
the base out on `infra/devin-bridge` keeps the bridge launch path working
while letting `main` honestly mean "upstream."

The bridge commit is preserved on `infra/devin-bridge` (also on
`backup/devin-cli-bridge-working`). Never delete it. Never merge it into
`main` or push it to `origin`.

## Historical note

Base previously sat on `exp/gate-c6-selection-execution-split` @ `d629034c`
(leftover C6 experiment checkout). That branch is preserved; nothing was
lost in the switch (two stale `.lock` files removed).

## New-work creation rule

```bash
cd /home/udi/udi_provate/TradingAgents
git fetch origin
git worktree add ../TradingAgents-<name> -b exp/<name> origin/main
```

Never branch new research from `infra/devin-bridge` just because it's the
current base checkout.

## Operator convention — resume sessions from their track worktree

```bash
cd ~/udi_provate/TradingAgents-tracks      && devin -r nonchalant-citipati   # PROJECT_CONTROL
cd ~/udi_provate/TradingAgents-alpha-rnd   && devin -r feather-room          # ALPHA_RND
cd ~/udi_provate/TradingAgents-expert-rnd  && devin -r groovy-allspice       # EXPERT_RND
cd ~/udi_provate/TradingAgents-c12         && devin -r kindly-nightshade     # C12
```

The cwd communicates track ownership. Do not resume track sessions from
the base directory.

## Bridge operations

Effective config (unchanged): `--quick-model swe-2-medium
--deep-model swe-2-high --timeout 1200`, port 8765, cwd=base,
`PYTHONPATH=.` → `devin-quick -> swe-2-medium`, `devin-deep -> swe-2-high`.

Restart (e.g. after reboot):

```bash
cd /home/udi/udi_provate/TradingAgents
PYTHONPATH=. nohup python3 -m devin_bridge \
  --quick-model swe-2-medium --deep-model swe-2-high --timeout 1200 \
  >> /tmp/devin_bridge_c12.log 2>&1 &
```
