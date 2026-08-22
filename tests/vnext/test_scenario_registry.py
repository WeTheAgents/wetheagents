from __future__ import annotations

import re
from pathlib import Path

from .scenarios import (
    ACCEPTED_FUTURE_SCENARIO_IDS,
    BLOCK9_SCENARIO_IDS,
    CHANGED_SCENARIO_IDS,
    COMPATIBLE_SCENARIO_IDS,
    CONTROL_PLANE_SCENARIO_IDS,
    CORRECTION_SCENARIO_IDS,
    CURRENT_SCENARIO_IDS,
    HISTORICAL_SCENARIO_REFS,
    PROPOSED_FUTURE_SCENARIO_IDS,
    SCENARIO_IDS,
    validate_registry,
)

SPEC_PATH = Path("oled/changes/wea-vnext-recreation/spec.md")
CORRECTION_SPEC_PATH = Path(
    "oled/changes/wea-vnext-s13c-financial-correction/spec.md"
)
BLOCK9_SPEC_PATH = Path("oled/changes/wea-vnext-block9-cutover/spec.md")


def _headings(level: int) -> tuple[str, ...]:
    source = SPEC_PATH.read_text(encoding="utf-8")
    return tuple(
        re.findall(
            rf"^{'#' * level} (S-[0-9]+[A-Z]?)\.",
            source,
            re.MULTILINE,
        )
    )


def test_scenario_registry_matches_effective_and_accepted_scopes_exactly() -> None:
    validate_registry()
    normative_headings = _headings(4)
    changed_headings = tuple(
        item
        for item in normative_headings
        if item not in ACCEPTED_FUTURE_SCENARIO_IDS
        and item not in CONTROL_PLANE_SCENARIO_IDS
        and item not in CORRECTION_SCENARIO_IDS
    )
    control_plane_headings = tuple(
        item for item in normative_headings if item in CONTROL_PLANE_SCENARIO_IDS
    )
    historical_headings = _headings(3)
    compatible_headings = tuple(
        item
        for item in historical_headings
        if item not in CHANGED_SCENARIO_IDS
        and item not in CONTROL_PLANE_SCENARIO_IDS
        and item not in CORRECTION_SCENARIO_IDS
        and item not in ACCEPTED_FUTURE_SCENARIO_IDS
    )
    correction_source = CORRECTION_SPEC_PATH.read_text(encoding="utf-8")
    correction_headings = tuple(
        dict.fromkeys(
            re.findall(r"^### (S-[0-9]+[A-Z]?)\.", correction_source, re.MULTILINE)
        )
    )
    block9_source = BLOCK9_SPEC_PATH.read_text(encoding="utf-8")
    block9_headings = tuple(
        re.findall(
            r"^#### Scenario (S-[0-9]+[A-Z]?):",
            block9_source,
            re.MULTILINE,
        )
    )

    assert CHANGED_SCENARIO_IDS == changed_headings
    assert CONTROL_PLANE_SCENARIO_IDS == control_plane_headings
    assert COMPATIBLE_SCENARIO_IDS == compatible_headings
    assert CORRECTION_SCENARIO_IDS == correction_headings
    assert BLOCK9_SCENARIO_IDS == block9_headings
    assert len(CURRENT_SCENARIO_IDS) == len(set(CURRENT_SCENARIO_IDS)) == 70
    assert set(CURRENT_SCENARIO_IDS) == (
        set(changed_headings)
        | set(control_plane_headings)
        | set(correction_headings)
        | (
            set(historical_headings)
            - set(ACCEPTED_FUTURE_SCENARIO_IDS)
            - set(CONTROL_PLANE_SCENARIO_IDS)
            - set(CORRECTION_SCENARIO_IDS)
        )
    )
    assert SCENARIO_IDS is CURRENT_SCENARIO_IDS
    assert CONTROL_PLANE_SCENARIO_IDS == ("S-11A", "S-11B")
    assert CORRECTION_SCENARIO_IDS == ("S-13C",)
    assert ACCEPTED_FUTURE_SCENARIO_IDS == BLOCK9_SCENARIO_IDS
    assert ACCEPTED_FUTURE_SCENARIO_IDS == tuple(
        f"S-{number}" for number in range(71, 80)
    )
    assert PROPOSED_FUTURE_SCENARIO_IDS == ()
    assert HISTORICAL_SCENARIO_REFS == tuple(
        f"0.8:{item}" for item in CHANGED_SCENARIO_IDS
    )
