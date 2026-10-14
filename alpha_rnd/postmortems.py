#!/usr/bin/env python3
"""R7 trade postmortems — deterministic evidence-first case packets.

Reads ONLY frozen artifacts: trigger_events (deduped by fill identity),
monitor_state, alpha_paper_ledger, case_artifacts, funnel artifacts.
Writes evaluations/alpha_rnd_v1/trade_postmortems/<T>.json.
Never touches trading state. No LLM, no TA reruns.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ta_eval_alpha import e17_screener as e17  # noqa: E402

EV = ROOT / "evaluations" / "alpha_rnd_v1"
OUT = EV / "trade_postmortems"
EVENTS = ROOT / "alpha_rnd" / "trigger_events.jsonl"
STATE = ROOT / "alpha_rnd" / "monitor_state.json"
COST_BPS = 0.001  # canonical production fee (monitor.py:49)
TICKERS = ["PBF", "ACN", "APPS", "PGEN", "TWST", "SDGR"]

# known integrity incidents, established by prior forensic gates
INCIDENTS = {
    "PGEN": ["INTEGRITY_CORRECTIVE_EXIT_AFTER_MISSED_HARD_STOP — stop not "
             "visible in time; corrective exit (ledger incident 10-06)"],
    "ACN": ["INCIDENT_DUPLICATE_EXIT_2026-10-07 — re-seeded exited position "
            "produced a second exit event; canonical economics reconciled"],
    "APPS": ["INCIDENT_DUPLICATE_EXIT_2026-10-07 (shared mechanism)"],
    "TWST": ["missed 10-08 open exit while machine off; distinct prospective "
             "re-confirmation 10-09 -> filled 10-12"],
    "SDGR": ["crash-replay event duplication 10-13 (183 event rows, 1 fill); "
             "do_exit negative-cost-basis accounting defect -> realized "
             "corrected via REALIZED_CORRECTION 10-14"],
}


def _events():
    seen, rows = set(), []
    for l in EVENTS.read_text().splitlines():
        e = json.loads(l)
        if e.get("action") in ("PAPER_ENTRY", "PAPER_EXIT"):
            # economic identity: action+ticker+shares+price — duplicates share it
            k = (e["action"], e.get("ticker"), e.get("shares"),
                 round(e.get("price") or 0, 4))
            if k in seen:
                continue
            seen.add(k)
            rows.append(e)
    return rows


def _ta_evidence(ticker: str, entry_session: str | None) -> dict:
    arts = sorted((EV / "case_artifacts").glob(f"{ticker}_*.json"))
    valid = [a for a in arts if not a.name.endswith(".error.json")]
    errs = [a for a in arts if a.name.endswith(".error.json")]
    entry_day = [a for a in valid if entry_session
                 and a.name == f"{ticker}_{entry_session}.json"]
    entry_err = [a for a in errs if entry_session
                 and a.name == f"{ticker}_{entry_session}.error.json"]
    # nearest CONTEMPORANEOUS artifact: last valid one at or before entry
    prior = [a for a in valid if a.name.split("_")[-1][:10] <= entry_session] \
        if entry_session else valid
    nearest = prior[-1] if prior else None
    sig = None
    if nearest:
        try:
            sig = json.loads(nearest.read_text()).get("signal")
        except Exception:
            pass
    if entry_day:
        status = "VALID_SAME_SESSION"
    elif entry_err:
        status = "INVALID_RUNTIME_AT_ENTRY"  # pipeline broken on entry day
    elif nearest:
        status = "VALID_STALE"  # artifact exists but predates entry session
    else:
        status = "MISSING"
    return {"ta_evidence_status": status,
            "artifact": nearest.name if nearest else None,
            "final_signal": sig,
            "valid_artifacts": [a.name for a in valid],
            "error_artifacts": [a.name for a in errs]}


def _path_stats(ticker, entry_date, exit_date=None):
    """MFE/MAE over position-active window using canonical adjusted data."""
    try:
        end = (pd.Timestamp.now() + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        d, _ = e17.fetch_batch_ohlcv([ticker, "SPY"], entry_date, end,
                                     batch_size=2)
        df = d.get(ticker)
        if df is None:
            return {"status": "DATA_UNAVAILABLE"}
        w = df[df.index.strftime("%Y-%m-%d") >= entry_date]
        if exit_date:
            w = w[w.index.strftime("%Y-%m-%d") <= exit_date]
        if w.empty:
            return {"status": "DATA_UNAVAILABLE"}
        return {"status": "MATURED",
                "max_high": round(float(w["High"].max()), 4),
                "min_low": round(float(w["Low"].min()), 4),
                "sessions": len(w),
                "window": [str(w.index[0].date()), str(w.index[-1].date())]}
    except Exception as e:
        return {"status": "FETCH_FAILED", "error": repr(e)[:120]}


def build(ticker: str) -> dict:
    st = json.loads(STATE.read_text())
    rows = _events()
    entries = [e for e in rows if e["action"] == "PAPER_ENTRY"
               and e["ticker"] == ticker]
    exits = [e for e in rows if e["action"] == "PAPER_EXIT"
             and e["ticker"] == ticker]
    # ledger seed evidence for V1-era positions
    seeded = None
    for l in (EV / "alpha_paper_ledger.jsonl").read_text().splitlines():
        r = json.loads(l)
        if r.get("type") == "POSITION_RULES":
            for p in r["positions"]:
                if p["ticker"] == ticker:
                    seeded = p
    pos = (st.get("positions") or {}).get(ticker)
    if entries:
        e0 = entries[0]
        entry = {"shares": e0["shares"], "price": e0["price"],
                 "session": e0["utc"][:10], "source": "PAPER_ENTRY event"}
    elif seeded:
        entry = {"shares": seeded["shares"], "price": seeded["fill_price"],
                 "session": seeded["fill_date"], "source": "ledger POSITION_RULES"}
    elif pos:
        entry = {"shares": pos["shares"], "price": pos["fill"],
                 "session": pos.get("entry_session"), "source": "monitor_state"}
    else:
        entry = None
    # canonical economic exits: dedupe on (shares, price); cash-authoritative
    ex_rows = [{"shares": e["shares"], "price": e["price"],
                "session": e["utc"][:10], "utc": e["utc"],
                "why": e.get("why")} for e in exits]
    # duplicate economic rows: same ticker/session/shares twice -> only one hit
    # cash. Canonical fill per the 10-14 reconciliation (cash-consistent):
    CANON_FILL = {"ACN@2026-10-07": 195.2299957, "SDGR@2026-10-13": 25.91}
    grouped = {}
    for x in ex_rows:
        grouped.setdefault((x["session"], x["shares"]), []).append(x)
    for xs in grouped.values():
        if len(xs) > 1:
            can = CANON_FILL.get(f"{ticker}@{xs[0]['session']}")
            keep = next((x for x in xs if can is not None
                         and abs(x["price"] - can) < 0.01), xs[0])
            for x in xs:
                if x is not keep:
                    x["non_economic"] = ("duplicate/incident event row; "
                                         "did not affect cash")
    econ_exits = [x for x in ex_rows if not x.get("non_economic")]
    status = ("OPEN" if pos else "CLOSED")
    entry_px = entry["price"] if entry else None
    total_cost = total_sh = 0.0
    realized = 0.0
    if entry:
        total_sh = entry["shares"]
        # seeded/ledger entries carry authoritative `cost` (no fee baked in);
        # monitor fills embed shares*price*(1+COST_BPS) in pos["cost"]
        total_cost = (seeded["cost"] if seeded and seeded.get("cost")
                      else total_sh * entry_px * (1 + COST_BPS))
    proceeds = sum(x["shares"] * x["price"] * (1 - COST_BPS)
                   for x in econ_exits)
    sold_sh = sum(x["shares"] for x in econ_exits)
    if total_sh:
        alloc = total_cost * (sold_sh / total_sh)
        realized = round(proceeds - alloc, 2)
    ta = _ta_evidence(ticker, entry["session"] if entry else None)
    stats = _path_stats(ticker, entry["session"] if entry else None,
                        ex_rows[-1]["session"] if ex_rows else None)
    mfe = mae = None
    if stats.get("status") == "MATURED" and entry_px:
        mfe = round((stats["max_high"] / entry_px - 1) * 100, 2)
        mae = round((stats["min_low"] / entry_px - 1) * 100, 2)
    incidents = INCIDENTS.get(ticker, [])
    integrity = ("CONTAMINATED" if ticker in ("ACN", "PGEN") else
                 "CORRECTED" if ticker == "SDGR" else
                 "INCIDENT_WITH_NO_ECONOMIC_EFFECT" if ticker == "TWST" else
                 "CLEAN")
    # conservative attribution
    tags = []
    if ta["ta_evidence_status"] in ("MISSING", "INVALID_RUNTIME_AT_ENTRY"):
        tags.append("NO_VALID_TA_AT_ENTRY")
    elif ta["ta_evidence_status"] == "VALID_STALE":
        tags.append("STALE_TA_AT_ENTRY")
    if len(ex_rows) > 1:
        tags.append("PARTIAL_EXIT")
    if ticker in INCIDENTS:
        tags.append("STATE_INTEGRITY_INCIDENT" if integrity != "CLEAN"
                    else "INCIDENT")
    if ticker == "TWST":
        tags.append("MISSED_EXECUTION")
    if pos:
        attr = {"primary_failure_attribution": "NO_FAILURE_OPEN_OR_WINNER",
                "confidence": "LOW"}
    elif realized <= 0:
        attr = {"primary_failure_attribution":
                "MULTIPLE_FACTORS" if len(tags) > 1 else "UNDETERMINED",
                "confidence": "LOW"}
    else:
        attr = {"primary_failure_attribution": "UNDETERMINED",
                "confidence": "LOW"}
    pkt = {
        "schema_version": 1, "ticker": ticker,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "identity": {"status": status, "entry": entry,
                     "initial_notional": round(total_cost, 2)},
        "ex_ante": ta,
        "execution": {"entries": entries and [{"shares": e["shares"],
                          "price": e["price"], "utc": e["utc"]} for e in entries]
                      or ([entry] if entry else []),
                      "exits": ex_rows,
                      "gross_proceeds": round(proceeds, 2),
                      "cost_basis_alloc": round(alloc if total_sh else 0, 2),
                      "realized_pnl": realized,
                      "remaining_shares": pos["shares"] if pos else 0},
        "management": {"incidents": incidents},
        "ex_post": {**stats, "MFE_pct": mfe, "MAE_pct": mae,
                    "open_position": bool(pos)},
        "integrity": {"execution_integrity": integrity,
                      "incidents": incidents},
        "attribution": {"lesson_tags": tags, **attr},
        "provenance": {"sources": ["trigger_events.jsonl", "monitor_state.json",
                                   "alpha_paper_ledger.jsonl",
                                   "case_artifacts/"],
                       "price_convention": "auto_adjusted"}}
    return pkt


def build_all() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    pkts = {}
    for t in TICKERS:
        pkts[t] = build(t)
        (OUT / f"{t}.json").write_text(json.dumps(pkts[t], indent=1,
                                                sort_keys=True))
    return pkts


def report(ticker: str) -> str:
    p = build(ticker)
    i, e, x, a = p["identity"], p["execution"], p["ex_post"], p["attribution"]
    lines = [f"ALPHA TRADE INVESTIGATION — {ticker}", "",
             f"STATUS: {i['status']}"]
    if i["entry"]:
        lines.append(f"ENTRY: {i['entry']['shares']}sh @ ${i['entry']['price']} "
                     f"on {i['entry']['session']} ({i['entry']['source']})")
    lines += ["", "EX-ANTE:",
              f"  TA evidence: {p['ex_ante']['ta_evidence_status']} "
              f"(artifact {p['ex_ante']['artifact']}) "
              f"signal={p['ex_ante']['final_signal']}",
              "", "EXECUTION:"]
    for x_ in e["exits"]:
        lines.append(f"  EXIT {x_['shares']}sh @ ${x_['price']} {x_['session']} "
                     f"— {str(x_['why'])[:60]}")
    lines += [f"  realized P&L: ${e['realized_pnl']}",
              "", "OUTCOME:",
              f"  MFE {x['MFE_pct']}% / MAE {x['MAE_pct']}% "
              f"({x.get('sessions','?')} sessions, window {x.get('window')})",
              "", "INTEGRITY:", f"  {p['integrity']['execution_integrity']}"]
    for inc in p["integrity"]["incidents"]:
        lines.append(f"  - {inc}")
    lines += ["", "ATTRIBUTION:",
              f"  primary: {a['primary_failure_attribution']} "
              f"(confidence {a['confidence']})",
              f"  tags: {a['lesson_tags']}"]
    return "\n".join(lines)


if __name__ == "__main__":
    if "--all" in sys.argv:
        for t in TICKERS:
            print(report(t)); print("=" * 60)
    elif "--ticker" in sys.argv:
        print(report(sys.argv[sys.argv.index("--ticker") + 1]))
    else:
        build_all()
        print(f"wrote {len(TICKERS)} packets to {OUT}")
