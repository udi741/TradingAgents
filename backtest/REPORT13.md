# AI-decision paper portfolio — operational integration

Branch `exp/decision-contract`. New module `alpha_rnd/decision_portfolio.py`
+ driver `backtest/decision_portfolio_runner.py`.

## Architecture

publication_intents (`decision` field authored by updated schema)
  -> `decision.from_intent` validation (geometry/R-R/provenance)
  -> risk engine size (1% budget / stop distance, $5k slot cap)
  -> `decision_portfolio` book: pending -> fill -> stop/target mgmt ->
     exit -> NAV, append-only `events.jsonl` + `book.json`
  -> data dir `~/udi_provate/TradingAgents-decision-portfolio`
     (SEPARATE from the 3-book shadow experiment — untouched)

## Verified trace (real authored decisions + real bars)

- ACN authored LONG (zone[203,205], stop193.5, tgt250): ingested as
  pending 10-23; bar low stayed above 205 → correctly NOT filled.
- ANF authored LONG (zone[153,158], stop144.5, tgt185, sz .117 →
  $585 notional): filled 3@158 on 10-23, marked 155.82 → NAV 99,992.99.
  Reconciles with earlier standalone sim (-7.48, 3 shares, same px).

## Isolation proof

- `test_writes_only_own_dir`: engine source contains no reference to
  live_watchlist, paper ledger, monitor_state, positions.json, publish().
- Reads: publication_intents, market bars. Writes: only its data dir.
- 5 lifecycle tests pass: fill→stop→exit, NO_TRADE rejection, SHORT
  paper-only (borrow cost, 2*fill-close mark), idempotent ingest,
  pending-exit ordering bug fixed (same-day re-arm), cash remainder fix.

## Operation after approval

Proposed cron (NOT installed): after nightly research
`40 23 * * 1-5 flock -n <dir>/lock python3 backtest/decision_portfolio_runner.py --session $(date +\%F)`
Each run: ingests new authored decisions, advances one completed session,
marks NAV. Idempotent per session.

## Deployment & rollback

- Deploy: merge exp/decision-contract to main after review; pull on
  production host; add the single cron line; create data dir.
- Rollback: `crontab -l | grep -v decision_portfolio_runner | crontab -`
  + `git checkout <prev>` — portfolio state is self-contained.
- Dirty checkout: deploy via `git stash`/`git pull --rebase`-style flow or
  a parallel checkout; shadow cron line untouched.

## Remaining obstacle

Real authored decisions only exist where the new schema ran (6 eval
tickers). Next production research session publishes decisions
automatically — but production must run the updated synthesize.py. Until
then the portfolio has nothing new to ingest (fail-closed by design).
