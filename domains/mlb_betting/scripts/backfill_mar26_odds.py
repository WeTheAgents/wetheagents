"""Backfill March 26, 2026 Opening Day odds from FanDuel.

ESPN pregame snapshot was missed for Opening Day. Odds recovered from
FanDuel Research articles (accessed 2026-03-29).

Source: https://www.fanduel.com/research/mlb (individual game pages)
Book: FanDuel Sportsbook

Run once:
    python scripts/backfill_mar26_odds.py
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PARQUET_PATH = Path(__file__).resolve().parent.parent / "data" / "raw" / "odds_2026" / "games_2026.parquet"
XLSX_PATH = Path(__file__).resolve().parent.parent / "data" / "raw" / "odds" / "mlb-odds-2026.xlsx"

XLSX_COLUMNS = [
    "date", "rot", "vh", "team", "pitcher",
    "inn_1", "inn_2", "inn_3", "inn_4", "inn_5",
    "inn_6", "inn_7", "inn_8", "inn_9", "final",
    "open_ml", "close_ml",
    "run_line", "run_line_odds",
    "open_ou", "open_ou_odds", "close_ou", "close_ou_odds",
]

# FanDuel odds for March 26, 2026 — all 11 Opening Day games.
# Convention: visitor row first, then home row (matching our xlsx schema).
# run_line: favorite gets -1.5, underdog gets +1.5 (standard MLB run line).
# open_ou_odds: over odds for home team row, under odds for away team row.
FANDUEL_ODDS = [
    # BOS @ CIN — Red Sox -158 fav
    {"team": "BOS", "vh": "V", "open_ml": -158, "close_ml": -158, "run_line": -1.5, "run_line_odds": 110,  "open_ou": 8.0, "open_ou_odds": -112, "close_ou": 8.0, "close_ou_odds": -112},
    {"team": "CIN", "vh": "H", "open_ml":  134, "close_ml":  134, "run_line":  1.5, "run_line_odds": -132, "open_ou": 8.0, "open_ou_odds": -108, "close_ou": 8.0, "close_ou_odds": -108},

    # MIN @ BAL — Orioles -138 fav
    {"team": "MIN", "vh": "V", "open_ml":  118, "close_ml":  118, "run_line":  1.5, "run_line_odds": -176, "open_ou": 8.5, "open_ou_odds": -118, "close_ou": 8.5, "close_ou_odds": -118},
    {"team": "BAL", "vh": "H", "open_ml": -138, "close_ml": -138, "run_line": -1.5, "run_line_odds": 146,  "open_ou": 8.5, "open_ou_odds": -104, "close_ou": 8.5, "close_ou_odds": -104},

    # PIT @ NYM — Mets -118 fav
    {"team": "PIT", "vh": "V", "open_ml":  100, "close_ml":  100, "run_line":  1.5, "run_line_odds": -194, "open_ou": 7.0, "open_ou_odds": 100,  "close_ou": 7.0, "close_ou_odds": 100},
    {"team": "NYM", "vh": "H", "open_ml": -118, "close_ml": -118, "run_line": -1.5, "run_line_odds": 158,  "open_ou": 7.0, "open_ou_odds": -122, "close_ou": 7.0, "close_ou_odds": -122},

    # TEX @ PHI — Phillies -162 fav
    {"team": "TEX", "vh": "V", "open_ml":  136, "close_ml":  136, "run_line":  1.5, "run_line_odds": -164, "open_ou": 8.0, "open_ou_odds": -112, "close_ou": 8.0, "close_ou_odds": -112},
    {"team": "PHI", "vh": "H", "open_ml": -162, "close_ml": -162, "run_line": -1.5, "run_line_odds": 136,  "open_ou": 8.0, "open_ou_odds": -108, "close_ou": 8.0, "close_ou_odds": -108},

    # LAA @ HOU — Astros -184 fav
    {"team": "LAA", "vh": "V", "open_ml":  154, "close_ml":  154, "run_line":  1.5, "run_line_odds": -146, "open_ou": 8.0, "open_ou_odds": -108, "close_ou": 8.0, "close_ou_odds": -108},
    {"team": "HOU", "vh": "H", "open_ml": -184, "close_ml": -184, "run_line": -1.5, "run_line_odds": 122,  "open_ou": 8.0, "open_ou_odds": -112, "close_ou": 8.0, "close_ou_odds": -112},

    # CHW @ MIL — Brewers -184 fav
    {"team": "CHW", "vh": "V", "open_ml":  154, "close_ml":  154, "run_line":  1.5, "run_line_odds": -140, "open_ou": 7.5, "open_ou_odds": 100,  "close_ou": 7.5, "close_ou_odds": 100},
    {"team": "MIL", "vh": "H", "open_ml": -184, "close_ml": -184, "run_line": -1.5, "run_line_odds": 116,  "open_ou": 7.5, "open_ou_odds": -122, "close_ou": 7.5, "close_ou_odds": -122},

    # TBR @ STL — Rays -130 fav
    {"team": "TBR", "vh": "V", "open_ml": -130, "close_ml": -130, "run_line": -1.5, "run_line_odds": 130,  "open_ou": 8.0, "open_ou_odds": -112, "close_ou": 8.0, "close_ou_odds": -112},
    {"team": "STL", "vh": "H", "open_ml":  110, "close_ml":  110, "run_line":  1.5, "run_line_odds": -156, "open_ou": 8.0, "open_ou_odds": -108, "close_ou": 8.0, "close_ou_odds": -108},

    # WSN @ CHC — Cubs -210 fav
    {"team": "WSN", "vh": "V", "open_ml":  176, "close_ml":  176, "run_line":  1.5, "run_line_odds": -142, "open_ou": 7.0, "open_ou_odds": -110, "close_ou": 7.0, "close_ou_odds": -110},
    {"team": "CHC", "vh": "H", "open_ml": -210, "close_ml": -210, "run_line": -1.5, "run_line_odds": 118,  "open_ou": 7.0, "open_ou_odds": -110, "close_ou": 7.0, "close_ou_odds": -110},

    # ARI @ LAD — Dodgers -260 fav
    {"team": "ARI", "vh": "V", "open_ml":  215, "close_ml":  215, "run_line":  1.5, "run_line_odds": 106,  "open_ou": 9.0, "open_ou_odds": -118, "close_ou": 9.0, "close_ou_odds": -118},
    {"team": "LAD", "vh": "H", "open_ml": -260, "close_ml": -260, "run_line": -1.5, "run_line_odds": -128, "open_ou": 9.0, "open_ou_odds": -104, "close_ou": 9.0, "close_ou_odds": -104},

    # CLE @ SEA — Mariners -188 fav
    {"team": "CLE", "vh": "V", "open_ml":  158, "close_ml":  158, "run_line":  1.5, "run_line_odds": -144, "open_ou": 6.5, "open_ou_odds": 100,  "close_ou": 6.5, "close_ou_odds": 100},
    {"team": "SEA", "vh": "H", "open_ml": -188, "close_ml": -188, "run_line": -1.5, "run_line_odds": 120,  "open_ou": 6.5, "open_ou_odds": -122, "close_ou": 6.5, "close_ou_odds": -122},

    # DET @ SDP — Tigers -126 fav
    {"team": "DET", "vh": "V", "open_ml": -126, "close_ml": -126, "run_line": -1.5, "run_line_odds": 140,  "open_ou": 7.0, "open_ou_odds": -114, "close_ou": 7.0, "close_ou_odds": -114},
    {"team": "SDP", "vh": "H", "open_ml":  108, "close_ml":  108, "run_line":  1.5, "run_line_odds": -170, "open_ou": 7.0, "open_ou_odds": -106, "close_ou": 7.0, "close_ou_odds": -106},
]

ODDS_COLS = [
    "open_ml", "close_ml", "run_line", "run_line_odds",
    "open_ou", "open_ou_odds", "close_ou", "close_ou_odds",
]


def main() -> None:
    df = pd.read_parquet(PARQUET_PATH)
    mar26 = df["date"] == 326

    before_nans = df.loc[mar26, "open_ml"].isna().sum()
    print(f"March 26 rows: {mar26.sum()}, with NaN odds: {before_nans}")

    if before_nans == 0:
        print("No NaN odds to fill — already patched.")
        return

    odds_lookup = {(r["team"], r["vh"]): r for r in FANDUEL_ODDS}

    patched = 0
    for idx in df.index[mar26]:
        key = (df.at[idx, "team"], df.at[idx, "vh"])
        if key in odds_lookup:
            row = odds_lookup[key]
            for col in ODDS_COLS:
                if pd.isna(df.at[idx, col]) or df.at[idx, col] is None:
                    df.at[idx, col] = row[col]
            patched += 1
        else:
            print(f"  WARNING: no odds found for {key}")

    after_nans = df.loc[mar26, "open_ml"].isna().sum()
    print(f"Patched {patched} rows. Remaining NaN odds: {after_nans}")

    # Save parquet
    df.to_parquet(PARQUET_PATH, index=False)
    print(f"Saved: {PARQUET_PATH}")

    # Export xlsx
    out = df[XLSX_COLUMNS].copy()
    out.to_excel(XLSX_PATH, index=False, header=True)
    size_kb = XLSX_PATH.stat().st_size / 1024
    print(f"Exported: {XLSX_PATH} ({size_kb:.0f} KB, {len(out)} rows)")


if __name__ == "__main__":
    main()
