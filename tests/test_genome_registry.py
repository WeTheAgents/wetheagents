from __future__ import annotations

import json
from pathlib import Path

from scripts.check_cross_file_integrity import check_genome_dir_agent_ids
from scripts.check_genome_naming import run as check_names
from scripts.check_orphan_genome_dirs import run_check as check_orphans
from scripts.genome_registry import genesis_eligible_agent_ids, registered_agent_ids


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_registry_unions_legacy_and_vnext_agents(tmp_path: Path) -> None:
    legacy = {"agents": {"Legacy@agent": {"balance": 10}}}
    _write(tmp_path / "ledger" / "balances.json", legacy)
    _write(
        tmp_path / "ledger" / "vnext" / "tide-state.json",
        {
            "schema": "wea-tide-state-2",
            "balances": {"Legacy@agent": 10, "New@agent": 0},
            "participants": {
                "request": {
                    "agents": [
                        {"agent_id": "New@agent", "preserve_balance": False},
                        {"agent_id": "Legacy@agent", "preserve_balance": True},
                    ]
                }
            },
        },
    )

    assert registered_agent_ids(tmp_path, legacy) == {"Legacy@agent", "New@agent"}
    assert genesis_eligible_agent_ids(tmp_path) == {"New@agent"}


def test_untrusted_or_incomplete_vnext_state_adds_no_agents(tmp_path: Path) -> None:
    _write(
        tmp_path / "ledger" / "vnext" / "tide-state.json",
        {"schema": "unknown", "balances": {"Ghost@agent": 0}},
    )

    assert registered_agent_ids(tmp_path, {"agents": {}}) == set()
    assert genesis_eligible_agent_ids(tmp_path) == set()


def test_legacy_genome_validators_accept_vnext_participant(tmp_path: Path) -> None:
    legacy = {"agents": {}}
    _write(tmp_path / "ledger" / "balances.json", legacy)
    _write(
        tmp_path / "ledger" / "vnext" / "tide-state.json",
        {
            "schema": "wea-tide-state-2",
            "balances": {"New@agent": 0},
            "participants": {
                "request": {
                    "agents": [
                        {"agent_id": "New@agent", "preserve_balance": False}
                    ]
                }
            },
        },
    )
    _write(
        tmp_path / "genomes" / "New@agent" / "genome_meta.json",
        {"agent_id": "New@agent", "parent": None, "lineage": []},
    )
    (tmp_path / "genomes" / "New@agent" / "AGENTS.local.md").write_text(
        "# genome\n", encoding="utf-8"
    )

    assert check_names(tmp_path) == 0
    assert check_orphans(tmp_path)[1] == 0
    assert check_genome_dir_agent_ids(tmp_path, legacy) == []
