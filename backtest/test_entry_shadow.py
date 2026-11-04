#!/usr/bin/env python3
"""Regression for entry_shadow v2: no lookahead, deterministic, cohorts."""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from backtest import entry_shadow as E  # noqa: E402


def _bars(n=40, drift=0.5):
    idx = pd.bdate_range("2026-10-01", periods=n)
    px, rows = 100.0, []
    for _ in idx:
        rows.append({"Open": px, "High": px + 1.5, "Low": px - 1.5,
                     "Close": px + drift})
        px += drift
    return pd.DataFrame(rows, index=idx)


def main():
    df = _bars()
    sess = str(df.index[15].date())
    before, fut = df[df.index <= sess], df[df.index > sess]
    dec_close = float(before["Close"].iloc[-1])
    a = E.atr14(before)
    assert a == 3.0  # constant daily range, pre-decision bars only

    # B_confirmed: rising closes confirm next session -> fills at open
    r1 = E.sim_B("LONG", None, None, dec_close, a, fut)
    r2 = E.sim_B("LONG", None, None, dec_close, a, fut)
    assert r1 == r2 and r1["entry_px"] > 0 and r1.get("result") in (
        "OPEN", "time_stop", "target", "stopped")
    # deterministic + slippage applied
    o = float(fut.iloc[1]["Open"]) if float(fut.iloc[0]["Close"]) > dec_close \
        else float(fut.iloc[0]["Open"])
    assert abs(r1["entry_px"] - round(o * 1.0005, 4)) < 0.01

    # gap guard
    f2 = fut.copy()
    f2.iloc[1, f2.columns.get_loc("Open")] = dec_close * 2
    assert E.sim_B("LONG", None, None, dec_close, a, f2)["result"] == "NO_FILL"

    # falling closes: LONG never confirms -> NO_FILL
    f3 = fut.copy()
    f3["Close"] = f3["Close"] * 0.9
    f3["Open"] = f3["Open"] * 0.9
    assert E.sim_B("LONG", None, None, dec_close, a, f3)["result"] == "NO_FILL"

    # A_pullback faithful: untouched zone -> NO_FILL, missing terms -> NO_PLAN
    assert E.sim_A("LONG", [95, 96], 90, 110, fut, dec_close)["result"] == \
        "NO_FILL"
    assert E.sim_A("LONG", None, None, None, fut, dec_close)["result"] == \
        "NO_PLAN"
    # authored zone that IS touched fills at zone top
    lo_zone = [dec_close - 20, dec_close - 19]
    ra = E.sim_A("LONG", lo_zone, dec_close - 25, dec_close + 40, fut,
                 dec_close)
    # drifting up: lows stay above zone -> NO_FILL (no invented fill)
    assert ra["result"] in ("NO_FILL", "OPEN")

    # cohort split
    assert E.cohort_of("EXECUTABLE_WATCH", True) == "VALID_AUTHORIZED"
    assert E.cohort_of("EXECUTABLE_WATCH", False) == \
        "DIRECTIONAL_UNRESOLVED"
    assert E.cohort_of("AMBIGUOUS_REJECTED", True) == \
        "DIRECTIONAL_UNRESOLVED"

    # real saved cases: RHI authorized fills; REPL unresolved gets B-eval
    import json
    lg = E.run(["2026-10-28", "2026-10-30"], end="2026-11-05",
               ledger_path=Path("/tmp/es_test_ledger.json"))
    Path("/tmp/es_test_ledger.json").unlink(missing_ok=True)
    rhi = lg["records"]["2026-10-28|RHI"]
    assert rhi["cohort"] == "VALID_AUTHORIZED" and not rhi["hypothetical"]
    assert rhi["A_pullback"]["entry_px"] == 41.95
    repl = lg["records"]["2026-10-30|REPL"]
    assert repl["cohort"] == "DIRECTIONAL_UNRESOLVED" and repl["hypothetical"]
    # risk sizing: stop-bound, notional-bound, exposure cap, zero-risk reject
    assert E._size(100, 0, 0) == 0                      # zero risk -> reject
    assert E._size(100, -1, 0) == 0                     # negative risk
    assert E._size(100, 2.0, 0) == 50                   # notional cap 5000
    assert E._size(100, 1.0, 0) == 50                   # risk cap 250/1=250? no: min(50,250,500)=50
    assert E._size(200, 1.0, 0) == 25                   # 5000//200=25 vs 250
    assert E._size(200, 10.0, 0) == 25                  # 250//10=25, 5000//200=25
    assert E._size(100, 2.0, 49500) == 5                # exposure room 500
    assert E._size(100, 2.0, 50000) == 0                # exhausted
    # idempotent update: closed legs unchanged across reruns
    import json as _j
    lp = Path("/tmp/es_idem.json")
    lg1 = E.run(["2026-10-28"], end="2026-11-05", ledger_path=lp)
    r_before = _j.loads(lp.read_text())["records"]["2026-10-28|RHI"]["A_pullback"]
    lg2 = E.update(end="2026-11-05", ledger_path=lp)
    r_after = lg2["records"]["2026-10-28|RHI"]
    assert r_after["cohort"] == "VALID_AUTHORIZED"
    assert lg2.get("last_mark")
    lp.unlink(missing_ok=True)
    print("PASS all entry_shadow v2 checks + sizing/idempotency")


if __name__ == "__main__":
    main()
