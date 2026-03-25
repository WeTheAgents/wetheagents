"""Team name canonicalization between football-data.co.uk and FBref.

Uses a static mapping file (data/static/team_name_map.json) that maps
every observed team name variant to a canonical 3-letter code.

The mapping is BOOTSTRAPPED via fuzzy matching, then MANUALLY reviewed
and committed. This avoids runtime fuzzy matching errors.

Brazilian Serie A has ~30 unique teams across 3 seasons — small enough
for manual verification.

Usage:
    from src.team_names import canonicalize, load_team_map

    df["home_team"] = df["Home"].map(canonicalize)
"""

import json
from functools import lru_cache
from pathlib import Path

MAP_PATH = Path(__file__).parent.parent / "data" / "static" / "team_name_map.json"

# Canonical codes for Brazilian Serie A teams (2019-2023 scope)
# This is the seed for the static mapping — covers the most common teams
CANONICAL_TEAMS = {
    "FLA": "Flamengo",
    "PAL": "Palmeiras",
    "CAM": "Atletico Mineiro",
    "CAP": "Athletico Paranaense",
    "INT": "Internacional",
    "SAO": "Sao Paulo",
    "COR": "Corinthians",
    "GRE": "Gremio",
    "FLU": "Fluminense",
    "SAN": "Santos",
    "FOR": "Fortaleza",
    "CEA": "Ceara",
    "BAH": "Bahia",
    "BOT": "Botafogo",
    "BRA": "Bragantino",
    "GOI": "Goias",
    "CUI": "Cuiaba",
    "AME": "America Mineiro",
    "JUV": "Juventude",
    "CFC": "Coritiba",
    "AVA": "Avai",
    "DER": "Sport Recife",
    "REC": "Sport Recife",
    "CSA": "CSA",
    "CHA": "Chapecoense",
    "VAS": "Vasco da Gama",
    "CRU": "Cruzeiro",
    "VIT": "Vitoria",
    "ACG": "Atletico Goianiense",
}


@lru_cache(maxsize=1)
def load_team_map() -> dict[str, str]:
    """Load the static team name mapping from JSON file."""
    if not MAP_PATH.exists():
        raise FileNotFoundError(
            f"Team name map not found at {MAP_PATH}. "
            "Run bootstrap_team_map() first to generate it."
        )
    with open(MAP_PATH, encoding="utf-8") as f:
        return json.load(f)


def canonicalize(name: str) -> str:
    """Resolve a team name to its canonical 3-letter code.

    Raises KeyError if name not in mapping.
    """
    mapping = load_team_map()
    if name not in mapping:
        raise KeyError(
            f"Unknown team name: '{name}'. "
            f"Add it to {MAP_PATH} and re-run."
        )
    return mapping[name]


def bootstrap_team_map(
    odds_teams: list[str],
    fbref_teams: list[str],
    threshold: int = 75,
) -> dict[str, str]:
    """One-time helper: generate initial team_name_map.json via fuzzy matching.

    Args:
        odds_teams: unique team names from football-data.co.uk
        fbref_teams: unique team names from FBref
        threshold: minimum fuzzy match score (0-100)

    Returns:
        dict mapping every variant to a canonical code
    """
    from thefuzz import process

    all_names = sorted(set(odds_teams) | set(fbref_teams))
    mapping: dict[str, str] = {}

    # First pass: match each name to the canonical teams list
    canonical_names = list(CANONICAL_TEAMS.values())
    canonical_codes = list(CANONICAL_TEAMS.keys())

    for name in all_names:
        best_match, score = process.extractOne(name, canonical_names)
        if score >= threshold:
            idx = canonical_names.index(best_match)
            code = canonical_codes[idx]
            mapping[name] = code
            print(f"  {name:30s} -> {code} ({best_match}, score={score})")
        else:
            mapping[name] = f"???_{name}"
            print(f"  {name:30s} -> ??? (best: {best_match}, score={score}) ** REVIEW **")

    # Save
    MAP_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(MAP_PATH, "w", encoding="utf-8") as f:
        json.dump(mapping, f, indent=2, ensure_ascii=False, sort_keys=True)

    print(f"\n  Saved {len(mapping)} entries to {MAP_PATH}")
    print("  Review and correct any '???' entries manually.")
    return mapping
