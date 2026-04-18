from __future__ import annotations

import sys
from datetime import date
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pandas as pd
import pytest

MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "scan_underdog_fielding_soft_filters.py"
)
SPEC = spec_from_file_location("scan_underdog_fielding_soft_filters", MODULE_PATH)
assert SPEC and SPEC.loader
scan = module_from_spec(SPEC)
sys.modules[SPEC.name] = scan
SPEC.loader.exec_module(scan)


def _fielding_line(
    rank: int,
    team: str,
    *,
    drs: str = "10",
    uzr: str = "2.5",
    oaa: str = "5",
    def_value: str = "6.0",
) -> str:
    parts = [
        str(rank),
        team,
        "---",
        "12900.0",
        "0",
        "0",
        "0",
        "0",
        "0",
        "0",
        "0",
        "0",
        drs,
        "0.0",
        "0.0",
        "0.0",
        "0.0",
        uzr,
        "0.0",
        "0.0",
        oaa,
        "0",
        def_value,
    ]
    return "\t".join(parts)


def test_parse_fangraphs_fielding_txt_returns_30_unique_teams(tmp_path):
    teams = sorted(scan.CANON_TEAM_CODES)
    lines = [_fielding_line(idx, team) for idx, team in enumerate(teams, start=1)]
    path = tmp_path / "2027.txt"
    path.write_text("\n".join(lines), encoding="utf-8")

    df = scan.parse_fangraphs_fielding_txt(path)

    assert len(df) == 30
    assert df["team"].nunique() == 30
    assert set(df.columns) == {
        "season_prior",
        "team",
        "drs_prev",
        "uzr_prev",
        "oaa_prev",
        "def_prev",
    }


def test_parse_handles_missing_uzr_and_ath_alias(tmp_path):
    path = tmp_path / "2025.txt"
    lines = [
        _fielding_line(1, "ATH", uzr="", oaa="-16", def_value="-23.2"),
        _fielding_line(2, "CHC"),
    ]
    path.write_text("\n".join(lines), encoding="utf-8")

    df = scan.parse_fangraphs_fielding_txt(path)

    ath = df[df["team"] == "OAK"].iloc[0]
    assert pd.isna(ath["uzr_prev"])
    assert ath["oaa_prev"] == pytest.approx(-16.0)
    assert ath["def_prev"] == pytest.approx(-23.2)


def test_collect_strategy_pick_rows_matches_direct_strategy_calls():
    target_date = pd.Timestamp("2026-04-12")
    rows = [
        {
            "season": 2026,
            "date": target_date,
            "away_team": "AW1",
            "home_team": "HM1",
            "home_close_ml": -140,
            "away_close_ml": 120,
            "home_run_line": -1.5,
            "away_run_line": 1.5,
            "away_run_line_odds": -105,
            "home_implied_prob": 0.58,
            "away_implied_prob": 0.44,
            "home_is_bullpen_no_starter": False,
            "away_is_bullpen_no_starter": False,
            "fav_is_home": True,
            "bp_ip_3d_home": 10.0,
            "bp_ip_3d_away": 4.0,
            "bp_workload_gap": 6.0,
            "home_sp_fip_short": 4.4,
            "away_sp_fip_short": 3.0,
            "starter_depth_diff_short": -1.5,
            "effective_obp_away": 0.34,
            "bp_sc_xwoba_std_home": 0.29,
            "deficit_recovery_diff": -0.05,
            "away_final": 5,
            "home_final": 3,
            "away_oaa_edge_prev": 4.0,
            "away_def_edge_prev": 3.0,
        }
    ]
    df = pd.DataFrame(rows)

    direct = scan.ACTIVE_STRATEGIES["tier3_pitcher_advantage"](
        df, target_date.date()
    )
    collected = scan.collect_strategy_pick_rows(df, "tier3_pitcher_advantage")

    assert len(collected) == len(direct) == 1
    assert collected.iloc[0]["market"] == direct[0].market
    assert collected.iloc[0]["tier"] == direct[0].tier


