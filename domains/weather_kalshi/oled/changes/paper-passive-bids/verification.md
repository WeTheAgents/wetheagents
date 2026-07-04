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

Result: `26 passed in 0.88s` after the final report text cleanup.

## Notes

- Did not run a live `--trade --settle` smoke in the new worktree, to avoid creating a parallel paper ledger outside the production scheduled task.
- Historical market-taker rows remain settlement-compatible because settlement still reads `fill_shares` and `fill_stake`.
- New passive rows append post-signal observations to `data/paper/paper_order_snapshots.jsonl`, which is under gitignored `data/paper/`.
