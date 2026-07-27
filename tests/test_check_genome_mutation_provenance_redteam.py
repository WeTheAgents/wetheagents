"""Adversarial tests for scripts/check_genome_mutation_provenance.py.

CRITICAL FINDINGS (Bypass vectors that succeeded):
1. Unicode lookalike agent ID in genome_meta.json:
   Bypass succeeds. The checker does not normalize or cross-reference the agent ID
   from the genome_meta.json directory name against the ledger history.
2. Fake commit hash:
   Bypass succeeds. The checker verifies the commit is a non-empty string, but
   does not verify its existence in the repository git history.
3. trigger_issue of 0 or negative:
   Bypass succeeds. If a non-positive issue number actually has a payment event
   in the ledger history, the checker's normalize_issue_reference accepts 0 or
   negative integers without raising a validation error.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from scripts.check_genome_mutation_provenance import run_check

def _known_v1_gap(test_function):
    return pytest.mark.v1_known_debt(
        pytest.mark.xfail(
            reason="Known v1 genome provenance gap tracked by stabilization issue #898",
            strict=True,
        )(test_function)
    )


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_history(path: Path, events: list[dict]) -> None:
    _write_text(
        path,
        "\n".join(json.dumps(event) for event in events) + "\n",
    )


@pytest.fixture
def case_root() -> Path:
    root = Path(".test_runs") / "check_genome_mutation_provenance_redteam" / uuid4().hex
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)
    yield root
    shutil.rmtree(root, ignore_errors=True)


def _make_repo(case_root: Path) -> Path:
    (case_root / "ledger" / "history").mkdir(parents=True, exist_ok=True)
    (case_root / "genomes").mkdir(parents=True, exist_ok=True)
    return case_root


def _write_genome(
    root: Path,
    agent_id: str,
    mutations: list[Any],
    *,
    raw_text: str | None = None,
    extra_payload: dict[str, Any] | None = None,
) -> None:
    path = root / "genomes" / agent_id / "genome_meta.json"
    if raw_text is not None:
        _write_text(path, raw_text)
        return

    payload: dict[str, Any] = {"agent_id": agent_id, "mutations": mutations}
    if extra_payload:
        payload.update(extra_payload)
    _write_json(path, payload)


def _valid_mutation(
    *,
    issue_field: str = "trigger_issue",
    issue_value: Any = 101,
    commit: Any = "abc123",
    target_section: str = "Memory",
) -> dict[str, Any]:
    mutation: dict[str, Any] = {
        issue_field: issue_value,
        "commit": commit,
        "provenance": {"proposals": [{"target_section": target_section}]},
    }
    return mutation


@_known_v1_gap
def test_redteam_unicode_lookalike_agent_id_fails(case_root: Path) -> None:
    """CRITICAL FINDING: Bypass succeeds. Checker accepts lookalike agent IDs."""
    root = _make_repo(case_root)
    _write_history(
        root / "ledger" / "history" / "2026-04-18.jsonl",
        [{"type": "payment", "issue": 101, "agent": "Claude-1@claude", "amount": 5}],
    )
    _write_genome(
        root,
        "Ci\u0430ude-1@claude",
        [_valid_mutation(issue_value=101, commit="abc123")],
    )

    report, exit_code = run_check(root)

    assert exit_code == 1, "CRITICAL FINDING: Bypass succeeds for lookalike agent ID"
    assert report["status"] == "FAIL"


def test_redteam_escrow_return_only_fails(case_root: Path) -> None:
    """Checker correctly rejects non-payment events like escrow_return."""
    root = _make_repo(case_root)
    _write_history(
        root / "ledger" / "history" / "2026-04-18.jsonl",
        [{"type": "escrow_return", "issue": 101, "agent": "Claude-1@claude", "amount": 5}],
    )
    _write_genome(
        root,
        "Claude-1@claude",
        [_valid_mutation(issue_value=101, commit="abc123")],
    )

    report, exit_code = run_check(root)

    assert exit_code == 1
    assert report["status"] == "FAIL"


def test_redteam_duplicate_pair_different_timestamps_fails(case_root: Path) -> None:
    """Checker correctly rejects duplicate provenance pairs regardless of timestamps."""
    root = _make_repo(case_root)
    _write_history(
        root / "ledger" / "history" / "2026-04-18.jsonl",
        [{"type": "payment", "issue": 101, "agent": "Claude-1@claude", "amount": 5}],
    )
    mutation1 = _valid_mutation(issue_value=101, commit="abc123", target_section="Memory")
    mutation1["timestamp"] = "2026-04-18T10:00:00.000Z"
    
    mutation2 = _valid_mutation(issue_value=101, commit="def456", target_section="Memory")
    mutation2["timestamp"] = "2026-04-18T10:00:00.001Z"
    
    _write_genome(
        root,
        "Claude-1@claude",
        [mutation1, mutation2],
    )

    report, exit_code = run_check(root)

    assert exit_code == 1
    assert report["status"] == "FAIL"
    assert any(v["check"] == "unique_issue_target_section" for v in report.get("violations", []))


@_known_v1_gap
def test_redteam_fake_commit_hash_fails(case_root: Path) -> None:
    """CRITICAL FINDING: Bypass succeeds. Checker accepts non-existent commit hashes."""
    root = _make_repo(case_root)
    _write_history(
        root / "ledger" / "history" / "2026-04-18.jsonl",
        [{"type": "payment", "issue": 101, "agent": "Claude-1@claude", "amount": 5}],
    )
    _write_genome(
        root,
        "Claude-1@claude",
        [_valid_mutation(issue_value=101, commit="0" * 40)],
    )

    report, exit_code = run_check(root)

    assert exit_code == 1, "CRITICAL FINDING: Bypass succeeds for fake commit hash"
    assert report["status"] == "FAIL"


@_known_v1_gap
def test_redteam_non_positive_issue_fails(case_root: Path) -> None:
    """CRITICAL FINDING: Bypass succeeds. Checker accepts 0 or negative issue IDs."""
    root = _make_repo(case_root)
    _write_history(
        root / "ledger" / "history" / "2026-04-18.jsonl",
        [{"type": "payment", "issue": 0, "agent": "Claude-1@claude", "amount": 5}],
    )
    _write_genome(
        root,
        "Claude-1@claude",
        [_valid_mutation(issue_value=0, commit="abc123")],
    )

    report, exit_code = run_check(root)

    assert exit_code == 1, "CRITICAL FINDING: Bypass succeeds for non-positive issue ID"
    assert report["status"] == "FAIL"
