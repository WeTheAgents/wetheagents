"""Tests for scripts/check_genome_completeness.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.check_genome_completeness import run, REQUIRED_META_FIELDS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_repo(
    tmp_path: Path,
    agent_ids: list[str],
    *,
    skip_agents: set[str] | None = None,
) -> Path:
    """Create a minimal repo layout under tmp_path.

    balances.json is populated with agent_ids.
    Returns the repo root.
    """
    if skip_agents is None:
        skip_agents = set()

    ledger = tmp_path / "ledger"
    ledger.mkdir()
    balances = {
        "version": 1,
        "agents": {
            aid: {
                "balance": 0,
                "registered_at": "2026-01-01T00:00:00Z",
                "platform": "claude-code",
                "github_username": "test",
            }
            for aid in agent_ids
        },
    }
    (ledger / "balances.json").write_text(json.dumps(balances), encoding="utf-8")

    genomes = tmp_path / "genomes"
    genomes.mkdir()
    return tmp_path


def _make_genome(
    genomes_dir: Path,
    agent_id: str,
    *,
    meta: dict | None | str = None,
    agents_local_content: str | None = "# genome",
) -> None:
    """Create a genome directory for agent_id.

    meta=None         → write a valid default genome_meta.json
    meta=<dict>       → write that dict as genome_meta.json
    meta=<str>        → write the raw string (allows invalid JSON)
    agents_local_content=None → do not create AGENTS.local.md
    agents_local_content=""   → create an empty AGENTS.local.md
    """
    d = genomes_dir / agent_id
    d.mkdir(parents=True, exist_ok=True)

    if meta is None:
        default = {
            "agent_id": agent_id,
            "fitness": {"tasks_completed": 0},
            "mutations": [],
        }
        (d / "genome_meta.json").write_text(
            json.dumps(default), encoding="utf-8"
        )
    elif isinstance(meta, str):
        # Raw string — allows injecting invalid JSON for error-path tests
        (d / "genome_meta.json").write_text(meta, encoding="utf-8")
    else:
        # Any JSON-serializable value (dict, list, int, …)
        (d / "genome_meta.json").write_text(json.dumps(meta), encoding="utf-8")

    if agents_local_content is not None:
        (d / "AGENTS.local.md").write_text(agents_local_content, encoding="utf-8")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_happy_path(tmp_path: Path) -> None:
    """All agents have complete genomes — overall PASS, exit 0."""
    root = _make_repo(tmp_path, ["Alice@claude", "Bob@codex"])
    genomes = root / "genomes"
    _make_genome(genomes, "Alice@claude")
    _make_genome(genomes, "Bob@codex")

    result, passed = run(root)

    assert passed is True
    assert result["status"] == "PASS"
    statuses = {c["status"] for c in result["checks"]}
    assert "FAIL" not in statuses


def test_missing_genome_dir(tmp_path: Path) -> None:
    """Agent with no genome directory → FAIL."""
    root = _make_repo(tmp_path, ["Alice@claude"])
    # Do NOT create the genome dir

    result, passed = run(root)

    assert passed is False
    assert result["status"] == "FAIL"
    fails = [c for c in result["checks"] if c["status"] == "FAIL"]
    assert any(c["check"] == "genome_dir" for c in fails)


def test_missing_genome_meta_json(tmp_path: Path) -> None:
    """genome_meta.json absent → FAIL."""
    root = _make_repo(tmp_path, ["Alice@claude"])
    genomes = root / "genomes"
    d = genomes / "Alice@claude"
    d.mkdir(parents=True)
    (d / "AGENTS.local.md").write_text("# genome", encoding="utf-8")
    # No genome_meta.json

    result, passed = run(root)

    assert passed is False
    fails = [c for c in result["checks"] if c["status"] == "FAIL"]
    assert any(c["check"] == "genome_meta_present" for c in fails)


def test_invalid_json_in_meta(tmp_path: Path) -> None:
    """genome_meta.json containing mangled JSON → FAIL."""
    root = _make_repo(tmp_path, ["Alice@claude"])
    genomes = root / "genomes"
    _make_genome(genomes, "Alice@claude", meta="{not valid json!!!")

    result, passed = run(root)

    assert passed is False
    fails = [c for c in result["checks"] if c["status"] == "FAIL"]
    assert any(c["check"] == "genome_meta_valid_json" for c in fails)


def test_meta_not_a_dict(tmp_path: Path) -> None:
    """genome_meta.json top-level is a list (not a dict) → FAIL.

    This is the T6S10 corruption scenario: non-dict structure.
    """
    root = _make_repo(tmp_path, ["Alice@claude"])
    genomes = root / "genomes"
    _make_genome(genomes, "Alice@claude", meta=[1, 2, 3])  # list, not dict

    result, passed = run(root)

    assert passed is False
    fails = [c for c in result["checks"] if c["status"] == "FAIL"]
    assert any(c["check"] == "genome_meta_is_dict" for c in fails)


def test_missing_required_field(tmp_path: Path) -> None:
    """genome_meta.json missing a required field → FAIL."""
    root = _make_repo(tmp_path, ["Alice@claude"])
    genomes = root / "genomes"
    # Omit 'mutations' (one of the required fields)
    partial_meta = {"agent_id": "Alice@claude", "fitness": {}}
    _make_genome(genomes, "Alice@claude", meta=partial_meta)

    result, passed = run(root)

    assert passed is False
    fails = [c for c in result["checks"] if c["status"] == "FAIL"]
    assert any(c["check"] == "genome_meta_required_fields" for c in fails)


def test_missing_agents_local_md(tmp_path: Path) -> None:
    """AGENTS.local.md absent → FAIL."""
    root = _make_repo(tmp_path, ["Alice@claude"])
    genomes = root / "genomes"
    _make_genome(genomes, "Alice@claude", agents_local_content=None)

    result, passed = run(root)

    assert passed is False
    fails = [c for c in result["checks"] if c["status"] == "FAIL"]
    assert any(c["check"] == "agents_local_md" for c in fails)


def test_empty_agents_local_md(tmp_path: Path) -> None:
    """AGENTS.local.md present but empty → FAIL."""
    root = _make_repo(tmp_path, ["Alice@claude"])
    genomes = root / "genomes"
    _make_genome(genomes, "Alice@claude", agents_local_content="")

    result, passed = run(root)

    assert passed is False
    fails = [c for c in result["checks"] if c["status"] == "FAIL"]
    assert any(c["check"] == "agents_local_md" for c in fails)


def test_orphan_genome_is_warn_not_fail(tmp_path: Path) -> None:
    """A genome dir with no balances.json entry is WARN, not FAIL."""
    root = _make_repo(tmp_path, ["Alice@claude"])
    genomes = root / "genomes"
    _make_genome(genomes, "Alice@claude")
    # Extra directory not in balances.json
    _make_genome(genomes, "Ghost@unknown")

    result, passed = run(root)

    # Overall still PASS (no FAIL checks)
    assert passed is True
    assert result["status"] == "PASS"
    warns = [c for c in result["checks"] if c["status"] == "WARN"]
    assert any(c["check"] == "orphan_genome" and "Ghost@unknown" in c["agent"] for c in warns)


def test_agent0_system_skipped(tmp_path: Path) -> None:
    """agent0@system is exempt from genome tracking and never causes FAIL."""
    root = _make_repo(tmp_path, ["agent0@system", "Alice@claude"])
    genomes = root / "genomes"
    _make_genome(genomes, "Alice@claude")
    # agent0@system has no genome directory — must not FAIL

    result, passed = run(root)

    assert passed is True
    assert result["status"] == "PASS"
    agent0_checks = [c for c in result["checks"] if c.get("agent") == "agent0@system"]
    assert agent0_checks == []


def test_output_structure(tmp_path: Path) -> None:
    """Result always has status, checks, summary keys."""
    root = _make_repo(tmp_path, ["Alice@claude"])
    genomes = root / "genomes"
    _make_genome(genomes, "Alice@claude")

    result, _ = run(root)

    assert "status" in result
    assert "checks" in result
    assert "summary" in result
    assert isinstance(result["checks"], list)
    assert isinstance(result["summary"], str)


def test_required_meta_fields_constant() -> None:
    """REQUIRED_META_FIELDS contains the three non-negotiable keys."""
    for field in ("agent_id", "fitness", "mutations"):
        assert field in REQUIRED_META_FIELDS
