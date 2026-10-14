#!/usr/bin/env python3
"""ALPHA_RND publication synthesizer — operational TRANSLATOR, not a strategy.

Converts frozen TA case artifacts into strict PublicationIntent records that
publish.py can validate and merge into live_watchlist.json. It extracts ONLY
what the artifact explicitly states; it never judges the stock.

Pipeline per session:
  deterministic extract (ticker, rating, numeric levels as TEXT SPANS)
  -> one bounded devin-deep bridge call (temp 0) translating artifact prose
     into PublicationIntent JSON
  -> deterministic fail-closed validator (evidence binding: every emitted
     number must appear in the source artifact text)
  -> intents_<session>.json  (durable synthesis checkpoint for resume)

  python3 -m alpha_rnd.synthesize <session>
"""

from __future__ import annotations

import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from alpha_rnd import infra_status as inf

ROOT = Path(__file__).resolve().parents[1]
EV = ROOT / "evaluations" / "alpha_rnd_v1"
BRIDGE = "http://127.0.0.1:8765/v1/chat/completions"
MODEL = "devin-deep"          # -> swe-2-high; temperature 0; timeout 1200
TIMEOUT_S = 1200

CLASSIFICATIONS = [
    "ACTIONABLE_NOW", "WATCH_FOR_ENTRY", "REANALYZE_ON_TRIGGER",
    "REJECT", "NO_WATCH",
]
WATCH_MODES = ["AUTO_ENTRY", "DETERMINISTIC_CONFIRMATION",
               "REANALYZE_ON_TRIGGER", "NONE"]

SCHEMA_HINT = """For EACH ticker emit one object:
{"ticker":str,"classification":"ACTIONABLE_NOW"|"WATCH_FOR_ENTRY"|
 "REANALYZE_ON_TRIGGER"|"REJECT"|"NO_WATCH",
 "watch_mode":"AUTO_ENTRY"|"DETERMINISTIC_CONFIRMATION"|
 "REANALYZE_ON_TRIGGER"|"NONE",
 "trigger":str|null,        // verbatim-ish entry condition stated in the text
 "params":{...}|null,       // numeric levels/zones ONLY if stated in the text
 "entry_convention":str|null,
 "invalidation":str|null,   // stop/invalidation explicitly stated
 "stop_level":number|null,  // stated stop price, else null
 "target":number|null,      // stated price target, else null
 "horizon":str|null,        // stated time horizon
 "reevaluation":str|null,   // stated catalyst/re-check
 "size_frac":number|null,   // fraction of standard allocation if stated, else null
 "auto_execution_authorized":bool, // true ONLY if text gives an executable
                                   // intraday/limit instruction
 "ambiguity":str|null}      // why it cannot be published, if unclear
Rules: every number must appear in the source text; do not invent levels,
stops, or targets; a Sell/Hold headline does NOT forbid a conditional
WATCH_FOR_ENTRY if the text states a re-entry plan; REJECT/NO_WATCH only when
the text contains no usable forward instruction. Output a JSON array only."""


def artifact_text(a: dict) -> str:
    return "\n".join(a.get(k) or "" for k in
                     ("final_trade_decision", "trader_investment_plan",
                      "risk_judge_decision", "investment_plan"))


class TranslatorInfra(Exception):
    """Transport/provider failure of the translator call: no valid model result."""

    def __init__(self, reason: str, raw: str):
        super().__init__(reason)
        self.reason, self.raw = reason, raw


def call_bridge(payload: dict) -> str:
    req = urllib.request.Request(
        BRIDGE, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    try:
        resp = urllib.request.urlopen(req, timeout=TIMEOUT_S)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:2000]
        raise TranslatorInfra(inf.classify(f"HTTP {e.code} {body}"), f"HTTP {e.code}: {body}") from e
    except (urllib.error.URLError, OSError) as e:
        raise TranslatorInfra(inf.classify(repr(e)), repr(e)) from e
    try:
        return json.loads(resp.read())["choices"][0]["message"]["content"]
    except (KeyError, IndexError, ValueError) as e:
        raise TranslatorInfra("MALFORMED_MODEL_OUTPUT", repr(e)) from e


