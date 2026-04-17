"""Forward-project entering features onto future overlay rows.

Pregame overlays for ``target_date`` contain games that have not been played
yet, so date-keyed entering-feature parquets do not have exact-match rows for
them. This module fills that gap in two ways:

  * Team-keyed features: carry forward the latest pre-target value for the team.
  * Starter-keyed features: first try the already-merged frame, then fall back
    directly to ``pitchers_2026/starter_entering_features.parquet`` by pitcher
    identity.

This is intentionally read-only and only touches rows on ``target_date``.
"""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
PITCHER_CACHE_PATH = BASE_DIR / "data" / "fetch_2026" / "pitcher_cache.json"
STARTER_ENTERING_PATH = BASE_DIR / "data" / "processed" / "pitchers_2026" / "starter_entering_features.parquet"
STARTER_GAME_LOGS_PATH = BASE_DIR / "data" / "processed" / "pitchers_2026" / "starter_game_logs.parquet"


TEAM_LEVEL_FEATURES = {
    "home": [
        "bp_fip_short_home",
        "bp_fip_7g_home",
        "bp_fip_long_home",
        "bp_ip_3d_home",
        "bp_sc_whiff_3d_home",
        "bp_sc_barrel_3d_home",
        "bp_sc_hard_hit_3d_home",
        "bp_sc_exit_velo_3d_home",
        "bp_sc_xwoba_3d_home",
        "bp_sc_whiff_delta_3d_home",
        "bp_sc_barrel_delta_3d_home",
        "bp_sc_xwoba_std_home",
        "bp_sc_barrel_std_home",
        "bp_sc_xwoba_15g_home",
        "bp_sc_barrel_15g_home",
        "top3_obp_short_home",
        "top3_obp_long_home",
        "top3_k_rate_short_home",
        "top3_k_rate_long_home",
        "top3_hr_rate_short_home",
        "top3_obp_vs_rhp_home",
        "top3_k_rate_vs_rhp_home",
        "top3_obp_vs_lhp_home",
        "top3_k_rate_vs_lhp_home",
        "n_batters_home",
    ],
    "away": [
        "bp_fip_short_away",
        "bp_fip_7g_away",
        "bp_fip_long_away",
        "bp_ip_3d_away",
        "bp_sc_whiff_3d_away",
        "bp_sc_barrel_3d_away",
        "bp_sc_hard_hit_3d_away",
        "bp_sc_exit_velo_3d_away",
        "bp_sc_xwoba_3d_away",
        "bp_sc_whiff_delta_3d_away",
        "bp_sc_barrel_delta_3d_away",
        "bp_sc_xwoba_std_away",
        "bp_sc_barrel_std_away",
        "bp_sc_xwoba_15g_away",
        "bp_sc_barrel_15g_away",
        "top3_obp_short_away",
        "top3_obp_long_away",
        "top3_k_rate_short_away",
        "top3_k_rate_long_away",
        "top3_hr_rate_short_away",
        "top3_obp_vs_rhp_away",
        "top3_k_rate_vs_rhp_away",
        "top3_obp_vs_lhp_away",
        "top3_k_rate_vs_lhp_away",
        "n_batters_away",
    ],
}

PITCHER_LEVEL_FEATURES = {
    "home_pitcher": [
        "home_sp_starts_prior",
        "home_sp_starts_short",
        "home_sp_starts_long",
        "home_sp_ip_short",
        "home_sp_ip_long",
        "home_sp_whip_short",
        "home_sp_whip_long",
        "home_sp_kbb_short",
        "home_sp_kbb_long",
        "home_sp_k9_short",
        "home_sp_k9_long",
        "home_sp_bb9_short",
        "home_sp_bb9_long",
        "home_sp_hr9_short",
        "home_sp_hr9_long",
        "home_sp_fip_short",
        "home_sp_fip_long",
        "home_sp_ip_per_start_short",
        "home_sp_ip_per_start_long",
    ],
    "away_pitcher": [
        "away_sp_starts_prior",
        "away_sp_starts_short",
        "away_sp_starts_long",
        "away_sp_ip_short",
        "away_sp_ip_long",
        "away_sp_whip_short",
        "away_sp_whip_long",
        "away_sp_kbb_short",
        "away_sp_kbb_long",
        "away_sp_k9_short",
        "away_sp_k9_long",
        "away_sp_bb9_short",
        "away_sp_bb9_long",
        "away_sp_hr9_short",
        "away_sp_hr9_long",
        "away_sp_fip_short",
        "away_sp_fip_long",
        "away_sp_ip_per_start_short",
        "away_sp_ip_per_start_long",
    ],
}

