# TradingAgents Command Center — dashboard runbook

Capability: `ops.command_center_dashboard` in
`docs/TRADINGAGENTS_CAPABILITY_REGISTRY.yaml`.

A local, **read-only-by-default** web dashboard over the real ALPHA and C12
state. It is an inspection and safe-operations surface, **not** a trading
interface. There is no code path from the dashboard into any economic state
file.

## Launch / shutdown

```bash
cd /home/udi/udi_provate/TradingAgents-dashboard   # this worktree
python3 -m dashboard.server                        # http://127.0.0.1:8420
```

Ctrl-C to stop. No daemon, no install step, no external network required —
the UI is a static SPA served by the same process; all data comes from local
files.

Config env vars (defaults are correct on this machine):
`TA_DASH_PREFIX`, `TA_DASH_ALPHA_ROOT`, `TA_DASH_C12_ROOT`,
`TA_DASH_TRACKS_ROOT`, `TA_DASH_HOST`, `TA_DASH_PORT`.

## Architecture

```
dashboard/
  server.py         FastAPI app: JSON /api/* + static SPA (hash routing)
  config.py         authoritative root paths (env-overridable for tests)
  readutil.py       tolerant readers; every read carries {state, mtime, age}
  truth_ledger.py   field -> api -> source -> freshness map (canonical)
  adapters/
    alpha.py        monitor_state, watchlist, funnel, candidates, artifacts,
                    entry snapshots, management actions/intents/analyses,
                    ledger, trigger/management events
    c12.py          C12 paper portfolio, NAV series, signal ledger
    capabilities.py TRADINGAGENTS_CAPABILITY_REGISTRY.yaml (loaded live)
    providers.py    infra_status.status_report() + registry provider semantics
    health.py       ops.ta health/status wrapper, bridge probe, systemd units
  static/           vanilla-JS SPA (no build step, no CDN)
  tests/            reconciliation, safety, edge-case tests
```

Freshness semantics: every API response embeds `meta` per source file
(`state`: ok|missing|malformed|empty|unreadable, `mtime_utc`,
`age_seconds`). The UI renders `—`/UNKNOWN for absent values; it never
substitutes zero.

## Data authority

The dashboard **never** computes its own economics. Cash, positions,
realized/unrealized, pending orders, and executed IDs come straight from
`alpha_rnd/monitor_state.json`; fills reconcile against
`alpha_paper_ledger.jsonl` (note: ledger lines ~24–128 carry the 2026-10-07
duplicate-exit incident — `monitor_state.json` remains the authority). C12 is
read from its own worktree and displayed only on the Tracks page — never
mixed into ALPHA figures. The full field→source map is
`dashboard/truth_ledger.py` (also exposed at `/api/truth-ledger`) and is
enforced by `dashboard/tests/test_reconciliation.py`.

## Safe controls

`#/controls` exposes an allowlist only:

| Control | Effect | Mutates state? |
|---|---|---|
| health-check | runs `ops.ta health` | no |
| status | runs `ops.ta status` | no |
| backup | runs `ops.ta backup --output artifacts/backups/<ts>.tar.gz` (takes the same file locks briefly; writes only the archive) | no economic state |

Every control requires an explicit `confirm=I_UNDERSTAND` POST — the UI
implements this as a two-step confirmation dialog. Anything not in the
allowlist returns 404. There is deliberately **no** scheduler pause, no
kill-switch toggle, and no order action in the dashboard: those mutate live
economics and remain CLI/manual operations by design.

## Pages

`#/overview` command center · `#/funnel` opportunity funnel + candidate pool
· `#/research` TA case artifacts with drilldown · `#/positions` portfolio +
per-ticker detail (entry plan vs current management plan, Phase-G snapshot,
timeline) · `#/management` deterministic vs adaptive management ·
`#/executions` pending/fills/ledger with authority notes · `#/performance`
evidence view (INSUFFICIENT_SAMPLE-aware) · `#/providers` provider/runtime
health · `#/health` ops.ta health + services · `#/capabilities` live registry
browser · `#/tracks` track boundaries · `#/controls` safe operations.

## Known caveats

- `ops.ta health` currently reports FAILED on "adaptive execution DISABLED
  (expected)" because `management_policy.json` execution is enabled — the
  check encodes the pre-2026-10-16 default; the dashboard surfaces the flag
  accurately rather than hiding it.
- `management_events.jsonl` repeats `MGMT_EXECUTION/ALREADY_ENQUEUED` ~1/min
  while the PBF partial exit waits for a valid open — the UI dedupes; the
  pending order itself is the authority.
- Seeded/legacy positions predate Phase G; where no `entry_snapshots/` record
  exists the UI says so instead of fabricating success-plan fields.
- `TWST_2026-10-16` entry snapshot carries a suspect `stop_rule.level=1.0`;
  the dashboard shows source values with freshness, and flags obviously
  inconsistent stop levels rather than correcting them.

## Testing

```bash
python3 -m pytest dashboard/tests/ -q      # unit + reconciliation + safety
python3 alpha_repo_docs_drift_check.py     # doc drift (must stay green)
```

Browser/E2E evidence: `artifacts/dashboard_review/`.
