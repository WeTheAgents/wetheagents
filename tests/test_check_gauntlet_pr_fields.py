from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import scripts.check_gauntlet_pr_fields as check_gauntlet_pr_fields

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "check_gauntlet_pr_fields.py"


def make_body(**overrides: str) -> str:
    fields = {
        "frontier_closed": "Closes a missing contract for gauntlet PR bodies",
        "artifact": "scripts/check_gauntlet_pr_fields.py + tests/test_check_gauntlet_pr_fields.py",
        "evidence": "9/9 targeted tests pass and CLI invocation returns PASS",
        "made_redundant": "Manual eyeballing of required PR metadata",
        "redundancy_proof": "The checker parses the PR body directly and rejects missing or empty fields.",
    }
    fields.update(overrides)
    return "\n".join(f"{name}: {value}" for name, value in fields.items())


def run_script(
    *,
    args: list[str] | None = None,
    stdin: str | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    run_env = os.environ.copy()
    if env:
        run_env.update(env)
    return subprocess.run(
        [sys.executable, str(SCRIPT), *(args or [])],
        cwd=REPO_ROOT,
        text=True,
        input=stdin,
        capture_output=True,
        check=False,
        env=run_env,
    )


def test_evaluate_passes_when_all_fields_present_and_non_empty() -> None:
    result = check_gauntlet_pr_fields.evaluate_pr_body(make_body())

    assert result == {"status": "PASS", "missing": [], "empty": []}


def test_evaluate_fails_when_one_field_is_missing() -> None:
    body = make_body().replace("artifact: scripts/check_gauntlet_pr_fields.py + tests/test_check_gauntlet_pr_fields.py\n", "")

    result = check_gauntlet_pr_fields.evaluate_pr_body(body)

    assert result["status"] == "FAIL"
    assert result["missing"] == ["artifact"]
    assert result["empty"] == []


def test_evaluate_fails_when_field_has_empty_value() -> None:
    result = check_gauntlet_pr_fields.evaluate_pr_body(make_body(evidence=""))

    assert result["status"] == "FAIL"
    assert result["missing"] == []
    assert result["empty"] == ["evidence"]


def test_evaluate_fails_when_all_fields_missing() -> None:
    result = check_gauntlet_pr_fields.evaluate_pr_body("This PR body forgot every gauntlet field.")

    assert result["status"] == "FAIL"
    assert result["missing"] == list(check_gauntlet_pr_fields.REQUIRED_FIELDS)
    assert result["empty"] == []


def test_evaluate_fails_when_field_has_only_whitespace() -> None:
    result = check_gauntlet_pr_fields.evaluate_pr_body(make_body(made_redundant="   \n\t"))

    assert result["status"] == "FAIL"
    assert result["empty"] == ["made_redundant"]


def test_evaluate_ignores_extra_fields() -> None:
    body = make_body() + "\nbonus_field: extra context"

    result = check_gauntlet_pr_fields.evaluate_pr_body(body)

    assert result["status"] == "PASS"


def test_evaluate_fails_on_partial_field_names() -> None:
    body = "\n".join(
        [
            "frontier: almost right but not the canonical field",
            "artifact: scripts/check_gauntlet_pr_fields.py",
            "evidence: tests pass",
            "made_redundant: Nothing — new enforcement dimension",
            "redundancy: also almost right",
        ]
    )

    result = check_gauntlet_pr_fields.evaluate_pr_body(body)

    assert result["status"] == "FAIL"
    assert result["missing"] == ["frontier_closed", "redundancy_proof"]


def test_evaluate_passes_when_fields_are_in_any_order() -> None:
    body = "\n".join(
        [
            "redundancy_proof: N/A",
            "artifact: scripts/check_gauntlet_pr_fields.py + tests/test_check_gauntlet_pr_fields.py",
            "frontier_closed: Order should not matter",
            "made_redundant: Nothing — new enforcement dimension",
            "evidence: 8 required scenarios covered",
        ]
    )

    result = check_gauntlet_pr_fields.evaluate_pr_body(body)

    assert result["status"] == "PASS"


def test_evaluate_accepts_multiline_field_values() -> None:
    body = "\n".join(
        [
            "frontier_closed: Closes a schema gap",
            "artifact: scripts/check_gauntlet_pr_fields.py",
            "evidence: 13/13 tests pass",
            "  Manual CLI invocation passes too",
            "made_redundant: Manual review of PR metadata",
            "redundancy_proof: The checker parses all required keys directly.",
        ]
    )

    result = check_gauntlet_pr_fields.evaluate_pr_body(body)

    assert result["status"] == "PASS"


def test_cli_accepts_body_argument_and_exits_zero_on_pass() -> None:
    completed = run_script(args=[make_body()])

    assert completed.returncode == 0
    assert json.loads(completed.stdout) == {"status": "PASS", "missing": [], "empty": []}


def test_cli_accepts_stdin_and_env_var() -> None:
    stdin_result = run_script(stdin=make_body(redundancy_proof="N/A"))
    env_result = run_script(env={"PR_BODY": make_body(frontier_closed="Loaded from env")})

    assert stdin_result.returncode == 0
    assert json.loads(stdin_result.stdout)["status"] == "PASS"
    assert env_result.returncode == 0
    assert json.loads(env_result.stdout)["status"] == "PASS"


@pytest.mark.parametrize("placeholder", ["<what gap this closes>", "_No response_", "TODO"])
def test_evaluate_treats_placeholder_values_as_empty(placeholder: str) -> None:
    result = check_gauntlet_pr_fields.evaluate_pr_body(make_body(frontier_closed=placeholder))

    assert result["status"] == "FAIL"
    assert result["empty"] == ["frontier_closed"]


def test_evaluate_matches_field_names_case_insensitively() -> None:
    body = "\n".join(
        [
            "FRONTIER_CLOSED: Case-insensitive parsing works",
            "Artifact: scripts/check_gauntlet_pr_fields.py",
            "EVIDENCE: 14/14 tests pass",
            "Made_Redundant: Manual PR-body scanning",
            "Redundancy_Proof: The regex normalizes field names before evaluation.",
        ]
    )

    result = check_gauntlet_pr_fields.evaluate_pr_body(body)

    assert result["status"] == "PASS"
