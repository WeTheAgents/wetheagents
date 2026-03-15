# Session 5 Status Report (Feb 15, 2026)

> Focus: Retrosheet integration to get **honest pitcher stats** and build a **Retrosheet master games table** with bookmaker odds merged at scale (≥99% match rate).

---

## 1. What was done

### 1.1 Retrosheet pitcher pipeline (no play-by-play, no zip extraction)

Implemented a full pipeline:
**Retrosheet `YYYYcsvs.zip` → `starter_game_logs` → entering-game pitcher features → `game_id_bridge`**

Key points:
- Reads `YYYYpitching.csv` + `YYYYgameinfo.csv` directly from `YYYYcsvs.zip` using `ZipFile` (no unpacking).
- Starter selection: `p_seq == 1` (first pitcher used for team in game).
- Entering-game rolling features computed with strict anti-leakage (`shift(1)` before expanding/rolling).
- Doubleheader ordering handled via `game_num` (from `gameinfo.number`) in sort key: `pitcher_id, date, game_num`.

**Artifacts produced** (already built):
- `data/processed/pitchers/starter_game_logs.parquet` (2 rows per game, home+away starters)
- `data/processed/pitchers/starter_entering_features.parquet` (ENTERING-game metrics, short=5/long=15)
- `data/processed/pitchers/game_id_bridge.parquet` (1 row per game, home/away starter ids + flags)
- `data/processed/pitchers/build_report.md` (coverage + validations)

**Rebuild command:**
```bash
python scripts/build_retrosheet_pitchers.py --start 2010 --end 2025 --out data/processed/pitchers
```

### 1.2 Bullpen / opener heuristics

Added additional game-level flags computed from full pitcher usage within a game:
- `is_bullpen_no_starter` per (gid, team): if **no pitcher** reaches ≥4.0 IP (default `max_outs < 12`).
- `is_opener_game`: short starter (≤2.0 IP) + different bulk pitcher + still has a “bulk” arm in game.

These are **heuristics** (useful as risk flags / model features), not ground-truth labels.

### 1.3 Merge Retrosheet pitchers into our dataset

Added `merge_retrosheet_pitchers()` to `src/data_loader.py`:
- Merges `game_id_bridge.parquet` onto our game-level dataset by `date + home_team + away_team` (with team-code mapping).
- Adds:
  - `home_starter_id`, `away_starter_id`
  - `home_is_bullpen_no_starter`, `away_is_bullpen_no_starter`
  - `home_is_opener_game`, `away_is_opener_game`
- Updates `is_bullpen_game` to True if either side has `*_is_bullpen_no_starter`.

### 1.4 K/BB smoothing change

Updated entering-game K/BB calculation to use smoothing:
\[
\text{kbb} = \frac{SO + 1}{BB + 1}
\]
This avoids infinities and reduces small-sample spikes.

---

## 2. Retrosheet master games + odds merge (≥99%)

### 2.1 Retrosheet game master from gamelogs (GL)

Implemented `src/retrosheet_games.py` to build a game-level master table from:
- `retrosheets/gl2010_19.zip` (gl2010..gl2019)
- `retrosheets/gl2020_25.zip` (gl2020..gl2025)

Provides:
- `gid` (HOME + YYYYMMDD + game_num)
- `date`, `season`, `game_num`
- `home_team`, `away_team`
- `home_final`, `away_final`, `home_win`
- inning runs `home_inn_1..9`, `away_inn_1..9` (from linescore strings)
- `is_extra_innings`

Also added helper `drop_doubleheaders()` for consistency with our existing hard filter (remove same-date same-matchup duplicates).

### 2.2 Merge bookmaker odds onto Retrosheet master

Created `scripts/build_retrosheet_master_with_odds.py` which:
- Builds Retrosheet master table from gamelogs
- Loads our sports-statistics xlsx dataset via `load_all_seasons()` + `apply_data_filters()` + `add_derived_odds()`
- Normalizes team codes to Retrosheet codes (critical mapping)
- **Default: uses regular season only** (`date.month < 10`) because Retrosheet GL typically excludes postseason
- Joins odds onto Retrosheet games at scale
- Produces an explicit match report with unmatched samples and “swap home/away” diagnostics

Outputs:
- `data/processed/retrosheet/retrosheet_master_games.parquet`
- `data/processed/retrosheet/retrosheet_master_games_with_odds.parquet`
- `data/processed/retrosheet/match_report.md`

**Result (regular season only, seasons 2010-2019 + 2021):**
- Match rate: **99.91%** (25,780 / 25,802)

Remaining unmatched cases are mostly explained by **home/away swaps** or rare data issues in the sports-statistics source; the report highlights “matchable by swapping” games but does not auto-fix them.

### 2.3 Team-code mapping fix

Extended `_map_team_code_to_retrosheet()` in `src/data_loader.py` to handle sports-statistics codes such as:
`LOS/CUB/SDG/SFO/KAN/TAM` → `LAN/CHN/SDN/SFN/KCA/TBA` etc.

This change is what raised the initial ~64% match rate to ~99%+.

### 2.4 Loader convenience

Added `load_retrosheet_master_games(with_odds=True, seasons=...)` in `src/data_loader.py` to read the processed Retrosheet parquet tables.

---

## 3. Validation summary

From `data/processed/pitchers/build_report.md`:
- Seasons 2010–2025: **100%** games with 2 starters (by `p_seq==1`)
- Total games: 37,975 (2010–2025, includes 2020 shortened season)
- Starter rows: 75,950
- Duplicate (gid, team) starters: 0
- Null pitcher ids: 0

---

## 4. Key takeaways

1. **We can get high-quality pitcher game logs without play-by-play** using Retrosheet `pitching.csv`.
2. Entering-game pitcher features are now **honest** (anti-leak) and reproducible.
3. Retrosheet can act as **source-of-truth** for game outcomes and inning lines, while we keep odds from the existing dataset.
4. Odds→Retrosheet merge is now effectively solved (**99.9% match rate**) for regular season.

---

## 5. Next steps (queued for next session)

1. Decide policy for the ~22 unmatched regular-season games (drop vs. manual fixes vs. safe auto-fix when swap-candidate is unambiguous).
2. Merge the new Retrosheet entering-game pitcher features into CatBoost experiment for series dogon and proceed with model training/validation.
3. Optionally expand Retrosheet master for additional seasons/markets as needed.

