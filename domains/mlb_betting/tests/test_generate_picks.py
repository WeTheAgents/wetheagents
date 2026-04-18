from __future__ import annotations

import sys
from datetime import date
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pandas as pd
import pytest

from src.strategies.base import Pick

MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "generate_picks_2026.py"
)
SPEC = spec_from_file_location("generate_picks_2026", MODULE_PATH)
assert SPEC and SPEC.loader
generate_picks_2026 = module_from_spec(SPEC)
sys.modules[SPEC.name] = generate_picks_2026
SPEC.loader.exec_module(generate_picks_2026)

TODAY = date(2026, 4, 17)


def _pick(tier: str, *, odds: float = 2.30) -> Pick:
    return Pick.make(
        target_date=TODAY,
        away="DET",
        home="BOS",
        market="ML_dog",
        side="away",
        tier=tier,
        historical_p=0.52,
        ref_odds_espn=odds,
        reason=tier,
        feature_snapshot={},
    )


def test_overlap_pair_gets_x15_stake_bonus_after_dedup():
    tier5 = _pick("tier5_ml_obp_recovery")
    tier4 = _pick("tier4_ml_depth_load")

    deduped = generate_picks_2026.dedup_overlapping_picks([tier5, tier4])
    assert len(deduped) == 1
    kept = deduped[0]
    assert kept.tier == "tier4_ml_depth_load"
    assert kept.also_qualified == ["tier5_ml_obp_recovery"]

    enriched = generate_picks_2026.enrich_pick(
        kept,
        None,
        0.25,
        operator_context={
            "tier5_fielding_oaa_edge_prev": -12.0,
            "tier5_fielding_oaa_q10_threshold": -42.7,
            "tier5_fielding_oaa_q10_pass": True,
        },
    )
    expected_base = 0.25 * generate_picks_2026.kelly(
        kept.historical_p * generate_picks_2026.HISTORICAL_P_SHRINK,
        kept.ref_odds_espn,
    )

    assert enriched.stake_fraction_base == pytest.approx(expected_base)
    assert enriched.stake_multiplier == pytest.approx(1.5)
    assert enriched.stake_multiplier_reason == "double_confirmed_ml_baskets"
    assert enriched.stake_fraction == pytest.approx(expected_base * 1.5)
    assert enriched.operator_flags == ["tier5_oaa_q10_pass"]
    assert enriched.feature_snapshot["tier5_fielding_oaa_edge_prev"] == pytest.approx(-12.0)
    assert enriched.feature_snapshot["tier5_fielding_oaa_q10_threshold"] == pytest.approx(-42.7)
    assert enriched.feature_snapshot["tier5_fielding_oaa_q10_pass"] is True
    assert enriched.schema_version == 4


def test_non_pair_overlap_keeps_base_stake():
    primary = _pick("tier4_ml_depth_load")
    primary.also_qualified = ["tier2_fatigue_gap"]

    enriched = generate_picks_2026.enrich_pick(primary, None, 0.25)
    expected_base = 0.25 * generate_picks_2026.kelly(
        primary.historical_p * generate_picks_2026.HISTORICAL_P_SHRINK,
        primary.ref_odds_espn,
    )

    assert enriched.stake_fraction_base == pytest.approx(expected_base)
    assert enriched.stake_multiplier == pytest.approx(1.0)
    assert enriched.stake_multiplier_reason is None
    assert enriched.stake_fraction == pytest.approx(expected_base)
    assert enriched.operator_flags == []


def test_tier5_pick_without_context_gets_unknown_operator_flag():
    pick = _pick("tier5_ml_obp_recovery")

    enriched = generate_picks_2026.enrich_pick(pick, None, 0.25)

    assert enriched.operator_flags == ["tier5_oaa_q10_unknown"]
    assert enriched.feature_snapshot["tier5_fielding_oaa_edge_prev"] is None
    assert enriched.feature_snapshot["tier5_fielding_oaa_q10_threshold"] == pytest.approx(-42.7)
    assert enriched.feature_snapshot["tier5_fielding_oaa_q10_pass"] is None


def test_build_tier5_operator_lookup_reads_target_day_signal():
    df = pd.DataFrame(
        [
            {
                "date": pd.Timestamp("2026-04-17"),
                "away_team": "DET",
                "home_team": "BOS",
                "tier5_fielding_oaa_edge_prev": -11.5,
                "tier5_fielding_oaa_q10_pass": True,
            },
            {
                "date": pd.Timestamp("2026-04-16"),
                "away_team": "DET",
                "home_team": "BOS",
                "tier5_fielding_oaa_edge_prev": -50.0,
                "tier5_fielding_oaa_q10_pass": False,
            },
        ]
    )

    lookup = generate_picks_2026.build_tier5_operator_lookup(df, TODAY)

    assert lookup[("DET", "BOS")]["tier5_fielding_oaa_edge_prev"] == pytest.approx(-11.5)
    assert lookup[("DET", "BOS")]["tier5_fielding_oaa_q10_threshold"] == pytest.approx(-42.7)
    assert lookup[("DET", "BOS")]["tier5_fielding_oaa_q10_pass"] is True
