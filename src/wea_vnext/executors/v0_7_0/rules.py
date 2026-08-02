"""Load and validate immutable Resolution Plan ruleset 0.7."""

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
    """Raised when packaged Resolution Plan rules are inconsistent."""


_EXPECTED_RULESET_SHA256 = (
    "f7d25041faceecaf318086dc74c19f0e20d7a23ede84963e410d2d18efb19aef"
)
_EXPECTED_DEPTH_MODES = {
    "explore": ["duel", "flat_pod", "frontier", "ranked"],
    "implement": ["frontier", "ranked"],
    "spec": ["frontier", "ranked"],
}
_EXPECTED_REJECT_CODES = [
    "authority",
    "declaration",
    "evidence_boundary",
    "identity",
    "matrix",
    "money",
]


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
        .joinpath("0.7.json")
        .read_bytes()
    )


def raw_ruleset_bytes() -> bytes:
    """Return exact canonical bytes used by executor 0.7.0."""
    raw = _resource_bytes()
    if sha256_hex(raw) != _EXPECTED_RULESET_SHA256:
        raise RulesetError("ruleset bytes do not match executor 0.7.0")
    if canonical_dumps(canonical_loads(raw)) != raw:
        raise RulesetError("ruleset must use exact canonical JSON bytes")
    return raw


def _exact_dict(value: Any, *, field: str, keys: set[str]) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        raise RulesetError(f"{field} has invalid keys")
    return value


def _positive_integer(value: Any, *, field: str) -> int:
    if type(value) is not int or value < 1:
        raise RulesetError(f"{field} must be a positive integer")
    return value


def _validate(content: dict[str, Any]) -> None:
    required = {
        "canonicalization",
        "depth_modes",
        "formal_reject_codes",
        "modes",
        "plan",
        "task_state",
        "tide_interface_version",
        "version",
    }
    if set(content) != required:
        raise RulesetError("ruleset top-level keys do not match the 0.7 schema")
    if content["version"] != "0.7" or content["tide_interface_version"] != "0.7":
        raise RulesetError("ruleset and Tide interface must both be 0.7")
    if content["depth_modes"] != _EXPECTED_DEPTH_MODES:
        raise RulesetError("depth/mode matrix is incomplete")
    if content["formal_reject_codes"] != _EXPECTED_REJECT_CODES:
        raise RulesetError("formal reject taxonomy is not the accepted 0.7 set")

    modes = _exact_dict(
        content["modes"],
        field="modes",
        keys={"duel", "flat_pod", "frontier", "ranked"},
    )
    ranked = _exact_dict(
        modes["ranked"],
        field="ranked",
        keys={"finite", "minimum_winners", "underfill"},
    )
    if (
        ranked["finite"] is not True
        or ranked["minimum_winners"] != 1
        or ranked["underfill"] != "pay-eligible-ranks-refund-unused"
    ):
        raise RulesetError("ranked rules are inconsistent")
    flat = _exact_dict(
        modes["flat_pod"],
        field="flat_pod",
        keys={"additive", "finite", "payout"},
    )
    if flat != {"additive": True, "finite": True, "payout": "equal"}:
        raise RulesetError("Flat PoD rules are inconsistent")
    frontier = _exact_dict(
        modes["frontier"],
        field="frontier",
        keys={"finite", "incentives", "novelty", "snapshot_identity_fields"},
    )
    if (
        frontier["finite"] is not True
        or frontier["incentives"] != ["fibonacci", "linear"]
        or frontier["snapshot_identity_fields"] != ["model", "genome", "runtime"]
    ):
        raise RulesetError("Frontier rules are inconsistent")
    duel = _exact_dict(
        modes["duel"],
        field="duel",
        keys={
            "bank_multiple_wea",
            "minimum_bank_wea",
            "outcome_percentages",
            "positions",
            "rounds",
        },
    )
    _positive_integer(duel["bank_multiple_wea"], field="duel.bank_multiple_wea")
    _positive_integer(duel["minimum_bank_wea"], field="duel.minimum_bank_wea")
    if duel["positions"] != 2 or duel["rounds"] != 3:
        raise RulesetError("Duel must contain two positions and three rounds")
    outcomes = _exact_dict(
        duel["outcome_percentages"],
        field="duel.outcome_percentages",
        keys={"inconclusive", "no_completers", "single_completer", "winner"},
    )
    for name, vector in outcomes.items():
        if (
            type(vector) is not list
            or len(vector) != 3
            or any(type(item) is not int or item < 0 for item in vector)
            or sum(vector) != 100
        ):
            raise RulesetError(f"Duel outcome {name} must distribute 100 percent")

    plan = _exact_dict(
        content["plan"],
        field="plan",
        keys={
            "author_approval_required",
            "escrow",
            "future_input_kinds",
            "materialize_on_approval",
            "semantic_triage_veto",
        },
    )
    if plan != {
        "author_approval_required": True,
        "escrow": "full-bank-on-approval",
        "future_input_kinds": ["selected_work_of"],
        "materialize_on_approval": "first-stage-only",
        "semantic_triage_veto": False,
    }:
        raise RulesetError("Resolution Plan activation rules are inconsistent")
    task_state = _exact_dict(
        content["task_state"],
        field="task_state",
        keys={"close_results", "statuses"},
    )
    if task_state != {
        "close_results": ["completed", "stopped"],
        "statuses": ["active", "closed", "paused"],
    }:
        raise RulesetError("task state table is inconsistent")


def load_ruleset() -> Ruleset:
    content = canonical_loads(raw_ruleset_bytes())
    if type(content) is not dict:
        raise RulesetError("ruleset root must be an object")
    _validate(content)
    return Ruleset(
        version=content["version"],
        interface_version=content["tide_interface_version"],
        content_hash=canonical_hash(content),
        content=freeze_json(content),
    )


__all__ = ["Ruleset", "RulesetError", "load_ruleset", "raw_ruleset_bytes"]
