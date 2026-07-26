from __future__ import annotations

import re
from pathlib import Path

from .scenarios import SCENARIO_IDS, validate_registry

SPEC_PATH = Path("oled/changes/wea-vnext-recreation/spec.md")


def test_scenario_registry_matches_spec_0_6_exactly() -> None:
    validate_registry()
    ids_in_spec = tuple(
        re.findall(
            r"^### (S-[0-9]+[A-Z]?)\.",
            SPEC_PATH.read_text(encoding="utf-8"),
            re.MULTILINE,
        )
    )

    assert len(ids_in_spec) == 55
    assert len(set(ids_in_spec)) == 55
    assert SCENARIO_IDS == ids_in_spec
