"""Tests for scripts/genome_self_audit.py."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.genome_self_audit import audit_agent, run, _required_sections_present

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 4, 13, 12, 0, 0, tzinfo=timezone.utc)
_RECENT_TS = "2026-04-12T12:00:00Z"
_STALE_TS = "2026-01-01T12:00:00Z"  # 102 days before _NOW


def _make_repo(tmp_path: Path, agent_id: str) -> Path:
    """Create a minimal repo with one registered agent."""
    root = tmp_path / "repo"
    (root / "ledger" / "history").mkdir(parents=True)
    (root / "genomes" / agent_id).mkdir(parents=True)

    balances = {
        "agents": {
            agent_id: {"balance": 100, "total_earned": 0, "total_spent": 0},
        }
    }
    (root / "ledger" / "balances.json").write_text(
        json.dumps(balances, indent=2), encoding="utf-8"
    )
    return root


def _write_meta(
    root: Path,
    agent_id: str,
    *,
    tasks_completed: int = 0,
    mutations: list | None = None,
    last_snapshot: str = _RECENT_TS,
) -> None:
    meta = {
        "agent_id": agent_id,
        "generation": 0,
        "parent": None,
        "created_at": "2026-03-07T12:00:00Z",
        "last_snapshot": last_snapshot,
        "role": "implementor",
        "fitness": {
            "tasks_completed": tasks_completed,
            "tasks_created": 0,
            "total_earned": tasks_completed * 10,
            "total_minted": 0,
            "gauntlet_slots": 0,
            "total_income": tasks_completed * 10,
        },
        "lineage": [],
        "mutations": mutations if mutations is not None else [],
    }
    (root / "genomes" / agent_id / "genome_meta.json").write_text(
        json.dumps(meta, indent=2), encoding="utf-8"
    )


def _write_md(root: Path, agent_id: str, content: str = "") -> None:
    (root / "genomes" / agent_id / "AGENTS.local.md").write_text(
        content, encoding="utf-8"
    )


_FULL_MD = """\
## Role
Implementor.

## Instructions
Do the thing.

## Memory
2026-04-01: learned stuff.
"""

_MISSING_MEMORY_MD = """\
## Role
Implementor.

