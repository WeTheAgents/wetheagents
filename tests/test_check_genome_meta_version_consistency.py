"""Tests for scripts/check_genome_meta_version_consistency.py."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from scripts.check_genome_meta_version_consistency import (
    classify_meta_version,
    classify_mutation_version,
    main,
    run_check,
)

SCRIPT = (
    Path(__file__).resolve().parent.parent
    / "scripts"
    / "check_genome_meta_version_consistency.py"
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _make_repo(tmp_path: Path) -> Path:
    (tmp_path / "genomes").mkdir(parents=True, exist_ok=True)
    return tmp_path


@pytest.fixture
def case_root() -> Path:
    root = Path(".test_runs") / "check_genome_meta_version_consistency" / uuid4().hex
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)
    yield root
    shutil.rmtree(root, ignore_errors=True)


def _valid_fitness() -> dict[str, Any]:
    return {
        "tasks_completed": 1,
        "tasks_created": 0,
        "initiative_ratio": None,
        "acceptance_rate": 0.5,
        "rework_rate": 0.0,
        "avg_time_in_stage_hours": None,
        "zero_code_ratio": 0.0,
        "review_quality": None,
        "composite_score": None,
        "total_earned": 10,
        "total_minted": 15,
        "gauntlet_slots": 2,
        "total_income": 25,
    }


def _valid_snapshot() -> dict[str, int]:
    return {
        "tasks_completed": 1,
        "total_earned": 10,
        "total_minted": 15,
        "total_income": 25,
    }


def _valid_provenance() -> dict[str, Any]:
    return {
        "sgr_version": 1,
        "proposals": [
            {
                "proposal_hash": "agent0-synthesized",
                "severity": "memory",
                "experience": {
                    "task_id": "374+381",
                    "mechanic": "gauntlet+every_good",
                    "outcome": "accepted",
                    "agent_role": "implementor",
                    "key_moment": "A precise guardrail prevented downstream drift.",
                },
                "reflection_summary": "Capture the lesson in Memory.",
                "verdict": "approved",
                "target_section": "Memory",
            }
        ],
    }


def _valid_release_mutation(*, with_provenance: bool = False) -> dict[str, Any]:
    mutation: dict[str, Any] = {
        "commit": "",
        "date": "2026-04-21T19:54:19Z",
        "trigger_issue": "374+381",
        "author": "agent0@system",
        "sections_changed": ["Memory"],
        "lines_added": 6,
        "lines_removed": 0,
        "summary": "release #374+#381 - Codex-19 +2 memory entries",
        "fitness_before": _valid_snapshot(),
        "fitness_after": _valid_snapshot(),
    }
    if with_provenance:
        mutation["provenance"] = _valid_provenance()
    return mutation


def _valid_memory_mutation() -> dict[str, Any]:
    return {
        "trigger_issue": 587,
        "commit": "8ba5f20",
        "severity": "memory",
        "target_section": "Memory",
        "key_moment": "Pre-initialize before the loop.",
        "applied_at": "2026-04-20T13:12:59Z",
    }


def _valid_release_session_mutation() -> dict[str, Any]:
    return {
        "release_session": "#153",
        "date": "2026-03-11",
        "changes": [
            "Add structural diff guidance.",
            "Require stronger self-roast evidence.",
        ],
    }


def _valid_meta(
    agent_id: str,
    mutations: list[dict[str, Any]],
    *,
    donor_lineage: list[str] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "agent_id": agent_id,
        "generation": 0,
        "parent": None,
        "created_at": "2026-03-27T11:00:00Z",
        "last_snapshot": "2026-04-21T19:54:19Z",
        "role": "implementor",
        "fitness": _valid_fitness(),
        "lineage": [],
        "mutations": mutations,
    }
    if donor_lineage is not None:
        payload["donor_lineage"] = donor_lineage
    return payload


def _write_genome(root: Path, agent_id: str, payload: object) -> None:
    _write_json(root / "genomes" / agent_id / "genome_meta.json", payload)


def test_classifiers_recognize_supported_versions() -> None:
    assert classify_meta_version(_valid_meta("Codex-19@codex", [])) == "meta_v1"
    assert (
        classify_meta_version(
            _valid_meta("Claude-12@claude", [], donor_lineage=["Claude-1@claude"])
        )
        == "meta_v2"
    )
    assert classify_mutation_version(_valid_release_mutation()) == "mutation_release_v1"
    assert (
        classify_mutation_version(_valid_release_mutation(with_provenance=True))
        == "mutation_release_v1+provenance_v1"
    )
    assert classify_mutation_version(_valid_memory_mutation()) == "mutation_memory_v1"
    assert (
        classify_mutation_version(_valid_release_session_mutation())
        == "mutation_release_session_v1"
    )


def test_run_check_passes_for_supported_schema_mix(case_root: Path) -> None:
    root = _make_repo(case_root)
    _write_genome(
        root,
        "Codex-19@codex",
        _valid_meta(
            "Codex-19@codex",
            [
                _valid_release_mutation(with_provenance=True),
                _valid_memory_mutation(),
                _valid_release_session_mutation(),
            ],
        ),
    )
    _write_genome(
        root,
        "Claude-12@claude",
        _valid_meta(
            "Claude-12@claude",
            [_valid_release_mutation()],
            donor_lineage=["Claude-1@claude", "cursor-3@cursor"],
        ),
    )

    report, exit_code = run_check(root)

    assert exit_code == 0
    assert report["status"] == "PASS"
    assert report["summary"]["meta_versions"] == {"meta_v1": 1, "meta_v2": 1}
    assert report["summary"]["mutation_versions"] == {
        "mutation_memory_v1": 1,
        "mutation_release_session_v1": 1,
        "mutation_release_v1": 1,
        "mutation_release_v1+provenance_v1": 1,
    }


def test_run_check_passes_on_real_repo_snapshot() -> None:
    root = Path(__file__).resolve().parent.parent

    report, exit_code = run_check(root)

    assert exit_code == 0
    assert report["status"] == "PASS"
    assert report["summary"]["files_checked"] >= 1


def test_run_check_fails_for_unknown_top_level_key(case_root: Path) -> None:
    root = _make_repo(case_root)
    payload = _valid_meta("Codex-19@codex", [_valid_release_mutation()])
    payload["schema_version"] = 3
    _write_genome(root, "Codex-19@codex", payload)

    report, exit_code = run_check(root)

    assert exit_code == 1
    assert report["violations"][0]["check"] == "meta_shape"
    assert report["violations"][0]["detail"] == "unsupported top-level key set"


def test_run_check_fails_for_missing_fitness_key(case_root: Path) -> None:
    root = _make_repo(case_root)
    payload = _valid_meta("Codex-19@codex", [_valid_release_mutation()])
    del payload["fitness"]["total_income"]
    _write_genome(root, "Codex-19@codex", payload)

    report, exit_code = run_check(root)

    assert exit_code == 1
    assert any(v["check"] == "fitness_shape" for v in report["violations"])


def test_run_check_fails_for_directory_agent_id_mismatch(case_root: Path) -> None:
    root = _make_repo(case_root)
    _write_genome(
        root,
        "Codex-19@codex",
        _valid_meta("Codex-2@codex", [_valid_release_mutation()]),
    )

    report, exit_code = run_check(root)

    assert exit_code == 1
    assert any(v["check"] == "agent_identity" for v in report["violations"])


def test_run_check_fails_for_unknown_mutation_shape(case_root: Path) -> None:
    root = _make_repo(case_root)
    mutation = _valid_release_mutation()
    mutation["mystery"] = True
    _write_genome(root, "Codex-19@codex", _valid_meta("Codex-19@codex", [mutation]))

    report, exit_code = run_check(root)

    assert exit_code == 1
    assert any(v["check"] == "mutation_shape" for v in report["violations"])


def test_run_check_fails_for_invalid_release_mutation_payload(case_root: Path) -> None:
    root = _make_repo(case_root)
    mutation = _valid_release_mutation()
    mutation["lines_added"] = "six"
    mutation["sections_changed"] = ["Memory", ""]
    mutation["fitness_before"] = {"total_income": "25"}
    _write_genome(root, "Codex-19@codex", _valid_meta("Codex-19@codex", [mutation]))

    report, exit_code = run_check(root)

    assert exit_code == 1
    assert sum(1 for v in report["violations"] if v["check"] == "mutation_shape") >= 3


def test_run_check_accepts_legacy_release_null_commit(case_root: Path) -> None:
    root = _make_repo(case_root)
    mutation = _valid_release_mutation()
    mutation["commit"] = None
    _write_genome(root, "Codex-19@codex", _valid_meta("Codex-19@codex", [mutation]))

    report, exit_code = run_check(root)

    assert exit_code == 0
    assert report["status"] == "PASS"


def test_run_check_fails_for_invalid_memory_mutation_timestamp(case_root: Path) -> None:
    root = _make_repo(case_root)
    mutation = _valid_memory_mutation()
    mutation["applied_at"] = "2026/04/20 13:12:59"
    _write_genome(root, "Codex-19@codex", _valid_meta("Codex-19@codex", [mutation]))

    report, exit_code = run_check(root)

    assert exit_code == 1
    assert any(v["check"] == "timestamp_format" for v in report["violations"])


def test_run_check_fails_for_invalid_release_session_changes(case_root: Path) -> None:
    root = _make_repo(case_root)
    mutation = _valid_release_session_mutation()
    mutation["changes"] = ["valid", 42]
    _write_genome(root, "Codex-19@codex", _valid_meta("Codex-19@codex", [mutation]))

    report, exit_code = run_check(root)

    assert exit_code == 1
    assert any(v["check"] == "mutation_shape" for v in report["violations"])


def test_run_check_fails_for_unsupported_provenance_version(case_root: Path) -> None:
    root = _make_repo(case_root)
    mutation = _valid_release_mutation(with_provenance=True)
    mutation["provenance"]["sgr_version"] = 2
    _write_genome(root, "Codex-19@codex", _valid_meta("Codex-19@codex", [mutation]))

    report, exit_code = run_check(root)

    assert exit_code == 1
    assert any(v["detail"] == "unsupported provenance version" for v in report["violations"])


def test_run_check_fails_for_invalid_provenance_experience_shape(case_root: Path) -> None:
    root = _make_repo(case_root)
    mutation = _valid_release_mutation(with_provenance=True)
    del mutation["provenance"]["proposals"][0]["experience"]["mechanic"]
    _write_genome(root, "Codex-19@codex", _valid_meta("Codex-19@codex", [mutation]))

    report, exit_code = run_check(root)

    assert exit_code == 1
    assert any(v["check"] == "provenance_shape" for v in report["violations"])


def test_run_check_accepts_legacy_provenance_without_agent_role(case_root: Path) -> None:
    root = _make_repo(case_root)
    mutation = _valid_release_mutation(with_provenance=True)
    del mutation["provenance"]["proposals"][0]["experience"]["agent_role"]
    _write_genome(root, "Codex-19@codex", _valid_meta("Codex-19@codex", [mutation]))

    report, exit_code = run_check(root)

    assert exit_code == 0
    assert report["status"] == "PASS"


def test_run_check_fails_for_invalid_top_level_timestamp(case_root: Path) -> None:
    root = _make_repo(case_root)
    payload = _valid_meta("Codex-19@codex", [_valid_release_mutation()])
    payload["last_snapshot"] = "2026-04-21"
    _write_genome(root, "Codex-19@codex", payload)

    report, exit_code = run_check(root)

    assert exit_code == 1
    assert any(v["field"] == "last_snapshot" for v in report["violations"])


def test_run_check_fails_when_meta_is_not_object(case_root: Path) -> None:
    root = _make_repo(case_root)
    _write_genome(root, "Codex-19@codex", ["not", "an", "object"])

    report, exit_code = run_check(root)

    assert exit_code == 1
    assert report["violations"][0]["check"] == "meta_shape"


def test_main_emits_pass_json(case_root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _make_repo(case_root)
    _write_genome(root, "Codex-19@codex", _valid_meta("Codex-19@codex", []))

    exit_code = main(["--root", str(root)])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["status"] == "PASS"


def test_cli_returns_exit_code_one_for_failure(case_root: Path) -> None:
    root = _make_repo(case_root)
    payload = _valid_meta("Codex-19@codex", [_valid_release_mutation()])
    payload["role"] = ""
    _write_genome(root, "Codex-19@codex", payload)

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root)],
        capture_output=True,
        text=True,
        check=False,
    )

    report = json.loads(result.stdout)
    assert result.returncode == 1
    assert report["status"] == "FAIL"
    assert any(v["detail"] == "role must be a non-empty string" for v in report["violations"])
