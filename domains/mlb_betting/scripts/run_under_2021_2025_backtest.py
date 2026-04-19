"""Canonical UNDER validation with real odds, calibration, drawdown, and veto scan."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import matplotlib
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from src.features import OU_FEATURES, build_ou_features
from src.model import UnderModelConfig
from src.under_live import (
    UNDER_BASE_THRESHOLD,
    UNDER_POWER_THRESHOLD,
)
from src.under_reporting import (
    compute_calibration_summary,
    compute_reliability_table,
    evaluate_under_threshold,
    run_under_walk_forward_single_year,
    scan_under_modifier_candidates,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
KNOWLEDGE_DIR = ROOT / "knowledge"
SUMMARY_PATH = KNOWLEDGE_DIR / "under_live_recheck_summary.json"
CALIBRATION_PLOT = KNOWLEDGE_DIR / "under_reliability_2021_2025.png"
OFFICIAL_PNL_PLOT = KNOWLEDGE_DIR / "under_real_odds_pnl_2021_2025.png"
BRIDGE_PNL_PLOT = KNOWLEDGE_DIR / "under_flat110_pnl_2010_2025.png"


def _feature_list(frame):
    return [feature for feature in OU_FEATURES if feature in frame.columns and frame[feature].notna().mean() > 0.3]


def _json_default(value):
    if isinstance(value, (np.integer, np.floating, np.bool_)):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Unsupported JSON value: {type(value)!r}")


def _plot_reliability(reliability, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(7, 7))
    ax.plot([0, 1], [0, 1], "k--", alpha=0.5, label="Perfect calibration")
    ax.plot(
        reliability["mean_predicted"],
        reliability["actual_rate"],
        "o-",
        color="#1f77b4",
        label="2021-2025 real-odds validation",
    )
    for _, row in reliability.iterrows():
        ax.annotate(
            f"n={int(row['n_games'])}",
            (row["mean_predicted"], row["actual_rate"]),
            textcoords="offset points",
            xytext=(4, 4),
            fontsize=8,
        )
    ax.set_xlabel("Mean predicted P(under)")
    ax.set_ylabel("Actual under rate")
    ax.set_title("UNDER Reliability (2021-2025)")
    ax.grid(True, alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def _plot_cumulative_units(preds, *, threshold: float, odds_col: str | None, fallback_decimal: float | None, path: Path, title: str) -> None:
    metrics = evaluate_under_threshold(
        preds,
        label=f"P>={threshold:.2f}",
        min_prob=threshold,
        odds_col=odds_col,
        fallback_decimal=fallback_decimal,
    )
    subset = preds[preds["p_under"] >= threshold].copy()
    subset = subset.sort_values(["date", "away_team", "home_team"]).reset_index(drop=True)
    if subset.empty:
        return
    if odds_col is None:
        bet_decimal = np.full(len(subset), float(fallback_decimal))
    else:
        from src.under_reporting import _resolve_decimal_odds  # noqa: PLC0415

        bet_decimal = _resolve_decimal_odds(
            subset,
            odds_col=odds_col,
            fallback_decimal=fallback_decimal,
        ).to_numpy()
    pnl = np.where(subset["under_hit"].astype(int).to_numpy() == 1, bet_decimal - 1.0, -1.0)
    cumulative = np.cumsum(pnl)

    fig, ax = plt.subplots(figsize=(12, 4.5))
    ax.plot(subset["date"], cumulative, color="#2a9d8f", linewidth=2)
    ax.axhline(0.0, color="black", linewidth=1, alpha=0.5)
    ax.set_title(
        f"{title}\nROI {metrics.roi_pct:+.1f}% | Max DD {metrics.max_drawdown_pct:.1f}% | Bets {metrics.bets}"
    )
    ax.set_ylabel("Cumulative units")
    ax.grid(True, alpha=0.25)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def _print_threshold(label, metrics) -> None:
    print(
        f"  {label:<20} bets={metrics.bets:4d} hit={metrics.hit_rate*100:5.1f}% "
        f"roi={metrics.roi_pct:+6.1f}% dd={metrics.max_drawdown_pct:5.1f}% "
        f"loss_streak={metrics.longest_loss_streak:2d}"
    )


def main() -> int:
    print("=" * 86)
    print("UNDER LIVE PROMOTION RECHECK")
    print("=" * 86)

    logger.info("Building O/U feature frame for canonical UNDER validation...")
    full = build_ou_features()
    full = full[full["season"] <= 2025].copy()
    features = _feature_list(full)
    cfg = UnderModelConfig()
    preds = run_under_walk_forward_single_year(full, features, cfg=cfg)

    official = preds[preds["season"].between(2021, 2025)].copy()
    bridge = preds[preds["season"].between(2010, 2025)].copy()

    official_reliability = compute_reliability_table(official)
    official_calibration = compute_calibration_summary(official)
    bridge_calibration = compute_calibration_summary(bridge)

    official_base = evaluate_under_threshold(
        official,
        label="under_totals",
        min_prob=UNDER_BASE_THRESHOLD,
        odds_col="close_ou_odds_under",
        fallback_decimal=None,
    )
    official_power = evaluate_under_threshold(
        official,
        label="under_totals_power",
        min_prob=UNDER_POWER_THRESHOLD,
        odds_col="close_ou_odds_under",
        fallback_decimal=None,
    )
    bridge_base = evaluate_under_threshold(
        bridge,
        label="under_totals",
        min_prob=UNDER_BASE_THRESHOLD,
    )
    bridge_power = evaluate_under_threshold(
        bridge,
        label="under_totals_power",
        min_prob=UNDER_POWER_THRESHOLD,
    )
    modifier_scan = scan_under_modifier_candidates(
        official,
        odds_col="close_ou_odds_under",
        fallback_decimal=None,
    )

    KNOWN_METRICS = {
        "official_real_odds_2021_2025": {
            "calibration": official_calibration,
            "reliability_table": official_reliability.to_dict(orient="records"),
            "thresholds": {
                "under_totals": official_base.__dict__,
                "under_totals_power": official_power.__dict__,
            },
        },
        "bridge_flat_110_2010_2025": {
            "calibration": bridge_calibration,
            "thresholds": {
                "under_totals": bridge_base.__dict__,
                "under_totals_power": bridge_power.__dict__,
            },
        },
        "modifier_scan": modifier_scan,
        "features": features,
        "prediction_counts": {
            "official_real_odds_2021_2025": int(len(official)),
            "bridge_flat_110_2010_2025": int(len(bridge)),
        },
    }
    SUMMARY_PATH.write_text(
        json.dumps(KNOWN_METRICS, indent=2, default=_json_default),
        encoding="utf-8",
    )

    if not official_reliability.empty:
        _plot_reliability(official_reliability, CALIBRATION_PLOT)
    _plot_cumulative_units(
        official,
        threshold=UNDER_BASE_THRESHOLD,
        odds_col="close_ou_odds_under",
        fallback_decimal=None,
        path=OFFICIAL_PNL_PLOT,
        title="UNDER cumulative PnL (2021-2025 real close odds)",
    )
    _plot_cumulative_units(
        bridge,
        threshold=UNDER_BASE_THRESHOLD,
        odds_col=None,
        fallback_decimal=1.909,
        path=BRIDGE_PNL_PLOT,
        title="UNDER cumulative PnL (2010-2025 flat -110 bridge)",
    )

    print("\nOfficial 2021-2025 (real under-side close odds):")
    print(
        f"  calibration: auc={official_calibration['auc']:.4f} "
        f"brier={official_calibration['brier']:.4f} "
        f"logloss={official_calibration['logloss']:.4f} "
        f"ece10={official_calibration['ece_10']:.4f}"
    )
    _print_threshold("under_totals", official_base)
    _print_threshold("under_totals_power", official_power)

    print("\nBridge 2010-2025 (flat -110):")
    print(
        f"  calibration: auc={bridge_calibration['auc']:.4f} "
        f"brier={bridge_calibration['brier']:.4f} "
        f"logloss={bridge_calibration['logloss']:.4f} "
        f"ece10={bridge_calibration['ece_10']:.4f}"
    )
    _print_threshold("under_totals", bridge_base)
    _print_threshold("under_totals_power", bridge_power)

    print("\nBullpen marginal veto scan:")
    selected = modifier_scan.get("selected")
    for candidate in modifier_scan.get("candidates", []):
        print(
            f"  {candidate['quantile_label']:<4} roi_delta={candidate['roi_delta_pct_points']:+5.2f}pp "
            f"dd_delta={candidate['drawdown_delta_pct_points']:+5.2f}pp "
            f"volume={candidate['volume_retained']*100:5.1f}% "
            f"live={'YES' if candidate['pass_live'] else 'no'}"
        )
    if selected is not None:
        print(
            f"  selected live modifier: {selected['quantile_label']} "
            f"(roi_delta={selected['roi_delta_pct_points']:+.2f}pp, "
            f"dd_delta={selected['drawdown_delta_pct_points']:+.2f}pp)"
        )
    else:
        print("  selected live modifier: none (shadow/advisory only)")

    print("\nArtifacts:")
    print(f"  summary: {SUMMARY_PATH}")
    print(f"  reliability plot: {CALIBRATION_PLOT}")
    print(f"  real-odds pnl plot: {OFFICIAL_PNL_PLOT}")
    print(f"  bridge pnl plot: {BRIDGE_PNL_PLOT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
