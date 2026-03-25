"""Build batter rolling features from Retrosheet batting.csv.

One-time script — run this before NRFI backtesting.

Usage:
    python scripts/build_retrosheet_batters.py
"""

import sys
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

from src.retrosheet_batters import build_and_save

if __name__ == "__main__":
    print("Building batter features from Retrosheet...")
    result = build_and_save()
    if not result.empty:
        print(f"\nDone! {len(result)} team-game lineup feature rows.")
        print(f"Columns: {list(result.columns)}")
        print(f"\nSample stats:")
        for col in ["top3_obp_short", "top3_k_rate_short", "top3_obp_vs_rhp", "top3_obp_vs_lhp"]:
            if col in result.columns:
                print(f"  {col}: mean={result[col].mean():.3f}, "
                      f"non-null={result[col].notna().sum()}/{len(result)}")
    else:
        print("ERROR: No data produced.")
