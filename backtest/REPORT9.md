# Corrected multi-year baseline (causal timing)

Source: `backtest/results/orig_corrected.json` — ORIG rules on the cached
1,824-ticker eligible universe, with the next-bar signal→fill fix
(`i > arm_day`). All other assumptions frozen: $100k/$5k/10-slot,
10bps/side, 2·ATR stop, close_below→next open, 60-session cap,
alphabetical admission, elig gates per entry date.

## Old vs corrected (alphabetical ORIG)

| Period | Old NAV% | Corrected NAV% | Old P&L | Corrected P&L | Admitted | PF | Max DD | SPY |
|---|---|---|---|---|---|---|---|---|
| 2024 | +5.83 | **+11.14** | +6,220 | +10,831 | 77 | 1.63 | 11.3k | +25.59% |
| 2025 | +10.68 | **-8.28** | +11,583 | -8,470 | 89 | 0.72 | 19.7k | +18.01% |
| 2026YTD | +20.94 | **+26.95** | +20,891 | +26,917 | 57 | 3.00 | 8.2k | +13.17% |

NAV reconciliation: end−start ≈ net_pnl + open marks (e.g., 2024:
+11,143 NAV delta vs +10,831 trade P&L ≈ $312 open marks); no hidden fees
— 10bps/side already inside each leg.

## Superseded artifacts

- `results/universe_pt.json` NAVs (+5.83/+10.68/+20.94%) — same-day fills.
- `results/admission_sensitivity.json` — all seed/alpha returns share the
  bug; the *conclusion* (±9-17pp ordering swings, no robust edge) is
  qualitatively unaffected but the numbers are stale.
- REPORT5/REPORT6 multi-year tables — superseded by this report.
- REPORT7 smoke-test positives (+2.4–3.4%) — superseded by REPORT8's
  corrected smoke test (all priorities negative in Oct).
- NOT superseded: survivorship-bias disclosure, the ordering-sensitivity
  mechanism finding, C12/ledger audits, the shadow design itself.

## Verdict on corrected baseline

Mixed: +11.1 / **-8.3** / +27.0% vs SPY +25.6/+18.0/+13.2% — still lags in
2024/2025, still leads 2026YTD. The same-day-fill bug did not rescue the
strategy; it reshuffled which period it won. Survivorship bias remains.
