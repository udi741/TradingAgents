# CURRENT STATE

Last updated: 2026-10-03 (by PROJECT_CONTROL initialization)

# WHAT THE USER SHOULD DO NOW

1. **Nothing is blocked on you.** All tracks are either running autonomously
   or waiting on calendar/expert events.
2. If the desktop shows a `REANALYSIS_REQUIRED` notification (SYNA, KOD, or
   HHH fired their trigger), hand that event to an ALPHA Devin session —
   see `runbooks/ALPHA_RND.md`.
3. If the expert sends a new BUY/ADD/SELL message, capture it **before any
   outcome is known** per `runbooks/EXPERT_NEW_SIGNAL.md` and hand it to the
   `groovy-allspice` session.
4. Otherwise: let the monitor and C12 Epoch 2 run. Check
   `state/ALPHA_RND.yaml` / `tracks/ALPHA_RND.md` for the current book.

## C12 — validation control (session `kindly-nightshade`)

- Status: ACTIVE, Epoch 2 prospective weekly cycles under the timing guard.
- Scoreable observations so far: 0 (Epoch 1 was a dry run; the 2026-09-25
  week was thrown out as LATE_DECISION_NON_SCOREABLE).
- Nothing for the user to do; it advances with real market weeks.
- Do not touch its worktree: `/home/udi/udi_provate/TradingAgents-c12`.

## ALPHA — active opportunity R&D (paper only, session `feather-room`)

- 3 open paper positions: **PBF** (short swing, stop 74.50 / close<78 exit,
  target ~90), **ACN** (medium term, close<194 exit, target ~250), **APPS**
  (event driven to ~Nov earnings, intraday stop 10.42).
- Book: ~$99,844.50 NAV on $100k start (as of 2026-10-02 close).
- 13 frozen watch triggers active until 2026-10-30; PGEN can AUTO_ENTRY at
  limit 8.20; SYNA/KOD/HHH are REANALYZE_ON_TRIGGER (never auto-buy).
- A per-minute cron monitor watches while the machine is on. If the machine
  is off, nothing is claimed and missed executions are flagged, never faked.
- Next ALPHA work: session-by-session marking; new discovery cycle only when
  the book/calendar justifies it.

## EXPERT — analysis only (session `groovy-allspice`)

- Status: WAITING_FOR_PROSPECTIVE_EXPERT_SIGNALS. Historical mimic is CLOSED
  (M2, M4, X2, X3 all rejected; decision layer stays official v0.5.0).
- Prospective count: 0 signals. Reopen threshold: 20 BUY/ADD, ≥5 losers or
  ≥25% loser rate, ≥15 explicit exits.
- User action: forward each new expert message verbatim for capture.

## PROJECT_CONTROL — this worktree

- V1 knowledge architecture initialized 2026-10-03.
- Track agents now maintain their own docs; PROJECT_CONTROL only handles
  major global doc changes.
