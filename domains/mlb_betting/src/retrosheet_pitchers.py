"""Retrosheet CSV (zips) → starter logs → entering-game pitcher features.

This module implements a lightweight pipeline that:
- Reads `YYYYgameinfo.csv` and `YYYYpitching.csv` directly from `YYYYcsvs.zip`
  (no extraction to disk).
- Builds a 2-rows-per-game starter log (home + away).
- Computes strictly ENTERING-game rolling pitching metrics (anti-leak).
- Builds a game bridge table for joining with other datasets.

Notes
-----
Retrosheet always has a "first pitcher used" (p_seq==1), but in "bullpen games"
there may be no pitcher with a typical starter workload. We mark such cases with
`is_bullpen_no_starter` per (gid, team), based on the maximum IP in the game.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from zipfile import ZipFile

import numpy as np
import pandas as pd

RETROSHEETS_DIR = Path(__file__).parent.parent / "retrosheets"
DEFAULT_OUTPUT_DIR = Path(__file__).parent.parent / "data" / "processed" / "pitchers"


@dataclass(frozen=True)
class BullpenConfig:
    """Heuristics for bullpen-game flags computed from per-game pitcher usage."""

    # If no pitcher reaches this workload, we say "no designated starter".
    # 12 outs = 4.0 IP (a pragmatic cutoff for "bulk starter-like" appearance).
    no_starter_max_outs_threshold: int = 12
    # Opener pattern: starter is short AND someone else is the bulk pitcher.
    opener_starter_max_outs: int = 6  # 2.0 IP


def _find_member(z: ZipFile, suffix: str) -> str:
    for n in z.namelist():
        if n.endswith(suffix):
            return n
    raise FileNotFoundError(f"Zip does not contain '*{suffix}': {z.filename}")


def _read_csv_from_zip(
    zip_path: Path,
    member: str,
    *,
    usecols: list[str] | None = None,
    dtype: dict[str, str] | None = None,
) -> pd.DataFrame:
    with ZipFile(zip_path) as z:
        with z.open(member) as f:
            return pd.read_csv(f, usecols=usecols, dtype=dtype)


def _parse_yyyymmdd_int(v: pd.Series) -> pd.Series:
    # Retrosheet stores dates as int YYYYMMDD. Keep timezone-naive midnight.
    return pd.to_datetime(v.astype("int64").astype(str), format="%Y%m%d", errors="coerce")


def _safe_div(n: pd.Series, d: pd.Series, *, eps: float = 1e-9) -> pd.Series:
    return n / (d.replace(0, np.nan) + eps)


def _ensure_int(df: pd.DataFrame, cols: Iterable[str]) -> pd.DataFrame:
    for c in cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).astype(int)
    return df


def load_year_gameinfo_and_pitching(
    season: int,
    *,
    retrosheets_dir: Path = RETROSHEETS_DIR,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load `gameinfo` and `pitching` for a single season."""
    zip_path = retrosheets_dir / f"{season}csvs.zip"
    if not zip_path.exists():
        raise FileNotFoundError(f"Missing Retrosheet archive: {zip_path}")

    with ZipFile(zip_path) as z:
        gameinfo_name = _find_member(z, f"{season}gameinfo.csv")
        pitching_name = _find_member(z, f"{season}pitching.csv")

    games = _read_csv_from_zip(zip_path, gameinfo_name)
    pitching = _read_csv_from_zip(zip_path, pitching_name)

    # Normalize types we rely on.
    games = _ensure_int(games, ["date", "number", "season"])
    pitching = _ensure_int(pitching, ["p_seq", "p_ipouts", "p_h", "p_w", "p_k", "p_er", "p_hr"])

    # Standardize column names to plan terminology.
    games = games.rename(columns={"visteam": "away_team", "hometeam": "home_team"})
    games["season"] = season
    games["date"] = _parse_yyyymmdd_int(games["date"])
    games["game_num"] = pd.to_numeric(games.get("number", 0), errors="coerce").fillna(0).astype(int)

    return games, pitching


