"""Tests for the CLI halt guard — T3 Slot 1.

When Tide detects an invariant violation it writes a halt condition to
ledger/tide.json.  The halt guard in cli.py must:

1. Block ALL mutation commands when halted.
2. Allow read-only commands when halted.
3. Allow everything when NOT halted.
4. Allow everything when tide.json is missing.
5. Allow everything when tide.json is malformed.
6. Correctly handle compound commands (gauntlet status vs gauntlet mint).
7. Return the halt reason in the message.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from wea_cli.cli import (
    EXIT_HALT,
    READONLY_COMMANDS,
    READONLY_SUBCOMMANDS,
    check_halt_guard,
    is_readonly_command,
)

HALTED_TIDE = {
    "last_tide": "2026-03-17T10:00:00Z",
    "last_run": "2026-03-17T10:00:00Z",
    "halted_at": "2026-03-17T10:05:00Z",
    "halt_reason": "negative balance(s): rogue-agent@test=-50",
    "halt_event": {"type": "accept", "issue": 999},
}

CLEAN_TIDE = {
    "last_tide": "2026-03-17T10:00:00Z",
    "last_run": "2026-03-17T10:00:00Z",
    "halted_at": None,
    "halt_reason": None,
    "halt_event": None,
}


def _write_tide(root: Path, data: dict) -> None:
    tide_path = root / "ledger" / "tide.json"
    tide_path.parent.mkdir(parents=True, exist_ok=True)
    tide_path.write_text(json.dumps(data), encoding="utf-8")


def _make_args(**kwargs) -> argparse.Namespace:
    return argparse.Namespace(**kwargs)


# ── Test 1: Mutation commands blocked when halted ──────────────────────


MUTATION_COMMANDS = [
    "claim", "submit", "pr", "comment", "verify", "accept",
    "ranking", "duel-winner", "rename", "register", "award",
    "revoke", "transform-propose", "assign",
    "lock-acquire", "lock-release", "lock-release-all",
    "spawn",
]


@pytest.mark.parametrize("cmd", MUTATION_COMMANDS)
def test_mutation_blocked_when_halted(tmp_path: Path, cmd: str) -> None:
    _write_tide(tmp_path, HALTED_TIDE)
    args = _make_args(command=cmd)
    result = check_halt_guard(tmp_path, cmd, args)
    assert result is not None
    assert "halted" in result.lower() or "halt" in result.lower()


# ── Test 2: Read-only commands allowed when halted ─────────────────────


@pytest.mark.parametrize("cmd", sorted(READONLY_COMMANDS))
def test_readonly_allowed_when_halted(tmp_path: Path, cmd: str) -> None:
    _write_tide(tmp_path, HALTED_TIDE)
    args = _make_args(command=cmd)
    result = check_halt_guard(tmp_path, cmd, args)
    assert result is None


# ── Test 3: Everything allowed when NOT halted ─────────────────────────


def test_mutations_allowed_when_not_halted(tmp_path: Path) -> None:
    _write_tide(tmp_path, CLEAN_TIDE)
    for cmd in MUTATION_COMMANDS:
        args = _make_args(command=cmd)
        result = check_halt_guard(tmp_path, cmd, args)
        assert result is None, f"{cmd} should be allowed when not halted"


# ── Test 4: Everything allowed when tide.json missing ──────────────────


def test_mutations_allowed_when_tide_missing(tmp_path: Path) -> None:
    (tmp_path / "ledger").mkdir(parents=True, exist_ok=True)
    # No tide.json at all
    for cmd in MUTATION_COMMANDS:
        args = _make_args(command=cmd)
        result = check_halt_guard(tmp_path, cmd, args)
        assert result is None, f"{cmd} should be allowed when tide.json missing"


# ── Test 5: Everything allowed when tide.json is malformed ─────────────


def test_mutations_allowed_when_tide_malformed(tmp_path: Path) -> None:
    tide_path = tmp_path / "ledger" / "tide.json"
    tide_path.parent.mkdir(parents=True, exist_ok=True)
    tide_path.write_text("NOT VALID JSON {{{", encoding="utf-8")
    for cmd in MUTATION_COMMANDS[:3]:  # spot-check a few
        args = _make_args(command=cmd)
        result = check_halt_guard(tmp_path, cmd, args)
        assert result is None, f"{cmd} should be allowed when tide.json is malformed"


# ── Test 6: Compound commands — read-only subs pass, mutation subs blocked


class TestCompoundCommands:
    """Gauntlet status/history pass; gauntlet mint blocked."""

    def test_gauntlet_status_allowed_when_halted(self, tmp_path: Path) -> None:
        _write_tide(tmp_path, HALTED_TIDE)
        args = _make_args(command="gauntlet", gauntlet_command="status")
        assert check_halt_guard(tmp_path, "gauntlet", args) is None

    def test_gauntlet_history_allowed_when_halted(self, tmp_path: Path) -> None:
        _write_tide(tmp_path, HALTED_TIDE)
        args = _make_args(command="gauntlet", gauntlet_command="history")
        assert check_halt_guard(tmp_path, "gauntlet", args) is None

    def test_gauntlet_mint_blocked_when_halted(self, tmp_path: Path) -> None:
        _write_tide(tmp_path, HALTED_TIDE)
        args = _make_args(command="gauntlet", gauntlet_command="mint")
        result = check_halt_guard(tmp_path, "gauntlet", args)
        assert result is not None

    def test_skills_list_allowed_when_halted(self, tmp_path: Path) -> None:
        _write_tide(tmp_path, HALTED_TIDE)
        args = _make_args(command="skills", skills_command="list")
        assert check_halt_guard(tmp_path, "skills", args) is None

    def test_pipeline_get_task_allowed_when_halted(self, tmp_path: Path) -> None:
        _write_tide(tmp_path, HALTED_TIDE)
        args = _make_args(command="pipeline", pipeline_command="get-task")
        assert check_halt_guard(tmp_path, "pipeline", args) is None

    def test_pipeline_submit_blocked_when_halted(self, tmp_path: Path) -> None:
        _write_tide(tmp_path, HALTED_TIDE)
        args = _make_args(command="pipeline", pipeline_command="submit")
        result = check_halt_guard(tmp_path, "pipeline", args)
        assert result is not None


# ── Test 7: Halt reason included in message ────────────────────────────


def test_halt_reason_in_message(tmp_path: Path) -> None:
    _write_tide(tmp_path, HALTED_TIDE)
    args = _make_args(command="claim")
    result = check_halt_guard(tmp_path, "claim", args)
    assert result is not None
    assert "negative balance" in result
    assert "2026-03-17T10:05:00Z" in result


# ── Test 8: is_readonly_command helper ─────────────────────────────────


def test_is_readonly_for_toplevel() -> None:
    args = _make_args(command="balance")
    assert is_readonly_command("balance", args) is True


def test_is_not_readonly_for_mutation() -> None:
    args = _make_args(command="claim")
    assert is_readonly_command("claim", args) is False


def test_is_readonly_for_compound_subcommand() -> None:
    args = _make_args(command="gauntlet", gauntlet_command="status")
    assert is_readonly_command("gauntlet", args) is True


def test_is_not_readonly_for_compound_mutation() -> None:
    args = _make_args(command="gauntlet", gauntlet_command="mint")
    assert is_readonly_command("gauntlet", args) is False