def synthesize(arts: dict[str, dict]) -> list[dict]:
    """One bounded semantic call for the whole session."""
    chunks = []
    for t, a in sorted(arts.items()):
        chunks.append(f"=== {t} ===\n{artifact_text(a)[:9000]}")
    msg = ("You translate frozen trading-analysis reports into operational "
           "watch specifications. You do NOT judge the stocks. Emit only what "
           "each report explicitly states.\n\n" + SCHEMA_HINT +
           "\n\nREPORTS:\n" + "\n\n".join(chunks))
    out = call_bridge({"model": MODEL, "temperature": 0,
                       "messages": [{"role": "user", "content": msg}]})
    m = re.search(r"\[.*\]", out, re.S)
    if not m:
        reason = inf.classify(out)  # provider error text returned as content
        raise TranslatorInfra(
            reason if reason != "UNKNOWN_MODEL_FAILURE" else "MALFORMED_MODEL_OUTPUT", out[:500])
    try:
        return json.loads(m.group(0))
    except ValueError as e:
        raise TranslatorInfra("MALFORMED_MODEL_OUTPUT", repr(e)) from e


NUM = re.compile(r"\d+\.?\d*")  # unsigned: "60-62" is a range, not -62


_WORD_FRAC = {"quarter": 0.25, "third": 1 / 3, "half": 0.5}


def _nums_in_text(text: str) -> set[float]:
    t = text.replace(",", "")
    out = {round(float(x), 4) for x in NUM.findall(t)}
    # percents: "5%", "1.25%" -> 0.05, 0.0125 (fraction form)
    for m in re.finditer(r"(\d+\.?\d*)\s*%", t):
        out.add(round(float(m.group(1)) / 100, 6))
    # percent ranges: "5-8%", "1.0%-1.25%" -> 0.05, 0.08 / 0.01, 0.0125
    for m in re.finditer(r"(\d+\.?\d*)\s*[-–]\s*(\d+\.?\d*)\s*%", t):
        out.add(round(float(m.group(1)) / 100, 6))
    # scaled words: "1.5M", "2 million shares", "83k" -> 1500000, 2000000, 83000
    for m in re.finditer(r"(\d+\.?\d*)\s*(?:M\b|million)", t, re.I):
        out.add(round(float(m.group(1)) * 1_000_000, 4))
    for m in re.finditer(r"(\d+\.?\d*)\s*K\b", t, re.I):
        out.add(round(float(m.group(1)) * 1_000, 4))
    # scaled ranges: "1.7-3.0 million-share", "83-84k" -> both endpoints scaled
    for m in re.finditer(r"(\d+\.?\d*)\s*[-–]\s*(\d+\.?\d*)\s*(M\b|million|K\b)", t, re.I):
        scale = 1_000_000 if m.group(3).lower().startswith(("m",)) else 1_000
        out.add(round(float(m.group(1)) * scale, 4))
    return out


def _levels(obj) -> list[float]:
    vals = []

    def walk(o):
        if isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, (list, tuple)):
            for v in o:
                walk(v)
        elif isinstance(o, (int, float)) and not isinstance(o, bool):
            vals.append(float(o))
    walk(obj)
    return vals


