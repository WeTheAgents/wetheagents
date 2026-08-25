"""Deferred public projections for the private GitHub-native pilot."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass

from .common import (
    Block9Error,
    canonical_bytes,
    require_relative_path,
    require_text,
    sha256_hex,
)


@dataclass(frozen=True, slots=True)
class ProjectionIntent:
    """A durable wish to update GitHub after canonical ledger acceptance."""

    projection_id: str
    target_type: str
    target_id: str
    desired_bytes: bytes
    desired_hash: str

    @classmethod
    def create(
        cls,
        *,
        projection_id: str,
        target_type: str,
        target_id: str,
        desired: Mapping[str, object],
    ) -> ProjectionIntent:
        require_text(projection_id, field="projection_id")
        if target_type not in {"comment", "label"}:
            raise Block9Error("projection target type is not accepted")
        require_text(target_id, field="projection target_id")
        if type(desired) is not dict:
            raise Block9Error("projection desired state must be an exact mapping")
        required = {"body"} if target_type == "comment" else {"label"}
        if set(desired) != required:
            raise Block9Error("projection desired fields are incomplete")
        for value in desired.values():
            require_text(value, field="projection desired value")
        desired_bytes = canonical_bytes(desired)
        return cls(
            projection_id,
            target_type,
            target_id,
            desired_bytes,
            sha256_hex(desired_bytes),
        )

    def __post_init__(self) -> None:
        require_text(self.projection_id, field="projection_id")
        if self.target_type not in {"comment", "label"}:
            raise Block9Error("projection target type is not accepted")
        require_text(self.target_id, field="projection target_id")
        if type(self.desired_bytes) is not bytes:
            raise Block9Error("projection desired state must be exact bytes")
        try:
            desired = json.loads(self.desired_bytes)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise Block9Error("projection desired state is not JSON") from exc
        if canonical_bytes(desired) != self.desired_bytes:
            raise Block9Error("projection desired state is not canonical")
        if sha256_hex(self.desired_bytes) != self.desired_hash:
            raise Block9Error("projection desired hash changed")


def build_public_activation_files(
    *,
    epoch_id: str,
    writer_agent_id: str,
    base_files: Mapping[str, bytes],
) -> dict[str, bytes]:
    """Add the active GitHub-native epoch to existing public guidance."""

    require_text(epoch_id, field="epoch_id")
    if writer_agent_id != "agent0@system":
        raise Block9Error("public writer must be agent0@system")
    if type(base_files) is not dict:
        raise Block9Error("public predecessor files must be an exact mapping")
    required_docs = {
        "README.md",
        "CONTRIBUTING.md",
        "AGENT0.md",
        "docs/VNEXT_BOUNDARY.md",
    }
    issue_forms = {
        path
        for path in base_files
        if path.startswith(".github/ISSUE_TEMPLATE/")
        and path.endswith((".yml", ".yaml"))
    }
    if not required_docs <= set(base_files) or not issue_forms:
        raise Block9Error("public predecessor documents are incomplete")
    if set(base_files) != required_docs | issue_forms:
        raise Block9Error("public predecessor path set is not closed")
    banner = (
        "<!-- wea-protocol-epoch:start -->\n"
        f"Active protocol epoch: {epoch_id}\n"
        "Ledger path: GitHub command -> Actions candidate -> reviewed PR -> main\n"
        f"Logical writer: {writer_agent_id}\n"
        "Public comment and label projections remain deferred.\n"
        "<!-- wea-protocol-epoch:end -->\n"
    ).encode()
    output: dict[str, bytes] = {}
    for raw_path, content in base_files.items():
        path = require_relative_path(raw_path, field="public activation path")
        if type(content) is not bytes:
            raise Block9Error("public predecessor content must be exact bytes")
        if b"wea-protocol-epoch:start" in content:
            raise Block9Error("public predecessor already contains an epoch block")
        output[path] = content.rstrip(b"\n") + b"\n\n" + banner
    return dict(sorted(output.items()))


def operational_status(
    *, epoch_id: str, intents: tuple[ProjectionIntent, ...]
) -> dict[str, object]:
    """Report the honest private-pilot state: canonical writes, no projections."""

    require_text(epoch_id, field="epoch_id")
    if type(intents) is not tuple or any(
        type(item) is not ProjectionIntent for item in intents
    ):
        raise Block9Error("projection intents must use exact types")
    identifiers = [item.projection_id for item in intents]
    if len(identifiers) != len(set(identifiers)):
        raise Block9Error("projection intent IDs contain duplicates")
    value = {
        "epoch_id": epoch_id,
        "writer_agent_id": "agent0@system",
        "projection_transport": "deferred",
        "status": "projection_deferred",
        "pending_projection_ids": sorted(identifiers),
    }
    canonical_bytes(value)
    return value


__all__ = [
    "ProjectionIntent",
    "build_public_activation_files",
    "operational_status",
]
