"""Load and validate immutable Resolution Plan ruleset 0.8."""

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
    "3460578b4ccf4e00e5dd981742ad0386590b76dd52db1f354d4a618beb7d059b"
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
        .joinpath("0.8.json")
        .read_bytes()
    )


def raw_ruleset_bytes() -> bytes:
    """Return exact canonical bytes used by executor 0.8.0."""
    raw = _resource_bytes()
    if sha256_hex(raw) != _EXPECTED_RULESET_SHA256:
        raise RulesetError("ruleset bytes do not match executor 0.8.0")
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


def _validate_modes(value: object) -> None:
    modes = _exact_dict(
        value,
        field="modes",
        keys={"duel", "flat_pod", "frontier", "ranked"},
    )
    ranked = _exact_dict(
        modes["ranked"],
        field="ranked",
        keys={
            "author_decision",
            "birdie",
            "finite",
            "minimum_winners",
            "settlement",
            "underfill",
        },
    )
    if ranked != {
        "author_decision": True,
        "birdie": True,
        "finite": True,
        "minimum_winners": 1,
        "settlement": "atomic-total-order",
        "underfill": "pay-eligible-ranks-refund-unused",
    }:
        raise RulesetError("ranked rules are inconsistent")
    flat = _exact_dict(
        modes["flat_pod"],
        field="flat_pod",
        keys={
            "acceptance_authority",
            "additive",
            "atomic_slot_payment",
            "birdie",
            "finite",
            "payout",
        },
    )
    if flat != {
        "acceptance_authority": ["normalized_validator", "author"],
        "additive": True,
        "atomic_slot_payment": True,
        "birdie": True,
        "finite": True,
        "payout": "equal",
    }:
        raise RulesetError("Flat PoD rules are inconsistent")
    frontier = _exact_dict(
        modes["frontier"],
        field="frontier",
        keys={
            "acceptance_authority",
            "atomic_slot_payment",
            "finite",
            "incentives",
            "novelty",
            "snapshot_identity_fields",
        },
    )
    if frontier != {
        "acceptance_authority": ["normalized_validator", "author"],
        "atomic_slot_payment": True,
        "finite": True,
        "incentives": ["fibonacci", "linear"],
        "novelty": "valid-and-distinct-from-accepted-prior-art",
        "snapshot_identity_fields": ["model", "genome", "runtime"],
    }:
        raise RulesetError("Frontier rules are inconsistent")
    duel = _exact_dict(
        modes["duel"],
        field="duel",
        keys={
            "admission",
            "author_decision",
            "bank_multiple_wea",
            "birdie",
            "minimum_bank_wea",
            "outcome_percentages",
            "positions",
            "rounds",
        },
    )
    if duel["admission"] != ["invited", "open"]:
        raise RulesetError("Duel admission rules are inconsistent")
    if duel["author_decision"] is not True or duel["birdie"] is not False:
        raise RulesetError("Duel authority rules are inconsistent")
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


def _validate(content: dict[str, Any]) -> None:
    required = {
        "canonicalization",
        "depth_modes",
        "formal_reject_codes",
        "lifecycle",
        "modes",
        "plan",
        "release",
        "roles",
        "schedules",
        "task_state",
        "tide_interface_version",
        "version",
    }
    if set(content) != required:
        raise RulesetError("ruleset top-level keys do not match the 0.8 schema")
    if content["version"] != "0.8" or content["tide_interface_version"] != "0.8":
        raise RulesetError("ruleset and Tide interface must both be 0.8")
    if content["depth_modes"] != _EXPECTED_DEPTH_MODES:
        raise RulesetError("depth/mode matrix is incomplete")
    if content["formal_reject_codes"] != _EXPECTED_REJECT_CODES:
        raise RulesetError("formal reject taxonomy is not the accepted 0.8 set")
    _validate_modes(content["modes"])
    if content["plan"] != {
        "author_approval_required": True,
        "escrow": "full-bank-on-approval",
        "future_input_kinds": ["selected_work_of"],
        "materialize_on_approval": "first-stage-only",
        "semantic_triage_veto": False,
        "stage_schedule_required": True,
    }:
        raise RulesetError("Resolution Plan activation rules are inconsistent")
    if content["schedules"] != {
        "duel": ["join_duration", "move_durations_6", "author_decision_duration"],
        "flat_pod": ["intake_duration"],
        "frontier": ["intake_duration"],
        "ranked": ["intake_duration", "author_decision_duration"],
    }:
        raise RulesetError("stage schedule table is inconsistent")
    if content["roles"] != {
        "funding": ["free", "treasury"],
        "hidden_plan_fee": False,
        "timeliness": "last-required-result",
        "warning_pause": "agent0-from-assigned-role",
    }:
        raise RulesetError("assigned-role rules are inconsistent")
    if content["release"] != {
        "duel": False,
        "implement_work": True,
        "non_triage_role": True,
        "triage": "successful-plan-only",
    }:
        raise RulesetError("Release rules are inconsistent")
    if content["lifecycle"] != {
        "event_order": [
            "effective_at",
            "source_id",
            "source_revision_id",
            "event_id",
        ],
        "pause_kinds": [
            "body_integrity_pause",
            "progression_pause",
            "risk_pause",
        ],
        "risk_pause": {
            "admitted_events": [
                "duel_join",
                "duel_move",
                "role_resolution",
                "role_result",
                "work_revision",
            ],
            "blocked_event_groups": [
                "child-materialization",
                "mode-settlement",
                "new-role-assignment",
                "stage-completion",
                "stage-decision",
            ],
            "body_resume_closes": False,
            "deadline_offset": False,
            "role_scope": "pre-pause-only",
        },
        "source_evidence": (
            "latest-accepted-github-revision-under-complete-confirmed-read-boundary"
        ),
        "stop_authority": "author",
        "suffix_replan_authority": "author",
    }:
        raise RulesetError("lifecycle authority rules are inconsistent")
    if content["task_state"] != {
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
