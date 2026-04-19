"""Canonical helpers for the Fav RL (-1.5) re-audit.

The current re-audit intentionally prioritizes the ``away favorite /
home underdog`` lane.  Pricing truth uses the recorded away-side run-line
odds when available; otherwise we fall back to the legacy vig-based
estimator from ``home +1.5`` odds.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.data_loader import american_to_decimal

FAV_RL_TOTAL_VIG = 1.045

OFFICIAL_SEASONS = [2021, 2022, 2023, 2024, 2025]
BRIDGE_SEASONS = [2014, 2015, 2016, 2017, 2018, 2019, 2021, 2022, 2023, 2024, 2025]
TRAIN_SEASONS = [2021, 2022, 2023, 2024]
TEST_SEASONS = [2025]

AWAY_FAV_PRICE_BANDS = [
    (0.55, 0.62),
    (0.62, 0.67),
    (0.67, 0.72),
    (0.72, 0.75),
]

CURRENT_SHADOW_FILTER = {
    "lane": "away_fav_home_dog",
    "impl_min": 0.62,
    "impl_max": 0.75,
    "fav_starter_fip_diff_max": -0.2,
    "fav_power_rate_diff_min": 0.0,
}
CURRENT_SHADOW_HISTORICAL_P = 0.512

NO_COLLAPSE_TEST_DELTA = -0.03

RESURRECTION_BAR = {
    "official_roi_min": 0.04,
    "test_2025_roi_min": 0.0,
    "cover_minus_breakeven_min": 0.015,
    "positive_seasons_min": 3,
    "official_seasons": len(OFFICIAL_SEASONS),
    "max_drawdown_worse_than_shadow_max": 3.0,
}

BASE_DIR = Path(__file__).resolve().parent.parent
KNOWLEDGE_DIR = BASE_DIR / "knowledge"

FAV_RL_REAUDIT_SUMMARY_PATH = KNOWLEDGE_DIR / "fav_rl_reaudit_summary.json"
FAV_RL_REAUDIT_REPORT_PATH = KNOWLEDGE_DIR / "fav_rl_reaudit_report.md"
FAV_RL_SHADOW_REPORT_PATH = KNOWLEDGE_DIR / "fav_rl_shadow_report.md"


@dataclass(frozen=True)
class FilterCandidate:
    name: str
    family: str
    mask: pd.Series


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _float_or_none(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)


def _json_default(value: Any) -> Any:
    if isinstance(value, (np.integer, np.floating, np.bool_)):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Not JSON serializable: {type(value)!r}")


def estimate_away_fav_rl_decimal(
    home_plus_one_point_five_american: float | int | None,
    *,
    total_vig: float = FAV_RL_TOTAL_VIG,
) -> float | None:
    """Estimate away -1.5 decimal odds from recorded home +1.5 odds."""
    if home_plus_one_point_five_american is None or pd.isna(home_plus_one_point_five_american):
        return None
    if float(home_plus_one_point_five_american) == 0:
        return None
    home_plus_decimal = american_to_decimal(float(home_plus_one_point_five_american))
    home_plus_implied = 1.0 / home_plus_decimal
    away_minus_implied = total_vig - home_plus_implied
    if away_minus_implied <= 0:
        return None
    return 1.0 / away_minus_implied


def _decimal_series(values: pd.Series) -> pd.Series:
    return values.apply(
        lambda value: american_to_decimal(float(value))
        if pd.notna(value) and float(value) != 0
        else np.nan
    )


def _ensure_fav_oriented(
    df: pd.DataFrame,
    raw_col: str,
    fav_col: str,
) -> None:
    if fav_col in df.columns:
        return
    if raw_col not in df.columns:
        df[fav_col] = np.nan
        return
    flip = np.where(df["fav_is_home"], 1.0, -1.0)
    df[fav_col] = df[raw_col] * flip


def build_fav_rl_reaudit_frame(
    spec_frame: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build the canonical fav-RL audit frame."""
    if spec_frame is None:
        from src.features import build_spec_features  # noqa: PLC0415

        spec_frame = build_spec_features()

    df = spec_frame.copy()
    if "involves_col" in df.columns:
        df = df[~df["involves_col"].fillna(False)].copy()
    if "is_extreme_line" in df.columns:
        df = df[~df["is_extreme_line"].fillna(False)].copy()
    if "home_run_line" in df.columns:
        df = df[df["home_run_line"].isin([-1.5, 1.5])].copy()

    if "fav_is_home" not in df.columns:
        df["fav_is_home"] = df["home_implied_prob"] >= df["away_implied_prob"]
    if "fav_implied_prob" not in df.columns:
        df["fav_implied_prob"] = np.where(
            df["fav_is_home"],
            df["home_implied_prob"],
            df["away_implied_prob"],
        )

    if "fav_margin" not in df.columns:
        df["fav_margin"] = np.where(
            df["fav_is_home"],
            df["home_final"] - df["away_final"],
            df["away_final"] - df["home_final"],
        )
    df["covers"] = df["fav_margin"] >= 2
    df["lane"] = np.where(df["fav_is_home"], "home_fav", "away_fav_home_dog")

    home_actual = _decimal_series(df["home_run_line_odds"]) if "home_run_line_odds" in df.columns else pd.Series(np.nan, index=df.index)
    away_actual = _decimal_series(df["away_run_line_odds"]) if "away_run_line_odds" in df.columns else pd.Series(np.nan, index=df.index)

    df["actual_rl_odds"] = np.where(df["fav_is_home"], home_actual, away_actual)
    df["estimated_rl_odds"] = np.where(
        df["fav_is_home"],
        home_actual,
        df["home_run_line_odds"].apply(estimate_away_fav_rl_decimal)
        if "home_run_line_odds" in df.columns
        else np.nan,
    )
    df["official_rl_odds"] = df["actual_rl_odds"].fillna(df["estimated_rl_odds"])
    df["price_source"] = np.where(
        df["actual_rl_odds"].notna(),
        "actual",
        np.where(df["estimated_rl_odds"].notna(), "estimated", "missing"),
    )

    _ensure_fav_oriented(df, "starter_fip_diff", "fav_starter_fip_diff")
    _ensure_fav_oriented(df, "power_rate_diff", "fav_power_rate_diff")
    _ensure_fav_oriented(df, "team_wrc_plus_diff", "fav_team_wrc_plus_diff")
    _ensure_fav_oriented(df, "effective_obp_diff", "fav_effective_obp_diff")
    _ensure_fav_oriented(df, "hold_rate_diff", "fav_hold_rate_diff")
    _ensure_fav_oriented(df, "close_game_wp_diff", "fav_close_game_wp_diff")
    _ensure_fav_oriented(df, "decisive_win_rate_diff", "fav_decisive_win_rate_diff")
    _ensure_fav_oriented(df, "decisive_loss_rate_diff", "fav_decisive_loss_rate_diff")
    _ensure_fav_oriented(df, "deficit_recovery_diff", "fav_deficit_recovery_diff")
    _ensure_fav_oriented(df, "bullpen_workload_3d_diff", "fav_bullpen_workload_3d_diff")
    _ensure_fav_oriented(df, "bullpen_fip_diff", "fav_bullpen_fip_diff")

    if "starter_depth_diff_short" in df.columns:
        flip = np.where(df["fav_is_home"], 1.0, -1.0)
        df["fav_starter_depth_diff_short"] = df["starter_depth_diff_short"] * flip
    else:
        df["fav_starter_depth_diff_short"] = np.nan

    if "bp_fip_7g_home" in df.columns and "bp_fip_7g_away" in df.columns:
        raw_bp_7g = df["bp_fip_7g_home"] - df["bp_fip_7g_away"]
        flip = np.where(df["fav_is_home"], 1.0, -1.0)
        df["fav_bp_7g_diff"] = raw_bp_7g * flip
    else:
        df["fav_bp_7g_diff"] = np.nan

    df["current_shadow_filter_pass"] = current_shadow_filter_mask(df)
    return df


