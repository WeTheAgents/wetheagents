"""Production betting strategies for the 2026 MLB season.

Each strategy module exports a single ``find_picks(games, target_date)``
function that takes an enriched (post-``build_all_features``) DataFrame
filtered to a single game date and returns a list of ``Pick`` objects.

Active strategies (per audit plan §3, sessions 25-27):
  - tier1_bullpen_day      — Sess 26 — ~24 games/season, 74.2% / 83.7% — bullpen-day rule
  - tier2_fatigue_gap      — Sess 26 — ~25-35 games/season, ~72% — bullpen workload gap
  - tier3_pitcher_advantage — Sess 27 — ~8 games/season, 79% — short-window swap (Decision §9.1)
  - fav_rl                 — manual/shadow only — away-fav current filter after 2026-04-19 re-audit
  - over_bullpen_mismatch  — Sess 33b — ~20 games/season, 61.7% — OVER on RPG+bullpen+SP
  - under_totals           — Sess 30 + live bundle — model-driven UNDER totals bands

Deferred (no production model yet, per audit §9.3):
  - yrfi   — research only, no saved CatBoost model. Defer to in-season research.
"""

from .base import Pick, add_derived_for_strategies
from .fav_rl import find_picks as find_fav_rl_picks
from .over_bullpen_mismatch import find_picks as find_over_picks
from .tier1_bullpen_day import find_picks as find_tier1_picks
from .tier2_fatigue_gap import find_picks as find_tier2_picks
from .tier3_pitcher_advantage import find_picks as find_tier3_picks
from .under_totals import find_picks as find_under_picks

ACTIVE_STRATEGIES = {
    "tier1_bullpen_day": find_tier1_picks,
    "tier2_fatigue_gap": find_tier2_picks,
    "tier3_pitcher_advantage": find_tier3_picks,
    "fav_rl": find_fav_rl_picks,
    "over_bullpen_mismatch": find_over_picks,
    "under_totals": find_under_picks,
}

__all__ = [
    "Pick",
    "ACTIVE_STRATEGIES",
    "add_derived_for_strategies",
    "find_tier1_picks",
    "find_tier2_picks",
    "find_tier3_picks",
    "find_fav_rl_picks",
    "find_over_picks",
    "find_under_picks",
]
