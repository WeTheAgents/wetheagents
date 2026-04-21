"""Single source of truth for production and research strategy wiring."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from .fav_rl import find_picks as find_fav_rl_picks
from .over_bullpen_mismatch import find_picks as find_over_picks
from .tier1_bullpen_day import find_picks as find_tier1_picks
from .tier2_fatigue_gap import find_picks as find_tier2_picks
from .tier3_pitcher_advantage import find_picks as find_tier3_picks
from .tier4_ml_depth_load import find_picks as find_tier4_picks
from .tier5_ml_obp_recovery import find_picks as find_tier5_picks
from .under_totals import find_picks as find_under_picks

StrategyFinder = Callable[[pd.DataFrame, date], list]


@dataclass(frozen=True)
class StrategySpec:
    tier: str
    find_picks: StrategyFinder
    enabled_by_default: bool
    requires_savant: bool = False
    requires_under_bundle: bool = False
    production_enabled: bool = True

    @property
    def source_path(self) -> Path:
        return Path(self.find_picks.__code__.co_filename).resolve()


STRATEGY_SPECS: tuple[StrategySpec, ...] = (
    StrategySpec("tier1_bullpen_day", find_tier1_picks, enabled_by_default=True),
    StrategySpec(
        "tier4_ml_depth_load",
        find_tier4_picks,
        enabled_by_default=True,
        requires_savant=True,
    ),
    StrategySpec(
        "tier5_ml_obp_recovery",
        find_tier5_picks,
        enabled_by_default=True,
        requires_savant=True,
    ),
    StrategySpec("tier3_pitcher_advantage", find_tier3_picks, enabled_by_default=True),
    StrategySpec("tier2_fatigue_gap", find_tier2_picks, enabled_by_default=True),
    StrategySpec(
        "under_totals",
        find_under_picks,
        enabled_by_default=True,
        requires_under_bundle=True,
    ),
    StrategySpec("over_bullpen_mismatch", find_over_picks, enabled_by_default=True),
    StrategySpec("fav_rl", find_fav_rl_picks, enabled_by_default=False, production_enabled=False),
)

STRATEGY_CATALOG = {spec.tier: spec for spec in STRATEGY_SPECS}
ACTIVE_STRATEGIES = {spec.tier: spec.find_picks for spec in STRATEGY_SPECS}
DEFAULT_PRODUCTION_TIERS = [
    spec.tier
    for spec in STRATEGY_SPECS
    if spec.enabled_by_default and spec.production_enabled
]
PRODUCTION_TIERS = [spec.tier for spec in STRATEGY_SPECS if spec.production_enabled]


def get_strategy_spec(tier: str) -> StrategySpec:
    return STRATEGY_CATALOG[tier]


def unknown_tiers(requested_tiers: list[str]) -> list[str]:
    return [tier for tier in requested_tiers if tier not in STRATEGY_CATALOG]
