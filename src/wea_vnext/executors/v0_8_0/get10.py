"""Pinned Frontier benchmark terms for Issue #10."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Get10PriorArt:
    slot: int
    expression: str
    classification: str

    def to_data(self) -> dict[str, object]:
        return {
            "classification": self.classification,
            "expression": self.expression,
            "slot": self.slot,
        }


GET10_ISSUE_NUMBER = 10
GET10_VALIDATOR_ID = "get10-normalized-code"
GET10_VALIDATOR_VERSION = "1"
GET10_PAYOUT_VECTOR = (13, 21, 34, 55, 89, 144, 233)
GET10_PRIOR_ART = (
    Get10PriorArt(0, "3^(1+1)+1", "seen-prior-art"),
    Get10PriorArt(1, "11-1^3", "legacy-noop-anti-example"),
    Get10PriorArt(2, "(3+1)!!+1+1", "seen-prior-art"),
    Get10PriorArt(3, "11-sqrt(1^3)", "legacy-noop-anti-example"),
    Get10PriorArt(4, "(1+1+1)/.3", "needs-author-after-normalization:3/0.3"),
    Get10PriorArt(5, "3/(.1+.1+.1)", "needs-author-after-normalization:3/0.3"),
)


def classify_legacy_expression(expression: str) -> str:
    """Return the frozen validator classification for one historical expression."""
    if type(expression) is not str or not expression:
        raise ValueError("expression must be a non-empty string")
    normalized = expression.replace(" ", "")
    matches = [
        item.classification for item in GET10_PRIOR_ART if item.expression == normalized
    ]
    if len(matches) != 1:
        return "not-seen"
    return matches[0]


def new_epoch_config() -> dict[str, object]:
    """Return the exact fully funded seven-slot Frontier configuration."""
    return {
        "acceptance": {
            "kind": "normalized_validator",
            "validator_id": GET10_VALIDATOR_ID,
            "version": GET10_VALIDATOR_VERSION,
        },
        "incentive": "fibonacci",
        "payout_vector": list(GET10_PAYOUT_VECTOR),
        "prior_art": [item.to_data() for item in GET10_PRIOR_ART],
        "snapshot_identity": "model+genome+runtime",
    }


__all__ = [
    "GET10_ISSUE_NUMBER",
    "GET10_PAYOUT_VECTOR",
    "GET10_PRIOR_ART",
    "GET10_VALIDATOR_ID",
    "GET10_VALIDATOR_VERSION",
    "Get10PriorArt",
    "classify_legacy_expression",
    "new_epoch_config",
]
