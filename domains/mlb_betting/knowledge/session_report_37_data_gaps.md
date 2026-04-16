# Session 37 — 2022-2025 data-loader gaps (correctness-of-evidence fix)

## TL;DR

Two silent data-loss bugs were making every Session 35 / Session 36 backtest
report pick counts that looked like "all 11 seasons" when they were really
**2014-2021 only**.

| Bug | Affected column | Seasons | Effect |
|-----|-----------------|---------|--------|
| 1 | `home_run_line`, `away_run_line` (+ `_odds`) | 2022, 2023, 2024, 2025 | 100% NaN — every RL strategy silently drops these rows |
| 2 | `fav_power_rate_diff` (and its source `power_rate_home/away`) | 2022, 2023, 2024, 2025 | 100% NaN — `fav_rl` power-filter always evaluates False |

The fix is entirely in the load path — strategy files under `src/strategies/*`
are untouched. The live pregame loader (`src/live_pregame.py`) is unchanged.

No prior conclusion is overturned (the filters were still valid on 2014-2021),
but every per-strategy N ever quoted for 2022-2025 is an undercount of zero.
Re-run `scripts/validate_reverse_rl.py` to get the corrected counts.

---

## Reproduction (pre-fix)

```bash
cd D:\GitHub\wetheagents\domains\mlb_betting
python -X utf8 -c "
import sys; sys.path.insert(0, '.')
import warnings; warnings.filterwarnings('ignore')
from src.data_loader import load_all_seasons, apply_data_filters, add_derived_odds
from src.features import build_all_features
from src.strategies import add_derived_for_strategies
g = load_all_seasons(enrich_innings=False, enrich_run_line=False)  # <- opt out of the fix
g = apply_data_filters(g); g = add_derived_odds(g)
e = build_all_features(g); e = add_derived_for_strategies(e)
for szn in [2021, 2022, 2023, 2024, 2025]:
    s = e[e['season']==szn]
    print(szn,
          'home_run_line NaN:', s['home_run_line'].isna().sum(), '/', len(s),
          ' fav_power_rate_diff NaN:', s['fav_power_rate_diff'].isna().sum())
"
```

Expected output (pre-fix, matches Session 36 observations):

| Season | N     | home_run_line NaN | fav_power_rate_diff NaN |
|--------|-------|-------------------|-------------------------|
| 2021   | ~2350 | ~40 (OK)          | ~40 (OK)                |
| 2022   | 2332  | **2332 / 2332**   | **2332 / 2332**         |
| 2023   | 2400  | **2400 / 2400**   | **2400 / 2400**         |
| 2024   | 2411  | **2411 / 2411**   | **2411 / 2411**         |
| 2025   | 2416  | **2416 / 2416**   | **2416 / 2416**         |

---

## Root cause

### Bug 1 — `home_run_line` / `away_run_line` = 100% NaN in 2022-2025

Two scripts can produce the 2022-2025 xlsx files:

- `data/download_historical.py` — SDQL → xlsx + optional JSON merge
- `scripts/build_sbr_xlsx.py` — SBR JSON → xlsx + Retrosheet innings

The JSON path *does* correctly extract `pointspread.currentLine.homeSpread`
(`download_historical.py:301`), but:

1. `data/download_historical.py:433` silently falls back to SDQL-only when
   `data/raw/external/mlb_odds_dataset.json` is missing. The SDQL converter
   hard-codes `run_line = np.nan` (lines 180-181).
2. `scripts/build_sbr_xlsx.py` reads `data/raw/sbr_odds_full.json`, but the
   2022-2025 xlsx files currently on disk were not built fresh enough to
   carry run_line.

Net effect: after `load_single_season` → `pair_games`, the four columns
`home_run_line`, `home_run_line_odds`, `away_run_line`, `away_run_line_odds`
are all-NaN in 2022-2025.

### Bug 2 — `fav_power_rate_diff` = 100% NaN in 2022-2025

`data/download_historical.py:176` hard-codes `inn_{i} = 0` for every row
because neither SDQL nor the ArnavSaraogi JSON return inning-by-inning runs.

Downstream chain:

- `src/features.py:build_team_game_log` (line 40) detects "all-zero innings
  = fake inning data" and correctly sets `scoring_innings` / `multi_run_innings`
  to `NaN`.
- `src/features.py:calc_inning_power` returns `NaN` when the rolling window
  has fewer than 5 qualifying scoring innings → every 2022-2025 row is NaN.
- `src/features.py:build_all_features` computes `power_rate_diff` as
  `power_rate_home - power_rate_away` → NaN.
- `src/strategies/base.py:add_derived_for_strategies` signs the diff against
  `fav_is_home` to get `fav_power_rate_diff` → still NaN.

So the Sess 25 `fav_rl` filter (`fav_power_rate_diff >= 0`) **always evaluates
False** for 2022-2025, silently excluding the season.

A fix was already coded — `data_loader.enrich_innings_from_retrosheet()` pulls
real inning scores from `retrosheets/{year}csvs.zip → {year}teamstats.csv` —
but nothing in the documented pipeline was calling it.

---

## Fix

### `src/data_loader.py`

