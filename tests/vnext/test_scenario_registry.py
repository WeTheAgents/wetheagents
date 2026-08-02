from __future__ import annotations

import re
from pathlib import Path

from .scenarios import (
    ACCEPTED_FUTURE_SCENARIO_IDS,
    CHANGED_SCENARIO_IDS,
    COMPATIBLE_SCENARIO_IDS,
    CURRENT_SCENARIO_IDS,
    HISTORICAL_SCENARIO_REFS,
    SCENARIO_IDS,
    validate_registry,
)

SPEC_PATH = Path("oled/changes/wea-vnext-recreation/spec.md")


def _headings(level: int) -> tuple[str, ...]:
    source = SPEC_PATH.read_text(encoding="utf-8")
    return tuple(
        re.findall(
            rf"^{'#' * level} (S-[0-9]+[A-Z]?)\.",
            source,
            re.MULTILINE,
        )
    )


def test_scenario_registry_matches_spec_0_9_scopes_exactly() -> None:
    validate_registry()
    changed_headings = _headings(4)
    historical_headings = _headings(3)
    compatible_headings = tuple(
        item
        for item in historical_headings
        if item not in CHANGED_SCENARIO_IDS
        and item not in ACCEPTED_FUTURE_SCENARIO_IDS
    )

    assert CHANGED_SCENARIO_IDS == changed_headings
    assert COMPATIBLE_SCENARIO_IDS == compatible_headings
    assert len(CURRENT_SCENARIO_IDS) == len(set(CURRENT_SCENARIO_IDS)) == 67
    assert set(CURRENT_SCENARIO_IDS) == (
        set(changed_headings)
        | (set(historical_headings) - set(ACCEPTED_FUTURE_SCENARIO_IDS))
    )
    assert SCENARIO_IDS is CURRENT_SCENARIO_IDS
    assert ACCEPTED_FUTURE_SCENARIO_IDS == ("S-11A", "S-11B", "S-13C")
    assert HISTORICAL_SCENARIO_REFS == tuple(
        f"0.8:{item}" for item in CHANGED_SCENARIO_IDS
    )