def compute_bullpen_flags(
    pitching: pd.DataFrame,
    *,
    cfg: BullpenConfig = BullpenConfig(),
) -> pd.DataFrame:
    """Compute bullpen-game flags per (gid, team) using full pitching lines."""
    required = {"gid", "id", "team", "p_seq", "p_ipouts"}
    missing = required - set(pitching.columns)
    if missing:
        raise ValueError(f"pitching is missing columns: {sorted(missing)}")

    p = pitching.copy()
    p = p[p["gid"].notna() & p["team"].notna()]
    p = _ensure_int(p, ["p_seq", "p_ipouts"])

    grp = p.groupby(["gid", "team"], sort=False)
    max_outs = grp["p_ipouts"].max().rename("max_outs")
    n_pitchers = grp.size().rename("n_pitchers")

    # Starter: p_seq == 1 (first pitcher used for the team in the game)
    starters = p[p["p_seq"] == 1][["gid", "team", "id", "p_ipouts"]].rename(
        columns={"id": "starter_id", "p_ipouts": "starter_outs"}
    )
    starters = starters.drop_duplicates(subset=["gid", "team"], keep="first")

    # Bulk pitcher: pitcher with max outs (tie → first occurrence).
    idx = grp["p_ipouts"].idxmax()
    bulk = p.loc[idx, ["gid", "team", "id", "p_ipouts"]].rename(
        columns={"id": "bulk_pitcher_id", "p_ipouts": "bulk_outs"}
    )

    flags = (
        pd.concat([max_outs, n_pitchers], axis=1)
        .reset_index()
        .merge(starters, on=["gid", "team"], how="left")
        .merge(bulk, on=["gid", "team"], how="left")
    )

    flags["is_bullpen_no_starter"] = flags["max_outs"] < cfg.no_starter_max_outs_threshold
    flags["is_opener_game"] = (
        (flags["starter_outs"].fillna(0) <= cfg.opener_starter_max_outs)
        & (flags["bulk_pitcher_id"] != flags["starter_id"])
        & (flags["max_outs"] >= cfg.no_starter_max_outs_threshold)
    )
    flags["starter_is_bulk"] = flags["starter_id"] == flags["bulk_pitcher_id"]

    # Convenience numeric columns
    flags["max_ip"] = flags["max_outs"] / 3.0
    flags["starter_ip"] = flags["starter_outs"].fillna(0).astype(int) / 3.0
    flags["bulk_ip"] = flags["bulk_outs"].fillna(0).astype(int) / 3.0

    return flags


