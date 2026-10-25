#!/usr/bin/env python3
"""Backtest follow-up experiments (no model calls).

Part 1: reconcile actual ledger; per-trade exposure-matched SPY benchmark.
Part 2: C) pre-registered event-gap/risk-regime filter;
        D) pre-registered profit-protection rule.
        B) hypothetical short variant is produced by historical_backtest.py.

Rules are FIXED a priori (not tuned on the sample):
  C: LONG fill is BLOCKED when, on the fill session,
     (a) |stock daily return| >= 8% on fill day or any of the prior 5
         sessions (post-event/gap regime), OR
     (b) SPY close < its trailing 20-session SMA (risk-off tape).
  D: profit protection = sell 50% at first close >= +8% over entry
     (next open), remaining half trails close_below at
     max(original stop, running peak close - 8pp) -> next open.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import historical_backtest as hb

EV = Path("/home/udi/udi_provate/TradingAgents/evaluations/alpha_rnd_v1")
OUT = Path(__file__).parent / "results"

# ----- Track A: verified actual ledger (trigger_events + ledger, deduped) --
TRACK_A = [
    # ticker, entry_date, entry_px, shares, [(exit_date, exit_px, shares, why)]
    ("PBF", "2026-10-02", 80.0, 62, []),
    ("ACN", "2026-10-02", 205.0, 24,
     [("2026-10-07", 195.23, 24, "close_below_194 next open")]),
    ("APPS", "2026-10-02", 11.30, 442,
     [("2026-10-07", 10.302, 442, "gap-through open < stop 10.42")]),
    ("PGEN", "2026-10-05", 8.20, 609,
     [("2026-10-06", 7.79, 609, "corrective exit, missed hard stop")]),
    ("SDGR", "2026-10-06", 31.00, 161,
     [("2026-10-07", 27.81, 100, "mgmt review sell ~100"),
      ("2026-10-13", 25.69, 61, "mgmt tightened stop")]),
    ("TWST", "2026-10-06", 209.55, 11,
     [("2026-10-07", 158.26, 4, "mgmt review sell ~4"),
      ("2026-10-12", 159.74, 7, "mgmt hard exit <164")]),
]
PBF_MARK_1023 = 76.17


def pnl_long(entry, exit_, sh):
    return round(sh * exit_ * (1 - hb.COST_BPS) - sh * entry * (1 + hb.COST_BPS), 2)


def track_a():
    rows, realized = [], 0.0
    for t, ed, px, sh, exits in TRACK_A:
        cost = sh * px * (1 + hb.COST_BPS)
        pnl = 0.0
        for xd, xp, xs, why in exits:
            pnl += xs * xp * (1 - hb.COST_BPS) - cost * (xs / sh)
        open_sh = sh - sum(x[2] for x in exits)
        unreal = pnl_long(px, PBF_MARK_1023, open_sh) if open_sh else 0.0
        rows.append({"ticker": t, "entry": f"{ed}@{px}", "shares": sh,
                     "exits": exits, "realized": round(pnl, 2),
                     "open_shares": open_sh, "unrealized": round(unreal, 2)})
        realized += pnl + unreal
    return rows, round(realized, 2)


def spy_pair(df_spy, entry_date, exit_date):
    b = {str(x.date()): r for x, r in df_spy.iterrows()}
    e, x = float(b[entry_date]["Close"]), float(b[exit_date]["Close"])
    return e, x


def experiment_c(trades, bars, spy):
    """Regime filter applied to each recorded fill."""
    spy_close = spy["Close"]
    spy_sma20 = spy_close.rolling(20).mean()
    spy_by = {str(x.date()): (float(spy_close.loc[x]),
                              float(spy_sma20.loc[x]))
              for x in spy.index}
    out = []
    for tr in trades:
        t, fd = tr["ticker"], tr["entry_date"]
        df = bars[t]
        idx = [str(x.date()) for x in df.index]
        i = idx.index(fd)
        window = df.iloc[max(0, i - 5):i + 1]["Close"].pct_change().abs()
        event_gap = bool((window >= 0.08).any())
        sc, sma = spy_by.get(fd, (None, None))
        spy_risk_off = bool(sc is not None and sc < sma)
        blocked = event_gap or spy_risk_off
        out.append({**tr, "event_gap": event_gap, "spy_risk_off": spy_risk_off,
                    "blocked": blocked})
    kept = [t for t in out if not t["blocked"]]
    blocked = [t for t in out if t["blocked"]]
    return {"kept": kept, "blocked": blocked,
            "pnl_delta_avoided": round(-sum(t["pnl"] for t in blocked), 2)}


def experiment_d(trades, bars):
    """Profit protection: trim half at first close >= +8%, trail rest at
    peak_close - 8pp (close_below -> next open); original stop floor kept."""
    out = []
    for tr in trades:
        if tr["direction"] != "LONG":
            continue
        t, fd, fill, stop = tr["ticker"], tr["entry_date"], \
            float(tr["entry_px"]), tr["stop"]
        df = bars[t]
        days = [x for x in df.index if str(x.date()) >= fd]
        peak = fill
        sh = tr["shares"]
        legs, state = [], "OPEN"
        for x in days:
            b = df.loc[x]
            s = str(x.date())
            c, o = float(b["Close"]), float(b["Open"])
            if state == "OPEN":
                if c <= stop:
                    nxt = days[list(days).index(x) + 1] if list(days).index(x) + 1 < len(days) else None
                    xp = float(df.loc[nxt]["Open"]) if nxt is not None else c
                    legs.append((sh, xp, "stop_next_open")); state = "DONE"; break
                if c >= fill * 1.08:
                    nxt_i = list(days).index(x) + 1
                    nxt = days[nxt_i] if nxt_i < len(days) else None
                    xp = float(df.loc[nxt]["Open"]) if nxt is not None else c
                    half = sh // 2 or 1
                    legs.append((half, xp, "trim_+8pct"))
                    sh -= half
                    state = "TRAIL"
            else:  # TRAIL
                peak = max(peak, c)
                trail = max(stop, peak * 0.92)
                if c <= trail:
                    nxt_i = list(days).index(x) + 1
                    nxt = days[nxt_i] if nxt_i < len(days) else None
                    xp = float(df.loc[nxt]["Open"]) if nxt is not None else c
                    legs.append((sh, xp, "trail_exit")); state = "DONE"; break
        if state != "DONE":
            last = df.loc[days[-1]]; xp = float(last["Close"])
            legs.append((sh, xp, "mark_end_of_data"))
        pnl = sum(s_ * xp * (1 - hb.COST_BPS) - s_ * fill * (1 + hb.COST_BPS)
                  for s_, xp, _ in legs)
        out.append({**tr, "expD_legs": legs, "expD_pnl": round(pnl, 2),
                    "orig_pnl": tr["pnl"],
                    "delta": round(pnl - tr["pnl"], 2)})
    return out


def sensitivity(trades, bars):
    """Re-price each trade under variant cost/stop assumptions.

    V1 base: 10bps/side, intraday stop fills at level (gap: open).
    V2: 25bps/side (heavy slippage+fees).
    V3: worst-case stop fills — every stop exits at min(stop, that session's
        open) for longs / max(stop, open) for shorts.
    V4: V2+V3 combined.
    """
    out = {}
    for v in ("V1_base", "V2_25bps", "V3_worst_stop", "V4_both"):
        tot = 0.0
        for tr in trades:
            c = 0.0025 if v in ("V2_25bps", "V4_both") else 0.001
            xp = tr["exit_px"]
            if v in ("V3_worst_stop", "V4_both") and "stop" in tr["exit_reason"]:
                b = bars[tr["ticker"]]
                row = b[b.index.strftime("%Y-%m-%d") == tr["exit_date"]]
                if len(row):
                    o = float(row["Open"].iloc[0])
                    xp = min(tr["stop"], o) if tr["direction"] == "LONG" \
                        else max(tr["stop"], o)
            sh = tr["shares"]
            if tr["direction"] == "LONG":
                pnl = sh * xp * (1 - c) - sh * tr["entry_px"] * (1 + c)
            else:
                pnl = sh * tr["entry_px"] * (1 - c) - sh * xp * (1 + c) \
                    - tr.get("borrow_cost", 0)
            tot += pnl
        out[v] = round(tot, 2)
    return out


def per_session(trades):
    from collections import defaultdict
    agg = defaultdict(lambda: {"n": 0, "pnl": 0.0})
    for tr in trades:
        a = agg[tr["session"]]
        a["n"] += 1
        a["pnl"] += tr["pnl"]
    return {s: {"n": v["n"], "pnl": round(v["pnl"], 2)}
            for s, v in sorted(agg.items())}


def main():
    res = json.loads((OUT / "backtest_results.json").read_text())
    trades = res["trades"]

    # price bars for traded tickers
    tickers = {t["ticker"] for t in trades} | {t for t, *_ in TRACK_A} | {"SPY"}
    bars = hb.fetch_bars(list(tickers), "2026-10-24")
    spy = bars["SPY"]

    # ---- Part 1: reconcile ledger ----
    rows, tot = track_a()
    print("== TRACK A reconciliation ==")
    for r in rows:
        print(r)
    print("realized+unrealized:", tot,
          "| ledger NAV check: 97621.55 vs 100000 =>", round(tot, 2))

    # ---- exposure-matched SPY benchmark per actual trade ----
    print("\n== per-trade SPY benchmark (same $, same dates) ==")
    tot_delta = 0.0
    for t, ed, px, sh, exits in TRACK_A:
        xd = exits[-1][0] if exits else "2026-10-23"
        xp = exits[-1][1] if exits else PBF_MARK_1023
        se, sx = spy_pair(spy, ed, xd)
        notional = sh * px
        strat = (xp / px - 1) * notional
        spy_pnl = (sx / se - 1) * notional
        tot_delta += strat - spy_pnl
        print(f"{t:5s} ${notional:8.0f} {ed}->{xd} "
              f"strat {strat:+8.1f} spy {spy_pnl:+8.1f} delta {strat-spy_pnl:+8.1f}")
    print("total delta vs SPY:", round(tot_delta, 2))

    # ---- Experiment C ----
    c = experiment_c([t for t in trades if t["direction"] == "LONG"], bars, spy)
    print("\n== EXP C: regime filter on all simulated LONG fills ==")
    for t in c["blocked"]:
        print("BLOCKED", t["ticker"], t["entry_date"], t["pnl"],
              "gap" if t["event_gap"] else "", "spy_off" if t["spy_risk_off"] else "")
    print("blocked:", len(c["blocked"]), "losses avoided:",
          c["pnl_delta_avoided"])

    # ---- Experiment D ----
    d = experiment_d(trades, bars)
    print("\n== EXP D: profit protection vs original ==")
    for t in d:
        print(f"{t['ticker']:5s} orig {t['orig_pnl']:+9.2f} "
              f"prot {t['expD_pnl']:+9.2f} delta {t['delta']:+9.2f} legs={t['expD_legs']}")
    print("sum delta:", round(sum(t['delta'] for t in d), 2))

    # ---- sensitivity + per-session (same-sample disclosure) ----
    longs = [t for t in trades if t["direction"] == "LONG"]
    shorts = [t for t in trades if t["direction"] == "SHORT"]
    print("\n== SENSITIVITY ==")
    print("LONG :", sensitivity(longs, bars))
    print("SHORT:", sensitivity(shorts, bars))
    print("\n== PER-SESSION P&L (decision session) ==")
    for s, v in per_session(trades).items():
        print(s, v)

    json.dump({"track_a": rows, "track_a_total": tot,
               "spy_benchmark_delta": round(tot_delta, 2),
               "exp_c": {"blocked": [{k: t[k] for k in
                          ("ticker", "entry_date", "pnl", "event_gap",
                           "spy_risk_off")} for t in c["blocked"]],
                         "kept": [{k: t[k] for k in
                          ("ticker", "entry_date", "pnl")} for t in c["kept"]],
                         "losses_avoided": c["pnl_delta_avoided"]},
               "exp_d": [{k: t[k] for k in ("ticker", "orig_pnl", "expD_pnl",
                                            "delta", "expD_legs")}
                         for t in d],
               "sensitivity": {"LONG": sensitivity(longs, bars),
                               "SHORT": sensitivity(shorts, bars)},
               "per_session": per_session(trades)},
              open(OUT / "experiments.json", "w"), indent=1)


if __name__ == "__main__":
    main()
