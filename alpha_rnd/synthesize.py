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


def call_bridge(payload: dict) -> str:
    req = urllib.request.Request(
        BRIDGE, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    resp = urllib.request.urlopen(req, timeout=TIMEOUT_S)
    return json.loads(resp.read())["choices"][0]["message"]["content"]


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
        raise ValueError("synthesizer returned no JSON array")
    return json.loads(m.group(0))


NUM = re.compile(r"\d+\.?\d*")  # unsigned: "60-62" is a range, not -62


_WORD_FRAC = {"quarter": 0.25, "third": 1 / 3, "half": 0.5}


def _nums_in_text(text: str) -> set[float]:
    t = text.replace(",", "")
    out = {round(float(x), 4) for x in NUM.findall(t)}
    # scaled words: "1.5M", "2 million shares" -> 1500000, 2000000
    for m in re.finditer(r"(\d+\.?\d*)\s*(?:M\b|million)", t, re.I):
        out.add(round(float(m.group(1)) * 1_000_000, 4))
    for m in re.finditer(r"(\d+\.?\d*)\s*K\b", t):
        out.add(round(float(m.group(1)) * 1_000, 4))
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


def run(session: str) -> dict:
    arts = {}
    for p in sorted((EV / "case_artifacts").glob(f"*_{session}.json")):
        a = json.loads(p.read_text())
        arts[a["ticker"]] = a
    out_path = EV / f"publication_intents_{session}.json"
    cached = json.loads(out_path.read_text()) if out_path.exists() else {}
    todo = {t: a for t, a in arts.items() if t not in cached.get("intents", {})}
    intents = dict(cached.get("intents", {}))
    if todo:
        for i in synthesize(todo):
            intents[i.get("ticker")] = i
    results, reviews = {}, []
    for t, a in arts.items():
        i = intents.get(t)
        errs = (["no intent emitted"] if i is None else validate(i, a))
        if errs:
            reviews.append({"ticker": t, "session": session,
                            "violations": errs,
                            "artifact": f"case_artifacts/{t}_{session}.json"})
        else:
            results[t] = i
    doc = {"session": session,
           "synthesized_at": datetime.now(timezone.utc).isoformat(),
           "model": MODEL, "temperature": 0,
           "intents": intents, "validated": sorted(results),
           "review_required": reviews}
    tmp = out_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, indent=1))
    tmp.replace(out_path)
    print(f"session={session} validated={sorted(results)} "
          f"review={[r['ticker'] for r in reviews]}")
    return doc


if __name__ == "__main__":
    run(sys.argv[1])
