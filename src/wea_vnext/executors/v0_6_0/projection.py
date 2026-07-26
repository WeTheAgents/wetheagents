"""Deterministic schema for post-commit GitHub projection intent."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from .canonical import canonical_hash


@dataclass(frozen=True)
class ProjectionIntent:
    repository: str
    issue_id: str
    transaction_id: str
    labels: tuple[str, ...]
    issue_state: str
    confirmation: str

    def __post_init__(self) -> None:
        for field in ("repository", "issue_id", "transaction_id", "confirmation"):
            value = getattr(self, field)
            if type(value) is not str or not value:
                raise ValueError(f"{field} must be a non-empty string")
        if self.issue_state not in {"open", "closed"}:
            raise ValueError("issue_state must be open or closed")
        if (
            isinstance(self.labels, (str, bytes))
            or not isinstance(self.labels, Sequence)
            or any(type(label) is not str or not label for label in self.labels)
        ):
            raise ValueError("labels must be a sequence of non-empty strings")
        object.__setattr__(self, "labels", tuple(sorted(set(self.labels))))

    @property
    def projection_id(self) -> str:
        return f"github-projection:{canonical_hash(self.to_data())}"

    def to_data(self) -> dict[str, Any]:
        return {
            "confirmation": self.confirmation,
            "issue_id": self.issue_id,
            "issue_state": self.issue_state,
            "labels": list(self.labels),
            "repository": self.repository,
            "transaction_id": self.transaction_id,
        }
