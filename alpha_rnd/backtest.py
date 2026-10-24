#!/usr/bin/env python3
"""Canonical evaluation/backtesting front door for TradingAgents.

ONE entry point routes to the existing engines — this module contains no
replay, monitor, synthesis, or strategy logic of its own.

  python -m alpha_rnd.backtest --help
  python -m alpha_rnd.backtest list
  python -m alpha_rnd.backtest targeted <manifest.json> [--ev-dir DIR]
  python -m alpha_rnd.backtest research-replay audit --as-of 2026-10-21
  python -m alpha_rnd.backtest research-replay run --as-of 2026-10-21 \\
      --policy CURRENT_PRODUCTION [--max-ta 3]
  python -m alpha_rnd.backtest strategy-backtest [--report SESSION...]
  python -m alpha_rnd.backtest prospective

FOUR DIFFERENT QUESTIONS — do not conflate:
  "the pipeline works"           -> TARGETED (engineering regression)
  "the AI reasoning works"       -> RESEARCH-REPLAY (model behavior)
  "the strategy would have won"  -> STRATEGY-BACKTEST (composite tools)
  "the live system has alpha"    -> PROSPECTIVE (forward evidence)
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EV = ROOT / "evaluations" / "alpha_rnd_v1"

# One source of truth for mode metadata — powers `list` and help text.
MODES = {
    "targeted": {
        "purpose": "Pipeline regression on explicit historical scenarios",
        "use": "changed publication/trigger/entry-gate/safety/order code",
        "ai": "NONE", "providers": "NONE", "cost": "LOW",
        "hindsight": "YES — scenarios are hindsight-selected; allowed "
                     "for engineering regression only",
        "contamination": "NONE (no model call)",
        "mutation": "NONE — in-memory state, tmp output dir",
        "alpha_evidence": "NONE — proves behavior, not edge",
        "engine": "alpha_rnd/scenario_replay.py",
    },
    "research-replay": {
        "purpose": "AI research/translation behavior on PIT inputs",
        "use": "changed prompts, agents, reasoning, synthesis quality",
        "ai": "YES", "providers": "POSSIBLE (per existing pipeline)",
        "cost": "MEDIUM/HIGH",
        "hindsight": "PIT inputs bounded, but see contamination",
        "contamination": "YES — MODEL_KNOWLEDGE_CONTAMINATION_RISK: the "
                         "current model may already know later events; "
                         "NOT clean alpha evidence",
        "mutation": "NONE — isolated evaluations/.../replays/ namespace",
        "alpha_evidence": "LIMITED — evaluates AI behavior, not profits",
        "engine": "alpha_rnd/replay.py",
    },
    "grid-backtest": {
        "purpose": "Decision-quality sweep over a ticker x date grid",
        "use": "scoring core TradingAgents decisions vs benchmark",
        "ai": "YES (TradingAgentsGraph per cell)", "providers": "YES",
        "cost": "HIGH",
        "hindsight": "PIT date-window bounded; grid chosen by user",
        "contamination": "YES — model may know later events",
        "mutation": "writes its own memory log only; your log untouched; "
                    "no production ALPHA state",
        "alpha_evidence": "LIMITED — decision scoring, NOT a portfolio "
                          "simulator (no fills/cash by design)",
        "engine": "tradingagents/backtest.py (+ `tradingagents backtest` "
                  "CLI)",
    },
    "strategy-backtest": {
        "purpose": "Historical economic performance of the full pipeline",
        "use": "would the defined process have performed over a sample",
        "ai": "YES (research-replay supplies TA)",
        "providers": "POSSIBLE", "cost": "HIGH",
        "hindsight": "PIT-bounded inputs; universe from frozen artifacts",
        "contamination": "YES — carries research-replay risk",
        "mutation": "NONE — replay namespace + read-only outcome joins",
        "alpha_evidence": "LIMITED — honest historical estimate with "
                          "stated caveats, not a promise of live alpha",
        "engine": "composite: replay.py + r5b_report.py + "
                  "cohort_outcomes.py (no dedicated engine exists)",
    },
    "prospective": {
        "purpose": "Forward evidence on data that postdates design freeze",
        "use": "is the deployed system finding/managing correctly",
        "ai": "NONE (status view; live system itself does call models)",
        "providers": "NONE", "cost": "LOW",
        "hindsight": "NO — forward outcomes only",
        "contamination": "NONE — this is the strongest non-hindsight "
                         "evidence class",
        "mutation": "NONE — read-only status of ledger/cohort tracking",
        "alpha_evidence": "STRONGEST AVAILABLE — real forward record",
        "engine": "status: cohort_outcomes.py + ta_outcomes.py + "
                  "paper ledger (read-only)",
    },
}

# Specialized/internal tools — documented, not top-level modes.
OTHER_TOOLS = [
    ("cohort_outcomes.py", "R2 rank-cohort forward outcomes (read-only)",
     "specialized: prospective measurement"),
    ("ta_outcomes.py", "R3 TA accept/reject outcome join (read-only)",
     "specialized: prospective measurement"),
    ("r5b_report.py", "paired replay-experiment outcome report",
     "specialized: strategy-backtest reporting"),
    ("mgmt_time_machine.py", "frozen adaptive-manager historical eval",
     "specialized: management regression"),
    ("reuse_engine/reuse_shadow/delta_probe",
     "repeat-analysis reuse validation (VALIDATE mode)",
     "specialized: reuse experiments"),
    ("postmortems.py / investigate.py / funnel_status.py",
     "evidence packets and observability CLIs", "specialized: diagnosis"),
    ("daily_scheduler / monitor / publish / synthesize",
     "production pipeline", "internal: not evaluation tools"),
]


def _print_list():
    for name, m in MODES.items():
        print(f"{name.upper()}\n"
              f"  purpose:      {m['purpose']}\n"
              f"  use when:     {m['use']}\n"
              f"  AI calls:     {m['ai']}   provider calls: {m['providers']}"
              f"   cost: {m['cost']}\n"
              f"  hindsight:    {m['hindsight']}\n"
              f"  contamination:{m['contamination']}\n"
              f"  mutation:     {m['mutation']}\n"
              f"  alpha evid.:  {m['alpha_evidence']}\n"
              f"  engine:       {m['engine']}\n")
    print("OTHER EXISTING TOOLS (specialized/internal, not top-level modes):")
    for tool, what, cls in OTHER_TOOLS:
        print(f"  {tool}: {what} [{cls}]")


def _targeted(args):
    from alpha_rnd import scenario_replay
    res = scenario_replay.run_manifest(args.manifest, args.ev_dir)
    return 0 if res["summary"]["failed"] == 0 else 1


def _research_replay(args):
    print("WARNING: research-replay may call AI models and data providers, "
          "incurs real cost, and carries MODEL_KNOWLEDGE_CONTAMINATION_RISK "
          "(the model may already know later events). NOT clean alpha "
          "evidence.", file=sys.stderr)
    if args.sub == "audit":
        from alpha_rnd import replay
        print(replay.audit(args.as_of))
        return 0
    from alpha_rnd import replay
    ctx = replay.ReplayContext.make(args.as_of, args.policy)
    print(json.dumps(replay.run(ctx, max_ta=args.max_ta,
                                upstream=args.upstream), indent=1))
    return 0


def _strategy_backtest(args):
    if not args.report:
        print("STRATEGY-BACKTEST is a composite, not a single engine:\n"
              "  1. python -m alpha_rnd.backtest research-replay run "
              "--as-of <s> --policy ANALYZE_ALL_CANDIDATES\n"
              "  2. python -m alpha_rnd.backtest strategy-backtest "
              "--report <s>\n"
              "  3. python -m alpha_rnd.cohort_outcomes update   "
              "(R2 forward outcomes)\n"
              "Caveats: PIT-bounded inputs; next-open fill semantics; "
              "MODEL_KNOWLEDGE_CONTAMINATION_RISK from the TA model call. "
              "A hindsight-selected scenario pack is NOT strategy evidence.")
        return 0
    from alpha_rnd import r5b_report
    print(r5b_report.report(args.report))
    return 0


def _grid_backtest(args):
    """Genuinely routes to the existing typer `backtest` command in
    cli/main.py (the registered `tradingagents` console script)."""
    print("GRID-BACKTEST: AI calls YES, provider calls YES, cost HIGH, "
          "MODEL_KNOWLEDGE_CONTAMINATION_RISK, decision scoring only — "
          "not a portfolio simulator, not clean alpha evidence.",
          file=sys.stderr)
    import typer
    from cli.main import app
    try:
        app(["backtest", *(args.args or [])], standalone_mode=False)
    except SystemExit as e:
        return e.code or 0
    except typer.Exit as e:
        return getattr(e, "exit_code", 1) or 0
    except Exception as e:  # click UsageError/Abort in standalone_mode=False
        if type(e).__module__.startswith("click"):
            return getattr(e, "exit_code", 1) or 0
        raise
    return 0


def _prospective(_args):
    from alpha_rnd import cohort_outcomes, ta_outcomes
    print("PROSPECTIVE (read-only status — no runnable simulation, no "
          "production mutation)\n")
    print("== cohort outcome tracker ==")
    print(cohort_outcomes.tracker_status())
    print("\n== TA accept/reject outcomes ==")
    print(ta_outcomes.status())
    print(f"\npaper ledger: {EV / 'alpha_paper_ledger.jsonl'}\n"
          "management state: evaluations/alpha_rnd_v1/management_state.json")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="python -m alpha_rnd.backtest",
        description=__doc__.splitlines()[0],
        epilog=(
            "DECISION GUIDE\n"
            "  changed execution/pipeline/safety code .......... targeted\n"
            "  changed prompts/reasoning/AI behavior ......... research-replay\n"
            "  historical economic performance .............. strategy-backtest\n"
            "  strongest forward (non-hindsight) evidence ... prospective\n"
            "\nFull guide: docs/BACKTESTING.md"),
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="mode")
    sub.add_parser("list", help="table of canonical modes + other tools")
    t = sub.add_parser(
        "targeted",
        help="deterministic pipeline replay; NO model/provider calls, "
             "isolated tmp state, <=12 scenarios / <=10 sessions")
    t.add_argument("manifest")
    t.add_argument("--ev-dir", default=None)
    r = sub.add_parser(
        "research-replay",
        help="PIT research replay — calls AI models; "
             "MODEL_KNOWLEDGE_CONTAMINATION_RISK; not clean alpha evidence")
    r.add_argument("sub", choices=["audit", "run"])
    r.add_argument("--as-of", required=True)
    r.add_argument("--policy", default="CURRENT_PRODUCTION",
                   choices=["CURRENT_PRODUCTION", "ANALYZE_ALL_CANDIDATES"])
    r.add_argument("--max-ta", type=int, default=None)
    r.add_argument("--upstream", default="recompute",
                   choices=["recompute", "frozen"])
    s = sub.add_parser("strategy-backtest",
                       help="composite historical economic eval (see docs)")
    s.add_argument("--report", nargs="*", default=None)
    g = sub.add_parser(
        "grid-backtest",
        help="ticker x date decision sweep — routes to `tradingagents "
             "backtest` CLI (model + provider calls, HIGH cost)")
    g.add_argument("args", nargs=argparse.REMAINDER,
                   help="passed through to `tradingagents backtest`")
    sub.add_parser("prospective",
                   help="read-only forward-evidence status")
    args = ap.parse_args(argv)
    if not args.mode:
        ap.print_help()
        return 0
    return {"list": lambda a: (_print_list(), 0)[1],
            "targeted": _targeted,
            "research-replay": _research_replay,
            "strategy-backtest": _strategy_backtest,
            "grid-backtest": _grid_backtest,
            "prospective": _prospective}[args.mode](args)


if __name__ == "__main__":
    sys.exit(main())
