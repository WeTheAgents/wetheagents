from __future__ import annotations

from pathlib import Path

import pytest

from wea_cli.cli import reject_retired_legacy_write
from wea_vnext.block9.common import Block9Error
from wea_vnext.block9.migration import (
    build_genesis,
    freeze_input_bundle,
    reconcile_obligations,
    reject_retired_write,
    replay_genesis,
)

from .test_block9_reconciliation import _payload


def test_gauntlet_and_achievement_history_is_readable_but_inactive() -> None:
    bundle = freeze_input_bundle(_payload())
    report = reconcile_obligations(
        bundle,
        {"issue-1": {"outcome": "settle-v1", "closure_hash": "4" * 64}},
    )
    state = replay_genesis(build_genesis(bundle, report, ()))
    assert state["historical"]["gauntlet"] == [{"mint": 20}]
    assert state["historical"]["achievements"] == [{"award": "first"}]
    assert state["opening_supply"] == 100
    assert state["genomes"] == {"alice": {"revision": 2}}
    assert "achievements" not in state
    assert "gauntlet" not in state


@pytest.mark.parametrize("command", ["gauntlet-mint", "award", "revoke", "transform"])
def test_retired_write_commands_reject(command: str) -> None:
    with pytest.raises(Block9Error, match="historical-only"):
        reject_retired_write(command)


def test_cli_explains_retired_writes_only_after_vnext_activation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert not reject_retired_legacy_write(tmp_path, "award")
    bootstrap = tmp_path / "ledger" / "vnext" / "bootstrap.json"
    bootstrap.parent.mkdir(parents=True)
    bootstrap.write_text("{}\n", encoding="utf-8")

    assert reject_retired_legacy_write(tmp_path, "award")
    assert "historical-only" in capsys.readouterr().out


def test_genome_tracker_workflow_is_retired() -> None:
    root = Path(__file__).resolve().parents[2]
    assert not (root / ".github/workflows/genome-mutation-tracker.yml").exists()
