# Verification — scalp v2 runner

Date: 2026-07-03

## Acceptance (spec.md)

- [x] `--retune` from local data: 45 cities, ran in ~75s. Sanity: h50 histogram
      {12:6, 13:8, 14:11, 15:9, 16:10, 17:1}; Madrid h50=17 city_rate=0.741,
      Hong Kong 13/0.122, Tokyo 13/0.04 — matches study climatology.
      entropy_q75=1.696 (rolling window) vs 1.918 (full train) — seasonal drift
      already visible, which is exactly why rolling retune exists.
- [x] Unit tests: `tests/test_paper_dayof_v2.py` — window selection (h50 window,
      separate 17:00 window, Madrid h50==17 collapse, B window) + dedup exceptions
      (flagged_wait_17 / clean_not_17_window do not block; hard skips do).
      Full domain suite: 21 passed.
- [x] Live `--trade --settle` run executes cleanly (considered=0 at 08:29 UTC —
      correct: no city in any v2 window at that minute).
- [~] First real v2 window fires later today via the scheduled task (unchanged,
      picks up new code automatically); ledger rows will carry
      `variant`/`h_star`/`flag`/`flag_inputs`. Check `data/paper/paper_trades.jsonl`
      after the Asia/Europe afternoon.
- [x] Existing tests pass; scheduled task unchanged.

## Codex review — 2 findings (P2), both fixed

- Runner import crashed when invoked by file path (`python scripts/paper_dayof.py`)
  → sys.path bootstrap added; verified: file-path invocation now works.
- `test_clob_book.py` import shadowed by repo-root `src/` package under monorepo
  pytest → loaded by file path with sys.modules registration (dataclasses need it).
- Suite verified green from BOTH the domain dir and the repo root: 21 passed / 21 passed.

## Notes

- Auto-retune: config regenerates when older than 30 days (rolling 60-day window),
  inside the normal `--trade` run — no new scheduled task.
- Flag inputs are recorded per trade row, so flag quality is auditable from the
  ledger itself (compare `flag` vs eventual rise outcome at settlement).
