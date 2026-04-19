from __future__ import annotations

import json
import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import numpy as np
import pandas as pd

from src.data_loader import enrich_totals_from_sbr, pair_games

BUILD_SBR_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "build_sbr_xlsx.py"
)
BUILD_SBR_SPEC = spec_from_file_location("build_sbr_xlsx", BUILD_SBR_PATH)
assert BUILD_SBR_SPEC and BUILD_SBR_SPEC.loader
build_sbr_xlsx = module_from_spec(BUILD_SBR_SPEC)
sys.modules[BUILD_SBR_SPEC.name] = build_sbr_xlsx
BUILD_SBR_SPEC.loader.exec_module(build_sbr_xlsx)


def test_parse_sbr_reads_totals_key_and_under_odds():
    raw = {
        "2024-04-15": [
            {
                "gameView": {
                    "gameType": "R",
                    "awayTeam": {"shortName": "BOS"},
                    "homeTeam": {"shortName": "CIN"},
                    "awayTeamScore": 3,
                    "homeTeamScore": 2,
                    "gameStatusText": "Final",
                },
                "odds": {
                    "moneyline": [],
                    "pointspread": [],
                    "totals": [
                        {
                            "sportsbook": "draftkings",
                            "openingLine": {"total": 8.0, "overOdds": -108, "underOdds": -112},
                            "currentLine": {"total": 7.5, "overOdds": 100, "underOdds": -122},
                        }
                    ],
                },
            }
        ]
    }

    parsed = build_sbr_xlsx.parse_sbr(raw, 2024)

    assert len(parsed) == 1
    row = parsed.iloc[0]
    assert row["open_ou"] == 8.0
    assert row["close_ou"] == 7.5
    assert row["open_ou_under_odds"] == -112
    assert row["close_ou_under_odds"] == -122
    assert row["open_ou_over_odds"] == -108
    assert row["close_ou_over_odds"] == 100


def test_pair_games_and_sbr_enrichment_keep_under_alias(tmp_path: Path):
    raw_rows = pd.DataFrame(
        [
            {
                "date": pd.Timestamp("2024-04-15"),
                "season": 2024,
                "month": 4,
                "day": 15,
                "vh": "V",
                "team": "BOS",
                "pitcher": "P1",
                "final": 3,
                "open_ml": 110,
                "close_ml": 120,
                "run_line": 1.5,
                "run_line_odds": -145,
                "open_ou": 8.0,
                "open_ou_odds": -112,
                "close_ou": 7.5,
                "close_ou_odds": -122,
                **{f"inn_{i}": 0 for i in range(1, 10)},
            },
            {
                "date": pd.Timestamp("2024-04-15"),
                "season": 2024,
                "month": 4,
                "day": 15,
                "vh": "H",
                "team": "CIN",
                "pitcher": "P2",
                "final": 2,
                "open_ml": -130,
                "close_ml": -140,
                "run_line": -1.5,
                "run_line_odds": 125,
                "open_ou": 8.0,
                "open_ou_odds": -108,
                "close_ou": 7.5,
                "close_ou_odds": 100,
                **{f"inn_{i}": 0 for i in range(1, 10)},
            },
        ]
    )

    paired = pair_games(raw_rows)
    assert paired.loc[0, "open_ou_odds_under"] == -112
    assert paired.loc[0, "close_ou_odds_under"] == -122

    games = paired.copy()
    games["open_ou_odds_under"] = np.nan
    games["close_ou_odds_under"] = np.nan
    games["open_ou"] = np.nan
    games["close_ou"] = np.nan

    sbr_json = {
        "2024-04-15": [
            {
                "gameView": {
                    "gameType": "R",
                    "awayTeam": {"shortName": "BOS"},
                    "homeTeam": {"shortName": "CIN"},
                },
                "odds": {
                    "totals": [
                        {
                            "sportsbook": "draftkings",
                            "openingLine": {"total": 8.0, "underOdds": -112},
                            "currentLine": {"total": 7.5, "underOdds": -122},
                        }
                    ]
                },
            }
        ]
    }
    sbr_path = tmp_path / "sbr.json"
    sbr_path.write_text(json.dumps(sbr_json), encoding="utf-8")

    enriched = enrich_totals_from_sbr(games, json_paths=[sbr_path], seasons=[2024])

    assert enriched.loc[0, "open_ou"] == 8.0
    assert enriched.loc[0, "close_ou"] == 7.5
    assert enriched.loc[0, "open_ou_odds_under"] == -112
    assert enriched.loc[0, "close_ou_odds_under"] == -122