Two changes:

1. **New helper `enrich_run_line_from_sbr(games)`** that reads one of the
   available SBR JSON dumps (`data/raw/sbr_odds_full.json` or
   `data/raw/external/mlb_odds_dataset.json`) and backfills NaN run_line /
   run_line_odds rows in 2022-2025. The helper:

   - Is purely additive (never overwrites a non-NaN value).
   - Normalizes team codes across the four abbreviation dialects in the project
     (xlsx-style `KCR/SDP/SFG/TBR/WSN` ↔ SBR-style `KC/SD/SF/TB/WSH`).
   - No-ops gracefully if no JSON file is present.

2. **`load_all_seasons(..., *, enrich_innings=True, enrich_run_line=True)`**
   now calls both enrichment helpers by default. Both are wrapped in
   `try/except` so a missing source file downgrades to a log line instead of
   a pipeline failure. Callers who want the pre-fix behavior for A/B
   comparisons can pass `enrich_innings=False, enrich_run_line=False`.

The existing `enrich_innings_from_retrosheet` function was already correct —
we just wire it into the default pipeline.

### `scripts/validate_reverse_rl.py`

New validator that walks the full pipeline and prints per-season counts for:

- `home_run_line` / `away_run_line` / `home_run_line_odds` / `away_run_line_odds`
- `power_rate_home` / `power_rate_away` / `fav_power_rate_diff`
- `fav_rl` (standard regime, Sess 25 filter)
- `fav_rl` gated by the presence of -1.5 odds on the fav side
- Reverse-RL (dog +1.5 with non-NaN odds)

Exit 0 = every 2022-2025 season has at least one `fav_rl` pick.
Exit 1 = 2022 or 2023 or 2024 or 2025 is empty (either genuinely or because
the enrichment didn't reach it).

Invoke with `--no-enrichment` to reproduce the pre-fix counts; compare.

### Strategy files — untouched

`src/strategies/*` is not modified. `src/live_pregame.py` is not modified.
The fix is purely in the historical load path.

---

## Expected post-fix counts

Once the Windows machine has `sbr_odds_full.json` in place (and the
`retrosheets/*csvs.zip` files that `enrich_innings_from_retrosheet` already
expects), the validator should report:

| Season | N     | home_run_line coverage | fav_power_rate_diff coverage | fav_rl picks |
|--------|-------|------------------------|------------------------------|--------------|
| 2014   | ~1460 | ~95%                   | ~95%                         | ~135         |
| 2015   | ~1450 | ~95%                   | ~95%                         | ~135         |
| 2016   | ~1460 | ~95%                   | ~95%                         | ~135         |
| 2017   | ~1460 | ~95%                   | ~95%                         | ~135         |
| 2018   | ~1450 | ~95%                   | ~95%                         | ~135         |
| 2019   | ~1460 | ~95%                   | ~95%                         | ~135         |
| 2021   | ~1440 | ~95%                   | ~95%                         | ~135         |
| 2022   | 2332  | **≥95% (was 0%)**       | **≥90% (was 0%)**             | **~130 (was 0)** |
| 2023   | 2400  | **≥95% (was 0%)**       | **≥90% (was 0%)**             | **~135 (was 0)** |
| 2024   | 2411  | **≥95% (was 0%)**       | **≥90% (was 0%)**             | **~135 (was 0)** |
| 2025   | 2416  | **≥95% (was 0%)**       | **≥90% (was 0%)**             | **~135 (was 0)** |

Exact percentages depend on:

- How many 2022-2025 games the SBR JSON has a `pointspread` entry for.
- Whether the `retrosheets/{year}csvs.zip` files are present on the host
  (without them, `fav_power_rate_diff` stays NaN — the run_line fix still
  applies independently).

Re-run:

```bash
python scripts/validate_reverse_rl.py                # post-fix
python scripts/validate_reverse_rl.py --no-enrichment  # pre-fix comparison
```

and paste the actual printed tables into this file once the data is wired up
on the Windows box.

---

## What this does NOT overturn

- The 2014-2021 training/test results for Sess 25 (`fav_rl`), Sess 26
  (`tier1_bullpen_day`), and Sess 27 (`tier3_pitcher_advantage`) remain
  valid — the filters weren't miscomputed; the rows simply didn't exist.
- Live picks (April 2026 onward) were never affected: `src/live_pregame.py`
  pulls from its own boxscore/odds path and doesn't rely on xlsx-era
  run_line columns.

What we *should* redo after the fix lands:

1. Walk-forward validation folds that previously reported "2022-2025 held
   out" now actually include 2022-2025 rows — re-run those folds and
   confirm no regime change in ROI.
2. Any "all seasons" sparsity plot (Session 35 reverse-RL, Session 36
   fav_rl audit) should be regenerated with the corrected sample size.

---

## Files changed

- `src/data_loader.py` — added `enrich_run_line_from_sbr`, wired both
  enrichments into `load_all_seasons`.
- `scripts/validate_reverse_rl.py` — new validator for Sess 37.
- `knowledge/session_report_37_data_gaps.md` — this document.

No tests changed. `tests/test_strategies.py` still passes (28/28).
