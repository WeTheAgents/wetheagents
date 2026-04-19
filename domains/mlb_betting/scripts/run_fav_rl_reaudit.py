"""Canonical Fav RL (-1.5) re-audit.

Focus lane: away favorite / home underdog first.
Outputs:
  - knowledge/fav_rl_reaudit_summary.json
  - knowledge/fav_rl_reaudit_report.md
  - knowledge/fav_rl_shadow_report.md
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
warnings.filterwarnings("ignore")

from src.fav_rl_audit import (  # noqa: E402
    BRIDGE_SEASONS,
    CURRENT_SHADOW_FILTER,
    CURRENT_SHADOW_HISTORICAL_P,
    OFFICIAL_SEASONS,
    RESURRECTION_BAR,
    TEST_SEASONS,
    TRAIN_SEASONS,
    bridge_subset,
    build_fav_rl_reaudit_frame,
    build_price_band_stage_rows,
    current_shadow_filter_mask,
    lane_passes_resurrection_bar,
    official_subset,
    pricing_reconciliation,
    scan_rule_filters,
    summarize_flat_bets,
    utc_now_iso,
    write_summary_files,
)


def _stats_row(label: str, stats: dict) -> dict:
    return {
        "label": label,
        "bets": stats["bets"],
        "cover_rate": stats["cover_rate"],
        "avg_odds": stats["avg_odds"],
        "breakeven": stats["breakeven"],
        "cover_minus_breakeven": stats["cover_minus_breakeven"],
        "roi": stats["roi"],
        "max_drawdown_units": stats["max_drawdown_units"],
        "longest_loss_streak": stats["longest_loss_streak"],
        "positive_seasons": stats["positive_seasons"],
    }


def _scan_row(name: str, family: str | None, row: dict) -> dict:
    official = row["official"]
    test = row["test_2025"]
    out = {
        "name": name,
        "official_bets": official["bets"],
        "official_cover_minus_breakeven": official["cover_minus_breakeven"],
        "official_roi": official["roi"],
        "test_2025_roi": test["roi"],
    }
    if family is not None:
        out["family"] = family
    return out


def main() -> int:
    print("Building canonical fav_rl re-audit frame...")
    frame = build_fav_rl_reaudit_frame()

    official = official_subset(frame)
    bridge = bridge_subset(frame)
    official_away = official[official["lane"] == "away_fav_home_dog"].copy()
    official_home = official[official["lane"] == "home_fav"].copy()

    current_shadow_official = official[current_shadow_filter_mask(official)].copy()
    current_shadow_bridge = bridge[current_shadow_filter_mask(bridge)].copy()
    current_shadow_2025 = official[
        current_shadow_filter_mask(official) & official["season"].isin(TEST_SEASONS)
    ].copy()

    official_baselines = [
        _stats_row("unified", summarize_flat_bets(official)),
        _stats_row("home_fav", summarize_flat_bets(official_home)),
        _stats_row("away_fav_home_dog", summarize_flat_bets(official_away)),
    ]
    bridge_baselines = [
        _stats_row("unified", summarize_flat_bets(bridge)),
        _stats_row("home_fav", summarize_flat_bets(bridge[bridge["lane"] == "home_fav"])),
        _stats_row(
            "away_fav_home_dog",
            summarize_flat_bets(bridge[bridge["lane"] == "away_fav_home_dog"]),
        ),
    ]
    current_shadow_rows = [
        _stats_row("official_2021_2025", summarize_flat_bets(current_shadow_official)),
        _stats_row("bridge_2014_2025", summarize_flat_bets(current_shadow_bridge)),
        _stats_row("test_2025", summarize_flat_bets(current_shadow_2025)),
    ]

    band_stage = build_price_band_stage_rows(frame)
    selected_band_rows = [row for row in band_stage if row["selected_for_scan"]]

    if selected_band_rows:
        band_mask = None
        for row in selected_band_rows:
            lo = row["implied_lo"]
            hi = row["implied_hi"]
            mask = (
                (official_away["fav_implied_prob"] >= lo)
                & (official_away["fav_implied_prob"] < hi)
            )
            band_mask = mask if band_mask is None else (band_mask | mask)
        scan_pool = official_away[band_mask].copy()
    else:
        scan_pool = official_away.iloc[0:0].copy()

    rule_scan = scan_rule_filters(scan_pool) if not scan_pool.empty else {
        "singles": [],
        "family_best": [],
        "combos": [],
    }

    shadow_drawdown = summarize_flat_bets(current_shadow_official)["max_drawdown_units"]
    live_candidates: list[dict] = []
    for row in rule_scan["singles"]:
        if lane_passes_resurrection_bar(
            row["official"],
            row["test_2025"],
            shadow_drawdown_units=shadow_drawdown,
        ):
            live_candidates.append(
                {
                    "type": "single",
                    "name": row["name"],
                    "official": row["official"],
                    "test_2025": row["test_2025"],
                }
            )
    for row in rule_scan["combos"]:
        if lane_passes_resurrection_bar(
            row["official"],
            row["test_2025"],
            shadow_drawdown_units=shadow_drawdown,
        ):
            live_candidates.append(
                {
                    "type": "combo",
                    "name": row["name"],
                    "official": row["official"],
                    "test_2025": row["test_2025"],
                }
            )

    live_candidates.sort(
        key=lambda row: (
            float(row["official"]["roi"] or -999.0),
            float(row["official"]["cover_minus_breakeven"] or -999.0),
        ),
        reverse=True,
    )
    best_live = live_candidates[0] if live_candidates else None
    verdict = "revive_live" if best_live is not None else "shadow_only"

    shadow_rows = current_shadow_official.sort_values(
        ["date", "away_team", "home_team"]
    )[
        ["date", "away_team", "home_team", "official_rl_odds", "covers", "fav_margin", "price_source"]
    ].copy()
    shadow_rows["date"] = shadow_rows["date"].dt.strftime("%Y-%m-%d")

    summary = {
        "generated_at": utc_now_iso(),
        "official_seasons": OFFICIAL_SEASONS,
        "bridge_seasons": BRIDGE_SEASONS,
        "train_seasons": TRAIN_SEASONS,
        "test_seasons": TEST_SEASONS,
        "resurrection_bar": RESURRECTION_BAR,
        "verdict": verdict,
        "current_shadow_filter": CURRENT_SHADOW_FILTER,
        "current_shadow_historical_p": CURRENT_SHADOW_HISTORICAL_P,
        "pricing_reconciliation": pricing_reconciliation(official_away),
        "official_baselines": official_baselines,
        "bridge_baselines": bridge_baselines,
        "current_shadow_filter_recheck": current_shadow_rows,
        "price_band_stage": [
            {
                "bucket": row["bucket"],
                "selected_for_scan": row["selected_for_scan"],
                "official_bets": row["official"]["bets"],
                "official_cover_minus_breakeven": row["official"]["cover_minus_breakeven"],
                "official_roi": row["official"]["roi"],
                "test_2025_roi": row["test_2025"]["roi"],
                "train_2021_2024": row["train_2021_2024"],
                "test_2025": row["test_2025"],
                "official": row["official"],
                "bridge_2014_2025": row["bridge_2014_2025"],
            }
            for row in band_stage
        ],
        "rule_scan": {
            "pool_bets": int(len(scan_pool)),
            "pool_cover_rate": float(scan_pool["covers"].mean()) if len(scan_pool) else None,
            "singles": [
                {
                    **_scan_row(row["name"], row["family"], row),
                    "train_2021_2024": row["train_2021_2024"],
                    "official": row["official"],
                    "test_2025": row["test_2025"],
                }
                for row in rule_scan["singles"]
            ],
            "combos": [
                {
                    **_scan_row(row["name"], None, row),
                    "families": row["families"],
                    "train_2021_2024": row["train_2021_2024"],
                    "official": row["official"],
                    "test_2025": row["test_2025"],
                }
                for row in rule_scan["combos"]
            ],
            "live_candidates": live_candidates,
        },
        "selected_live_candidate": best_live,
        "shadow_strategy": {
            "mode": "away_fav_only_current_filter" if best_live is None else "away_fav_live_candidate",
            "label": (
                "away_fav_only_current_filter"
                if best_live is None
                else best_live["name"]
            ),
            "historical_p": CURRENT_SHADOW_HISTORICAL_P if best_live is None else best_live["official"]["cover_rate"],
            "away_fav_only": True,
        },
        "shadow_report_rows": shadow_rows.to_dict(orient="records"),
    }

    write_summary_files(summary)

    print("\n=== Verdict ===")
    print(f"Verdict: {verdict}")
    if best_live is not None:
        print(
            f"Best live candidate: {best_live['name']} | "
            f"official ROI {best_live['official']['roi']:+.3f} | "
            f"2025 ROI {best_live['test_2025']['roi']:+.3f}"
        )
    else:
        print("No away-fav lane cleared the resurrection bar; keeping fav_rl shadow-only.")
        shadow_stats = summarize_flat_bets(current_shadow_official)
        print(
            "Shadow basket (current away-fav filter): "
            f"{shadow_stats['bets']} bets | ROI {shadow_stats['roi']:+.3f} | "
            f"cover-be {shadow_stats['cover_minus_breakeven']:+.3f}"
        )

    print(f"\nSummary -> knowledge/fav_rl_reaudit_summary.json")
    print(f"Report  -> knowledge/fav_rl_reaudit_report.md")
    print(f"Shadow  -> knowledge/fav_rl_shadow_report.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