def current_shadow_filter_mask(df: pd.DataFrame) -> pd.Series:
    """Current away-fav shadow basket."""
    return (
        (~df["fav_is_home"])
        & (df["fav_implied_prob"] >= CURRENT_SHADOW_FILTER["impl_min"])
        & (df["fav_implied_prob"] < CURRENT_SHADOW_FILTER["impl_max"])
        & (df["fav_starter_fip_diff"] <= CURRENT_SHADOW_FILTER["fav_starter_fip_diff_max"])
        & (df["fav_power_rate_diff"] >= CURRENT_SHADOW_FILTER["fav_power_rate_diff_min"])
    )


def longest_loss_streak(covers: pd.Series) -> int:
    max_streak = 0
    current = 0
    for covered in covers.fillna(False).astype(bool):
        if covered:
            current = 0
            continue
        current += 1
        max_streak = max(max_streak, current)
    return max_streak


def _season_rows(df: pd.DataFrame, odds_col: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if df.empty:
        return rows
    for season in sorted(df["season"].dropna().astype(int).unique().tolist()):
        sub = df[df["season"] == season].copy()
        if sub.empty:
            continue
        metrics = _summarize_flat_bets_core(
            sub,
            odds_col=odds_col,
            include_season_rows=False,
        )
        rows.append(
            {
                "season": season,
                "bets": metrics["bets"],
                "cover_rate": metrics["cover_rate"],
                "avg_odds": metrics["avg_odds"],
                "breakeven": metrics["breakeven"],
                "cover_minus_breakeven": metrics["cover_minus_breakeven"],
                "roi": metrics["roi"],
            }
        )
    return rows


def _summarize_flat_bets_core(
    df: pd.DataFrame,
    *,
    odds_col: str = "official_rl_odds",
    include_season_rows: bool = True,
) -> dict[str, Any]:
    """Flat 1u reporting summary for a filtered bet set without season recursion."""
    if df.empty:
        return {
            "bets": 0,
            "cover_rate": None,
            "avg_odds": None,
            "breakeven": None,
            "cover_minus_breakeven": None,
            "roi": None,
            "max_drawdown_units": None,
            "longest_loss_streak": None,
            "actual_prices": 0,
            "estimated_prices": 0,
            "positive_seasons": 0,
            "season_rows": [],
        }

    used = df[df[odds_col].notna()].copy()
    if used.empty:
        out = _summarize_flat_bets_core(
            pd.DataFrame(columns=df.columns),
            odds_col=odds_col,
            include_season_rows=include_season_rows,
        )
        out["bets"] = int(len(df))
        return out

    used = used.sort_values(["date", "away_team", "home_team"]).copy()
    pnl = np.where(used["covers"], used[odds_col] - 1.0, -1.0)
    cumulative = np.cumsum(pnl)
    peak = np.maximum.accumulate(cumulative)
    drawdown = peak - cumulative

    avg_odds = float(used[odds_col].mean())
    cover_rate = float(used["covers"].mean())
    breakeven = 1.0 / avg_odds if avg_odds > 0 else None
    season_rows = _season_rows(used, odds_col) if include_season_rows else []
    positive_seasons = sum(
        1 for row in season_rows if row["roi"] is not None and row["roi"] > 0
    )
    return {
        "bets": int(len(used)),
        "cover_rate": cover_rate,
        "avg_odds": avg_odds,
        "breakeven": breakeven,
        "cover_minus_breakeven": (
            cover_rate - breakeven if breakeven is not None else None
        ),
        "roi": float(np.mean(pnl)),
        "max_drawdown_units": float(drawdown.max()) if len(drawdown) else 0.0,
        "longest_loss_streak": longest_loss_streak(used["covers"]),
        "actual_prices": int((used["price_source"] == "actual").sum()),
        "estimated_prices": int((used["price_source"] == "estimated").sum()),
        "positive_seasons": positive_seasons,
        "season_rows": season_rows,
    }


def summarize_flat_bets(
    df: pd.DataFrame,
    *,
    odds_col: str = "official_rl_odds",
) -> dict[str, Any]:
    """Flat 1u reporting summary for a filtered bet set."""
    return _summarize_flat_bets_core(df, odds_col=odds_col, include_season_rows=True)


def official_subset(df: pd.DataFrame) -> pd.DataFrame:
    return df[df["season"].isin(OFFICIAL_SEASONS)].copy()


def bridge_subset(df: pd.DataFrame) -> pd.DataFrame:
    return df[df["season"].isin(BRIDGE_SEASONS)].copy()


def build_price_band_stage_rows(df: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    away = df[df["lane"] == "away_fav_home_dog"].copy()
    if away.empty:
        return rows
    for lo, hi in AWAY_FAV_PRICE_BANDS:
        mask = (away["fav_implied_prob"] >= lo) & (away["fav_implied_prob"] < hi)
        official = away[mask & away["season"].isin(OFFICIAL_SEASONS)].copy()
        train = official[official["season"].isin(TRAIN_SEASONS)].copy()
        test = official[official["season"].isin(TEST_SEASONS)].copy()
        bridge = away[mask & away["season"].isin(BRIDGE_SEASONS)].copy()
        train_stats = summarize_flat_bets(train)
        test_stats = summarize_flat_bets(test)
        official_stats = summarize_flat_bets(official)
        bridge_stats = summarize_flat_bets(bridge)
        selected = bool(
            train_stats["bets"] >= 25
            and (train_stats["cover_minus_breakeven"] or -999) >= 0.0
            and (
                test_stats["cover_minus_breakeven"] is None
                or test_stats["cover_minus_breakeven"] >= NO_COLLAPSE_TEST_DELTA
            )
        )
        rows.append(
            {
                "bucket": f"[{lo:.2f},{hi:.2f})",
                "implied_lo": lo,
                "implied_hi": hi,
                "selected_for_scan": selected,
                "official": official_stats,
                "train_2021_2024": train_stats,
                "test_2025": test_stats,
                "bridge_2014_2025": bridge_stats,
            }
        )
    return rows


def build_rule_candidates(df: pd.DataFrame) -> list[FilterCandidate]:
    """Rule-based candidate families for the away-fav lane."""
    candidates: list[FilterCandidate] = []

    def add(name: str, family: str, mask: pd.Series) -> None:
        candidates.append(FilterCandidate(name=name, family=family, mask=mask.fillna(False)))

    if "fav_starter_fip_diff" in df.columns:
        add("fav_starter_fip_diff<=-0.30", "pitching", df["fav_starter_fip_diff"] <= -0.30)
        add("fav_starter_fip_diff<=-0.50", "pitching", df["fav_starter_fip_diff"] <= -0.50)
    if "fav_starter_depth_diff_short" in df.columns:
        add("fav_starter_depth_diff_short>=0.30", "pitching", df["fav_starter_depth_diff_short"] >= 0.30)
        add("fav_starter_depth_diff_short>=0.70", "pitching", df["fav_starter_depth_diff_short"] >= 0.70)

    if "fav_power_rate_diff" in df.columns:
        add("fav_power_rate_diff>=0.02", "attack", df["fav_power_rate_diff"] >= 0.02)
        add("fav_power_rate_diff>=0.05", "attack", df["fav_power_rate_diff"] >= 0.05)
    if "fav_team_wrc_plus_diff" in df.columns:
        add("fav_team_wrc_plus_diff>=5", "attack", df["fav_team_wrc_plus_diff"] >= 5.0)
        add("fav_team_wrc_plus_diff>=10", "attack", df["fav_team_wrc_plus_diff"] >= 10.0)
    if "fav_effective_obp_diff" in df.columns:
        add("fav_effective_obp_diff>=0.005", "attack", df["fav_effective_obp_diff"] >= 0.005)
        add("fav_effective_obp_diff>=0.010", "attack", df["fav_effective_obp_diff"] >= 0.010)

    if "fav_bullpen_workload_3d_diff" in df.columns:
        add("dog_bp_more_tired>=1", "bullpen", df["fav_bullpen_workload_3d_diff"] <= -1.0)
        add("dog_bp_more_tired>=2", "bullpen", df["fav_bullpen_workload_3d_diff"] <= -2.0)
    if "fav_bp_7g_diff" in df.columns:
        add("fav_bp_7g_diff<=-0.20", "bullpen", df["fav_bp_7g_diff"] <= -0.20)
        add("fav_bp_7g_diff<=-0.30", "bullpen", df["fav_bp_7g_diff"] <= -0.30)
    if "fav_hold_rate_diff" in df.columns:
        add("fav_hold_rate_diff>=0.02", "bullpen", df["fav_hold_rate_diff"] >= 0.02)
        add("fav_hold_rate_diff>=0.05", "bullpen", df["fav_hold_rate_diff"] >= 0.05)

    if "fav_close_game_wp_diff" in df.columns:
        add("fav_close_game_wp_diff<=0.00", "margin", df["fav_close_game_wp_diff"] <= 0.0)
        add("fav_close_game_wp_diff<=-0.03", "margin", df["fav_close_game_wp_diff"] <= -0.03)
    if "fav_decisive_win_rate_diff" in df.columns:
        add("fav_decisive_win_rate_diff>=0.02", "margin", df["fav_decisive_win_rate_diff"] >= 0.02)
        add("fav_decisive_win_rate_diff>=0.05", "margin", df["fav_decisive_win_rate_diff"] >= 0.05)
    if "fav_decisive_loss_rate_diff" in df.columns:
        add("fav_decisive_loss_rate_diff<=0.00", "margin", df["fav_decisive_loss_rate_diff"] <= 0.0)
        add("fav_decisive_loss_rate_diff<=-0.02", "margin", df["fav_decisive_loss_rate_diff"] <= -0.02)

    return candidates


def _score_for_rank(train_stats: dict[str, Any], test_stats: dict[str, Any]) -> tuple[float, float, float]:
    return (
        float(train_stats["cover_minus_breakeven"] or -999.0),
        float(test_stats["roi"] or -999.0),
        float(train_stats["roi"] or -999.0),
    )


def scan_rule_filters(
    pool: pd.DataFrame,
    *,
    min_bets: int = 20,
) -> dict[str, Any]:
    """Run singles + constrained 2-way combo scan inside a selected pool."""
    singles: list[dict[str, Any]] = []
    candidates = build_rule_candidates(pool)
    official = pool[pool["season"].isin(OFFICIAL_SEASONS)].copy()

    for candidate in candidates:
        official_sub = official[candidate.mask.loc[official.index]].copy()
        if len(official_sub) < min_bets:
            continue
        train_sub = official_sub[official_sub["season"].isin(TRAIN_SEASONS)].copy()
        test_sub = official_sub[official_sub["season"].isin(TEST_SEASONS)].copy()
        singles.append(
            {
                "name": candidate.name,
                "family": candidate.family,
                "official": summarize_flat_bets(official_sub),
                "train_2021_2024": summarize_flat_bets(train_sub),
                "test_2025": summarize_flat_bets(test_sub),
            }
        )

    singles.sort(
        key=lambda row: _score_for_rank(row["train_2021_2024"], row["test_2025"]),
        reverse=True,
    )

    family_best: list[dict[str, Any]] = []
    seen_families: set[str] = set()
    for row in singles:
        if row["family"] in seen_families:
            continue
        family_best.append(row)
        seen_families.add(row["family"])
        if len(family_best) >= 6:
            break

    name_to_candidate = {candidate.name: candidate for candidate in candidates}
    combos: list[dict[str, Any]] = []
    for idx, left in enumerate(family_best):
        for right in family_best[idx + 1 :]:
            left_mask = name_to_candidate[left["name"]].mask
            right_mask = name_to_candidate[right["name"]].mask
            combo_mask = left_mask & right_mask
            official_sub = official[combo_mask.loc[official.index]].copy()
            if len(official_sub) < min_bets:
                continue
            train_sub = official_sub[official_sub["season"].isin(TRAIN_SEASONS)].copy()
            test_sub = official_sub[official_sub["season"].isin(TEST_SEASONS)].copy()
            combos.append(
                {
                    "name": f"{left['name']} + {right['name']}",
                    "families": [left["family"], right["family"]],
                    "official": summarize_flat_bets(official_sub),
                    "train_2021_2024": summarize_flat_bets(train_sub),
                    "test_2025": summarize_flat_bets(test_sub),
                }
            )

    combos.sort(
        key=lambda row: _score_for_rank(row["train_2021_2024"], row["test_2025"]),
        reverse=True,
    )
    return {
        "singles": singles,
        "family_best": family_best,
        "combos": combos,
    }


def lane_passes_resurrection_bar(
    official_stats: dict[str, Any],
    test_stats: dict[str, Any],
    *,
    shadow_drawdown_units: float | None,
) -> bool:
    if official_stats["bets"] == 0:
        return False
    if official_stats["roi"] is None or official_stats["roi"] < RESURRECTION_BAR["official_roi_min"]:
        return False
    if test_stats["roi"] is None or test_stats["roi"] < RESURRECTION_BAR["test_2025_roi_min"]:
        return False
    if (
        official_stats["cover_minus_breakeven"] is None
        or official_stats["cover_minus_breakeven"] < RESURRECTION_BAR["cover_minus_breakeven_min"]
    ):
        return False
    if official_stats["positive_seasons"] < RESURRECTION_BAR["positive_seasons_min"]:
        return False
    if (
        shadow_drawdown_units is not None
        and official_stats["max_drawdown_units"] is not None
        and official_stats["max_drawdown_units"]
        > shadow_drawdown_units + RESURRECTION_BAR["max_drawdown_worse_than_shadow_max"]
    ):
        return False
    return True


def pricing_reconciliation(away_fav_df: pd.DataFrame) -> dict[str, Any]:
    both = away_fav_df[
        away_fav_df["actual_rl_odds"].notna() & away_fav_df["estimated_rl_odds"].notna()
    ].copy()
    if both.empty:
        return {"n": 0, "overall": {}, "per_season": []}

    pct_error = (both["estimated_rl_odds"] / both["actual_rl_odds"]) - 1.0
    abs_error = both["estimated_rl_odds"] - both["actual_rl_odds"]
    overall = {
        "mean_actual_rl_odds": float(both["actual_rl_odds"].mean()),
        "mean_estimated_rl_odds": float(both["estimated_rl_odds"].mean()),
        "median_actual_rl_odds": float(both["actual_rl_odds"].median()),
        "median_estimated_rl_odds": float(both["estimated_rl_odds"].median()),
        "mean_pct_error": float(pct_error.mean()),
        "median_pct_error": float(pct_error.median()),
        "mean_abs_error": float(abs_error.mean()),
    }
    rows = []
    for season in sorted(both["season"].dropna().astype(int).unique().tolist()):
        sub = both[both["season"] == season].copy()
        pct = (sub["estimated_rl_odds"] / sub["actual_rl_odds"]) - 1.0
        rows.append(
            {
                "season": season,
                "n": int(len(sub)),
                "mean_actual_rl_odds": float(sub["actual_rl_odds"].mean()),
                "mean_estimated_rl_odds": float(sub["estimated_rl_odds"].mean()),
                "mean_pct_error": float(pct.mean()),
                "median_pct_error": float(pct.median()),
            }
        )
    return {"n": int(len(both)), "overall": overall, "per_season": rows}


def markdown_table(rows: list[dict[str, Any]], columns: list[tuple[str, str]]) -> str:
    if not rows:
        return "_none_"
    header = "| " + " | ".join(label for _, label in columns) + " |"
    sep = "| " + " | ".join("---" for _ in columns) + " |"
    body = []
    for row in rows:
        body.append(
            "| "
            + " | ".join(str(row.get(key, "")) for key, _ in columns)
            + " |"
        )
    return "\n".join([header, sep, *body])


def write_summary_files(summary: dict[str, Any]) -> None:
    KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
    FAV_RL_REAUDIT_SUMMARY_PATH.write_text(
        json.dumps(summary, indent=2, default=_json_default),
        encoding="utf-8",
    )

    report = [
        "# Fav RL Re-Audit",
        "",
        f"- Generated: `{summary['generated_at']}`",
        f"- Verdict: `{summary['verdict']}`",
        f"- Shadow mode: `{summary['shadow_strategy']['mode']}`",
        "",
        "## Pricing Reconciliation",
        "",
        markdown_table(
            summary["pricing_reconciliation"]["per_season"],
            [
                ("season", "Season"),
                ("n", "N"),
                ("mean_actual_rl_odds", "Actual"),
                ("mean_estimated_rl_odds", "Estimated"),
                ("mean_pct_error", "Mean % Err"),
            ],
        ),
        "",
        "## Official Baselines (2021-2025)",
        "",
        markdown_table(
            summary["official_baselines"],
            [
                ("label", "Lane"),
                ("bets", "Bets"),
                ("cover_rate", "Cover"),
                ("avg_odds", "Avg Odds"),
                ("breakeven", "BE"),
                ("cover_minus_breakeven", "Cover-BE"),
                ("roi", "ROI"),
                ("max_drawdown_units", "MaxDD"),
            ],
        ),
        "",
        "## Current Shadow Filter Recheck",
        "",
        markdown_table(
            summary["current_shadow_filter_recheck"],
            [
                ("label", "Slice"),
                ("bets", "Bets"),
                ("cover_rate", "Cover"),
                ("avg_odds", "Avg Odds"),
                ("breakeven", "BE"),
                ("cover_minus_breakeven", "Cover-BE"),
                ("roi", "ROI"),
            ],
        ),
        "",
        "## Price Bands",
        "",
        markdown_table(
            summary["price_band_stage"],
            [
                ("bucket", "Bucket"),
                ("selected_for_scan", "Selected"),
                ("official_bets", "Official N"),
                ("official_cover_minus_breakeven", "Official Cover-BE"),
                ("official_roi", "Official ROI"),
                ("test_2025_roi", "2025 ROI"),
            ],
        ),
        "",
        "## Rule Singles",
        "",
        markdown_table(
            summary["rule_scan"]["singles"][:12],
            [
                ("name", "Filter"),
                ("family", "Family"),
                ("official_bets", "Official N"),
                ("official_cover_minus_breakeven", "Official Cover-BE"),
                ("official_roi", "Official ROI"),
                ("test_2025_roi", "2025 ROI"),
            ],
        ),
        "",
        "## Rule Combos",
        "",
        markdown_table(
            summary["rule_scan"]["combos"][:12],
            [
                ("name", "Combo"),
                ("official_bets", "Official N"),
                ("official_cover_minus_breakeven", "Official Cover-BE"),
                ("official_roi", "Official ROI"),
                ("test_2025_roi", "2025 ROI"),
            ],
        ),
        "",
    ]
    FAV_RL_REAUDIT_REPORT_PATH.write_text("\n".join(report), encoding="utf-8")

    shadow_rows = summary.get("shadow_report_rows", [])
    shadow_report = [
        "# Fav RL Shadow Report",
        "",
        f"- Mode: `{summary['shadow_strategy']['mode']}`",
        f"- Filter: `{summary['shadow_strategy']['label']}`",
        "",
        markdown_table(
            shadow_rows,
            [
                ("date", "Date"),
                ("away_team", "Away"),
                ("home_team", "Home"),
                ("official_rl_odds", "Odds"),
                ("covers", "Covers"),
                ("fav_margin", "Fav Margin"),
                ("price_source", "Price Source"),
            ],
        ),
        "",
    ]
    FAV_RL_SHADOW_REPORT_PATH.write_text("\n".join(shadow_report), encoding="utf-8")