STARTER_META_COLUMNS = {
    "gid",
    "season",
    "date",
    "game_num",
    "home_team",
    "away_team",
    "team",
    "is_home",
    "opponent",
}

SAVANT_DIFF_METRICS = {
    "bp_sc_xwoba_std",
    "bp_sc_xwoba_15g",
    "bp_sc_barrel_std",
    "bp_sc_barrel_15g",
    "bp_sc_whiff_3d",
    "bp_sc_barrel_3d",
    "bp_sc_whiff_delta_3d",
    "bp_sc_barrel_delta_3d",
}

LATE_GAME_DIFF_FEATURES = {
    "hold_rate": "hold_rate_diff",
    "close_game_wp": "close_game_wp_diff",
    "deficit_recovery_rate": "deficit_recovery_diff",
}


def _fill_team_feature(
    df: pd.DataFrame,
    team_col: str,
    feature: str,
    target_date: date,
) -> int:
    """Fill target-date team features from each team's latest pre-target row."""
    if feature not in df.columns:
        return 0

    target_mask = df["date"].dt.date == target_date
    if not target_mask.any():
        return 0

    pre_mask = (df["date"].dt.date < target_date) & df[feature].notna()
    if not pre_mask.any():
        return 0

    latest = (
        df.loc[pre_mask, [team_col, "date", feature]]
        .sort_values("date")
        .groupby(team_col)[feature]
        .last()
    )

    rows_to_fill = target_mask & df[feature].isna()
    if not rows_to_fill.any():
        return 0

    df.loc[rows_to_fill, feature] = df.loc[rows_to_fill, team_col].map(latest)
    return int((rows_to_fill & df[feature].notna()).sum())


def _fill_team_feature_from_history(
    df: pd.DataFrame,
    team_col: str,
    feature: str,
    target_date: date,
    history_sources: list[tuple[str, str]],
) -> int:
    """Fill a target-date team feature from the latest prior team history.

    Unlike `_fill_team_feature`, this can combine prior home/away columns into
    one team-level history. That matters for side-specific columns such as
    Savant bullpen metrics, which are team features but get merged into the
    frame as separate `_home` / `_away` columns.
    """
    if feature not in df.columns or team_col not in df.columns:
        return 0

    target_mask = df["date"].dt.date == target_date
    if not target_mask.any():
        return 0

    rows_to_fill = target_mask & df[feature].isna()
    if not rows_to_fill.any():
        return 0

    history_frames: list[pd.DataFrame] = []
    pre_mask = df["date"].dt.date < target_date
    for source_team_col, source_feature in history_sources:
        if source_team_col not in df.columns or source_feature not in df.columns:
            continue
        source_mask = pre_mask & df[source_feature].notna()
        if not source_mask.any():
            continue
        history_frames.append(
            df.loc[source_mask, [source_team_col, "date", source_feature]]
            .rename(columns={source_team_col: "team", source_feature: "value"})
        )

    if not history_frames:
        return 0

    latest = (
        pd.concat(history_frames, ignore_index=True)
        .sort_values("date")
        .groupby("team")["value"]
        .last()
    )

    df.loc[rows_to_fill, feature] = df.loc[rows_to_fill, team_col].map(latest)
    return int((rows_to_fill & df[feature].notna()).sum())


def _fill_pitcher_feature(
    df: pd.DataFrame,
    pitcher_col: str,
    feature: str,
    target_date: date,
) -> int:
    """Fill target-date starter features from the merged frame itself."""
    if feature not in df.columns or pitcher_col not in df.columns:
        return 0

    target_mask = df["date"].dt.date == target_date
    if not target_mask.any():
        return 0

    pre_mask = (df["date"].dt.date < target_date) & df[feature].notna()
    if not pre_mask.any():
        return 0

    latest = (
        df.loc[pre_mask, [pitcher_col, "date", feature]]
        .sort_values("date")
        .groupby(pitcher_col)[feature]
        .last()
    )

    rows_to_fill = target_mask & df[feature].isna()
    if not rows_to_fill.any():
        return 0

    df.loc[rows_to_fill, feature] = df.loc[rows_to_fill, pitcher_col].map(latest)
    return int((rows_to_fill & df[feature].notna()).sum())


