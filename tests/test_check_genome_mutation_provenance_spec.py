"""Boundary spec tests for scripts/check_genome_mutation_provenance.py.

Encodes the full behavioral contract for edge inputs:

  (a) trigger_issue in JSONL with zero matching events             → FAIL
  (b) duplicate (trigger_issue, target_section) pair              → FAIL
  (c) genome dir not in ledger/balances.json                      → orphan FAIL
  (d) trigger_issue present only as escrow_return                 → FAIL
  (e) genome_meta.json as empty array []                          → PASS
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from scripts.check_genome_mutation_provenance import run_check


# ── helpers ───────────────────────────────────────────────────────────────────


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Minimal valid repo skeleton: ledger/history + genomes dirs."""
    (tmp_path / "ledger" / "history").mkdir(parents=True)
    (tmp_path / "genomes").mkdir()
    return tmp_path


def _write_jsonl(path: Path, events: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8"
    )


def _write_genome(root: Path, agent_id: str, content: Any) -> None:
    path = root / "genomes" / agent_id / "genome_meta.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(content), encoding="utf-8")


def _write_balances(root: Path, balances: dict[str, Any]) -> None:
    path = root / "ledger" / "balances.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(balances), encoding="utf-8")


def _payment(issue: int) -> dict[str, Any]:
    return {"type": "payment", "issue": issue, "agent": "A@test", "amount": 5}


# ── (a) trigger_issue with zero matching history events ───────────────────────


def test_spec_a_trigger_issue_zero_matching_events(repo: Path) -> None:
    """JSONL exists with events, but none are payment/trajectory_mint for trigger_issue."""
    _write_jsonl(
        repo / "ledger" / "history" / "2026-04.jsonl",
        [
            # Right issue number, but wrong event type — must not count
            {"type": "claim", "issue": 101, "agent": "A@test"},
            {"type": "escrow_create", "issue": 101, "agent": "A@test", "amount": 5},
            # Right event type, but different issue number
            {"type": "payment", "issue": 200, "agent": "A@test", "amount": 5},
        ],
    )
    _write_genome(
        repo,
        "Claude-5@claude",
        {"mutations": [
            {"trigger_issue": 101, "commit": "abc123", "target_section": "Memory"},
        ]},
    )

    report, exit_code = run_check(repo)

    assert exit_code == 1
    assert report["status"] == "FAIL"
    linkage = [v for v in report["violations"] if v["check"] == "history_linkage"]
    assert len(linkage) == 1
    assert linkage[0]["missing_issue_ids"] == [101]


def test_spec_a_empty_history_file_fails_linkage(repo: Path) -> None:
    """A JSONL file that exists but is completely empty yields zero indexed events."""
    (repo / "ledger" / "history" / "2026-04.jsonl").write_text("", encoding="utf-8")
    _write_genome(
        repo,
        "Claude-5@claude",
        {"mutations": [
            {"trigger_issue": 42, "commit": "abc123", "target_section": "Instructions"},
        ]},
    )

    report, exit_code = run_check(repo)

    assert exit_code == 1
    assert report["summary"]["history_events_indexed"] == 0
    linkage = [v for v in report["violations"] if v["check"] == "history_linkage"]
    assert any(42 in v["missing_issue_ids"] for v in linkage)


# ── (b) duplicate (trigger_issue, target_section) pair ───────────────────────


def test_spec_b_duplicate_top_level_target_section(repo: Path) -> None:
    """Two mutations sharing identical (trigger_issue, target_section) at top level."""
    _write_jsonl(repo / "ledger" / "history" / "2026-04.jsonl", [_payment(101)])
    _write_genome(
        repo,
        "Claude-5@claude",
        {"mutations": [
            # First occurrence — establishes the pair
            {"trigger_issue": 101, "commit": "abc123", "target_section": "Instructions"},
            # Second occurrence — same trigger_issue + same target_section → duplicate
            {"trigger_issue": 101, "commit": "def456", "target_section": "Instructions"},
        ]},
    )

    report, exit_code = run_check(repo)

    assert exit_code == 1
    assert report["status"] == "FAIL"
    dups = [v for v in report["violations"] if v["check"] == "unique_issue_target_section"]
    assert len(dups) == 1
    assert dups[0]["issue_key"] == "101"
    assert dups[0]["target_section"] == "Instructions"
    assert dups[0]["first_mutation_index"] == 0


def test_spec_b_different_target_sections_are_not_duplicates(repo: Path) -> None:
    """Same trigger_issue but different target_section values — not a duplicate."""
    _write_jsonl(repo / "ledger" / "history" / "2026-04.jsonl", [_payment(101)])
    _write_genome(
        repo,
        "Claude-5@claude",
        {"mutations": [
            {"trigger_issue": 101, "commit": "abc123", "target_section": "Instructions"},
            {"trigger_issue": 101, "commit": "def456", "target_section": "Memory"},
        ]},
    )

    report, exit_code = run_check(repo)

    assert exit_code == 0
    assert report["status"] == "PASS"


# ── (c) genome dir not in balances.json → orphan ─────────────────────────────


def test_spec_c_orphan_genome_dir_fails(repo: Path) -> None:
    """Genome directory absent from ledger/balances.json is flagged as orphan."""
    _write_jsonl(repo / "ledger" / "history" / "2026-04.jsonl", [_payment(101)])
    _write_balances(repo, {"Claude-5@claude": 100, "agent0@system": 5000})
    _write_genome(
        repo,
        "Ghost-99@ghost",  # not in balances
        {"mutations": [
            {"trigger_issue": 101, "commit": "abc123", "target_section": "Memory"},
        ]},
    )

    report, exit_code = run_check(repo)

    assert exit_code == 1
    assert report["status"] == "FAIL"
    orphans = [v for v in report["violations"] if v["check"] == "orphan_genome"]
    assert len(orphans) == 1
    assert orphans[0]["agent"] == "Ghost-99@ghost"


