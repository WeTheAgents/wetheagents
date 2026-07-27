"""Load and validate immutable ruleset 0.6 from package resources."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from importlib import resources
from typing import Any

from .canonical import (
    canonical_dumps,
    canonical_hash,
    canonical_loads,
    freeze_json,
    sha256_hex,
)


class RulesetError(ValueError):
    """Raised when packaged rules are incomplete or internally inconsistent."""


_EXPECTED_RULESET_SHA256 = (
    "21538935ed5e0b3662589a3f631e8d7220ddc0bc12f7a182cb6c592b7848fa9b"
)


@dataclass(frozen=True)
class Ruleset:
    version: str
    interface_version: str
    content_hash: str
    content: Mapping[str, Any]


def _resource_bytes() -> bytes:
    return (
        resources.files("wea_vnext")
        .joinpath("rulesets")
        .joinpath("0.6.json")
        .read_bytes()
    )


def raw_ruleset_bytes() -> bytes:
    """Return the exact canonical bytes used for the ruleset content hash."""
    raw = _resource_bytes()
    if sha256_hex(raw) != _EXPECTED_RULESET_SHA256:
        raise RulesetError("ruleset bytes do not match executor 0.6.2")
    canonical = canonical_dumps(canonical_loads(raw))
    if raw != canonical:
        raise RulesetError("ruleset must use exact canonical JSON bytes")
    return raw


def _require_integer(value: Any, *, field: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise RulesetError(f"{field} must be an integer >= {minimum}")
    return value


def _validate(content: dict[str, Any]) -> None:
    required = {
        "canonicalization",
        "event_order",
        "mechanics",
        "profiles",
        "review_stages",
        "task_state",
        "tide_interface_version",
        "transitions",
        "version",
    }
    if set(content) != required:
        raise RulesetError("ruleset top-level keys do not match the 0.6 schema")
    if content["version"] != "0.6" or content["tide_interface_version"] != "0.6":
        raise RulesetError("ruleset and Tide interface must both be 0.6")

    profiles = content["profiles"]
    expected_profiles = {"spec-only", "direct-pr", "full-build", "duel"}
    if not isinstance(profiles, dict) or set(profiles) != expected_profiles:
        raise RulesetError("profile table is incomplete")
    mechanics = content["mechanics"]
    expected_mechanics = {
        "best-x",
        "duel",
        "linear",
        "pod",
        "progressive",
        "winner-take-all",
    }
    if not isinstance(mechanics, dict) or set(mechanics) != expected_mechanics:
        raise RulesetError("mechanic table is incomplete")
    known_mechanics = set(mechanics)
    for profile_name, profile in profiles.items():
        if not isinstance(profile, dict):
            raise RulesetError(f"profile {profile_name} must be an object")
        selected = profile.get("mechanics")
        if (
            not isinstance(selected, list)
            or not selected
            or not set(selected) <= known_mechanics
        ):
            raise RulesetError(f"profile {profile_name} has invalid mechanics")

    review_stages = content["review_stages"]
    if not isinstance(review_stages, dict):
        raise RulesetError("review_stages must be an object")
    for stage_name, stage in review_stages.items():
        if not isinstance(stage, dict):
            raise RulesetError(f"review stage {stage_name} must be an object")
        _require_integer(stage.get("fee_wea"), field=f"{stage_name}.fee_wea", minimum=1)

    best_x = mechanics["best-x"]
    percentages = best_x.get("percentages") if isinstance(best_x, dict) else None
    if not isinstance(percentages, dict) or set(percentages) != {"2", "3", "4", "5"}:
        raise RulesetError("Best-X percentages must define X=2..5")
    for winner_count, vector in percentages.items():
        if not isinstance(vector, list) or len(vector) != int(winner_count):
            raise RulesetError(f"Best-X vector {winner_count} has the wrong length")
        if (
            sum(_require_integer(item, field="Best-X percentage") for item in vector)
            != 100
        ):
            raise RulesetError(f"Best-X vector {winner_count} does not sum to 100")

    duel = mechanics["duel"]
    if not isinstance(duel, dict):
        raise RulesetError("Duel mechanics must be an object")
    _require_integer(
        duel.get("minimum_bank_wea"), field="duel.minimum_bank_wea", minimum=10
    )
    _require_integer(
        duel.get("bank_multiple_wea"), field="duel.bank_multiple_wea", minimum=1
    )
    if set(duel.get("outcomes", {})) != {
        "inconclusive",
        "no-completers",
        "single-completer",
        "winner",
    }:
        raise RulesetError("Duel outcome table is incomplete")

    transitions = content["transitions"]
    expected_transition_tables = {
        "direct-pr",
        "duel",
        "full-build",
        "infinite-work",
        "pre-contract",
        "spec-only",
        "universal",
    }
    if (
        not isinstance(transitions, dict)
        or set(transitions) != expected_transition_tables
    ):
        raise RulesetError("transition tables are incomplete")
    for table_name, table in transitions.items():
        if not isinstance(table, list) or not table:
            raise RulesetError(f"transition table {table_name} must be non-empty")
        if any(
            not isinstance(transition, list)
            or len(transition) != 3
            or not all(isinstance(item, str) and item for item in transition)
            for transition in table
        ):
            raise RulesetError(f"transition table {table_name} contains an invalid row")

    declared_states = {
        stage for profile in profiles.values() for stage in profile["stages"]
    } | set(content["task_state"]["transition_states"])
    for table_name, table in transitions.items():
        for source, _event, target in table:
            if source not in declared_states or target not in declared_states:
                raise RulesetError(
                    f"transition table {table_name} uses an undeclared state"
                )
    for table_name, intake_stage in {
        "direct-pr": "pr-intake",
        "full-build": "spec-intake",
        "spec-only": "spec-intake",
    }.items():
        if any(
            target == intake_stage
            for _source, _event, target in transitions[table_name]
        ):
            raise RulesetError(f"finite transition table {table_name} reopens intake")


def load_ruleset() -> Ruleset:
    content = canonical_loads(raw_ruleset_bytes())
    if not isinstance(content, dict):
        raise RulesetError("ruleset root must be an object")
    _validate(content)
    return Ruleset(
        version=content["version"],
        interface_version=content["tide_interface_version"],
        content_hash=canonical_hash(content),
        content=freeze_json(content),
    )