def _discover_savant_base_metrics(df: pd.DataFrame) -> list[str]:
    """Return Savant team metrics present as side-specific columns."""
    metrics = set()
    for col in df.columns:
        if not col.startswith("bp_sc_"):
            continue
        if col.endswith("_home"):
            metrics.add(col[:-5])
        elif col.endswith("_away"):
            metrics.add(col[:-5])
    return sorted(metrics)


def _discover_savant_diff_metrics(df: pd.DataFrame) -> list[str]:
    """Return diff metrics to recompute after Savant forward-projection."""
    metrics = set(SAVANT_DIFF_METRICS)
    for col in df.columns:
        if col.startswith("bp_sc_") and col.endswith("_diff"):
            metrics.add(col[:-5])
    return sorted(metrics)


def _fill_savant_team_features(
    df: pd.DataFrame,
    target_date: date,
) -> dict[str, int]:
    """Carry forward Savant bullpen team features onto target-date rows."""
    filled: dict[str, int] = {}
    target_mask = df["date"].dt.date == target_date
    if not target_mask.any():
        return filled

    base_metrics = _discover_savant_base_metrics(df)
    if not base_metrics:
        return filled

    for base in base_metrics:
        home_feature = f"{base}_home"
        away_feature = f"{base}_away"
        history_sources = [
            ("home_team", home_feature),
            ("away_team", away_feature),
        ]
        n_home = _fill_team_feature_from_history(
            df,
            "home_team",
            home_feature,
            target_date,
            history_sources,
        )
        if n_home:
            filled[home_feature] = n_home
        n_away = _fill_team_feature_from_history(
            df,
            "away_team",
            away_feature,
            target_date,
            history_sources,
        )
        if n_away:
            filled[away_feature] = n_away

    for base in _discover_savant_diff_metrics(df):
        home_feature = f"{base}_home"
        away_feature = f"{base}_away"
        diff_feature = f"{base}_diff"
        if home_feature not in df.columns or away_feature not in df.columns:
            continue
        df[diff_feature] = df[home_feature] - df[away_feature]
        n_diff = int((target_mask & df[diff_feature].notna()).sum())
        if n_diff:
            filled[diff_feature] = n_diff

    return filled


def _fill_late_game_team_features(
    df: pd.DataFrame,
    target_date: date,
) -> dict[str, int]:
    """Carry forward latest prior late-game team metrics onto target-date rows."""
    filled: dict[str, int] = {}
    target_mask = df["date"].dt.date == target_date
    if not target_mask.any():
        return filled

    for base, diff_feature in sorted(LATE_GAME_DIFF_FEATURES.items()):
        home_feature = f"{base}_home"
        away_feature = f"{base}_away"
        history_sources = [
            ("home_team", home_feature),
            ("away_team", away_feature),
        ]
        n_home = _fill_team_feature_from_history(
            df,
            "home_team",
            home_feature,
            target_date,
            history_sources,
        )
        if n_home:
            filled[home_feature] = n_home
        n_away = _fill_team_feature_from_history(
            df,
            "away_team",
            away_feature,
            target_date,
            history_sources,
        )
        if n_away:
            filled[away_feature] = n_away

        if home_feature not in df.columns or away_feature not in df.columns:
            continue
        df[diff_feature] = df[home_feature] - df[away_feature]
        n_diff = int((target_mask & df[diff_feature].notna()).sum())
        if n_diff:
            filled[diff_feature] = n_diff

    return filled


def _load_pitcher_code_lookup() -> dict[str, str]:
    """Build {pitcher_code -> pitcher_id} from local caches/logs."""
    from data.fetch_2026.pitcher_codes import PitcherCodeRegistry  # noqa: PLC0415

    registry = PitcherCodeRegistry()
    lookup: dict[str, str] = {}
    hand_cache: dict[str, str] = {}

    if PITCHER_CACHE_PATH.exists():
        raw = json.loads(PITCHER_CACHE_PATH.read_text(encoding="utf-8"))
        for name, info in raw.items():
            if not isinstance(info, dict):
                continue
            pitcher_id = info.get("mlb_id")
            if pitcher_id in (None, ""):
                continue
            hand = str(info.get("hand") or "R").strip().upper() or "R"
            hand_cache[str(name)] = hand
            code = registry.get_code(str(name), hand)
            if code:
                lookup[code] = str(pitcher_id)

    if STARTER_GAME_LOGS_PATH.exists():
        logs = pd.read_parquet(STARTER_GAME_LOGS_PATH, columns=["pitcher_id", "pitcher_name"])
        logs = logs.dropna(subset=["pitcher_id", "pitcher_name"]).drop_duplicates()
        for _, row in logs.iterrows():
            name = str(row["pitcher_name"]).strip()
            if not name:
                continue
            hand = hand_cache.get(name, "R")
            code = registry.get_code(name, hand)
            if code and code not in lookup:
                lookup[code] = str(row["pitcher_id"])

    return lookup


