"""Regression tests for xlsx -> Retrosheet team-code mapping.

These guard against team-code drift when MLB renames / relocates a franchise.
The immediate motivator is the 2025 Athletics relocation to Sacramento, after
which Retrosheet switched the team code from ``OAK`` to ``ATH``. The xlsx
feeds keep ``OAK``, so without a season-aware remap the inning, starter, and
bullpen joins silently drop all 162 A's games in 2025+.

Any future rename that Retrosheet reflects in their team codes must be added
to ``_map_team_code_to_retrosheet`` and covered by a case here.
"""

from __future__ import annotations

import pytest

from src.data_loader import _map_team_code_to_retrosheet


# ---------------------------------------------------------------------------
# Athletics: OAK (xlsx) <-> OAK (Retrosheet <=2024) / ATH (Retrosheet >=2025)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("season", [2018, 2019, 2022, 2023, 2024])
def test_oak_maps_to_oak_through_2024(season: int) -> None:
    """Pre-relocation seasons keep the legacy ``OAK`` Retrosheet code."""
    assert _map_team_code_to_retrosheet("OAK", season) == "OAK"
    # Reverse: an xlsx row that already carries the modern ``ATH`` code (rare
    # but possible if an upstream source drifts) still lands on the legacy
    # Retrosheet label for these seasons.
    assert _map_team_code_to_retrosheet("ATH", season) == "OAK"


@pytest.mark.parametrize("season", [2025, 2026, 2027])
def test_oak_maps_to_ath_from_2025(season: int) -> None:
    """After the Sacramento relocation Retrosheet uses ``ATH``."""
    assert _map_team_code_to_retrosheet("OAK", season) == "ATH"
    assert _map_team_code_to_retrosheet("ATH", season) == "ATH"


def test_oak_without_season_falls_back_to_legacy() -> None:
    """Season-less callers (pre-pair utilities) keep the historical code.

    This is intentionally conservative: most historical code paths predate
    the relocation and expect ``OAK``. Callers that hit 2025+ data must
    pass the season explicitly.
    """
    assert _map_team_code_to_retrosheet("OAK", None) == "OAK"
    assert _map_team_code_to_retrosheet("ATH", None) == "OAK"


# ---------------------------------------------------------------------------
# Marlins: FLA/FLO -> FLO (<=2011), MIA (>=2012). Existing behavior; guard it.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("season", [2004, 2010, 2011])
def test_marlins_pre_2012_maps_to_flo(season: int) -> None:
    assert _map_team_code_to_retrosheet("FLA", season) == "FLO"
    assert _map_team_code_to_retrosheet("MIA", season) == "FLO"


@pytest.mark.parametrize("season", [2012, 2020, 2025])
def test_marlins_from_2012_maps_to_mia(season: int) -> None:
    assert _map_team_code_to_retrosheet("FLA", season) == "MIA"
    assert _map_team_code_to_retrosheet("MIA", season) == "MIA"


# ---------------------------------------------------------------------------
# Full 2025 lineup: every xlsx team code must resolve to an actual
# Retrosheet 2025 team code. This is the integration-level check that
# would have caught the OAK -> ATH drift.
# ---------------------------------------------------------------------------


# Observed in mlb-odds-2025.xlsx (src.data_loader.RAW_ODDS_DIR).
XLSX_2025_TEAMS: set[str] = {
    "ARI", "ATL", "BAL", "BOS", "CHC", "CHW", "CIN", "CLE", "COL", "DET",
    "HOU", "KCR", "LAA", "LAD", "MIA", "MIL", "MIN", "NYM", "NYY", "OAK",
    "PHI", "PIT", "SDP", "SEA", "SFG", "STL", "TBR", "TEX", "TOR", "WSN",
}

# Retrosheet 2025 team codes. Loaded lazily from the real zip in the
# integration test so this list can stay in lock-step with upstream data,
# but we also keep a static reference here for plain parametrize runs.
RETROSHEET_2025_TEAMS: set[str] = {
    "ANA", "ARI", "ATH", "ATL", "BAL", "BOS", "CHA", "CHN", "CIN", "CLE",
    "COL", "DET", "HOU", "KCA", "LAN", "MIA", "MIL", "MIN", "NYA", "NYN",
    "PHI", "PIT", "SDN", "SEA", "SFN", "SLN", "TBA", "TEX", "TOR", "WAS",
}


@pytest.mark.parametrize("xlsx_code", sorted(XLSX_2025_TEAMS))
def test_every_xlsx_2025_team_resolves_to_a_retrosheet_code(xlsx_code: str) -> None:
    """Every xlsx team must land on a valid Retrosheet 2025 code.

    Parametrizing per team makes the failure message point at the exact
    franchise that drifted.
    """
    rs = _map_team_code_to_retrosheet(xlsx_code, 2025)
    assert rs in RETROSHEET_2025_TEAMS, (
        f"xlsx team {xlsx_code!r} maps to {rs!r}, which is not a valid "
        f"Retrosheet 2025 code. Likely a team rename / relocation that is "
        f"not yet reflected in _map_team_code_to_retrosheet."
    )


def test_retrosheet_2025_codes_match_live_data() -> None:
    """Tighter check: the static reference matches what retrosheet_games
    actually produces for 2025.

    Skipped automatically if the 2025 teamstats zip is not yet downloaded
    (e.g. in a fresh clone); the parametrized test above still runs.
    """
    try:
        from src.retrosheet_games import load_inning_scores_from_teamstats
        ts = load_inning_scores_from_teamstats([2025])
    except Exception as e:  # noqa: BLE001 - fetch/zip errors are environmental
        pytest.skip(f"Retrosheet 2025 teamstats not available: {e}")

    if ts.empty:
        pytest.skip("Retrosheet 2025 teamstats zip is present but empty.")

    live_codes = set(ts["home_team"].unique()) | set(ts["away_team"].unique())
    # NLS / ALS are the All-Star placeholders; ignore them when comparing to
    # the regular-season universe.
    live_regular = {c for c in live_codes if c not in {"ALS", "NLS"}}

    assert live_regular == RETROSHEET_2025_TEAMS, (
        f"Retrosheet 2025 team codes drifted. "
        f"Expected {sorted(RETROSHEET_2025_TEAMS)}, got {sorted(live_regular)}. "
        f"Update RETROSHEET_2025_TEAMS and the mapping in "
        f"_map_team_code_to_retrosheet if a franchise was renamed."
    )
