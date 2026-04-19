"""Tests for scripts/check_genome_mutation_provenance.py."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest

from scripts.check_genome_mutation_provenance import (
    extract_target_sections,
    load_history_issue_ids,
    load_jsonl_line,
    main,
    normalize_issue_reference,
    run_check,
)

SCRIPT = (
    Path(__file__).resolve().parent.parent
    / "scripts"
    / "check_genome_mutation_provenance.py"
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
    root = Path(".test_runs") / "check_genome_mutation_provenance" / uuid4().hex
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


def test_normalize_issue_reference_handles_int_and_composite_string() -> None:
    assert normalize_issue_reference(101) == ("101", [101])
    assert normalize_issue_reference("381+374+381") == ("374+381", [374, 381])


def test_extract_target_sections_reads_top_level_and_provenance() -> None:
    mutation = {
        "target_section": "Instructions",
        "provenance": {
            "proposals": [
                {"target_section": "Memory"},
                {"target_section": "Instructions"},
                {"target_section": "Memory"},
            ]
        },
    }

    assert extract_target_sections(mutation) == ["Instructions", "Memory"]


def test_load_history_issue_ids_indexes_only_relevant_events(case_root: Path) -> None:
    root = _make_repo(case_root)
    _write_history(
        root / "ledger" / "history" / "2026-04-18.jsonl",
        [
            {"type": "payment", "issue": 101, "agent": "A@test", "amount": 5},
            {"type": "trajectory_mint", "issue": 202, "agents": ["A@test"], "per_agent": [5]},
            {"type": "claim", "issue": 303, "agent": "A@test"},
        ],
    )

    issue_ids, relevant_events = load_history_issue_ids(root)

    assert issue_ids == {101, 202}
    assert relevant_events == 2


def test_load_jsonl_line_repairs_legacy_invalid_escape() -> None:
    payload = load_jsonl_line(
        '{"type":"payment","issue":101,"agent":"A@test","amount":5,"note":"3^2 - \\!3 + 1 = 10"}'
    )

    assert payload["issue"] == 101
    assert payload["note"] == "3^2 - \\!3 + 1 = 10"


def test_run_check_passes_for_valid_repo(case_root: Path) -> None:
    root = _make_repo(case_root)
    _write_history(
        root / "ledger" / "history" / "2026-04-18.jsonl",
        [
            {"type": "payment", "issue": 101, "agent": "A@test", "amount": 5},
            {"type": "trajectory_mint", "issue": 202, "agents": ["A@test"], "per_agent": [5]},
            {"type": "payment", "issue": 303, "agent": "A@test", "amount": 9},
        ],
    )
    _write_genome(
        root,
        "Codex-19@codex",
        [
            _valid_mutation(issue_value=101, commit="abc123", target_section="Memory"),
            _valid_mutation(
                issue_field="issue",
                issue_value="202+303",
                commit="def456",
                target_section="Instructions",
            ),
        ],
    )

    report, exit_code = run_check(root)

    assert exit_code == 0
    assert report["status"] == "PASS"
    assert report["summary"]["mutations_checked"] == 2
    assert report["violations"] == []


def test_run_check_accepts_legacy_issue_field(case_root: Path) -> None:
    root = _make_repo(case_root)
    _write_history(
        root / "ledger" / "history" / "2026-04-18.jsonl",
        [{"type": "payment", "issue": 404, "agent": "A@test", "amount": 7}],
    )
    _write_genome(
        root,
        "Claude-1@claude",
        [_valid_mutation(issue_field="issue", issue_value=404, commit="deadbeef")],
    )

    report, exit_code = run_check(root)

    assert exit_code == 0
    assert report["status"] == "PASS"


def test_run_check_accepts_legacy_invalid_escape_in_history(case_root: Path) -> None:
    root = _make_repo(case_root)
    _write_text(
        root / "ledger" / "history" / "2026-03-03.jsonl",
        '{"type":"payment","issue":101,"agent":"A@test","amount":5,"note":"3^2 - \\!3 + 1 = 10"}\n',
    )
    _write_genome(root, "Codex-19@codex", [_valid_mutation(issue_value=101, commit="abc123")])

    report, exit_code = run_check(root)

    assert exit_code == 0
    assert report["status"] == "PASS"


def test_run_check_fails_when_history_linkage_missing(case_root: Path) -> None:
    root = _make_repo(case_root)
    _write_history(
        root / "ledger" / "history" / "2026-04-18.jsonl",
        [{"type": "payment", "issue": 101, "agent": "A@test", "amount": 5}],
    )
    _write_genome(
        root,
        "Codex-19@codex",
        [_valid_mutation(issue_value=999, commit="abc123")],
    )

    report, exit_code = run_check(root)

    assert exit_code == 1
    assert report["status"] == "FAIL"
    assert report["violations"][0]["check"] == "history_linkage"
    assert report["violations"][0]["missing_issue_ids"] == [999]


def test_run_check_fails_when_issue_reference_is_malformed(case_root: Path) -> None:
    root = _make_repo(case_root)
    _write_history(
        root / "ledger" / "history" / "2026-04-18.jsonl",
        [{"type": "payment", "issue": 101, "agent": "A@test", "amount": 5}],
    )
    _write_genome(
        root,
        "Codex-19@codex",
        [_valid_mutation(issue_value="101+oops", commit="abc123")],
    )

    report, exit_code = run_check(root)

    assert exit_code == 1
    assert report["violations"][0]["check"] == "history_linkage"
    assert "not an integer" in report["violations"][0]["detail"]


def test_run_check_fails_when_commit_empty_string(case_root: Path) -> None:
    root = _make_repo(case_root)
    _write_history(
        root / "ledger" / "history" / "2026-04-18.jsonl",
        [{"type": "payment", "issue": 101, "agent": "A@test", "amount": 5}],
    )
    _write_genome(
        root,
        "Codex-19@codex",
        [_valid_mutation(issue_value=101, commit="")],
    )

    report, exit_code = run_check(root)

    assert exit_code == 1
    assert report["violations"][0]["check"] == "commit_non_empty"


def test_run_check_fails_when_commit_is_null(case_root: Path) -> None:
    root = _make_repo(case_root)
    _write_history(
        root / "ledger" / "history" / "2026-04-18.jsonl",
        [{"type": "payment", "issue": 101, "agent": "A@test", "amount": 5}],
    )
    _write_genome(
        root,
        "Codex-19@codex",
        [_valid_mutation(issue_value=101, commit=None)],
    )

    report, exit_code = run_check(root)

    assert exit_code == 1
    assert report["violations"][0]["check"] == "commit_non_empty"
    assert report["violations"][0]["commit"] is None


def test_run_check_fails_for_duplicate_pair_within_same_genome(case_root: Path) -> None:
    root = _make_repo(case_root)
    _write_history(
        root / "ledger" / "history" / "2026-04-18.jsonl",
        [{"type": "payment", "issue": 101, "agent": "A@test", "amount": 5}],
    )
    _write_genome(
        root,
        "Codex-19@codex",
        [
            _valid_mutation(issue_field="trigger_issue", issue_value=101, commit="aaa"),
            _valid_mutation(issue_field="issue", issue_value="101", commit="bbb"),
        ],
    )

    report, exit_code = run_check(root)

    assert exit_code == 1
    duplicate = next(
        violation
        for violation in report["violations"]
        if violation["check"] == "unique_issue_target_section"
    )
    assert duplicate["issue_key"] == "101"
    assert duplicate["target_section"] == "Memory"


def test_run_check_allows_same_pair_in_different_genomes(case_root: Path) -> None:
    root = _make_repo(case_root)
    _write_history(
        root / "ledger" / "history" / "2026-04-18.jsonl",
        [{"type": "payment", "issue": 101, "agent": "A@test", "amount": 5}],
    )
    _write_genome(root, "Codex-19@codex", [_valid_mutation(issue_value=101, commit="aaa")])
    _write_genome(root, "Claude-1@claude", [_valid_mutation(issue_value=101, commit="bbb")])

    report, exit_code = run_check(root)

    assert exit_code == 0
    assert report["status"] == "PASS"


def test_run_check_fails_on_invalid_genome_json(case_root: Path) -> None:
    root = _make_repo(case_root)
    _write_history(
        root / "ledger" / "history" / "2026-04-18.jsonl",
        [{"type": "payment", "issue": 101, "agent": "A@test", "amount": 5}],
    )
    _write_genome(root, "Codex-19@codex", [], raw_text="{not-json")

    report, exit_code = run_check(root)

    assert exit_code == 1
    assert report["violations"][0]["check"] == "genome_meta_readable"
    assert "contains invalid JSON" in report["violations"][0]["detail"]


def test_run_check_fails_on_invalid_history_jsonl(case_root: Path) -> None:
    root = _make_repo(case_root)
    _write_text(root / "ledger" / "history" / "2026-04-18.jsonl", "{bad-json\n")
    _write_genome(root, "Codex-19@codex", [_valid_mutation(issue_value=101, commit="aaa")])

    report, exit_code = run_check(root)

    assert exit_code == 1
    assert report["violations"][0]["check"] == "repository"
    assert "contains invalid JSON" in report["violations"][0]["detail"]


def test_run_check_fails_when_mutations_is_not_a_list(case_root: Path) -> None:
    root = _make_repo(case_root)
    _write_history(
        root / "ledger" / "history" / "2026-04-18.jsonl",
        [{"type": "payment", "issue": 101, "agent": "A@test", "amount": 5}],
    )
    _write_genome(
        root,
        "Codex-19@codex",
        [],
        extra_payload={"mutations": {"bad": "shape"}},
    )

    report, exit_code = run_check(root)

    assert exit_code == 1
    assert report["violations"][0]["check"] == "mutations_list"


def test_run_check_fails_when_mutation_entry_is_not_object(case_root: Path) -> None:
    root = _make_repo(case_root)
    _write_history(
        root / "ledger" / "history" / "2026-04-18.jsonl",
        [{"type": "payment", "issue": 101, "agent": "A@test", "amount": 5}],
    )
    _write_genome(root, "Codex-19@codex", ["bad-entry"])

    report, exit_code = run_check(root)

    assert exit_code == 1
    assert report["violations"][0]["check"] == "mutation_object"


def test_main_emits_pass_json(case_root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _make_repo(case_root)
    _write_history(
        root / "ledger" / "history" / "2026-04-18.jsonl",
        [{"type": "payment", "issue": 101, "agent": "A@test", "amount": 5}],
    )
    _write_genome(root, "Codex-19@codex", [_valid_mutation(issue_value=101, commit="abc123")])

    exit_code = main(["--root", str(root)])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["status"] == "PASS"


def test_cli_returns_exit_code_one_for_failure(case_root: Path) -> None:
    root = _make_repo(case_root)
    _write_history(
        root / "ledger" / "history" / "2026-04-18.jsonl",
        [{"type": "payment", "issue": 101, "agent": "A@test", "amount": 5}],
    )
    _write_genome(root, "Codex-19@codex", [_valid_mutation(issue_value=999, commit="")])

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root)],
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(result.stdout)
    assert result.returncode == 1
    assert payload["status"] == "FAIL"
    assert payload["summary"]["violations"] == 2
