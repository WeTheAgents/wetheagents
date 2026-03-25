# Claude Code Instructions -- football-betting

## Project Overview

Football (soccer) betting backtest system. Goal: validate Squad Stability Score (SSS) as a predictive signal for mid-tier league betting, starting with Turkish Super Lig.

**Core hypothesis**: bookmakers price mid-tier leagues with less accuracy than top leagues. Official lineups published ~60min before kickoff create an information asymmetry. Teams fielding weakened squads (rotation, youth, reserves) underperform their implied odds.

**Phase 0 (current)**: Signal validation only. No ML model, no betting simulation. Just: "does weighted SSS correlate with outcome deviation from odds?"

## Data

- **Odds**: football-data.co.uk per-season CSVs (T1_SSSS.csv) — Pinnacle closing + market average
- **Lineups + stats**: transfermarkt-datasets — starting XI, minutes, goals, assists
- **Seasons**: 2021, 2022, 2023 (Turkish Super Lig runs August-May, European calendar)
- **Join**: canonicalized team codes via club_id (transfermarkt) and team name (odds)
- **Coverage**: 1073 matches, 100% lineup coverage, 97% exact join rate
- **Download**: `python data/download_odds.py` + `python data/download_transfermarkt.py`

## Key Metric: Weighted Squad Stability Score

```
impact_i = max(player_minutes/team_minutes,
               player_goals/team_goals,
               player_assists/team_assists)
SSS_w = Σ(impact_i × MinPct_i) / Σ(impact_i)   for i in starting XI
```

Minutes-share is always included as baseline (so defenders with 0 goals/assists still have impact).
Two variants: cumulative (season-to-date) and rolling-10.

## Running

```bash
# Download data
python data/download_odds.py
python data/download_transfermarkt.py

# Signal test (Phase 0 deliverable)
python scripts/run_sss_signal_test.py
```

## Key Filters

- Three outcomes: H/D/A (not binary like MLB)
- Implied probabilities: vig-removed via `p_fair = (1/odds) / sum(1/all_odds)`
- Mean overround: 3.2% (tight Pinnacle odds)
- All features computed using ONLY data before the current match (no leakage)

## Architecture

- `src/data_loader.py` — load odds + transfermarkt, join via club_id mapping, filter, derive implied probs
- `src/features.py` — weighted SSS computation (cumulative + rolling-10)
- `src/team_names.py` — canonical team name mapping (not used in current pipeline — team IDs used instead)
- `data/download_odds.py` — football-data.co.uk per-season CSV downloader
- `data/download_transfermarkt.py` — transfermarkt-datasets downloader (games, lineups, appearances)
- `scripts/run_sss_signal_test.py` — Phase 0 signal validation