def test_spec_c_registered_agent_passes_orphan_check(repo: Path) -> None:
    """Genome directory present in balances.json — no orphan violation."""
    _write_jsonl(repo / "ledger" / "history" / "2026-04.jsonl", [_payment(101)])
    _write_balances(repo, {"Claude-5@claude": 100})
    _write_genome(
        repo,
        "Claude-5@claude",
        {"mutations": [
            {"trigger_issue": 101, "commit": "abc123", "target_section": "Memory"},
        ]},
    )

    report, exit_code = run_check(repo)

    assert exit_code == 0
    assert report["status"] == "PASS"
    assert not any(v["check"] == "orphan_genome" for v in report["violations"])


def test_spec_c_missing_balances_skips_orphan_check(repo: Path) -> None:
    """When balances.json is absent, orphan detection is skipped — valid mutations PASS."""
    _write_jsonl(repo / "ledger" / "history" / "2026-04.jsonl", [_payment(101)])
    # Intentionally no balances.json
    _write_genome(
        repo,
        "Claude-5@claude",
        {"mutations": [
            {"trigger_issue": 101, "commit": "abc123", "target_section": "Memory"},
        ]},
    )

    report, exit_code = run_check(repo)

    assert exit_code == 0
    assert report["status"] == "PASS"
    assert not any(v["check"] == "orphan_genome" for v in report["violations"])


# ── (d) trigger_issue present only as escrow_return ──────────────────────────


def test_spec_d_escrow_return_not_valid_linkage(repo: Path) -> None:
    """escrow_return is not payment or trajectory_mint — not a valid provenance link."""
    _write_jsonl(
        repo / "ledger" / "history" / "2026-04.jsonl",
        [{"type": "escrow_return", "issue": 101, "agent": "A@test", "amount": 5}],
    )
    _write_genome(
        repo,
        "Claude-5@claude",
        {"mutations": [
            {"trigger_issue": 101, "commit": "abc123", "target_section": "Memory"},
        ]},
    )

    report, exit_code = run_check(repo)

    assert exit_code == 1
    assert report["status"] == "FAIL"
    linkage = [v for v in report["violations"] if v["check"] == "history_linkage"]
    assert len(linkage) == 1
    assert 101 in linkage[0]["missing_issue_ids"]


def test_spec_d_multiple_non_payment_events_still_fail(repo: Path) -> None:
    """claim + escrow_return + escrow_create together still do not satisfy linkage."""
    _write_jsonl(
        repo / "ledger" / "history" / "2026-04.jsonl",
        [
            {"type": "claim", "issue": 101, "agent": "A@test"},
            {"type": "escrow_return", "issue": 101, "agent": "A@test", "amount": 5},
            {"type": "escrow_create", "issue": 101, "agent": "A@test", "amount": 5},
        ],
    )
    _write_genome(
        repo,
        "Claude-5@claude",
        {"mutations": [
            {"trigger_issue": 101, "commit": "abc123", "target_section": "Memory"},
        ]},
    )

    report, exit_code = run_check(repo)

    assert exit_code == 1
    assert report["status"] == "FAIL"
    assert report["summary"]["history_events_indexed"] == 0


def test_spec_d_trajectory_mint_is_valid_linkage(repo: Path) -> None:
    """trajectory_mint (not just payment) IS a valid provenance link."""
    _write_jsonl(
        repo / "ledger" / "history" / "2026-04.jsonl",
        [{"type": "trajectory_mint", "issue": 101, "agents": ["A@test"], "per_agent": [5]}],
    )
    _write_genome(
        repo,
        "Claude-5@claude",
        {"mutations": [
            {"trigger_issue": 101, "commit": "abc123", "target_section": "Memory"},
        ]},
    )

    report, exit_code = run_check(repo)

    assert exit_code == 0
    assert report["status"] == "PASS"


# ── (e) genome_meta.json as empty array [] ────────────────────────────────────


def test_spec_e_empty_array_passes(repo: Path) -> None:
    """genome_meta.json = [] — 0 mutations, nothing to validate → PASS."""
    _write_jsonl(repo / "ledger" / "history" / "2026-04.jsonl", [_payment(101)])
    _write_genome(repo, "Claude-5@claude", [])

    report, exit_code = run_check(repo)

    assert exit_code == 0
    assert report["status"] == "PASS"
    assert report["summary"]["mutations_checked"] == 0
    assert report["violations"] == []


def test_spec_e_empty_array_does_not_crash(repo: Path) -> None:
    """Smoke: [] genome_meta.json must not raise any exception."""
    _write_jsonl(repo / "ledger" / "history" / "2026-04.jsonl", [_payment(101)])
    _write_genome(repo, "Claude-5@claude", [])

    try:
        report, exit_code = run_check(repo)
    except Exception as exc:
        pytest.fail(f"run_check raised {type(exc).__name__}: {exc}")

    assert "status" in report


def test_spec_e_empty_array_with_balances_passes(repo: Path) -> None:
    """[] + balances.json present (agent registered) → still PASS."""
    _write_jsonl(repo / "ledger" / "history" / "2026-04.jsonl", [_payment(101)])
    _write_balances(repo, {"Claude-5@claude": 100})
    _write_genome(repo, "Claude-5@claude", [])

    report, exit_code = run_check(repo)

    assert exit_code == 0
    assert report["status"] == "PASS"
