# RUNBOOK: ALPHA_RND

Worktree: `/home/udi/udi_provate/TradingAgents-alpha-rnd`
(branch `exp/alpha-rnd-v1`). Devin session: `feather-room`.

## Opportunity discovery cycle

A discovery cycle (V1/V2 pattern): build the eligible universe with frozen
hygiene filters, run the frozen discovery lanes, freeze a balanced
candidate pool, pick the deep-analysis top-10 by the frozen score rule, run
full official v0.5.0 TA on each, and classify each result
(ACTIONABLE_NOW / WATCH_FOR_ENTRY / REJECT). Freeze all watch triggers with
expiry before any future price is observed. Run another cycle only when
justified: free book slots, watchlist decay/expiry, or explicit user request —
not on a fixed cadence.

## Paper book

`evaluations/alpha_rnd_v1/alpha_paper_ledger.jsonl` (append-only). $100k start, ~$5k/position, max 10
positions. Fills only from frozen prospective triggers. Marks recorded each
completed session at the close.

## Watchlist & trigger classes

`alpha_rnd/live_watchlist.json`. Classes:

- **AUTO_ENTRY** (PGEN @ limit 8.20): monitor paper-fills automatically when
  the frozen limit is touched intraday.
- **DETERMINISTIC_CONFIRMATION** (IOVA, CDNA, SDGR, ASST, TXG, TWST, PAYC,
  XNCR, AXGN): mechanical close/volume rules; on confirmation, fill at the
  next regular-session open.
- **REANALYZE_ON_TRIGGER** (SYNA, KOD, HHH): notify + mark
  REANALYSIS_REQUIRED; NEVER auto-buys.

## Automatic monitor

`alpha_rnd/monitor.py` — pure market-data, no LLM. Runs via per-minute cron
while the machine is on:

- Once: `cd /home/udi/udi_provate/TradingAgents-alpha-rnd && PYTHONPATH=. python3 -m alpha_rnd.monitor --once`
- Status: `... python3 -m alpha_rnd.monitor --status`
- Loop (manual alternative): `... python3 -m alpha_rnd.monitor --loop`
- Stop: remove the cron line (`crontab -e`) or kill the `--loop` process.

Events are appended to `alpha_rnd/trigger_events.jsonl`; desktop popups via
`notify-send`.

## Open-position exits (frozen)

- PBF: intraday low <= 74.50 -> exit @74.50 (or actual open if gapped
  through); completed close < 78 -> pending exit at NEXT open.
- ACN: completed close < 194 -> pending exit at NEXT open.
- APPS: intraday low <= 10.42 -> exit @10.42 (or actual open if gapped).
- No invented stops; no discretionary profit-taking in V1.

## Close-confirmation timing

A condition that is only knowable at the close can never fill at that close;
it becomes PENDING_NEXT_OPEN and fills at the actual next regular-session
open including gaps.

## Machine-off limitation

The monitor only runs while the computer is on/awake. If a required
next-open execution passed while off, the monitor records
MISSED_EXECUTION_REVIEW_REQUIRED — review it manually; never book an
invented fill.

## When a popup says REANALYSIS_REQUIRED

1. Read the event in `alpha_rnd/trigger_events.jsonl` (ticker, trigger,
   frozen artifact reference).
2. Start a Devin ALPHA session and invoke the prepared
   `ALPHA_RND_SINGLE_TICKER_REFRESH` procedure: inputs = ticker + frozen
   artifact + trigger event; output = BUY_NOW / KEEP_WATCHING / REJECT with
   horizon + execution instruction.
3. Any resulting order must be frozen before acting on it.

## Holding horizons

Each position's intended horizon comes from its frozen artifact (PBF ~2-3
weeks reevaluate ~Oct-16; ACN 6-12 months reevaluate next earnings; APPS to
~Nov earnings). 5/20/60(/120/250)-session marks and vs-SPY are research
measurement points, never automatic exits.
