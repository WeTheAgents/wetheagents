# Codex Daily Runbook — weather_kalshi

Purpose: keep the data pipeline and the paper-trading loop healthy. ~5 minutes/day.
Run everything from `domains/weather_kalshi`. All commands are local/public reads —
no API keys, no wallets, no real orders.

## Daily (once, any time after 09:30 local)

```bash
# 1. Collect markets + candle history (gap-filling, idempotent)
python -m scripts.collect_all_cities  >> logs/history/history_run_$(date +%F).log 2>&1

# 2. Rebuild the ML panel
python -m scripts.build_ml_panel      >> logs/history/ml_panel_build_$(date +%F).log 2>&1

# 3. Paper-trading loop health (Windows task `dayof-paper-trade` runs every 15 min on its own)
tail -3 logs/paper_dayof.log          # last entry must be < 20 min old
schtasks /query /tn dayof-paper-trade # Status: Ready, Last Result: 0

# 4. Refresh the paper report
python -m scripts.build_paper_report  # -> reports/paper_trading_report.html
```

Success criteria: step 1 prints "Collection complete"; step 3 shows a recent run
and `Last Result: 0`; step 4 writes the report without errors.

## If something fails

- Log the error into `logs/history/` and report it in the daily summary —
  do NOT retry destructively, do NOT edit or delete anything under `data/paper/`
  (that is the paper-trade ledger; the runner owns it).
- If the scheduled task is missing or stale, re-register it (PowerShell, note the
  battery flags — the laptop runs on battery and the default is AC-only):

```powershell
$action  = New-ScheduledTaskAction -Execute "C:\Users\peach\AppData\Local\Programs\Python\Python313\python.exe" -Argument "-m scripts.paper_dayof --trade --settle" -WorkingDirectory "D:\GitHub\wetheagents\domains\weather_kalshi"
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 15)
$set     = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 10) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName "dayof-paper-trade" -Action $action -Trigger $trigger -Settings $set
```

## Rules

- **All logs go to `logs/history/`** (gitignored). Never write `*.log` into the
  domain root — it is ignored now, but keep the tree clean anyway.
- `data/static/scalp_hours.json` (per-city entry hours + flag rates) is
  auto-retuned by the runner when older than 30 days. Manual retune:
  `python -m scripts.paper_dayof --retune`. Do not edit it by hand.
- The runner windows: strategy A at each city's `h50` local hour (clean days) or
  17:00 (flagged days); strategy B at 16:30. Details:
  `oled/changes/scalp-v2-runner/spec.md`.
- Paper execution is passive-only from 2026-07-04: rows place a virtual
  `$24` bid ladder (`$10/$8/$6`) and every scheduled cycle appends post-signal
  observations to `data/paper/paper_order_snapshots.jsonl` until settlement.
- gamma-api.polymarket.com needs VPN (DNS-blocked) — the daily flow does NOT use it.

## Order-book statistics for wings research (ML stage 0)

Slow-horizon depth data is the chronic blocker of every past study (sessions
8–11: signals existed, executability could not be proven). Keep book statistics
flowing daily; the ML cheap-wings pipeline (v2: intl / T-1) consumes them.

**What to run** (existing sweep, no new code):

```bash
# One book sweep of today's key brackets across all cities (~2 min, no VPN needed)
python -m scripts.paper_dayof --sweep   >> logs/history/book_sweep_$(date +%F).log 2>&1
```

Writes `data/paper/book_sweeps.parquet` (append): one row per (city, **bracket**)
— since 2026-07-07 the sweep records **every** bracket, tagged `role` =
`curmax`/`above`/`favorite` for the key ones and `wing` for the rest (the cheap
wings are the ML pipeline's actual target). Each row has `best_bid/best_ask/
spread/mid`, full-side depth in shares, and $24-stake VWAP fill sims
(`yes24_avg`/`no24_avg`; `STAKE = sum(LADDER_STAKES) = 24`). ~11 book calls/city
now instead of 3. CLOB `/book` works without VPN.

**Cadence**: ~3×/day. The three triggers below fire at 09:00 / 14:30 / 21:00
**machine-local** time (scheduled-task triggers are always local — there is no
UTC option), spreading sweeps across intl morning, US morning and US afternoon.
Exact times are not critical; even coverage is. Either run manually in each
codex session, or register a dedicated task (battery flags mandatory, laptop
runs on battery):

```powershell
$action   = New-ScheduledTaskAction -Execute "C:\Users\peach\AppData\Local\Programs\Python\Python313\python.exe" -Argument "-m scripts.paper_dayof --sweep" -WorkingDirectory "D:\GitHub\wetheagents\domains\weather_kalshi"
$triggers = @(
  New-ScheduledTaskTrigger -Daily -At 09:00
  New-ScheduledTaskTrigger -Daily -At 14:30
  New-ScheduledTaskTrigger -Daily -At 21:00
)
$set      = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 15) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName "book-sweeps" -Action $action -Trigger $triggers -Settings $set
```

**⚠ Remaining coverage gap (operator decision pending):**

- The sweep still covers **today (T-0) only** — `run_sweep` builds `md` from
  `now_local.date()`. There is **no T-1/T-2 book collection**, although tomorrow's
  markets exist in `all_cities_markets.parquet` (`clob_token_id_yes` is there).
  Slow-horizon executability stays unprovable until this exists. (The
  all-brackets gap was closed 2026-07-07.)

## NBM day-of archive (repaired 2026-07-07)

The historical day-of NBM percentiles in `data/raw/snapshots/` are **wrong** (two
GRIB bugs in `src/nbm_client.py`, now fixed: the instantaneous TMP field was read
instead of the windowed MaxT, and the Lambert grid was point-looked-up as regular
lat/lon → offshore). Day-of `nbm_median` was ~16.5F off realized; now ~1.7F.

- **Do not** use `snapshot_*.parquet` `nbm_*` columns for day-of ML — use the
  clean rebuild `data/raw/nbm_backfill/nbm_dayof.parquet`.
- Rebuild / extend (idempotent, needs cfgrib → `uv run`):
  ```bash
  uv run python -m scripts.backfill_nbm_dayof --data-root <main-checkout>/data
  ```
- Going forward the live `daily_snapshot` NBM is fixed too, **but** run it at or
  after **13:45 UTC** so today's 12Z cycle is published (earlier runs fall back
  to an older cycle — still correct now, just staler).

## Weekly (Mondays)

- Skim `reports/paper_trading_report.html`: P&L section and run-health gaps.
- Sanity: `python -m pytest tests/ -q` (all green, ~2s).
