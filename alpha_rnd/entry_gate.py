"""Entry-authorization gate (fail-closed).

A watch may open a NEW position only if the watch revision is the latest frozen
publication decision for its ticker AND that decision is EXECUTABLE_WATCH.
Everything else (RISK_PLAN_REQUIRED, PUBLISHED_NON_EXECUTABLE, AMBIGUOUS_REJECTED,
RESEARCH_ONLY, NO_ACTION, legacy watches with no publication evidence, or a newer
revision with no disposition) cannot create an entry. REANALYZE_ON_TRIGGER watches
never enter this gate: they only ever produce a reanalysis request.
"""
import json
import re
from pathlib import Path

PUB_DIR = Path(__file__).resolve().parents[1] / "evaluations" / "alpha_rnd_v1"


def _watch_session(w: dict) -> str | None:
    m = re.search(r"_(\d{4}-\d{2}-\d{2})\.json", str(w.get("artifact") or ""))
    return m.group(1) if m else None


def latest_decision(ticker: str, pub_dir: Path | None = None) -> tuple[str, str | None] | None:
    """(session, disposition) of the newest frozen publication doc that mentions
    the ticker; disposition is None if that doc carries no disposition for it."""
    best = None
    for p in sorted((pub_dir or PUB_DIR).glob("publication_intents_*.json")):
        d = json.loads(p.read_text())
        disp = (d.get("dispositions") or {}).get(ticker)
        intent = (d.get("intents") or {}).get(ticker)
        if disp is None and intent is None:
            continue
        best = (p.stem.rsplit("_", 1)[-1], (disp or {}).get("disposition"))
    return best


def authorized(w: dict, pub_dir: Path | None = None) -> bool:
    lat = latest_decision(w["ticker"], pub_dir)
    if lat is None:
        return False
    session, disp = lat
    return disp == "EXECUTABLE_WATCH" and session == _watch_session(w)
