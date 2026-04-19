"""OVER bullpen mismatch (Sess 33b).

Pattern: bet OVER when all three hold simultaneously:
  1) Offense expects more runs than market is pricing
     → rpg_vs_line = combined_rpg - close_ou >= 2.0
  2) Both bullpens are tired / bad last 7 games
     → bullpen_fip_7g_combined = bp_fip_7g_home + bp_fip_7g_away >= 7.5
  3) Neither starter is a quality anchor
     → sp_fip_floor_short = max(home_sp_fip_short, away_sp_fip_short) >= 4.5

Backtest (Sess 33b, 2010-2025 walk-forward):
  → N = 298 games (~20/season), Over% 61.7%, ROI +17.9%
  → 10%-trim 57.6%, era-stable (pre-2021 63% vs modern 60%)
  → 12/15 profitable seasons, bad years 2016/2021/2024

Two-pick pattern for 2x sizing (see audit plan Phase 2):
  - Base pick: `over_bullpen_mismatch`, historical_p = 0.617
  - Power pick (emitted ADDITIONALLY if power trigger fires):
      `over_bullpen_mismatch_power`, historical_p = 0.74
      Power trigger: bullpen_fip_7g_combined >= 10.0
                     OR close_ou <= 8.0
  Two picks with higher p → higher Kelly stake organically. The generator's
  dedup (same market+side on same game) is keyed on tier, so both survive.

Reference odds: flat -110 on OVER (decimal 1.909) — O/U market lacks
per-book odds in the current xlsx schema; the generator's Polymarket layer
will override with live prices when available.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from .base import Pick, feature_snapshot

TIER_BASE = "over_bullpen_mismatch"
TIER_POWER = "over_bullpen_mismatch_power"

P_BASE = 0.617   # Sess 33b full-population over rate
P_POWER = 0.74   # Sess 33b power-bucket over rate (FIP>=10 or line<=8)

RPG_MIN = 2.0
BULLPEN_FIP_MIN = 7.5
SP_QUALITY_FLOOR_MIN = 4.5

POWER_BULLPEN_FIP = 10.0
POWER_CLOSE_OU = 8.0

REF_ODDS_OVER = 1.909   # -110 default

SNAPSHOT_COLS = [
    "combined_rpg",
    "close_ou",
    "rpg_vs_line",
    "bullpen_fip_7g_combined",
    "bp_fip_7g_home",
    "bp_fip_7g_away",
    "sp_fip_floor_short",
    "home_sp_fip_short",
    "away_sp_fip_short",
]


def find_picks(games: pd.DataFrame, target_date: date) -> list[Pick]:
    if games.empty:
        return []

    df = games[games["date"].dt.date == target_date] if hasattr(
        games["date"].iloc[0], "date"
    ) else games[games["date"] == target_date]

    if df.empty:
        return []

    required = ["rpg_vs_line", "bullpen_fip_7g_combined", "sp_fip_floor_short",
                "close_ou"]
    if any(c not in df.columns for c in required):
        return []

    mask = (
        (df["rpg_vs_line"] >= RPG_MIN)
        & (df["bullpen_fip_7g_combined"] >= BULLPEN_FIP_MIN)
        & (df["sp_fip_floor_short"] >= SP_QUALITY_FLOOR_MIN)
    )
    qualified = df[mask]

    picks: list[Pick] = []
    for _, row in qualified.iterrows():
        snap = feature_snapshot(row, SNAPSHOT_COLS)
        base_reason = (
            f"rpg_vs_line={row['rpg_vs_line']:.2f}≥{RPG_MIN}"
            f" & bullpen_fip_7g={row['bullpen_fip_7g_combined']:.2f}≥{BULLPEN_FIP_MIN}"
            f" & sp_floor={row['sp_fip_floor_short']:.2f}≥{SP_QUALITY_FLOOR_MIN}"
        )

        picks.append(
            Pick.make(
                target_date=target_date,
                away=str(row["away_team"]),
                home=str(row["home_team"]),
                market="O/U",
                side="over",
                tier=TIER_BASE,
                historical_p=P_BASE,
                ref_odds_espn=REF_ODDS_OVER,
                market_line=float(row["close_ou"]),
                reason=base_reason,
                feature_snapshot=snap,
            )
        )

        # Power trigger — emit a SECOND pick so Kelly ramps to effectively 2x.
        power_fip = row["bullpen_fip_7g_combined"] >= POWER_BULLPEN_FIP
        power_line = row["close_ou"] <= POWER_CLOSE_OU
        if bool(power_fip) or bool(power_line):
            triggers = []
            if power_fip:
                triggers.append(
                    f"bullpen_fip_7g={row['bullpen_fip_7g_combined']:.2f}"
                    f"≥{POWER_BULLPEN_FIP}"
                )
            if power_line:
                triggers.append(f"close_ou={row['close_ou']:.1f}≤{POWER_CLOSE_OU}")
            power_reason = base_reason + " | POWER: " + " | ".join(triggers)

            picks.append(
                Pick.make(
                    target_date=target_date,
                    away=str(row["away_team"]),
                    home=str(row["home_team"]),
                    market="O/U",
                    side="over",
                    tier=TIER_POWER,
                    historical_p=P_POWER,
                    ref_odds_espn=REF_ODDS_OVER,
                    market_line=float(row["close_ou"]),
                    reason=power_reason,
                    feature_snapshot=snap,
                )
            )

    return picks