## Instructions
Do the thing.
"""


def _write_payment(root: Path, agent_id: str, count: int = 1) -> None:
    events = [
        {"type": "payment", "agent": agent_id, "amount": 10, "issue": i}
        for i in range(count)
    ]
    lines = [json.dumps(e) for e in events]
    (root / "ledger" / "history" / "2026-04-01.jsonl").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Unit tests for _required_sections_present
# ---------------------------------------------------------------------------


def test_required_sections_all_present():
    assert _required_sections_present(_FULL_MD) == []


def test_required_sections_missing_memory():
    missing = _required_sections_present(_MISSING_MEMORY_MD)
    assert missing == ["memory"]


def test_required_sections_empty_doc():
    missing = _required_sections_present("")
    assert set(missing) == {"role", "instructions", "memory"}


def test_required_sections_case_insensitive():
    md = "## ROLE\n## INSTRUCTIONS\n## MEMORY\n"
    assert _required_sections_present(md) == []


# ---------------------------------------------------------------------------
# audit_agent tests
# ---------------------------------------------------------------------------


def test_pass_healthy_agent(tmp_path: Path):
    agent_id = "test-agent@test"
    root = _make_repo(tmp_path, agent_id)
    _write_meta(root, agent_id, tasks_completed=2, mutations=[{"commit": "abc"}])
    _write_md(root, agent_id, _FULL_MD)
    _write_payment(root, agent_id, count=2)

    findings = audit_agent(
        agent_id,
        root / "genomes",
        root / "ledger" / "history",
        now=_NOW,
    )

    statuses = {f["check"]: f["status"] for f in findings}
    assert statuses["stale_snapshot"] == "PASS"
    assert statuses["silent_agent"] == "PASS"
    assert statuses["fitness_drift"] == "PASS"
    assert statuses["section_coverage"] == "PASS"


def test_stale_snapshot_warns(tmp_path: Path):
    agent_id = "stale-agent@test"
    root = _make_repo(tmp_path, agent_id)
    _write_meta(root, agent_id, last_snapshot=_STALE_TS)
    _write_md(root, agent_id, _FULL_MD)

    findings = audit_agent(
        agent_id,
        root / "genomes",
        root / "ledger" / "history",
        stale_days=30,
        now=_NOW,
    )

    stale = next(f for f in findings if f["check"] == "stale_snapshot")
    assert stale["status"] == "WARN"
    assert "102" in stale["detail"]


def test_silent_agent_warns(tmp_path: Path):
    agent_id = "silent-agent@test"
    root = _make_repo(tmp_path, agent_id)
    _write_meta(root, agent_id, tasks_completed=3, mutations=[])
    _write_md(root, agent_id, _FULL_MD)
    _write_payment(root, agent_id, count=3)

    findings = audit_agent(
        agent_id,
        root / "genomes",
        root / "ledger" / "history",
        now=_NOW,
    )

    silent = next(f for f in findings if f["check"] == "silent_agent")
    assert silent["status"] == "WARN"
    assert "tasks_completed=3" in silent["detail"]


def test_fitness_drift_fails(tmp_path: Path):
    agent_id = "drift-agent@test"
    root = _make_repo(tmp_path, agent_id)
    # genome says 1 task, ledger history shows 3 tasks
    _write_meta(root, agent_id, tasks_completed=1, mutations=[{"commit": "abc"}])
    _write_md(root, agent_id, _FULL_MD)
    _write_payment(root, agent_id, count=3)

    findings = audit_agent(
        agent_id,
        root / "genomes",
        root / "ledger" / "history",
        now=_NOW,
    )

    drift = next(f for f in findings if f["check"] == "fitness_drift")
    assert drift["status"] == "FAIL"
    assert "tasks_completed=1" in drift["detail"]
    assert "3 payment" in drift["detail"]


def test_missing_section_warns(tmp_path: Path):
    agent_id = "nosec-agent@test"
    root = _make_repo(tmp_path, agent_id)
    _write_meta(root, agent_id)
    _write_md(root, agent_id, _MISSING_MEMORY_MD)

    findings = audit_agent(
        agent_id,
        root / "genomes",
        root / "ledger" / "history",
        now=_NOW,
    )

    sec = next(f for f in findings if f["check"] == "section_coverage")
    assert sec["status"] == "WARN"
    assert "memory" in sec["detail"]


def test_no_genome_dir_returns_empty(tmp_path: Path):
    root = _make_repo(tmp_path, "ghost-agent@test")
    # Don't create genomes/ghost-agent@test/genome_meta.json
    findings = audit_agent(
        "ghost-agent@test",
        root / "genomes",
        root / "ledger" / "history",
        now=_NOW,
    )
    # Missing directory / meta → skip silently (check_genome_completeness handles it)
    assert findings == []


# ---------------------------------------------------------------------------
# run() integration tests
# ---------------------------------------------------------------------------


def test_run_pass_on_clean_repo(tmp_path: Path):
    agent_id = "good-agent@test"
    root = _make_repo(tmp_path, agent_id)
    _write_meta(root, agent_id, tasks_completed=1, mutations=[{"commit": "abc"}])
    _write_md(root, agent_id, _FULL_MD)
    _write_payment(root, agent_id, count=1)

    result, passed = run(root, stale_days=30)
    assert passed is True
    assert result["status"] == "PASS"


def test_run_fail_on_fitness_drift(tmp_path: Path):
    agent_id = "bad-agent@test"
    root = _make_repo(tmp_path, agent_id)
    _write_meta(root, agent_id, tasks_completed=0, mutations=[])  # says 0
    _write_md(root, agent_id, _FULL_MD)
    _write_payment(root, agent_id, count=2)  # ledger says 2

    result, passed = run(root, stale_days=30)
    assert passed is False
    assert result["status"] == "FAIL"


def test_run_warn_does_not_fail(tmp_path: Path):
    agent_id = "warn-agent@test"
    root = _make_repo(tmp_path, agent_id)
    # stale snapshot + silent agent, but no fitness drift
    _write_meta(root, agent_id, tasks_completed=2, mutations=[], last_snapshot=_STALE_TS)
    _write_md(root, agent_id, _FULL_MD)
    _write_payment(root, agent_id, count=2)

    result, passed = run(root, stale_days=30)
    # WARNs (stale + silent) but no FAIL → passed=True
    assert passed is True
    warn_checks = [f for f in result["checks"] if f["status"] == "WARN"]
    assert any(f["check"] == "stale_snapshot" for f in warn_checks)
    assert any(f["check"] == "silent_agent" for f in warn_checks)


def test_run_agent0_is_skipped(tmp_path: Path):
    root = tmp_path / "repo"
    (root / "ledger" / "history").mkdir(parents=True)
    (root / "genomes").mkdir(parents=True)
    balances = {
        "agents": {
            "agent0@system": {"balance": 5000},
        }
    }
    (root / "ledger" / "balances.json").write_text(
        json.dumps(balances), encoding="utf-8"
    )
    result, passed = run(root, stale_days=30)
    assert result["checks"] == []  # agent0@system is exempt
    assert passed is True
