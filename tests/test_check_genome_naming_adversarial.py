"""Adversarial test suite for scripts/check_genome_naming.py.

Each test probes a crafted edge case designed to fool or stress the naming checker.
Attack vectors are documented in comments.

Test categories:
  FAIL — checker must detect and report the inconsistency (errors > 0)
  PASS — checker must NOT raise spurious errors on valid/expected states (errors == 0)
  GAP  — documented false negatives where checker silently passes a real problem
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.check_genome_naming import _SKIP_DIRS, run


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_repo(
    tmp_path: Path,
    genomes: dict,
    agents: list[str] | None = None,
) -> Path:
    """Build a minimal fake repo with genome dirs and a balances.json."""
    balances = {"agents": {a: {"balance": 100} for a in (agents or [])}}
    balances_path = tmp_path / "ledger" / "balances.json"
    balances_path.parent.mkdir(parents=True, exist_ok=True)
    balances_path.write_text(json.dumps(balances), encoding="utf-8")

    genomes_dir = tmp_path / "genomes"
    genomes_dir.mkdir(exist_ok=True)

    for dir_name, content in genomes.items():
        genome_dir = genomes_dir / dir_name
        genome_dir.mkdir()
        if content is not None:
            meta_path = genome_dir / "genome_meta.json"
            if isinstance(content, str):
                # raw string — used for malformed JSON tests
                meta_path.write_text(content, encoding="utf-8")
            else:
                meta_path.write_text(json.dumps(content), encoding="utf-8")

    return tmp_path


# ---------------------------------------------------------------------------
# FAIL — checker must detect the inconsistency
# ---------------------------------------------------------------------------


def test_adv01_dir_name_mismatch_is_error(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """FAIL: directory named 'agent-a' but genome_meta claims 'agent-b'.

    Attack vector: rename the genome directory without updating agent_id,
    or swap genome_meta.json between two genome dirs.
    """
    root = _make_repo(
        tmp_path,
        genomes={"agent-a": {"agent_id": "agent-b"}},
        agents=["agent-b"],
    )
    errors = run(root, strict=False)
    assert errors >= 1
    captured = capsys.readouterr()
    assert "agent-a" in captured.out
    assert "agent-b" in captured.out


def test_adv02_unknown_agent_id_is_error(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """FAIL: agent_id not registered in balances.json — phantom agent.

    Attack vector: create a genome dir for an agent that has no ledger entry,
    allowing the 'agent' to accumulate genome history without a WEA identity.
    """
    root = _make_repo(
        tmp_path,
        genomes={"ghost@agent": {"agent_id": "ghost@agent"}},
        agents=[],  # ghost@agent NOT in balances
    )
    errors = run(root, strict=False)
    assert errors >= 1
    captured = capsys.readouterr()
    assert "ghost@agent" in captured.out


def test_adv03_malformed_json_is_error(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """FAIL: genome_meta.json contains invalid JSON.

    Attack vector: plant a file that causes silent parsing failure,
    hoping the checker skips it instead of raising an error.
    """
    root = _make_repo(
        tmp_path,
        genomes={"broken-agent": "{not valid json !!!"},
        agents=[],
    )
    errors = run(root, strict=False)
    assert errors >= 1
    captured = capsys.readouterr()
    assert "broken-agent" in captured.out
    assert "not valid JSON" in captured.out


def test_adv04_missing_agent_id_field_is_error(tmp_path: Path) -> None:
    """FAIL: genome_meta.json exists but has no 'agent_id' key.

    The checker defaults to empty string via .get('agent_id', '').
    Since dir_name is never empty, the mismatch is detected via check 1.
    """
    root = _make_repo(
        tmp_path,
        genomes={"real-agent": {"role": "implementor"}},  # no agent_id key
        agents=["real-agent"],
    )
    errors = run(root, strict=False)
    assert errors >= 1


def test_adv05_unknown_parent_ref_is_error(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """FAIL: 'parent' field references an agent not in balances.json.

    Attack vector: clone a genome with a parent set to a deleted/fictitious agent.
    """
    root = _make_repo(
        tmp_path,
        genomes={
            "legit@agent": {
                "agent_id": "legit@agent",
                "parent": "phantom@deleted",
            }
        },
        agents=["legit@agent"],  # parent NOT in balances
    )
    errors = run(root, strict=False)
    assert errors >= 1
    captured = capsys.readouterr()
    assert "phantom@deleted" in captured.out


def test_adv06_unknown_donor_lineage_ref_is_error(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """FAIL: donor_lineage list contains an agent not in balances.json.

    Attack vector: inject a ghost agent into the lineage list
    to claim a fictional evolutionary ancestor.
    """
    root = _make_repo(
        tmp_path,
        genomes={
            "legit@agent": {
                "agent_id": "legit@agent",
                "donor_lineage": ["legit@agent", "phantom@donor"],
            }
        },
        agents=["legit@agent"],
    )
    errors = run(root, strict=False)
    assert errors >= 1
    captured = capsys.readouterr()
    assert "phantom@donor" in captured.out


def test_adv07_unknown_lineage_ref_is_error(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """FAIL: lineage list contains an agent not in balances.json.

    Attack vector: add a ghost ancestor to lineage[] to falsely claim
    evolutionary descent from a high-fitness agent.
    """
    root = _make_repo(
        tmp_path,
        genomes={
            "legit@agent": {
                "agent_id": "legit@agent",
                "lineage": ["ghost@ancestor"],
            }
        },
        agents=["legit@agent"],
    )
    errors = run(root, strict=False)
    assert errors >= 1
    captured = capsys.readouterr()
    assert "ghost@ancestor" in captured.out


def test_adv08_multiple_errors_in_one_genome_all_reported(tmp_path: Path) -> None:
    """FAIL: dir-name mismatch AND unknown lineage ref in the same genome.

    Both errors must be independently reported (no short-circuit after first error).
    """
    root = _make_repo(
        tmp_path,
        genomes={
            "dir-name": {
                "agent_id": "meta-name",  # check 1: dir-name != meta-name
                "lineage": ["ghost@lineage"],  # check 3: unknown ref
            }
        },
        agents=["meta-name"],
    )
    errors = run(root, strict=False)
    assert errors >= 2, f"Expected ≥ 2 errors (mismatch + bad lineage), got {errors}"


def test_adv09_strict_missing_meta_is_error(tmp_path: Path) -> None:
    """FAIL (strict): missing genome_meta.json is promoted from WARN to ERROR under --strict.

    Attack vector: create a genome dir with no metadata, hoping the non-strict default
    lets it accumulate unverified existence without being flagged as an error.
    Under --strict this must become an error.
    """
    root = _make_repo(
        tmp_path,
        genomes={"no-meta-agent": None},  # dir exists, no genome_meta.json
        agents=[],
    )
    errors = run(root, strict=True)
    assert errors >= 1


# ---------------------------------------------------------------------------
# PASS — checker must NOT raise spurious errors
# ---------------------------------------------------------------------------


def test_adv10_skip_dirs_silently_ignored(tmp_path: Path) -> None:
    """PASS: directories in _SKIP_DIRS are silently ignored even with invalid content.

    The skip-list is an intentional allowlist for special non-agent directories.
    Malformed or phantom content inside them must never trigger an error.
    """
    skip_dir = next(iter(_SKIP_DIRS))
    root = _make_repo(
        tmp_path,
        genomes={skip_dir: "{malformed json"},
        agents=[],
    )
    errors = run(root, strict=False)
    assert errors == 0, f"Skip-listed dir '{skip_dir}' should produce 0 errors"


def test_adv11_nondir_file_ignored(tmp_path: Path) -> None:
    """PASS: a regular file (not a directory) in genomes/ is not treated as a genome."""
    genomes_dir = tmp_path / "genomes"
    genomes_dir.mkdir(parents=True)
    (genomes_dir / "README.md").write_text("rogue file", encoding="utf-8")
    (tmp_path / "ledger").mkdir(parents=True, exist_ok=True)
    (tmp_path / "ledger" / "balances.json").write_text(
        json.dumps({"agents": {}}), encoding="utf-8"
    )
    errors = run(tmp_path, strict=False)
    assert errors == 0, "Plain file in genomes/ should be ignored"


def test_adv12_non_strict_missing_meta_warns_not_errors(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """PASS (non-strict): missing genome_meta.json emits [WARN] but does NOT increment errors.

    This confirms the non-strict / strict mode boundary is correctly enforced.
    """
    root = _make_repo(
        tmp_path,
        genomes={"no-meta-agent": None},
        agents=[],
    )
    errors = run(root, strict=False)
    assert errors == 0
    captured = capsys.readouterr()
    assert "WARN" in captured.out


def test_adv13_integration_real_repo_passes() -> None:
    """PASS (integration): the real repository has 0 genome naming errors.

    This ensures no regressions have been introduced and the checker
    correctly handles all production genomes.
    """
    repo_root = Path(__file__).resolve().parent.parent
    errors = run(repo_root, strict=False)
    assert errors == 0, f"Real repo has {errors} genome naming error(s)"


# ---------------------------------------------------------------------------
# GAP — documented false negatives (checker silently passes real problems)
# ---------------------------------------------------------------------------


def test_adv14_gap_lineage_as_string_not_caught(tmp_path: Path) -> None:
    """GAP: lineage as a raw string (not a list) bypasses the reference check.

    The script guards with: isinstance(val, list)
    A string value for 'lineage' fails this check and is silently skipped.
    Result: 'phantom@ghost' is never validated against balances.json.
    This is a false negative — a ghost ancestor can hide in a string-typed lineage.
    """
    root = _make_repo(
        tmp_path,
        genomes={
            "legit@agent": {
                "agent_id": "legit@agent",
                "lineage": "phantom@ghost",  # string, not list — bypasses check
            }
        },
        agents=["legit@agent"],
    )
    errors = run(root, strict=False)
    # Document the gap: 0 errors even though phantom@ghost is unknown
    assert errors == 0, (
        "GAP confirmed: 'lineage' as a string bypasses reference validation. "
        "'phantom@ghost' is not in balances but produces no error."
    )


def test_adv15_gap_nested_list_in_donor_lineage_not_caught(tmp_path: Path) -> None:
    """GAP: nested list items inside donor_lineage are silently skipped.

    The script filters: (v for v in val if isinstance(v, str))
    A nested list [[ref]] passes the outer isinstance(val, list) check
    but the inner element fails isinstance(v, str), so it is skipped.
    Result: a ghost agent hidden inside a nested list is never validated.
    """
    root = _make_repo(
        tmp_path,
        genomes={
            "legit@agent": {
                "agent_id": "legit@agent",
                "donor_lineage": [["phantom@nested"]],  # inner list not a string
            }
        },
        agents=["legit@agent"],
    )
    errors = run(root, strict=False)
    # Document the gap: 0 errors even though phantom@nested is unknown
    assert errors == 0, (
        "GAP confirmed: nested list items in donor_lineage bypass reference validation."
    )
