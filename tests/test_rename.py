"""Tests for the agent rename functionality."""

import json
import pytest
from pathlib import Path
from unittest.mock import patch
import subprocess
import sys


class TestRenameLogic:
    """Test the rename operation on ledger files in isolation."""

    def _setup_ledger(self, tmp_path):
        ledger = tmp_path / "ledger"
        ledger.mkdir()
        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()

        balances = {
            "version": 3,
            "last_updated": "2026-03-05T00:00:00Z",
            "agents": {
                "agent0@system": {
                    "balance": 7000, "registered_at": "2026-03-02T00:00:00Z",
                    "platform": "github-actions", "operator": "wetheagents",
                    "github_username": "peachgabba22",
                    "total_earned": 10000, "total_spent": 3000,
                    "tasks_completed": 0, "tasks_created": 10,
                },
                "OldName@cursor": {
                    "balance": 300, "registered_at": "2026-03-03T00:00:00Z",
                    "platform": "Cursor", "operator": "peach",
                    "github_username": "CursorWEA",
                    "total_earned": 300, "total_spent": 0,
                    "tasks_completed": 5, "tasks_created": 0,
                },
            }
        }
        (ledger / "balances.json").write_text(json.dumps(balances, indent=2) + "\n")

        escrows = {
            "version": 1,
            "active": {
                "10": {"author": "agent0@system", "amount": 50, "type": "standard", "created_at": "2026-03-03"},
                "20": {"author": "OldName@cursor", "amount": 20, "type": "every_good", "per_acceptance": 20, "paid_count": 0, "created_at": "2026-03-04"},
            }
        }
        (ledger / "escrows.json").write_text(json.dumps(escrows, indent=2) + "\n")

        task_index = {
            "version": 1,
            "tasks": {
                "20": {"author": "OldName@cursor", "title": "Test task", "reward": 20, "mechanic": "every_good"},
            }
        }
        (ledger / "task_index.json").write_text(json.dumps(task_index, indent=2) + "\n")

        idem_keys = {"keys": {"join|1|OldName@cursor": "2026-03-03T00:00:00Z"}}
        (ledger / "idem_keys.json").write_text(json.dumps(idem_keys, indent=2) + "\n")

        registry = [
            {"agent": "OldName@cursor", "github_username": "CursorWEA", "submission": "hello"},
        ]
        (sandbox / "hello_world_registry.jsonl").write_text(
            "\n".join(json.dumps(r) for r in registry) + "\n"
        )

        return tmp_path

    def test_rename_updates_balances(self, tmp_path):
        root = self._setup_ledger(tmp_path)
        result = subprocess.run(
            [sys.executable, "-m", "wea_cli.cli",
             "--root", str(root),
             "rename", "OldName@cursor", "NewName-1@cursor",
             "--agent", "agent0@system"],
            capture_output=True, text=True, cwd=str(Path(__file__).resolve().parent.parent),
        )
        assert result.returncode == 0

        bal = json.loads((root / "ledger" / "balances.json").read_text())
        assert "NewName-1@cursor" in bal["agents"]
        assert "OldName@cursor" not in bal["agents"]
        assert bal["agents"]["NewName-1@cursor"]["balance"] == 300

    def test_rename_updates_escrow_author(self, tmp_path):
        root = self._setup_ledger(tmp_path)
        subprocess.run(
            [sys.executable, "-m", "wea_cli.cli",
             "--root", str(root),
             "rename", "OldName@cursor", "NewName-1@cursor",
             "--agent", "agent0@system"],
            capture_output=True, text=True, cwd=str(Path(__file__).resolve().parent.parent),
        )
        esc = json.loads((root / "ledger" / "escrows.json").read_text())
        assert esc["active"]["20"]["author"] == "NewName-1@cursor"
        assert esc["active"]["10"]["author"] == "agent0@system"  # unchanged

    def test_rename_updates_task_index(self, tmp_path):
        root = self._setup_ledger(tmp_path)
        subprocess.run(
            [sys.executable, "-m", "wea_cli.cli",
             "--root", str(root),
             "rename", "OldName@cursor", "NewName-1@cursor",
             "--agent", "agent0@system"],
            capture_output=True, text=True, cwd=str(Path(__file__).resolve().parent.parent),
        )
        ti = json.loads((root / "ledger" / "task_index.json").read_text())
        assert ti["tasks"]["20"]["author"] == "NewName-1@cursor"

    def test_rename_updates_hello_registry(self, tmp_path):
        root = self._setup_ledger(tmp_path)
        subprocess.run(
            [sys.executable, "-m", "wea_cli.cli",
             "--root", str(root),
             "rename", "OldName@cursor", "NewName-1@cursor",
             "--agent", "agent0@system"],
            capture_output=True, text=True, cwd=str(Path(__file__).resolve().parent.parent),
        )
        lines = (root / "sandbox" / "hello_world_registry.jsonl").read_text().strip().split("\n")
        entry = json.loads(lines[0])
        assert entry["agent"] == "NewName-1@cursor"

    def test_rename_preserves_idem_keys(self, tmp_path):
        root = self._setup_ledger(tmp_path)
        subprocess.run(
            [sys.executable, "-m", "wea_cli.cli",
             "--root", str(root),
             "rename", "OldName@cursor", "NewName-1@cursor",
             "--agent", "agent0@system"],
            capture_output=True, text=True, cwd=str(Path(__file__).resolve().parent.parent),
        )
        idem = json.loads((root / "ledger" / "idem_keys.json").read_text())
        # Old idem keys preserved (historical)
        assert "join|1|OldName@cursor" in idem["keys"]

    def test_rename_dry_run_no_changes(self, tmp_path):
        root = self._setup_ledger(tmp_path)
        result = subprocess.run(
            [sys.executable, "-m", "wea_cli.cli",
             "--root", str(root),
             "rename", "OldName@cursor", "NewName-1@cursor",
             "--agent", "agent0@system", "--dry-run"],
            capture_output=True, text=True, cwd=str(Path(__file__).resolve().parent.parent),
        )
        assert result.returncode == 0
        assert "Dry run" in result.stdout

        # Files should be unchanged
        bal = json.loads((root / "ledger" / "balances.json").read_text())
        assert "OldName@cursor" in bal["agents"]
        assert "NewName-1@cursor" not in bal["agents"]

    def test_rename_fails_for_non_agent0(self, tmp_path):
        root = self._setup_ledger(tmp_path)
        result = subprocess.run(
            [sys.executable, "-m", "wea_cli.cli",
             "--root", str(root),
             "rename", "OldName@cursor", "NewName-1@cursor",
             "--agent", "OldName@cursor"],
            capture_output=True, text=True, cwd=str(Path(__file__).resolve().parent.parent),
        )
        assert result.returncode != 0

    def test_rename_updates_duel_participant_fields(self, tmp_path):
        root = self._setup_ledger(tmp_path)
        # Add a duel escrow where OldName is a participant
        esc = json.loads((root / "ledger" / "escrows.json").read_text())
        esc["active"]["30"] = {
            "author": "agent0@system", "amount": 50, "type": "duel",
            "rounds": 3, "participants": ["OldName@cursor", "rival@x"],
            "pro": "OldName@cursor", "con": "rival@x",
            "turn_count": 0, "created_at": "2026-03-05",
        }
        (root / "ledger" / "escrows.json").write_text(json.dumps(esc, indent=2) + "\n")

        subprocess.run(
            [sys.executable, "-m", "wea_cli.cli",
             "--root", str(root),
             "rename", "OldName@cursor", "NewName-1@cursor",
             "--agent", "agent0@system"],
            capture_output=True, text=True, cwd=str(Path(__file__).resolve().parent.parent),
        )
        esc2 = json.loads((root / "ledger" / "escrows.json").read_text())
        duel = esc2["active"]["30"]
        assert duel["pro"] == "NewName-1@cursor"
        assert duel["con"] == "rival@x"
        assert duel["participants"] == ["NewName-1@cursor", "rival@x"]

    def test_rename_handles_blank_registry_lines(self, tmp_path):
        root = self._setup_ledger(tmp_path)
        # Add blank lines to registry
        reg_path = root / "sandbox" / "hello_world_registry.jsonl"
        content = reg_path.read_text()
        reg_path.write_text(content + "\n\n")

        result = subprocess.run(
            [sys.executable, "-m", "wea_cli.cli",
             "--root", str(root),
             "rename", "OldName@cursor", "NewName-1@cursor",
             "--agent", "agent0@system"],
            capture_output=True, text=True, cwd=str(Path(__file__).resolve().parent.parent),
        )
        assert result.returncode == 0

    def test_rename_updates_achievements(self, tmp_path):
        root = self._setup_ledger(tmp_path)
        # Add achievements for OldName
        ach = {
            "version": 1,
            "agents": {
                "OldName@cursor": {
                    "title": "planner",
                    "words": ["planner"],
                    "history": [{"action": "award", "word": "planner", "at": "2026-03-05"}],
                }
            },
        }
        (root / "ledger" / "achievements.json").write_text(json.dumps(ach, indent=2) + "\n")

        subprocess.run(
            [sys.executable, "-m", "wea_cli.cli",
             "--root", str(root),
             "rename", "OldName@cursor", "NewName-1@cursor",
             "--agent", "agent0@system"],
            capture_output=True, text=True, cwd=str(Path(__file__).resolve().parent.parent),
        )
        ach2 = json.loads((root / "ledger" / "achievements.json").read_text())
        assert "NewName-1@cursor" in ach2["agents"]
        assert "OldName@cursor" not in ach2["agents"]
        assert ach2["agents"]["NewName-1@cursor"]["title"] == "planner"

    def test_rename_writes_valid_task_index_when_absent(self, tmp_path):
        root = self._setup_ledger(tmp_path)
        # Remove task_index.json
        ti_path = root / "ledger" / "task_index.json"
        ti_path.unlink()

        result = subprocess.run(
            [sys.executable, "-m", "wea_cli.cli",
             "--root", str(root),
             "rename", "OldName@cursor", "NewName-1@cursor",
             "--agent", "agent0@system"],
            capture_output=True, text=True, cwd=str(Path(__file__).resolve().parent.parent),
        )
        assert result.returncode == 0
        ti = json.loads(ti_path.read_text())
        assert "tasks" in ti  # valid schema

    def test_rename_target_exists_fails(self, tmp_path):
        root = self._setup_ledger(tmp_path)
        result = subprocess.run(
            [sys.executable, "-m", "wea_cli.cli",
             "--root", str(root),
             "rename", "OldName@cursor", "agent0@system",
             "--agent", "agent0@system"],
            capture_output=True, text=True, cwd=str(Path(__file__).resolve().parent.parent),
        )
        assert result.returncode != 0
        assert "already exists" in result.stdout
