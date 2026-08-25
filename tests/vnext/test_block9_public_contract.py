from __future__ import annotations

import pytest

from wea_vnext.block9.common import Block9Error
from wea_vnext.block9.projection import (
    ProjectionIntent,
    build_public_activation_files,
    operational_status,
)


def _intent(projection_id: str = "projection-1") -> ProjectionIntent:
    return ProjectionIntent.create(
        projection_id=projection_id,
        target_type="comment",
        target_id="issue-1",
        desired={"body": "Accepted"},
    )


def test_private_pilot_records_projection_without_a_local_app() -> None:
    intent = _intent()
    status = operational_status(epoch_id="epoch-2", intents=(intent,))

    assert status == {
        "epoch_id": "epoch-2",
        "writer_agent_id": "agent0@system",
        "projection_transport": "deferred",
        "status": "projection_deferred",
        "pending_projection_ids": ["projection-1"],
    }


def test_projection_intent_is_exact_and_duplicate_ids_fail() -> None:
    intent = _intent()
    assert intent.desired_hash
    with pytest.raises(Block9Error, match="duplicates"):
        operational_status(epoch_id="epoch-2", intents=(intent, intent))


def test_public_activation_files_only_update_human_guidance() -> None:
    base_files = {
        "README.md": b"# Project\n",
        "CONTRIBUTING.md": b"# Contributing\n",
        "AGENT0.md": b"# Agent0\n",
        "docs/VNEXT_BOUNDARY.md": b"# Boundary\n",
        ".github/ISSUE_TEMPLATE/task.yml": b"name: Task\n",
    }
    files = build_public_activation_files(
        epoch_id="epoch-2",
        writer_agent_id="agent0@system",
        base_files=base_files,
    )

    assert set(files) == set(base_files)
    assert all(
        b"GitHub command -> Actions candidate" in value
        for value in files.values()
    )
    assert all(b"projections remain deferred" in value for value in files.values())
