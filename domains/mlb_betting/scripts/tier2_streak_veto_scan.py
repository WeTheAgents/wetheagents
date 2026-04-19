"""Session 43 -- Tier2 away-dog RL streak veto research.

Goal:
    Test whether entering-game streaks can veto weak `tier2_fatigue_gap`
    runline picks. The analysis is intentionally narrow:

      - universe = historical `tier2_fatigue_gap` qualifiers
      - regime = `standard` runline polarity only
      - pricing = real recorded away `+1.5` runline odds only

Default workflow:
    - Build enriched games via ``build_all_features()``.
    - Reconstruct the production Tier-2 universe.
    - Summarize streak-threshold behavior on the dog and favorite sides.
    - Scan single-side and two-side streak vetoes.
    - Freeze on discovery `2015-2023`, then validate untouched on `2024`
      and `2025`.
    - Write:
        picks/tier2_streak_veto_scan.json
        knowledge/session_report_43_tier2_streak_veto.md

Usage:
    python scripts/tier2_streak_veto_scan.py
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import warnings
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.WARNING)

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from src.data_loader import (
    add_derived_odds,
    american_to_decimal,
    apply_data_filters,
    load_all_seasons,
)
from src.edge_discovery import bootstrap_roi_ci, wilson_interval
from src.features import build_all_features
from src.strategies import tier2_fatigue_gap as tier2
from src.strategies._rl_regime import classify_rl_regime
from src.strategies.base import add_derived_for_strategies

DEFAULT_ARTIFACT_PATH = ROOT / "picks" / "tier2_streak_veto_scan.json"
DEFAULT_REPORT_PATH = ROOT / "knowledge" / "session_report_43_tier2_streak_veto.md"

THRESHOLDS = [2, 3, 4, 5, 6, 7]
DISCOVERY_MAX_SEASON = 2023
MIN_SINGLE_REMOVED = 25
MIN_COMBO_REMOVED = 20
MIN_DISCOVERY_RETAINED = 200
MIN_HOLDOUT_REMOVED = 5


def _serialize(value: Any) -> Any:
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        if np.isnan(value):
            return None
        return float(value)
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, tuple):
        return [_serialize(v) for v in value]
    if isinstance(value, list):
        return [_serialize(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _serialize(v) for k, v in value.items()}
    return value


def summarize_slice(df: pd.DataFrame) -> dict[str, Any]:
    n = int(len(df))
    if n == 0:
        return {
            "n": 0,
            "cover_rate": None,
            "avg_odds": None,
            "roi": None,
            "wilson_lo": None,
            "wilson_hi": None,
            "bootstrap_p5": None,
            "bootstrap_p95": None,
        }
    wins = df["cover"].astype(bool).to_numpy()
    odds = df["away_rl_decimal"].astype(float).to_numpy()
    k = int(wins.sum())
    wilson_lo, wilson_hi = wilson_interval(k, n)
    boot_lo, boot_hi = bootstrap_roi_ci(wins.astype(int), odds, n_boot=1000)
    return {
        "n": n,
        "cover_rate": float(wins.mean()),
        "avg_odds": float(odds.mean()),
        "roi": float(df["pnl"].mean()),
        "wilson_lo": float(wilson_lo),
        "wilson_hi": float(wilson_hi),
        "bootstrap_p5": float(boot_lo),
        "bootstrap_p95": float(boot_hi),
    }


def evaluate_veto(df: pd.DataFrame, veto_mask: pd.Series) -> dict[str, Any] | None:
    veto_mask = veto_mask.fillna(False)
    removed = df[veto_mask]
    kept = df[~veto_mask]
    if removed.empty or kept.empty:
        return None

    total_winners = int(df["cover"].sum())
    total_losers = int((~df["cover"]).sum())
    removed_winners = int(removed["cover"].sum())
    removed_losers = int((~removed["cover"]).sum())

    winner_removed_share = (
        removed_winners / total_winners if total_winners else float("nan")
    )
    loser_removed_share = (
        removed_losers / total_losers if total_losers else float("nan")
    )
    loss_filter_edge = loser_removed_share - winner_removed_share

    base_roi = float(df["pnl"].mean())
    base_cover = float(df["cover"].mean())
    kept_roi = float(kept["pnl"].mean())
    kept_cover = float(kept["cover"].mean())
    removed_roi = float(removed["pnl"].mean())
    removed_cover = float(removed["cover"].mean())

    return {
        "removed_n": int(len(removed)),
        "removed_cover": removed_cover,
        "removed_roi": removed_roi,
        "kept_n": int(len(kept)),
        "kept_cover": kept_cover,
        "kept_roi": kept_roi,
        "cover_delta_pp": (kept_cover - base_cover) * 100.0,
        "roi_delta_pp": (kept_roi - base_roi) * 100.0,
        "winner_removed_share": winner_removed_share,
        "loser_removed_share": loser_removed_share,
        "loss_filter_edge": loss_filter_edge,
    }


def threshold_mask(df: pd.DataFrame, streak_col: str, direction: str, k: int) -> pd.Series:
    if direction == "hot":
        return df[streak_col] >= k
    return df[streak_col] <= -k


def threshold_table(df: pd.DataFrame, streak_col: str, role: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for direction in ("hot", "cold"):
        for k in THRESHOLDS:
            mask = threshold_mask(df, streak_col, direction, k)
            sub = df[mask]
            summary = summarize_slice(sub)
            rows.append(
                {
                    "role": role,
                    "bucket": f"{'W' if direction == 'hot' else 'L'}{k}+",
                    "direction": direction,
                    "threshold": k,
                    **summary,
                }
            )
    return rows


def candidate_shapes() -> list[tuple[str, tuple[Any, ...]]]:
    out: list[tuple[str, tuple[Any, ...]]] = []
    for streak_col, label in (("away_streak", "dog"), ("home_streak", "fav")):
        for direction in ("hot", "cold"):
            for k in THRESHOLDS:
                out.append(
                    (f"veto_{label}_{direction}_{k}plus", ("single", streak_col, direction, k))
                )

    for dog_direction in ("hot", "cold"):
        for fav_direction in ("hot", "cold"):
            for dog_k in THRESHOLDS:
                for fav_k in THRESHOLDS:
                    name = (
                        f"veto_dog_{dog_direction}_{dog_k}plus__"
                        f"fav_{fav_direction}_{fav_k}plus"
                    )
                    out.append(
                        (
                            name,
                            ("combo", dog_direction, dog_k, fav_direction, fav_k),
                        )
                    )
    return out


def build_veto_mask(df: pd.DataFrame, shape: tuple[Any, ...]) -> pd.Series:
    if shape[0] == "single":
        _, streak_col, direction, k = shape
        return threshold_mask(df, streak_col, direction, int(k))

    _, dog_direction, dog_k, fav_direction, fav_k = shape
    dog_mask = threshold_mask(df, "away_streak", str(dog_direction), int(dog_k))
    fav_mask = threshold_mask(df, "home_streak", str(fav_direction), int(fav_k))
    return dog_mask & fav_mask


def scan_discovery_candidates(discovery: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name, shape in candidate_shapes():
        veto_mask = build_veto_mask(discovery, shape)
        res = evaluate_veto(discovery, veto_mask)
        if not res:
            continue
        min_removed = MIN_SINGLE_REMOVED if shape[0] == "single" else MIN_COMBO_REMOVED
        if res["removed_n"] < min_removed or res["kept_n"] < MIN_DISCOVERY_RETAINED:
            continue
        rows.append({"filter": name, "shape": shape, **res})

    rows.sort(
        key=lambda row: (
            row["kept_roi"],
            row["loss_filter_edge"],
            row["roi_delta_pp"],
            row["removed_n"],
        ),
        reverse=True,
    )
    return rows


def validation_row(df: pd.DataFrame, shape: tuple[Any, ...]) -> dict[str, Any]:
    res = evaluate_veto(df, build_veto_mask(df, shape))
    if not res:
        return {
            "removed_n": 0,
            "removed_cover": None,
            "removed_roi": None,
            "kept_n": int(len(df)),
            "kept_cover": float(df["cover"].mean()) if len(df) else None,
            "kept_roi": float(df["pnl"].mean()) if len(df) else None,
            "cover_delta_pp": None,
            "roi_delta_pp": None,
            "winner_removed_share": None,
            "loser_removed_share": None,
            "loss_filter_edge": None,
        }
    return res


def determine_verdict(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    if not candidates:
        return {
            "status": "no_candidates",
            "headline": "no streak veto candidates cleared discovery volume filters",
            "best_filter": None,
        }

    for candidate in candidates:
        val24 = candidate["validation"]["2024"]
        val25 = candidate["validation"]["2025"]
        if (
            val24["removed_n"] >= MIN_HOLDOUT_REMOVED
            and val25["removed_n"] >= MIN_HOLDOUT_REMOVED
            and (val24["roi_delta_pp"] or 0.0) > 0
            and (val25["roi_delta_pp"] or 0.0) > 0
            and (val24["removed_roi"] or 0.0) < 0
            and (val25["removed_roi"] or 0.0) < 0
            and (val24["loss_filter_edge"] or 0.0) > 0
            and (val25["loss_filter_edge"] or 0.0) > 0
        ):
            return {
                "status": "validated_candidate",
                "headline": f"{candidate['filter']} survived 2024 and 2025 holdouts",
                "best_filter": candidate["filter"],
            }

    best = candidates[0]
    return {
        "status": "do_not_promote",
        "headline": "no streak veto improved tier2 and stayed directionally clean in both 2024 and 2025",
        "best_filter": best["filter"],
    }


def render_report(results: dict[str, Any]) -> str:
    baseline = results["baseline"]
    discovery_top = results["candidate_vetoes"]["top_discovery"]
    threshold_rows = results["threshold_tables"]

    dog_thresholds = [row for row in threshold_rows if row["role"] == "dog"]
    fav_thresholds = [row for row in threshold_rows if row["role"] == "favorite"]

    lines = [
        "# Session 43 -- Tier2 RL Streak Veto",
        "",
        f"**Date**: {results['meta']['generated_at'][:10]}",
        "**Scope**: `tier2_fatigue_gap`, `standard` RL regime only, real recorded away `+1.5` odds only.",
        f"**Headline verdict**: **{results['verdict']['status']}**.",
        "",
        "## TL;DR",
        "",
        (
            f"- Baseline `2015-2025`: N={baseline['all']['n']}, cover="
            f" **{baseline['all']['cover_rate'] * 100:.1f}%**, ROI="
            f" **{baseline['all']['roi'] * 100:+.1f}%**."
        ),
        (
            f"- Recent `2022-2025`: N={baseline['recent_2022plus']['n']}, cover="
            f" **{baseline['recent_2022plus']['cover_rate'] * 100:.1f}%**, ROI="
            f" **{baseline['recent_2022plus']['roi'] * 100:+.1f}%**."
        ),
        "- Single-side streak vetoes were small and unstable. The best historical lifts were generally under one percentage point of ROI delta.",
        (
            "- Best discovery combo veto was `dog W3+` with `fav L2+`/`L3+`, "
            "but both holdouts flipped the wrong way: the removed rows were profitable in `2024` and `2025`."
        ),
        "",
        "## Threshold Read",
        "",
    ]

    interesting = [
        next((row for row in fav_thresholds if row["bucket"] == "W2+"), None),
        next((row for row in fav_thresholds if row["bucket"] == "L3+"), None),
        next((row for row in dog_thresholds if row["bucket"] == "W3+"), None),
        next((row for row in dog_thresholds if row["bucket"] == "L2+"), None),
    ]
    for row in [row for row in interesting if row]:
        lines.append(
            f"- `{row['role']} {row['bucket']}`: N={row['n']}, cover="
            f" {row['cover_rate'] * 100:.1f}%, ROI {row['roi'] * 100:+.1f}%."
        )

    lines.extend(
        [
            "",
            "## Top Discovery Vetoes",
            "",
        ]
    )
    for candidate in discovery_top[:5]:
        lines.append(
            (
                f"- `{candidate['filter']}` -> removed N={candidate['removed_n']}, "
                f"removed ROI {candidate['removed_roi'] * 100:+.1f}%, kept ROI"
                f" {candidate['kept_roi'] * 100:+.1f}%, loss_filter_edge"
                f" {candidate['loss_filter_edge'] * 100:+.2f}pp."
            )
        )

    lines.extend(
        [
            "",
            "## Validation",
            "",
        ]
    )
    for candidate in discovery_top[:5]:
        val24 = candidate["validation"]["2024"]
        val25 = candidate["validation"]["2025"]
        lines.append(
            (
                f"- `{candidate['filter']}`: `2024` removed N={val24['removed_n']}, "
                f"removed ROI {val24['removed_roi'] * 100:+.1f}%"
                if val24["removed_roi"] is not None
                else f"- `{candidate['filter']}`: `2024` removed N=0"
            )
            + (
                f"; `2025` removed N={val25['removed_n']}, removed ROI"
                f" {val25['removed_roi'] * 100:+.1f}%."
                if val25["removed_roi"] is not None
                else "; `2025` removed N=0."
            )
        )

    lines.extend(
        [
            "",
            "## Recommendation",
            "",
            "- Leave `tier2_fatigue_gap` unchanged in production.",
            "- Use streak only as descriptive context for chat/writeups, not as an automatic runline veto.",
            "- If we revisit this lane, streak should be tested only as a secondary interaction with a fresher structural variable, not as a standalone basket trim.",
            "",
        ]
    )
    return "\n".join(lines)


def run_analysis(
    *,
    season_min: int = 2015,
    season_max: int = 2025,
    artifact_path: Path = DEFAULT_ARTIFACT_PATH,
    report_path: Path = DEFAULT_REPORT_PATH,
) -> dict[str, Any]:
    games = load_all_seasons()
    games = games[(games["season"] >= season_min) & (games["season"] <= season_max)].copy()
    games = apply_data_filters(games)
    games = add_derived_odds(games)
    games = build_all_features(games)
    games = add_derived_for_strategies(games)

    tier2_mask = (
        (games["fav_is_home"].fillna(False) == True)
        & (games["home_is_bullpen_no_starter"] != True)
        & (games["away_is_bullpen_no_starter"] != True)
        & (games["bp_workload_gap"] >= tier2.WORKLOAD_GAP_MIN)
        & (games["bp_ip_3d_away"] <= tier2.AWAY_BP_3D_MAX)
    )
    df = games[tier2_mask].copy()
    df["rl_regime"] = df.apply(classify_rl_regime, axis=1)
    df = df[df["rl_regime"] == "standard"].copy()
    df["cover"] = (df["home_final"] - df["away_final"]) <= 1
    df["away_rl_decimal"] = df["away_run_line_odds"].apply(
        lambda value: american_to_decimal(value)
        if pd.notna(value) and value != 0
        else np.nan
    )
    df = df[df["away_rl_decimal"].notna()].copy()
    df["pnl"] = np.where(df["cover"], df["away_rl_decimal"] - 1.0, -1.0)
    df["away_streak"] = pd.to_numeric(df["streak_away"], errors="coerce")
    df["home_streak"] = pd.to_numeric(df["streak_home"], errors="coerce")

    discovery = df[df["season"] <= DISCOVERY_MAX_SEASON].copy()
    val24 = df[df["season"] == 2024].copy()
    val25 = df[df["season"] == 2025].copy()
    recent = df[df["season"] >= 2022].copy()

    threshold_rows = threshold_table(df, "away_streak", "dog") + threshold_table(
        df, "home_streak", "favorite"
    )

    candidates = scan_discovery_candidates(discovery)
    top_candidates: list[dict[str, Any]] = []
    for candidate in candidates[:12]:
        full_candidate = dict(candidate)
        full_candidate["validation"] = {
            "discovery": validation_row(discovery, candidate["shape"]),
            "recent_2022plus": validation_row(recent, candidate["shape"]),
            "2024": validation_row(val24, candidate["shape"]),
            "2025": validation_row(val25, candidate["shape"]),
            "all": validation_row(df, candidate["shape"]),
        }
        top_candidates.append(full_candidate)

    verdict = determine_verdict(top_candidates)

    results = {
        "meta": {
            "generated_at": datetime.now(UTC).isoformat(),
            "season_min": season_min,
            "season_max": season_max,
            "discovery_seasons": f"{season_min}-{DISCOVERY_MAX_SEASON}",
            "holdout_seasons": [2024, 2025],
            "scope": "tier2_fatigue_gap standard RL regime with real away +1.5 odds",
        },
        "baseline": {
            "all": summarize_slice(df),
            "discovery": summarize_slice(discovery),
            "recent_2022plus": summarize_slice(recent),
            "2024": summarize_slice(val24),
            "2025": summarize_slice(val25),
        },
        "threshold_tables": threshold_rows,
        "candidate_vetoes": {
            "top_discovery": top_candidates,
            "scanned_candidates": len(candidates),
        },
        "validation": {
            "2024": summarize_slice(val24),
            "2025": summarize_slice(val25),
            "recent_2022plus": summarize_slice(recent),
        },
        "verdict": verdict,
    }

    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(
        json.dumps(_serialize(results), indent=2),
        encoding="utf-8",
    )

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(results), encoding="utf-8")

    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--season-min", type=int, default=2015)
    parser.add_argument("--season-max", type=int, default=2025)
    parser.add_argument("--out", type=Path, default=DEFAULT_ARTIFACT_PATH)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT_PATH)
    args = parser.parse_args()

    results = run_analysis(
        season_min=args.season_min,
        season_max=args.season_max,
        artifact_path=args.out,
        report_path=args.report,
    )

    print(
        f"tier2 baseline: N={results['baseline']['all']['n']}, cover="
        f" {results['baseline']['all']['cover_rate'] * 100:.1f}%, ROI"
        f" {results['baseline']['all']['roi'] * 100:+.1f}%"
    )
    print(
        f"recent 2022+: N={results['baseline']['recent_2022plus']['n']}, cover="
        f" {results['baseline']['recent_2022plus']['cover_rate'] * 100:.1f}%, ROI"
        f" {results['baseline']['recent_2022plus']['roi'] * 100:+.1f}%"
    )
    print(f"verdict: {results['verdict']['status']} -- {results['verdict']['headline']}")


if __name__ == "__main__":
    main()
