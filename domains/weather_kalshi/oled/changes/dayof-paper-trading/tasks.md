# Tasks — dayof-paper-trading

- [x] T1. `src/clob_book.py`: fetch_order_book + walk_fill + NO-side helper; unit tests
      in `tests/test_clob_book.py` (7 passed).
- [x] T2. `scripts/paper_dayof.py`: shared city/market/METAR loading, strategy window
      logic, `--trade` with dedup + JSONL ledger + run traces (traces include outcome
      per codex P3).
- [x] T3. `--settle` mode (price-history based, atomic ledger rewrite) — code path live
      check pending first settlement (2026-07-04).
- [x] T4. `--sweep` mode → `data/paper/book_sweeps.parquet` (107 snapshots, 39 cities).
- [x] T5. `scripts/build_paper_report.py` → `reports/paper_trading_report.html`.
- [x] T6. `dayof-paper-trade` schtasks job registered (every 15 min), visible in query.
- [x] T7. Live validation: sweep OK; `--trade` fired in Tokyo/Seoul window A
      (correct rule-based skips, books + METAR recorded); dedup verified.
- [x] T8. verification.md written; codex review 2 findings fixed (open-top brackets
      in study analysis, skip reasons in traces).
