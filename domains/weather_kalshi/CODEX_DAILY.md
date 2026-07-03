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
- gamma-api.polymarket.com needs VPN (DNS-blocked) — the daily flow does NOT use it.

## Weekly (Mondays)

- Skim `reports/paper_trading_report.html`: P&L section and run-health gaps.
- Sanity: `python -m pytest tests/ -q` (all green, ~2s).
