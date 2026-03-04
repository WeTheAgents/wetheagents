from __future__ import annotations

import json
from pathlib import Path
import shutil
from uuid import uuid4

import pytest


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


@pytest.fixture
def temp_repo() -> Path:
    root = Path(".test_runs") / f"run_{uuid4().hex}"
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
    ledger_dir = root / "ledger"
    history_dir = ledger_dir / "history"
    sandbox_dir = root / "sandbox"
    history_dir.mkdir(parents=True, exist_ok=True)
    sandbox_dir.mkdir(parents=True, exist_ok=True)

    _write_json(
        ledger_dir / "balances.json",
        {
            "version": 1,
            "last_updated": "2026-03-04T00:00:00Z",
            "agents": {
                "agent0@system": {
                    "balance": 10000,
                    "total_earned": 10000,
                    "total_spent": 0,
                    "tasks_completed": 0,
                    "tasks_created": 0,
                },
                "author@local": {
                    "balance": 500,
                    "total_earned": 500,
                    "total_spent": 0,
                    "tasks_completed": 0,
                    "tasks_created": 0,
                },
                "alice@test": {
                    "balance": 0,
                    "total_earned": 0,
                    "total_spent": 0,
                    "tasks_completed": 0,
                    "tasks_created": 0,
                },
                "bob@test": {
                    "balance": 0,
                    "total_earned": 0,
                    "total_spent": 0,
                    "tasks_completed": 0,
                    "tasks_created": 0,
                },
                "carol@test": {
                    "balance": 0,
                    "total_earned": 0,
                    "total_spent": 0,
                    "tasks_completed": 0,
                    "tasks_created": 0,
                },
            },
        },
    )

    _write_json(ledger_dir / "escrows.json", {"version": 1, "active": {}})
    _write_json(ledger_dir / "idem_keys.json", {"keys": {}})
    _write_json(ledger_dir / "pending.json", {"version": 1, "queue": []})
    (sandbox_dir / "hello_world_registry.jsonl").write_text("", encoding="utf-8")

    yield root

    shutil.rmtree(root, ignore_errors=True)
