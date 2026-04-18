from __future__ import annotations

import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pandas as pd

MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "scan_underdog_fielding_oracle_veto.py"
)
SPEC = spec_from_file_location("scan_underdog_fielding_oracle_veto", MODULE_PATH)
assert SPEC and SPEC.loader
oracle = module_from_spec(SPEC)
sys.modules[SPEC.name] = oracle
SPEC.loader.exec_module(oracle)


def _baseline_rows(
    strategy_name: str,
    flagged_col: str,
    *,
    signal: bool,
) -> pd.DataFrame:
    base = [
        {
            "strategy_name": strategy_name,
            "analysis_slice": "tier1_ml" if strategy_name == "tier1_bullpen_day" else "all",
            "season": 2024,
            "won": True,
            "pnl": 30.0,
            "away_oaa_oracle_bottom10": False,
            "away_def_oracle_bottom10": False,
        },
        {
            "strategy_name": strategy_name,
            "analysis_slice": "tier1_rl_standard"
            if strategy_name == "tier1_bullpen_day"
            else "all",
            "season": 2024,
            "won": True,
            "pnl": 20.0,
            "away_oaa_oracle_bottom10": False,
            "away_def_oracle_bottom10": False,
        },
        {
            "strategy_name": strategy_name,
            "analysis_slice": "tier1_rl_flipped"
            if strategy_name == "tier1_bullpen_day"
            else "all",
            "season": 2024,
            "won": False,
            "pnl": -100.0,
            "away_oaa_oracle_bottom10": False,
            "away_def_oracle_bottom10": False,
        },
        {
            "strategy_name": strategy_name,
            "analysis_slice": "tier1_ml" if strategy_name == "tier1_bullpen_day" else "all",
            "season": 2024,
            "won": False if signal else True,
            "pnl": -100.0 if signal else 25.0,
            "away_oaa_oracle_bottom10": False,
            "away_def_oracle_bottom10": False,
        },
        {
            "strategy_name": strategy_name,
            "analysis_slice": "tier1_rl_standard"
            if strategy_name == "tier1_bullpen_day"
            else "all",
            "season": 2025,
            "won": True,
            "pnl": 35.0,
            "away_oaa_oracle_bottom10": False,
            "away_def_oracle_bottom10": False,
        },
        {
            "strategy_name": strategy_name,
            "analysis_slice": "tier1_rl_flipped"
            if strategy_name == "tier1_bullpen_day"
            else "all",
            "season": 2025,
            "won": True,
            "pnl": 15.0,
            "away_oaa_oracle_bottom10": False,
            "away_def_oracle_bottom10": False,
        },
        {
            "strategy_name": strategy_name,
            "analysis_slice": "tier1_ml" if strategy_name == "tier1_bullpen_day" else "all",
            "season": 2025,
            "won": False,
            "pnl": -100.0,
            "away_oaa_oracle_bottom10": False,
            "away_def_oracle_bottom10": False,
        },
        {
            "strategy_name": strategy_name,
            "analysis_slice": "tier1_rl_standard"
            if strategy_name == "tier1_bullpen_day"
            else "all",
            "season": 2025,
            "won": False if signal else True,
            "pnl": -100.0 if signal else 22.0,
            "away_oaa_oracle_bottom10": False,
            "away_def_oracle_bottom10": False,
        },
    ]
    df = pd.DataFrame(base)
    df[flagged_col] = [False, False, False, True, False, False, False, True]
    return df


def test_build_same_season_oracle_flags_marks_bottom_three_and_ties():
    teams = sorted(oracle.CANON_TEAM_CODES)
    values = [-10.0, -9.0, -8.0, -8.0] + [float(x) for x in range(26)]
    fielding = pd.DataFrame(
        {
            "season_prior": 2025,
            "team": teams,
            "oaa_prev": values,
            "def_prev": values,
        }
    )

    out = oracle.build_same_season_oracle_flags(fielding)

    assert out["away_oaa_oracle_bottom10"].sum() == 4
    assert out["away_def_oracle_bottom10"].sum() == 4


def test_join_same_season_oracle_flags_uses_full_league_table():
    teams = sorted(oracle.CANON_TEAM_CODES)
    values = [-10.0, -9.0, -8.0] + [float(x) for x in range(27)]
    fielding = pd.DataFrame(
        {
            "season_prior": 2025,
            "team": teams,
            "oaa_prev": values,
            "def_prev": values,
        }
    )
    enriched = pd.DataFrame(
        [
            {
                "season": 2025,
                "away_team": teams[0],
                "home_team": teams[10],
            },
            {
                "season": 2025,
                "away_team": teams[15],
                "home_team": teams[12],
            },
        ]
    )

    out = oracle.join_same_season_oracle_flags(enriched, fielding)

    assert bool(out.iloc[0]["away_oaa_oracle_bottom10"]) is True
    assert bool(out.iloc[1]["away_oaa_oracle_bottom10"]) is False


def test_evaluate_oracle_family_labels_signal_only_when_bar_cleared():
    signal_df = _baseline_rows(
        "tier5_ml_obp_recovery",
        "away_oaa_oracle_bottom10",
        signal=True,
    )
    fail_df = _baseline_rows(
        "tier5_ml_obp_recovery",
        "away_def_oracle_bottom10",
        signal=False,
    )

    signal_row = oracle.evaluate_oracle_family(
        signal_df,
        strategy_name="tier5_ml_obp_recovery",
        family_key="oaa_bottom10_oracle",
        flag_col="away_oaa_oracle_bottom10",
    )
    fail_row = oracle.evaluate_oracle_family(
        fail_df,
        strategy_name="tier5_ml_obp_recovery",
        family_key="def_bottom10_oracle",
        flag_col="away_def_oracle_bottom10",
    )

    assert signal_row["status"] == "oracle_signal"
    assert signal_row["fail_reasons"] == ""
    assert fail_row["status"] == "no_signal"
    assert fail_row["fail_reasons"] != ""


def test_build_oracle_summary_includes_aggregate_row_and_season_columns():
    signal_df = _baseline_rows(
        "tier1_bullpen_day",
        "away_oaa_oracle_bottom10",
        signal=True,
    )
    baseline_by_strategy = {
        "tier1_bullpen_day": signal_df,
        "tier2_fatigue_gap": _baseline_rows(
            "tier2_fatigue_gap",
            "away_def_oracle_bottom10",
            signal=False,
        ),
        "tier3_pitcher_advantage": pd.DataFrame(),
        "tier4_ml_depth_load": pd.DataFrame(),
        "tier5_ml_obp_recovery": pd.DataFrame(),
    }

    summary = oracle.build_oracle_summary(baseline_by_strategy)

    assert oracle.AGGREGATE_STRATEGY in set(summary["strategy_name"])
    assert "base_roi_2024" in summary.columns
    assert "filtered_roi_2025" in summary.columns

    fail_row = summary[
        (summary["strategy_name"] == "tier2_fatigue_gap")
        & (summary["family"] == "def_bottom10_oracle")
    ].iloc[0]
    assert fail_row["status"] == "no_signal"
    assert fail_row["fail_reasons"] != ""