def build_starter_game_logs_for_year(
    season: int,
    *,
    retrosheets_dir: Path = RETROSHEETS_DIR,
    bullpen_cfg: BullpenConfig = BullpenConfig(),
) -> pd.DataFrame:
    """Build starter logs for a single season (2 rows per game)."""
    games, pitching = load_year_gameinfo_and_pitching(season, retrosheets_dir=retrosheets_dir)

    p = pitching.copy()
    if "stattype" in p.columns:
        p = p[p["stattype"] == "value"]

    # Keep starters
    starters = p[p["p_seq"] == 1].copy()
    starters = starters.rename(columns={"id": "pitcher_id"})

    # Avoid column name collisions on merge: pitching.csv includes `date`/`number` too.
    for col in ["date", "number", "season", "game_num", "home_team", "away_team"]:
        if col in starters.columns:
            starters = starters.drop(columns=[col])

    # Join game metadata
    keep_game_cols = ["gid", "season", "date", "game_num", "home_team", "away_team"]
    starters = starters.merge(games[keep_game_cols], on="gid", how="left", validate="m:1")

    starters["team"] = starters["team"].astype(str)
    starters["home_team"] = starters["home_team"].astype(str)
    starters["away_team"] = starters["away_team"].astype(str)

    starters["is_home"] = starters["team"] == starters["home_team"]
    starters["opponent"] = np.where(
        starters["is_home"], starters["away_team"], starters["home_team"]
    )

    # Derived pitching line
    starters = _ensure_int(starters, ["p_ipouts", "p_h", "p_w", "p_k", "p_er", "p_hr"])
    starters["outs"] = starters["p_ipouts"].astype(int)
    starters["ip"] = starters["outs"] / 3.0
    starters["h"] = starters["p_h"].astype(int)
    starters["bb"] = starters["p_w"].astype(int)
    starters["so"] = starters["p_k"].astype(int)
    starters["er"] = starters["p_er"].astype(int)
    starters["hr"] = starters["p_hr"].astype(int)
    if "p_bfp" in starters.columns:
        starters["bfp"] = pd.to_numeric(starters["p_bfp"], errors="coerce")
    if "p_hbp" in starters.columns:
        starters["hbp"] = pd.to_numeric(starters["p_hbp"], errors="coerce")

    # Bullpen flags (per gid/team)
    flags = compute_bullpen_flags(pitching, cfg=bullpen_cfg)
    starters = starters.merge(flags, on=["gid", "team"], how="left", validate="m:1")

    # Final column set (keep raw fields too for audit)
    out_cols = [
        "gid",
        "season",
        "date",
        "game_num",
        "home_team",
        "away_team",
        "team",
        "is_home",
        "opponent",
        "pitcher_id",
        "outs",
        "ip",
        "h",
        "bb",
        "so",
        "er",
        "hr",
        "bfp",
        "hbp",
        "is_bullpen_no_starter",
        "is_opener_game",
        "starter_is_bulk",
        "max_outs",
        "max_ip",
        "starter_outs",
        "starter_ip",
        "bulk_pitcher_id",
        "bulk_outs",
        "bulk_ip",
        "n_pitchers",
    ]
    out_cols = [c for c in out_cols if c in starters.columns]
    starters = starters[out_cols].copy()

    return starters


def build_starter_game_logs(
    seasons: Iterable[int],
    *,
    retrosheets_dir: Path = RETROSHEETS_DIR,
    bullpen_cfg: BullpenConfig = BullpenConfig(),
) -> pd.DataFrame:
    """Build starter logs for multiple seasons."""
    parts: list[pd.DataFrame] = []
    for s in seasons:
        parts.append(
            build_starter_game_logs_for_year(
                int(s), retrosheets_dir=retrosheets_dir, bullpen_cfg=bullpen_cfg
            )
        )
    logs = pd.concat(parts, ignore_index=True)
    logs = logs.sort_values(["pitcher_id", "date", "game_num"]).reset_index(drop=True)
    return logs


def build_game_id_bridge(starter_game_logs: pd.DataFrame) -> pd.DataFrame:
    """Build a 1-row-per-game bridge table with home/away starter ids."""
    required = {"gid", "season", "date", "game_num", "home_team", "away_team", "team", "pitcher_id"}
    missing = required - set(starter_game_logs.columns)
    if missing:
        raise ValueError(f"starter_game_logs missing columns: {sorted(missing)}")

    df = starter_game_logs.copy()
    home = df[df["team"] == df["home_team"]][
        ["gid", "pitcher_id", "is_bullpen_no_starter", "is_opener_game"]
    ].rename(
        columns={
            "pitcher_id": "home_starter_id",
            "is_bullpen_no_starter": "home_is_bullpen_no_starter",
            "is_opener_game": "home_is_opener_game",
        }
    )
    away = df[df["team"] == df["away_team"]][
        ["gid", "pitcher_id", "is_bullpen_no_starter", "is_opener_game"]
    ].rename(
        columns={
            "pitcher_id": "away_starter_id",
            "is_bullpen_no_starter": "away_is_bullpen_no_starter",
            "is_opener_game": "away_is_opener_game",
        }
    )

    base_cols = ["gid", "season", "date", "home_team", "away_team", "game_num"]
    base = df[base_cols].drop_duplicates(subset=["gid"], keep="first")
    bridge = base.merge(home, on="gid", how="left").merge(away, on="gid", how="left")

    return bridge


