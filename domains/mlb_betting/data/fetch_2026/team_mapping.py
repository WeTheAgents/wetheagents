"""Map team abbreviations from ESPN and MLB Stats API to our 3-letter codes.

Our canonical codes match the sports-statistics.com xlsx convention used across
the 2004-2025 historical dataset. ESPN and MLB Stats API use slightly different
abbreviations for a handful of teams.
"""

# ESPN scoreboard API abbreviations → our codes.
# Most are identity; only mismatches listed explicitly.
ESPN_TO_CODE = {
    "ARI": "ARI", "ATL": "ATL", "BAL": "BAL", "BOS": "BOS",
    "CHC": "CHC", "CHW": "CHW", "CWS": "CHW", "CIN": "CIN", "CLE": "CLE",
    "COL": "COL", "DET": "DET", "HOU": "HOU", "LAA": "LAA",
    "LAD": "LAD", "MIA": "MIA", "MIL": "MIL", "MIN": "MIN",
    "NYM": "NYM", "NYY": "NYY", "OAK": "OAK", "PHI": "PHI",
    "PIT": "PIT", "SEA": "SEA", "STL": "STL", "TEX": "TEX",
    "TOR": "TOR",
    # Mismatches:
    "KC": "KCR",
    "SD": "SDP",
    "SF": "SFG",
    "TB": "TBR",
    "WSH": "WSN",
    # Sacramento Athletics (2025+), same franchise as Oakland
    "ATH": "OAK",
    # Fallback aliases
    "AZ": "ARI",
    "WAS": "WSN",
}

# MLB Stats API abbreviations — same mapping works (they use identical short codes).
MLB_API_TO_CODE = ESPN_TO_CODE


def normalize_team(abbr: str) -> str:
    """Convert an ESPN or MLB API team abbreviation to our canonical 3-letter code.

    Raises KeyError if the abbreviation is unknown.
    """
    code = ESPN_TO_CODE.get(abbr)
    if code is None:
        raise KeyError(f"Unknown team abbreviation: {abbr!r}")
    return code