def _load_latest_starter_features(target_date: date) -> tuple[pd.DataFrame, dict[str, str]]:
    """Return latest pre-target starter row per pitcher_id + code lookup."""
    if not STARTER_ENTERING_PATH.exists():
        return pd.DataFrame(), {}

    starter = pd.read_parquet(STARTER_ENTERING_PATH)
    if starter.empty:
        return starter, {}

    starter["date"] = pd.to_datetime(starter["date"]).dt.normalize()
    starter["pitcher_id"] = starter["pitcher_id"].astype(str)
    pre = starter[starter["date"].dt.date < target_date].copy()
    if pre.empty:
        return pd.DataFrame(), _load_pitcher_code_lookup()

    latest = (
        pre.sort_values("date")
        .groupby("pitcher_id", as_index=False)
        .last()
        .set_index("pitcher_id")
    )
    return latest, _load_pitcher_code_lookup()


def _fill_pitcher_features_from_parquet(
    df: pd.DataFrame,
    target_date: date,
) -> dict[str, int]:
    """Backfill starter features directly from the 2026 starter parquet."""
    latest, code_lookup = _load_latest_starter_features(target_date)
    if latest.empty:
        return {}

    filled: dict[str, int] = {}
    target_mask = df["date"].dt.date == target_date
    if not target_mask.any():
        return filled

    side_config = {
        "home": {"pitcher_col": "home_pitcher", "starter_id_col": "home_starter_id"},
        "away": {"pitcher_col": "away_pitcher", "starter_id_col": "away_starter_id"},
    }

    for side, cfg in side_config.items():
        pitcher_col = cfg["pitcher_col"]
        starter_id_col = cfg["starter_id_col"]
        bridge_flag_col = f"starter_history_bridge_missing_{side}"
        if pitcher_col not in df.columns:
            continue
        if starter_id_col not in df.columns:
            df[starter_id_col] = pd.NA
        if bridge_flag_col not in df.columns:
            df[bridge_flag_col] = False

        renamed = {
            col: f"{side}_sp_{col}"
            for col in latest.columns
            if col not in STARTER_META_COLUMNS
        }
        row_idxs = list(df.index[target_mask])
        for idx in row_idxs:
            pitcher_code = str(df.at[idx, pitcher_col] or "").strip()
            starter_id = df.at[idx, starter_id_col]
            if pd.isna(starter_id) or str(starter_id).strip() == "":
                starter_id = code_lookup.get(pitcher_code)
                if starter_id is not None:
                    df.at[idx, starter_id_col] = starter_id

            if starter_id is None or pd.isna(starter_id):
                continue
            starter_key = str(starter_id)
            if starter_key not in latest.index:
                df.at[idx, bridge_flag_col] = True
                continue

            source = latest.loc[starter_key]
            bridge_missing = bool(source.get("starter_history_bridge_missing", False))
            df.at[idx, bridge_flag_col] = bridge_missing
            for raw_col, target_col in renamed.items():
                if target_col not in df.columns:
                    df[target_col] = np.nan
                if pd.isna(df.at[idx, target_col]):
                    value = source[raw_col]
                    if pd.notna(value):
                        df.at[idx, target_col] = value
                        filled[target_col] = filled.get(target_col, 0) + 1

    return filled


