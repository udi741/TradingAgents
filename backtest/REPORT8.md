# Prospective AI-ranking shadow — timing fix, runner, activation boundary

## Task 1 — Corrected information timing

Two real timing defects were found and fixed:

1. **Ratings:** previously eligible same day (`pub_date <= fill_date`).
   Only dates are published → now eligible strictly from the next session
   (`d < date`).
2. **Same-day fills:** the mechanical signal arms on the signal-day
   *close*; the prior code allowed a zone touch on that same bar — a fill
   before the signal could exist. `sim_period` now enforces
   `i > arm_day` (fills only on later bars).

**Corrected October smoke test** (identical rules, Oct 1–23):

| Priority | Admitted | NAV% | P&L | PF |
|---|---|---|---|---|
| Alphabetical | 20 | **-4.16%** | -4,167 | 0.41 |
| AI rating | 19 | **-4.76%** | -4,766 | 0.38 |
| Shuffle s1 | 19 | -5.81% | -5,818 | 0.24 |
| Shuffle s7 | 21 | -8.95% | -8,965 | 0.06 |

48 candidate fills, 9 contested days. The earlier positive numbers
(+2.4–3.4%) were inflated by same-day fills — **corrected results are all
negative** and AI-vs-controls remain within noise. The October window is
confirmed underpowered AND the previous direction claim was unsafe; both
are now disclosed.

## Task 2 — Shadow runner (`backtest/shadow_runner.py`)

- Three books A/B/C share one candidate stream, rules, caps, costs.
- Append-only `backtest/shadow/decisions.jsonl` (one record per session);
  `books.json` snapshot. Reruns of a logged session skip the append —
  idempotent. All inputs carry source + eligibility timestamps.
- Records: candidates, contested days, per-book admissions, rejects,
  NAV, P&L, PF, DD, trade lists.

## Task 3 — Safe activation boundary

- Reads only published artifacts + market data; writes only under
  `backtest/shadow/` inside this worktree — no live watchlist, ledger,
  positions, cron, systemd, or order APIs touched.
- Manual dry run executed: `python3 backtest/shadow_runner.py --session
  2026-10-23 --dry-run` → ran to completion, wrote shadow records only;
  rerun skipped ledger append (idempotency verified).
- Scheduling proposal (NOT enabled): a daily cron after the nightly
  research job, e.g. `python3 -m backtest.shadow_runner --session $(date
  +%F)` under the worktree path — requires explicit approval; it is
  intentionally not installed.

## Task 4 — Evaluation definition (frozen)

Report after ≥8 weeks of accumulated sessions (not a calendar deadline):
contested-admission count, per-book NAV/net P&L/expectancy/PF/max DD,
AI-vs-A and AI-vs-C deltas, and rank correlation between AI rating and
trade outcome **on contested days only**. Success is declared only if the
delta is stable in sign across periods, not on one favorable month.

## Dry-run shadow snapshot (Oct window, all books)

A_alpha −2.71% · B_ai_rating −5.23% · C_shuffle_42 −7.94% — consistent
with the corrected smoke test.

## Activation decision

**Safe to activate** with the boundary above (read-only inputs, isolated
outputs, no orders, no recurring execution). Remaining approvals: (1)
placing the shadow runner under the production worktree path or a data
dir — currently only backtest code exists; (2) optional cron entry after
review; (3) reading production pool/intent files from the shadow — it
does so today, read-only.

## Addendum — timing-correction propagation (Task A/B)

**Task B causal verification — PASSED:**
- Monday-close signal: fixture proves fill lands next session
  (signal 2025-05-27 → fill 2025-05-28), never on the signal day.
- Monday-published rating: `rating_at` returns None on Monday, 'Buy' on
  Tuesday — invisible until next session.
- Idempotency: rerun of a logged session skips ledger append (verified).
- Shadow writes only `backtest/shadow/` — no production file touched.
- Dry-run vs corrected smoke test differ because: (a) shadow ran with
  yf `end='2026-10-23'` exclusive (bars through 10-22) vs smoke test
  `end='2026-10-24'` (bars through 10-23), and (b) shadow book C uses
  seed 42 vs smoke seeds 1/7. Rules and timing logic are identical.
- Daily OHLC affects decisions only on/after that bar; ratings only
  after next-session eligibility; fills only after armed next bar.
- Historical dry run ≠ prospective observation: the dry run replays
  recorded artifacts; prospective mode will consume future sessions
  whose outcomes are unknown.

**Task A corrected baseline:** `results/orig_corrected.json` (run in
progress at commit time — identical ORIG rules, cached 1,824-ticker bars,
alphabetical admission). Prior +5.83/+10.68/+20.94% figures included
same-day fills and are NOT point-in-time safe; corrected numbers land
with this file. Conclusions at risk: REPORT5/REPORT6 profitability
figures and smoke-test NAVs; the survivorship-bias and
ordering-sensitivity warnings stand regardless.
