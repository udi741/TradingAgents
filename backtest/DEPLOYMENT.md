# Decision-portfolio deployment (paper-only)

## Deploy (after approval)
1. Review + merge `exp/decision-contract` to main on GitHub.
2. On the production host — DO NOT stash/reset/clean the dirty checkout:
   ```
   cd ~/udi_provate/TradingAgents
   git fetch origin
   git merge --ff-only origin/main          # ff-only; dirty files preserved
   ```
   (dirty checkout keeps operational state; merge is additive — the only
   production-path change is the new `decision` field + `decision.py`.)
3. `mkdir -p ~/udi_provate/TradingAgents-decision-portfolio`
4. Add ONE cron line (proposal — not installed):
   `40 23 * * 1-5 /usr/bin/flock -n ~/udi_provate/TradingAgents-decision-portfolio/lock /usr/bin/python3 ~/udi_provate/TradingAgents-backtest/backtest/decision_portfolio_runner.py --catchup >> ~/udi_provate/TradingAgents-decision-portfolio/runner.log 2>&1`

## Rollback
`crontab -l | grep -v decision_portfolio_runner | crontab -` then
`git revert` the merge. Portfolio state is self-contained in its data dir;
production watchlist/ledger/PBF/C12 untouched.

## How research produces decisions (no extra inference)
The existing nightly scheduler already calls `synthesize.run(session)` →
one batch translator call. The updated SCHEMA_HINT adds a mandatory
`decision` field per ticker; `run()` attaches the validated unified
decision to each persisted intent. Same call, same quota (DEEP_QUOTA=10),
zero additional inference beyond normal operation.

## How the portfolio operates daily
`--catchup` (idempotent, flock-guarded):
1. Every business day after `book.last_mark` through the latest COMPLETED
   bar: ingest that day's `publication_intents` (decisions fill-eligible
   only from the NEXT session — no publication-day fills),
2. advance all books one day: pending-exit opens, stop checks, pending
   fills, NAV mark; `last_mark` makes reruns no-ops.
3. Late publications are picked up automatically (chronological pubs);
   missing/incomplete bar days are a retryable skip.

## Capital & risk formula
$100,000 start. Per position: notional = min($5,000 × size_frac, $5,000)
where size_frac = AI size or risk-engine `permissible_size_frac` =
min(1, 0.01 / |entry−stop|/entry). Max 10 positions, whole shares,
10bps/side, ~2%/yr short borrow on SHORT legs (paper only).

## Inspect
```
cat ~/udi_provate/TradingAgents-decision-portfolio/book.json       # NAV/positions/P&L
cat ~/udi_provate/TradingAgents-decision-portfolio/events.jsonl    # per-session ledger
tail ~/udi_provate/TradingAgents-decision-portfolio/runner.log
```

## Protections confirmed
- Backward-compatible: `decision` is an additive field; old intents
  without it still work (validators treat absence as legacy).
- `_machine_executable`, entry_gate, monitor — untouched; SHORT can never
  reach the LONG path (paper objects only).
- 22 tests pass incl. publication-day fill ban, pending-exit ordering,
  SHORT paper-only, writes-only-own-dir.
- Shadow experiment, crontab (5 ALPHA/C12 jobs), PBF positions — untouched.