def build_entering_features(
    starter_game_logs: pd.DataFrame,
    *,
    short_window: int = 5,
    long_window: int = 15,
) -> pd.DataFrame:
    """Compute strict entering-game rolling metrics for starter logs.

    The output has the same granularity as `starter_game_logs` (one row per starter-game),
    but every metric is computed ONLY from starts strictly before the current game.
    """
    df = starter_game_logs.copy()
    required = {"pitcher_id", "date", "game_num", "h", "bb", "so", "hr", "er", "outs"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"starter_game_logs missing columns: {sorted(missing)}")

    df = df.sort_values(["pitcher_id", "date", "game_num"]).reset_index(drop=True)
    grp = df.groupby("pitcher_id", sort=False)

    sum_cols = ["h", "bb", "so", "hr", "er", "outs"]
    for c in sum_cols:
        shifted = grp[c].shift(1)
        df[f"{c}_prior_sum"] = shifted.groupby(df["pitcher_id"]).cumsum()
        df[f"{c}_short_sum"] = (
            shifted.groupby(df["pitcher_id"])
            .rolling(short_window, min_periods=1)
            .sum()
            .reset_index(level=0, drop=True)
        )
        df[f"{c}_long_sum"] = (
            shifted.groupby(df["pitcher_id"])
            .rolling(long_window, min_periods=1)
            .sum()
            .reset_index(level=0, drop=True)
        )

    # Starts counts (reliability signals)
    shifted_outs = grp["outs"].shift(1)
    df["starts_prior"] = grp.cumcount()
    df["starts_short"] = (
        shifted_outs.groupby(df["pitcher_id"])
        .rolling(short_window, min_periods=1)
        .count()
        .reset_index(level=0, drop=True)
        .astype(int)
    )
    df["starts_long"] = (
        shifted_outs.groupby(df["pitcher_id"])
        .rolling(long_window, min_periods=1)
        .count()
        .reset_index(level=0, drop=True)
        .astype(int)
    )

    # IP
    for prefix in ["prior", "short", "long"]:
        outs_sum = df[f"outs_{prefix}_sum"]
        df[f"ip_{prefix}"] = outs_sum / 3.0

    # Metrics
    def _whip(h_sum: pd.Series, bb_sum: pd.Series, ip: pd.Series) -> pd.Series:
        return _safe_div(h_sum + bb_sum, ip)

    def _k9(so_sum: pd.Series, ip: pd.Series) -> pd.Series:
        return _safe_div(9.0 * so_sum, ip)

    def _bb9(bb_sum: pd.Series, ip: pd.Series) -> pd.Series:
        return _safe_div(9.0 * bb_sum, ip)

    def _hr9(hr_sum: pd.Series, ip: pd.Series) -> pd.Series:
        return _safe_div(9.0 * hr_sum, ip)

    def _kbb(so_sum: pd.Series, bb_sum: pd.Series) -> pd.Series:
        # Smoothed ratio to avoid inf and reduce small-sample spikes.
        # (SO+1)/(BB+1) is a common pragmatic smoothing.
        return (so_sum + 1.0) / (bb_sum + 1.0)

    for prefix in ["short", "long"]:
        h_sum = df[f"h_{prefix}_sum"]
        bb_sum = df[f"bb_{prefix}_sum"]
        so_sum = df[f"so_{prefix}_sum"]
        hr_sum = df[f"hr_{prefix}_sum"]
        ip = df[f"ip_{prefix}"]

        df[f"whip_{prefix}"] = _whip(h_sum, bb_sum, ip)
        df[f"kbb_{prefix}"] = _kbb(so_sum, bb_sum)
        df[f"k9_{prefix}"] = _k9(so_sum, ip)
        df[f"bb9_{prefix}"] = _bb9(bb_sum, ip)
        df[f"hr9_{prefix}"] = _hr9(hr_sum, ip)
        df[f"ip_{prefix}"] = ip

    # Keep only a focused set of columns: keys + computed features + reliability.
    keep = [
        "gid",
        "season",
        "date",
        "game_num",
        "home_team",
        "away_team",
        "team",
        "is_home",
        "opponent",
        "pitcher_id",
        "starts_prior",
        "ip_prior",
        "starts_short",
        "starts_long",
        "ip_short",
        "ip_long",
        "whip_short",
        "whip_long",
        "kbb_short",
        "kbb_long",
        "k9_short",
        "k9_long",
        "bb9_short",
        "bb9_long",
        "hr9_short",
        "hr9_long",
    ]
    keep = [c for c in keep if c in df.columns]
    return df[keep].copy()