def validate(intent: dict, a: dict) -> list[str]:
    """Deterministic fail-closed checks; returns list of violations."""
    errs = []
    t = intent.get("ticker")
    if t != a["ticker"]:
        errs.append(f"ticker mismatch {t}!={a['ticker']}")
        return errs
    if intent.get("classification") not in CLASSIFICATIONS:
        errs.append("bad classification")
    mode = intent.get("watch_mode")
    if mode not in WATCH_MODES:
        errs.append("bad watch_mode")
    if intent.get("ambiguity"):
        errs.append(f"ambiguous: {intent['ambiguity']}")
    src_nums = _nums_in_text(artifact_text(a))
    for v in _levels({k: intent.get(k) for k in ("params", "stop_level",
                                               "target")}):
        if not any(abs(v - s) <= max(0.005 * abs(s), 0.01) for s in src_nums):
            errs.append(f"unsupported number {v}")
    sf = intent.get("size_frac")
    if sf is not None:
        words = artifact_text(a).lower()
        ok = any(abs(sf - s) <= 0.005 * abs(s) for s in src_nums) or \
            any(abs(sf - f) < 0.02 for w, f in _WORD_FRAC.items() if w in words) \
            or sf == 1.0
        if not ok:
            errs.append(f"unsupported size_frac {sf}")
    cls = intent.get("classification")
    if mode == "AUTO_ENTRY" or cls == "ACTIONABLE_NOW":
        if not intent.get("auto_execution_authorized"):
            errs.append("auto entry without authorization")
        if not intent.get("params"):
            errs.append("auto entry without explicit params")
        if a.get("signal") not in ("Buy", "Overweight"):
            errs.append(f"auto entry contradicts TA signal {a.get('signal')}")
    if cls == "ACTIONABLE_NOW" and a.get("signal") not in ("Buy", "Overweight"):
        errs.append("ACTIONABLE_NOW contradicts TA signal")
    if mode == "AUTO_ENTRY" and not intent.get("stop_level"):
        errs.append("AUTO_ENTRY without stated stop")
    if cls in ("REJECT", "NO_WATCH") and mode not in ("NONE", None):
        errs.append("reject/no-watch with watch_mode")
    if cls in ("WATCH_FOR_ENTRY", "REANALYZE_ON_TRIGGER") and not (
            intent.get("trigger") or intent.get("params")):
        errs.append("watch without any trigger")
    # Historical contract: a trigger that depends on a news/catalyst/deal
    # check cannot be a mechanical confirmation — it needs reanalysis.
    trig_text = " ".join(str(intent.get(k) or "") for k in
                         ("trigger", "entry_convention", "reevaluation",
                          "ambiguity")).lower()
    if (mode == "DETERMINISTIC_CONFIRMATION"
            and re.search(r"catalyst|news|deal|offering|check", trig_text)):
        errs.append("event/news-gated trigger must be REANALYZE_ON_TRIGGER")
    return errs


DISPOSITIONS = ["EXECUTABLE_WATCH", "REANALYZE_ON_TRIGGER", "RISK_PLAN_REQUIRED",
                "RESEARCH_ONLY", "AMBIGUOUS_REJECTED", "NO_ACTION",
                "OPEN_POSITION_MANAGEMENT", "PUBLISHED_NON_EXECUTABLE"]
PUBLISHABLE = {"EXECUTABLE_WATCH", "REANALYZE_ON_TRIGGER",
               "PUBLISHED_NON_EXECUTABLE"}

# Param keys the production monitor can mechanically evaluate (see
# close_pass/intraday_pass). An intent without one is descriptive, not
# executable — regardless of validation status.
_EXECUTABLE_PARAM_KEYS = {
    "zone", "zone1", "zone2", "pb_zone", "retest_zone", "bo_level",
    "levels", "kill", "probe_zone", "gate_date", "reclaim", "hold",
    "alt_level", "veto_level"}


def _machine_executable(i: dict) -> bool:
    """EXECUTABLE_WATCH == the production monitor can actually evaluate the
    entry mechanically AND a machine-actionable post-entry risk plan exists."""
    if i.get("watch_mode") not in ("AUTO_ENTRY", "DETERMINISTIC_CONFIRMATION"):
        return False
    p = i.get("params") or {}
    if not _EXECUTABLE_PARAM_KEYS & set(p):
        return False
    return _has_risk_plan(i)


def _has_risk_plan(i: dict) -> bool:
    if i.get("stop_level"):
        return True
    inv = i.get("invalidation")
    if isinstance(inv, dict) and inv.get("type") in (
            "intraday_stop", "close_below", "price_below"):
        return True
    return bool(re.search(r"stop \$?(\d+\.?\d*)", str(inv or "")))


