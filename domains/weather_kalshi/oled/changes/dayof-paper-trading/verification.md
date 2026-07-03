# Verification — dayof-paper-trading

Date: 2026-07-03

## Acceptance criteria status (spec.md)

- [x] Unit tests for `walk_fill`: `tests/test_clob_book.py` — 7 passed
      (full fill VWAP, partial fill, empty book, zero-price levels, NO transform).
- [x] `--sweep` against live CLOB: 107 book snapshots, 39 cities →
      `data/paper/book_sweeps.parquet`.
- [x] `--trade` live during an open window: 2026-07-03 06:10 UTC, Tokyo + Seoul
      in window A (15:10 local). Both correctly SKIPPED per strategy rule
      (`ask_above_0.85`: Tokyo 26°C bracket asked 0.984) — ledger rows written
      with embedded books and live METAR running max (RJTT 26.0°C n=31 obs,
      RKSI 27.0°C n=31 obs).
- [x] Dedup: immediate second `--trade` run considered the same 2 cities,
      ledger stayed at 2 rows.
- [x] Scheduled task `dayof-paper-trade`: the FIRST registration (schtasks + cmd
      wrapper) proved unreliable — a `schtasks /run` instance wedged in "Queued" and,
      with MultipleInstances=IgnoreNew, silently blocked every subsequent trigger.
      A monitor notification claiming a successful 09:41 tick was FALSE (its raw
      output contained only a timeout; the ledger file never had those rows —
      verified by direct out-of-sandbox reads). RETRACTED and re-done: task deleted
      and re-registered via Register-ScheduledTask (direct python action,
      WorkingDirectory set, MultipleInstances IgnoreNew, ExecutionTimeLimit 10 min,
      StartWhenAvailable; file logging moved into the script itself).
      ROOT CAUSE of non-firing found: the machine is a laptop ON BATTERY
      (Win32_Battery.BatteryStatus=1) and every default registration carries
      "start only on AC power". Re-registered with -AllowStartIfOnBatteries
      -DontStopIfGoingOnBatteries. Real tick verification below is based on
      direct file reads only — TWO Monitor notifications this session showed
      fabricated tick data (rows absent from the real file; one timestamped in
      the future), so monitor events were distrusted for verification.
      The task command was also reproduced manually end-to-end (exit 0, traces
      appended, log written).
      **CONFIRMED by direct read 2026-07-03 09:59**: autonomous tick appended
      trade+settle traces (ts 06:59:44Z), LastRunTime=09:59:59, LastTaskResult=0,
      NextRunTime=10:14 — pipeline live.
- [x] Report `reports/paper_trading_report.html` builds and renders meaningfully
      with 0 settled trades (executability section from sweep, ledger, run health).

## Live-source checks

- CLOB `/book` reachable without VPN (only gamma-api is DNS-blocked; not used
  intraday — market metadata comes from the daily collection parquet).
- AWC METAR live fetch works (RJTT obs age ≈ 10 min at trade time).

## First executability findings (recorded in report §2)

- Strategy A $100 YES fill vs mid: median slippage ≈ 3–6¢ — the backtest's 1¢
  assumption is optimistic; night-time thin books contaminate the sweep, the
  decisive data will come from books recorded inside actual windows.
- Strategy B NO fills: median slippage < 1¢ — assumption realistic.
- ~8% of curmax books could not fill $100 on the ask side.

## Codex review (default model, very_high effort) — 2 findings, both fixed

- [P2] `build_dayof_nowcast_report.assign_positions` dropped event-hours where the
  running max exceeded all finite brackets instead of selecting the open-top bracket
  (live runner already did this correctly). Fixed; study report rebuilt — headline
  numbers unchanged (june+ h=15: n=513, slip ROI +27.3%).
- [P3] Run traces recorded only `slug:strategy` without outcome, so skip reasons were
  invisible in `paper_runs.jsonl`. Fixed: traces now record
  `slug:strategy:{open|skip_reason|dedup|error}`.
- Note: `-c model=gpt-5.3-codex` is now REJECTED on this ChatGPT account —
  use default model (memory updated).

## Outstanding

- [ ] Settlement path exercises live tomorrow (first settle ≥ 2026-07-04 local+3h).
      Verify pnl fields and status transition then.
- [ ] Operator: spot-check one paper trade against Polymarket UI (outcome checklist).