def test_settle_pick_rows_preserves_tier1_standard_and_flipped_lanes():
    picks = pd.DataFrame(
        [
            {
                "strategy_name": "tier1_bullpen_day",
                "tier": "tier1_bullpen_day",
                "date": pd.Timestamp("2026-04-12"),
                "away_team": "AAA",
                "home_team": "BBB",
                "market": "ML_dog",
                "side": "away",
                "ref_odds_espn": 2.20,
                "away_final": 4,
                "home_final": 3,
            },
            {
                "strategy_name": "tier1_bullpen_day",
                "tier": "tier1_bullpen_day",
                "date": pd.Timestamp("2026-04-12"),
                "away_team": "AAA",
                "home_team": "BBB",
                "market": "RL_+1.5",
                "side": "away",
                "ref_odds_espn": 1.85,
                "away_final": 4,
                "home_final": 3,
            },
            {
                "strategy_name": "tier1_bullpen_day",
                "tier": "tier1_bullpen_day_flipped",
                "date": pd.Timestamp("2026-04-12"),
                "away_team": "CCC",
                "home_team": "DDD",
                "market": "RL_-1.5",
                "side": "away",
                "ref_odds_espn": 2.10,
                "away_final": 6,
                "home_final": 3,
            },
        ]
    )
    picks["analysis_slice"] = [
        scan.pick_slice_label("tier1_bullpen_day", row.tier, row.market)
        for row in picks.itertuples()
    ]

    settled = scan.settle_pick_rows(picks)

    assert set(settled["analysis_slice"]) == {
        "tier1_ml",
        "tier1_rl_standard",
        "tier1_rl_flipped",
    }
    assert settled["won"].tolist() == [True, True, True]


def test_pass_diagnostics_matches_canonical_removed_share_formula():
    selected = pd.DataFrame({"won": [True, True, False, False]})
    pass_mask = pd.Series([True, False, True, False])

    out = scan.pass_diagnostics(selected, pass_mask)

    assert out["winner_pass_rate"] == pytest.approx(0.5)
    assert out["loser_pass_rate"] == pytest.approx(0.5)
    assert out["winner_removed_share"] == pytest.approx(0.5)
    assert out["loser_removed_share"] == pytest.approx(0.5)
    assert out["loss_filter_edge"] == pytest.approx(0.0)


def test_choose_family_candidate_requires_retention_bar_and_positive_edge():
    rows = pd.DataFrame(
        [
            {
                "strategy_name": "tier4_ml_depth_load",
                "family": "oaa_guard",
                "analysis_slice": "all",
                "quantile": 0.10,
                "threshold": -50.0,
                "base_roi": 12.0,
                "filtered_roi": 13.0,
                "retention": 0.74,
                "loss_filter_edge": 0.05,
                "worse_season_count": 0,
                "eligible": False,
            },
            {
                "strategy_name": "tier4_ml_depth_load",
                "family": "oaa_guard",
                "analysis_slice": "all",
                "quantile": 0.15,
                "threshold": -40.0,
                "base_roi": 12.0,
                "filtered_roi": 12.5,
                "retention": 0.80,
                "loss_filter_edge": 0.03,
                "worse_season_count": 1,
                "eligible": True,
            },
        ]
    )

    chosen = scan.choose_family_candidate(rows)

    assert chosen is not None
    assert chosen["quantile"] == pytest.approx(0.15)
    assert chosen["retention"] >= 0.75


def test_build_candidate_summary_reports_no_candidate_explicitly():
    threshold_table = pd.DataFrame(
        [
            {
                "strategy_name": "tier1_bullpen_day",
                "family": "oaa_guard",
                "analysis_slice": "all",
                "quantile": 0.10,
                "threshold": -10.0,
                "base_roi": 10.0,
                "filtered_roi": 9.0,
                "retention": 0.90,
                "loss_filter_edge": 0.01,
                "worse_season_count": 2,
                "eligible": False,
            }
        ]
    )

    summary = scan.build_candidate_summary(threshold_table)
    row = summary[
        (summary["strategy_name"] == "tier1_bullpen_day")
        & (summary["family"] == "oaa_guard")
    ].iloc[0]

    assert row["status"] == "no_candidate"


def test_evaluate_strategy_family_thresholds_includes_season_roi_columns():
    baseline = pd.DataFrame(
        [
            {
                "season": 2024,
                "won": True,
                "pnl": 25.0,
                "away_oaa_edge_prev": -10.0,
            },
            {
                "season": 2024,
                "won": False,
                "pnl": -100.0,
                "away_oaa_edge_prev": -20.0,
            },
            {
                "season": 2025,
                "won": True,
                "pnl": 30.0,
                "away_oaa_edge_prev": 5.0,
            },
            {
                "season": 2025,
                "won": False,
                "pnl": -100.0,
                "away_oaa_edge_prev": -5.0,
            },
        ]
    )

    out = scan.evaluate_strategy_family_thresholds(
        baseline,
        strategy_name="tier5_ml_obp_recovery",
        family_key="oaa_guard",
        feature_col="away_oaa_edge_prev",
        quantiles=(0.10,),
    )

    assert "base_roi_2024" in out.columns
    assert "filtered_roi_2024" in out.columns
    assert "base_roi_2025" in out.columns
    assert "filtered_roi_2025" in out.columns