def validate_starter_logs(starter_game_logs: pd.DataFrame) -> dict[str, object]:
    """Run basic validations and return a small structured report."""
    df = starter_game_logs.copy()
    issues: dict[str, object] = {}

    # Expect 2 starters per gid (home + away). Keep numbers for reporting.
    per_gid = df.groupby("gid").size()
    issues["games_total"] = int(per_gid.shape[0])
    issues["games_with_2_starters"] = int((per_gid == 2).sum())
    issues["games_with_not_2_starters"] = int((per_gid != 2).sum())

    # No duplicates per (gid, team)
    dup = df.duplicated(subset=["gid", "team"], keep=False)
    issues["duplicate_gid_team_rows"] = int(dup.sum())

    # Null pitcher_id
    issues["null_pitcher_id_rows"] = int(df["pitcher_id"].isna().sum())

    return issues


def build_report_markdown(
    starter_game_logs: pd.DataFrame,
    *,
    seasons: Iterable[int] | None = None,
) -> str:
    """Build a compact markdown report for coverage & validations."""
    df = starter_game_logs.copy()
    if seasons is not None:
        df = df[df["season"].isin(list(seasons))].copy()

    lines: list[str] = []
    lines.append("# Retrosheet pitchers build report\n")

    # Per-season coverage
    lines.append("## Coverage by season\n")
    lines.append("| season | games | games_with_2_starters | coverage |\n")
    lines.append("|---:|---:|---:|---:|\n")
    for season, g in df.groupby("season"):
        per_gid = g.groupby("gid").size()
        games = int(per_gid.shape[0])
        ok = int((per_gid == 2).sum())
        cov = (ok / games) if games else math.nan
        lines.append(f"| {int(season)} | {games} | {ok} | {cov:.4f} |\n")

    # Bullpen stats
    if "is_bullpen_no_starter" in df.columns:
        lines.append("\n## Bullpen flags (starter rows)\n")
        n = len(df)
        n_bull = int(df["is_bullpen_no_starter"].fillna(False).sum())
        n_open = int(df.get("is_opener_game", False).fillna(False).sum())
        lines.append(f"- total starter rows: {n}\n")
        lines.append(f"- bullpen (no designated starter): {n_bull} ({n_bull / max(n, 1):.2%})\n")
        lines.append(f"- opener games: {n_open} ({n_open / max(n, 1):.2%})\n")

    # Validations summary
    lines.append("\n## Validations\n")
    v = validate_starter_logs(df)
    for k in sorted(v.keys()):
        lines.append(f"- {k}: {v[k]}\n")

    return "".join(lines)


def save_outputs(
    starter_game_logs: pd.DataFrame,
    starter_entering_features: pd.DataFrame,
    game_id_bridge: pd.DataFrame,
    *,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    report_markdown: str | None = None,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    starter_game_logs.to_parquet(output_dir / "starter_game_logs.parquet", index=False)
    starter_entering_features.to_parquet(
        output_dir / "starter_entering_features.parquet", index=False
    )
    game_id_bridge.to_parquet(output_dir / "game_id_bridge.parquet", index=False)

    if report_markdown is not None:
        (output_dir / "build_report.md").write_text(report_markdown, encoding="utf-8")
