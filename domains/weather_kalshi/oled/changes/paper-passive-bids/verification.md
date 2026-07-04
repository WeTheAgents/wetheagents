# Verification — paper-passive-bids

## Commands

```powershell
python -m pytest domains/weather_kalshi/tests/test_paper_dayof_v2.py domains/weather_kalshi/tests/test_clob_book.py -q
```

Result: `22 passed in 1.14s`.

```powershell
python -m scripts.build_paper_report
```

Result: report written to `domains/weather_kalshi/reports/paper_trading_report.html`.

```powershell
python -m py_compile scripts/paper_dayof.py scripts/build_paper_report.py src/clob_book.py
```

Result: pass.

```powershell
python -m pytest domains/weather_kalshi/tests -q
```

Result: `27 passed in 0.89s` after strict passive-only settlement/reporting.

## Notes

- Historical market-taker rows are ignored by active settlement/reporting; the live paper ledger was reset separately in `data/paper/`.
- New passive rows append post-signal observations to `data/paper/paper_order_snapshots.jsonl`, which is under gitignored `data/paper/`.
- Runtime reset on 2026-07-04: cleared `paper_trades.jsonl`, `paper_runs.jsonl`, `paper_order_snapshots.jsonl`, and removed old `book_sweeps.parquet`; manual scheduled run returned `Last Result: 0` and wrote only fresh empty `track/trade/settle` traces.
