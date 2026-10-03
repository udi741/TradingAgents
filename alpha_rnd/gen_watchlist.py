#!/usr/bin/env python3
"""Generate the authoritative ALPHA_RND live watchlist (frozen watch triggers)."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "alpha_rnd" / "live_watchlist.json"

# classes: AUTO_ENTRY | DETERMINISTIC_CONFIRMATION | REANALYZE_ON_TRIGGER | AMBIGUOUS
WATCHES = [
    # ---- V1 watches (frozen 2026-10-02 artifacts, decision_session 2026-10-01)
    {"ticker": "IOVA", "cls": "DETERMINISTIC_CONFIRMATION", "v": 1,
     "trigger": "2 consecutive daily closes inside $12.20-13.00 (mechanical 'stabilization' read of 'multiple sessions of stabilization'), then staged small entry at next session open within zone; ALT: weekly close >$15.30 with weekly volume > prior week",
     "trigger_type": "multi_close_in_zone|weekly_close_breakout",
     "params": {"zone": [12.20, 13.00], "closes_required": 2, "alt_level": 15.30},
     "entry_convention": "next-session open after confirmation (zone leg, fill <= zone top)",
     "invalidation": "hard stop below entry structure (per artifact)",
     "horizon": "reassess ~early-Nov earnings", "artifact": "IOVA_2026-10-01.json", "size_frac": 1.0},
    {"ticker": "CDNA", "cls": "DETERMINISTIC_CONFIRMATION", "v": 1,
     "trigger": "daily close inside $60-62 with session volume < 20-day avg (declining-volume pullback)",
     "trigger_type": "close_in_zone_low_vol",
     "params": {"zone": [60.00, 62.00]},
     "entry_convention": "next-session open after qualifying close",
     "invalidation": "decisive close < 55.90",
     "horizon": "weeks-3 months", "artifact": "CDNA_2026-10-01.json", "size_frac": 0.3},
    {"ticker": "SDGR", "cls": "DETERMINISTIC_CONFIRMATION", "v": 1,
     "trigger": "daily close > $32.45 on volume > 20-day avg, then fill on retest into $30-31; OR daily close inside $24-26 with no single-day |move|>8% in prior 5 sessions (news-gap guard)",
     "trigger_type": "close_breakout_retest|orderly_pullback_close",
     "params": {"bo_level": 32.45, "retest_zone": [30.0, 31.0], "pb_zone": [24.0, 26.0], "gap_guard": 0.08},
     "entry_convention": "retest leg: zone-top limit 31.0 after breakout close; pullback leg: next-session open after qualifying close",
     "invalidation": "NOT_STATED",
     "horizon": "trigger-event driven", "artifact": "SDGR_2026-10-01.json", "size_frac": 1.0},
    # ---- V2 watches (frozen 2026-10-03, decision_session 2026-10-02)
    {"ticker": "PGEN", "cls": "AUTO_ENTRY", "v": 2,
     "trigger": "intraday price <= $8.20 (staggered limit buys $8.00-8.20; do not chase >8.54)",
     "trigger_type": "intraday_zone_touch",
     "params": {"zone": [8.00, 8.20]},
     "entry_convention": "zone-top limit $8.20 (ALPHA_RND convention)",
     "invalidation": "stop $7.75; structural <$7.03",
     "horizon": "1-3 months through Q3 print", "artifact": "PGEN_2026-10-02.json", "size_frac": 1.0},
    {"ticker": "SYNA", "cls": "REANALYZE_ON_TRIGGER", "v": 2,
     "trigger": "pullback toward ~$112, or <$106, or second bidder / deal-negative news",
     "trigger_type": "price_level_or_event",
     "params": {"levels": [106.0, 112.0]},
     "entry_convention": "REANALYSIS_REQUIRED only (needs no-deal-negative-news check)",
     "invalidation": "deal-break gap", "horizon": "deal resolution wks-qtr",
     "artifact": "SYNA_2026-10-02.json", "size_frac": 1.0},
    {"ticker": "ASST", "cls": "DETERMINISTIC_CONFIRMATION", "v": 2,
     "trigger": "after 2026-10-13: 3 consecutive daily closes > $35 (absorption), OR intraday price <= $26.25 (deep-pullback leg, quarter size)",
     "trigger_type": "event_gated_multi_close|intraday_zone_touch",
     "params": {"gate_date": "2026-10-13", "level": 35.0, "closes_required": 3, "pb_zone": [26.25, 26.25]},
     "entry_convention": "confirmation leg: next-session open; pullback leg: limit 26.25 quarter size",
     "invalidation": "hard stop <$25 (pullback leg)",
     "horizon": "post-Oct-13 warrant window", "artifact": "ASST_2026-10-02.json", "size_frac": 0.25},
    {"ticker": "KOD", "cls": "REANALYZE_ON_TRIGGER", "v": 2,
     "trigger": "a priced equity offering in the $55-80 range (event, not price pattern); price <=$80 or >=$55 alone is NOT the trigger",
     "trigger_type": "event_only",
     "params": {"offering_range": [55.0, 80.0], "manual_event": True},
     "entry_convention": "REANALYSIS_REQUIRED 2-3 sessions after priced offering",
     "invalidation": "size-as-stop (Dec binary)",
     "horizon": "~1-3 months / Dec P3", "artifact": "KOD_2026-10-02.json", "size_frac": 0.5},
    {"ticker": "TXG", "cls": "DETERMINISTIC_CONFIRMATION", "v": 2,
     "trigger": "daily close inside $84-86 with session volume < 20-day avg (stabilization proxy), OR daily close inside $74.60-77.88 (shelf leg)",
     "trigger_type": "close_in_zone_low_vol|close_in_zone",
     "params": {"zone1": [84.0, 86.0], "zone2": [74.60, 77.88]},
     "entry_convention": "next-session open after qualifying close",
     "invalidation": "stop under ~$72 (shelf leg)",
     "horizon": "1-3 months", "artifact": "TXG_2026-10-02.json", "size_frac": 0.5},
    {"ticker": "TWST", "cls": "DETERMINISTIC_CONFIRMATION", "v": 2,
     "trigger": "daily close > $200.31 with volume > 20-day avg (post-lockup breakout), OR 2 consecutive closes inside $178-183",
     "trigger_type": "close_breakout_vol|multi_close_in_zone",
     "params": {"bo_level": 200.31, "zone": [178.0, 183.0], "closes_required": 2, "veto_level": 183.39},
     "entry_convention": "next-session open after qualifying close; void if close <183.39 on >20d-avg volume",
     "invalidation": "stay out if $183.39 breaks on heavy volume",
     "horizon": "1-3 months post-lockup", "artifact": "TWST_2026-10-02.json", "size_frac": 0.5},
    {"ticker": "PAYC", "cls": "DETERMINISTIC_CONFIRMATION", "v": 2,
     "trigger": "daily close > $232 on >=1.5M shares (MACD check at close pass), OR daily close inside $200-205 after a down day on volume < prior up-day volume",
     "trigger_type": "close_breakout_vol|gapfill_probe",
     "params": {"bo_level": 232.0, "vol_min": 1_500_000, "probe_zone": [200.0, 205.0], "kill": 213.0},
     "entry_convention": "next-session open; ALL triggers void on daily close <213",
     "invalidation": "daily close <213 removes triggers",
     "horizon": "flat; review next filing", "artifact": "PAYC_2026-10-02.json", "size_frac": 0.25},
    {"ticker": "XNCR", "cls": "DETERMINISTIC_CONFIRMATION", "v": 2,
     "trigger": "daily close > $25.70 on >2M shares (confirmed breakout)",
     "trigger_type": "close_breakout_vol",
     "params": {"bo_level": 25.70, "vol_min": 2_000_000},
     "entry_convention": "next-session open after qualifying close",
     "invalidation": "NOT_STATED",
     "horizon": "days-2-6 wks range resolution", "artifact": "XNCR_2026-10-02.json", "size_frac": 1.0},
    {"ticker": "AXGN", "cls": "DETERMINISTIC_CONFIRMATION", "v": 2,
     "trigger": "daily close > $40.00 AND next session closes/holds > $38.70 (2-step reclaim)",
     "trigger_type": "reclaim_2step",
     "params": {"reclaim": 40.00, "hold": 38.70},
     "entry_convention": "next-session open after hold confirmed; 1/3 standard allocation",
     "invalidation": "stop below reclaim candle",
     "horizon": "2-8 weeks", "artifact": "AXGN_2026-10-02.json", "size_frac": 0.33},
    {"ticker": "HHH", "cls": "REANALYZE_ON_TRIGGER", "v": 2,
     "trigger": "price into $63.75-65.80 (needs catalyst check first) OR daily close > $74.88 on expanding volume",
     "trigger_type": "price_zone_event_gate|close_breakout",
     "params": {"zone": [63.75, 65.80], "bo_level": 74.88},
     "entry_convention": "pullback leg: REANALYSIS_REQUIRED (catalyst check); breakout leg recorded, review before entry",
     "invalidation": "~$73.8 breakout leg",
     "horizon": "4-8 weeks", "artifact": "HHH_2026-10-02.json", "size_frac": 0.15},
]

POSITIONS = [
    {"ticker": "PBF", "shares": 62, "fill": 80.00, "style": "SHORT_SWING",
     "invalidation": {"type": "intraday_stop", "level": 74.50, "label": "hard stop"},
     "exit_rules": [{"type": "close_below", "level": 78.00, "label": "failed breakout"}],
     "reeval": "time-box ~Oct-16 window (2-3wk); review at next completed session after 2026-10-16",
     "horizon": "2-3wk time-box", "artifact": "PBF_2026-10-01.json"},
    {"ticker": "ACN", "shares": 24, "fill": 205.00, "style": "MEDIUM_TERM",
     "invalidation": {"type": "close_below", "level": 194.00, "label": "daily close below 200 SMA"},
     "exit_rules": [{"type": "close_below", "level": 194.00}],
     "reeval": "next earnings (op-margin check); gap-fill <183 secondary invalidation",
     "horizon": "6-12 months", "artifact": "ACN_2026-10-01.json"},
    {"ticker": "APPS", "shares": 442, "fill": 11.30, "style": "EVENT_DRIVEN",
     "invalidation": {"type": "intraday_stop", "level": 10.42, "label": "hard stop"},
     "exit_rules": [{"type": "intraday_below", "level": 10.42}],
     "reeval": "~Nov-3 earnings (primary clock)",
     "horizon": "through ~Nov-3 earnings", "artifact": "APPS_2026-10-01.json"},
]

def build_doc() -> dict:
    doc = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "watch_expiry": "2026-10-30",
        "recommendation_freeze": "2026-10-02 (V1) / 2026-10-03 (V2)",
        "sizing": {"position_notional": 5000.0, "max_positions": 10, "cost_bps": 0.001},
        "watches": WATCHES,
        "open_positions": POSITIONS,
    }
    blob = json.dumps(doc, sort_keys=True).encode()
    doc["sha256"] = hashlib.sha256(blob).hexdigest()
    return doc


def main():
    doc = build_doc()
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, indent=1))
    tmp.replace(OUT)
    print(OUT, doc["sha256"][:16], len(WATCHES), "watches", len(POSITIONS), "positions")

if __name__ == "__main__":
    main()