def _recompute_lineup_interactions(df: pd.DataFrame) -> None:
    """Recompute matchup-dependent lineup features after team projection."""
    required = {
        "away_sp_hand",
        "home_sp_hand",
        "top3_obp_vs_rhp_home",
        "top3_obp_vs_lhp_home",
        "top3_obp_vs_rhp_away",
        "top3_obp_vs_lhp_away",
    }
    if not required.issubset(df.columns):
        return

    df["effective_obp_home"] = np.where(
        df["away_sp_hand"] == "R",
        df["top3_obp_vs_rhp_home"],
        np.where(df["away_sp_hand"] == "L", df["top3_obp_vs_lhp_home"], np.nan),
    )
    df["effective_obp_away"] = np.where(
        df["home_sp_hand"] == "R",
        df["top3_obp_vs_rhp_away"],
        np.where(df["home_sp_hand"] == "L", df["top3_obp_vs_lhp_away"], np.nan),
    )
    df["effective_obp_combined"] = df["effective_obp_home"] + df["effective_obp_away"]
    df["effective_obp_diff"] = df["effective_obp_home"] - df["effective_obp_away"]


def _recompute_savant_diffs(df: pd.DataFrame) -> None:
    """Recompute home-away Savant mismatch columns after team-value projection."""
    for metric in [
        "xwoba_std",
        "xwoba_15g",
        "barrel_std",
        "barrel_15g",
        "whiff_3d",
        "barrel_3d",
        "whiff_delta_3d",
        "barrel_delta_3d",
    ]:
        home_col = f"bp_sc_{metric}_home"
        away_col = f"bp_sc_{metric}_away"
        diff_col = f"bp_sc_{metric}_diff"
        if home_col in df.columns and away_col in df.columns:
            df[diff_col] = df[home_col] - df[away_col]


def forward_project_features(
    df: pd.DataFrame,
    target_date: date,
) -> pd.DataFrame:
    """Carry forward last-available team/pitcher values onto ``target_date`` rows."""
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"])

    filled_summary: dict[str, int] = {}

    for side, feats in TEAM_LEVEL_FEATURES.items():
        team_col = f"{side}_team"
        for feature in feats:
            n = _fill_team_feature(out, team_col, feature, target_date)
            if n:
                filled_summary[feature] = filled_summary.get(feature, 0) + n

    for pitcher_col, feats in PITCHER_LEVEL_FEATURES.items():
        for feature in feats:
            n = _fill_pitcher_feature(out, pitcher_col, feature, target_date)
            if n:
                filled_summary[feature] = filled_summary.get(feature, 0) + n

    parquet_fills = _fill_pitcher_features_from_parquet(out, target_date)
    for feature, n in parquet_fills.items():
        filled_summary[feature] = filled_summary.get(feature, 0) + n

    savant_fills = _fill_savant_team_features(out, target_date)
    for feature, n in savant_fills.items():
        filled_summary[feature] = filled_summary.get(feature, 0) + n

    late_game_fills = _fill_late_game_team_features(out, target_date)
    for feature, n in late_game_fills.items():
        filled_summary[feature] = filled_summary.get(feature, 0) + n

    # Re-derive bullpen-no-starter flags for target-date overlay rows.
    # merge_retrosheet_pitchers() does LEFT JOIN + .fillna(False) on unmatched
    # rows — overlay games have no entry in game_id_bridge (bridge only contains
    # completed games), so flags are forced to False even when no starter is listed.
    # For pregame overlays, an empty pitcher code IS the bullpen-game signal:
    # ESPN shows no probable starter when a team goes to the bullpen.
    _target_date_mask = out["date"].dt.date == target_date
    for _side in ("home", "away"):
        _pitcher_col = f"{_side}_pitcher"
        _flag_col = f"{_side}_is_bullpen_no_starter"
        if _pitcher_col not in out.columns or _flag_col not in out.columns:
            continue
        _is_empty = out[_pitcher_col].isna() | (
            out[_pitcher_col].astype(str).str.strip() == ""
        )
        out.loc[_target_date_mask, _flag_col] = _is_empty[_target_date_mask]
        _n = int(_is_empty[_target_date_mask].sum())
        if _n:
            filled_summary[_flag_col] = _n

    _recompute_lineup_interactions(out)
    _recompute_savant_diffs(out)

    try:
        from src.features import refresh_feature_consistency_flags  # noqa: PLC0415

        out = refresh_feature_consistency_flags(out)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to refresh feature consistency flags: %s", exc)

    if filled_summary:
        logger.info(
            "Forward-projected features for %s: %s",
            target_date,
            ", ".join(f"{k}={v}" for k, v in sorted(filled_summary.items())),
        )
    else:
        logger.info("Forward-projection: no rows filled for %s", target_date)

    return out
