from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from wea_cli import cli

ROOT = Path(__file__).resolve().parent.parent


def test_general_claim_command_is_not_registered() -> None:
    parser = cli.build_parser()
    subcommands = next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )

    assert "claim" not in subcommands.choices
    assert not hasattr(cli, "cmd_claim")


def test_general_claim_invocation_is_rejected() -> None:
    parser = cli.build_parser()

    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["claim", "42"])

    assert exc_info.value.code == 2


def test_paused_legacy_writers_are_absent() -> None:
    assert not (ROOT / "scripts" / "claim_fast.py").exists()
    assert not (ROOT / ".github" / "workflows" / "claim-fast.yml").exists()
    assert not (ROOT / ".github" / "workflows" / "agent0-ledger-candidate.yml").exists()
    tide = (ROOT / ".github" / "workflows" / "tide.yml").read_text(encoding="utf-8")
    assert "python -m wea_vnext.tide run" in tide
    assert "scripts/tide.py" not in tide
    assert not (ROOT / ".github" / "workflows" / "auto-triage.yml").exists()