def disposition(intent: dict | None, errs: list[str], held: set[str]) -> str:
    """Deterministic fail-closed publication disposition. Normal TA ambiguity
    maps to a non-executable class — never a user-facing emergency."""
    if intent is None:
        return "AMBIGUOUS_REJECTED"
    cls = intent.get("classification")
    if cls in ("REJECT", "NO_WATCH"):
        return "NO_ACTION"
    if cls == "REANALYZE_ON_TRIGGER" or intent.get("watch_mode") == "REANALYZE_ON_TRIGGER":
        if errs:
            pass  # falls through to error mapping below
        else:
            return "REANALYZE_ON_TRIGGER"
    if not errs:
        return "EXECUTABLE_WATCH" if _machine_executable(intent) \
            else "PUBLISHED_NON_EXECUTABLE"
    if intent.get("ticker") in held:
        return "OPEN_POSITION_MANAGEMENT"
    text = " ".join(errs).lower()
    if "ambiguous" in text or "unsupported" in text:
        return "AMBIGUOUS_REJECTED"
    if "news-gated" in text or "catalyst" in text:
        return "REANALYZE_ON_TRIGGER"
    if not _has_risk_plan(intent):
        return "RISK_PLAN_REQUIRED"
    return "RESEARCH_ONLY"


def run(session: str) -> dict:
    arts = {}
    for p in sorted((EV / "case_artifacts").glob(f"*_{session}.json")):
        a = json.loads(p.read_text())
        arts[a["ticker"]] = a
    held = set()
    try:
        held = set(json.loads(
            (ROOT / "alpha_rnd" / "monitor_state.json").read_text()
        ).get("positions") or {})
    except Exception:
        pass
    out_path = EV / f"publication_intents_{session}.json"
    cached = json.loads(out_path.read_text()) if out_path.exists() else {}
    todo = {t: a for t, a in arts.items() if t not in cached.get("intents", {})}
    intents = dict(cached.get("intents", {}))
    status_path = EV / f"publication_status_{session}.json"
    if todo:
        try:
            for i in synthesize(todo):
                intents[i.get("ticker")] = i
        except TranslatorInfra as e:
            rec = inf.failure_record(session, None, "publication_synthesis", e.raw,
                                     reason=e.reason)
            rec["tickers"] = sorted(todo)
            status_path.write_text(json.dumps(rec, indent=1, sort_keys=True))
            print(f"session={session} translator INFRASTRUCTURE_FAILED {e.reason}")
            return {"session": session, **rec, "validated": [], "dispositions": {},
                    "review_required": []}
    status_path.unlink(missing_ok=True)
    results, reviews, disps = {}, [], {}
    for t, a in arts.items():
        i = intents.get(t)
        if i is None:  # translator returned a valid array that omits this ticker
            disps[t] = {"disposition": inf.ANALYSIS_STATUS, "reason_code": "MALFORMED_MODEL_OUTPUT",
                        "violations": ["translator output omitted ticker"], "executable": False,
                        "user_action_required": False, "artifact": f"case_artifacts/{t}_{session}.json"}
            continue
        errs = validate(i, a)
        d = disposition(i, errs, held)
        disps[t] = {"disposition": d, "violations": errs,
                    "executable": d == "EXECUTABLE_WATCH",
                    "user_action_required": False,
                    "artifact": f"case_artifacts/{t}_{session}.json"}
        if errs:
            reviews.append({"ticker": t, "session": session,
                            "disposition": d,
                            "violations": errs,
                            "artifact": f"case_artifacts/{t}_{session}.json"})
        else:
            results[t] = i
    doc = {"session": session,
           "synthesized_at": datetime.now(timezone.utc).isoformat(),
           "model": MODEL, "temperature": 0,
           "intents": intents, "validated": sorted(results),
           "dispositions": disps,
           "review_required": reviews}
    tmp = out_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, indent=1))
    tmp.replace(out_path)
    print(f"session={session} validated={sorted(results)} "
          f"review={[r['ticker'] for r in reviews]}")
    return doc


if __name__ == "__main__":
    run(sys.argv[1])
