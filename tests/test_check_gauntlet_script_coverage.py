"""Tests for scripts/check_gauntlet_script_coverage.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.check_gauntlet_script_coverage import (
    check_coverage,
    find_test_file,
    load_exceptions,
    main,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_script(tmp_path: Path, name: str) -> Path:
    p = tmp_path / "scripts" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("# script\n")
    return p


def _make_test(tmp_path: Path, name: str, subdir: str = "") -> Path:
    if subdir:
        p = tmp_path / "tests" / subdir / name
    else:
        p = tmp_path / "tests" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("# test\n")
    return p


def _make_exceptions(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "scripts" / "COVERAGE_EXCEPTIONS.txt"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return p


def _run(tmp_path: Path) -> dict:
    return check_coverage(
        tmp_path / "scripts",
        tmp_path / "tests",
        tmp_path / "scripts" / "COVERAGE_EXCEPTIONS.txt",
    )


# ---------------------------------------------------------------------------
# load_exceptions
# ---------------------------------------------------------------------------


def test_load_exceptions_parses_name_and_reason(tmp_path):
    exc = tmp_path / "COVERAGE_EXCEPTIONS.txt"
    exc.write_text("check_foo.py: no test because reasons\ncheck_bar.py: legacy\n")
    result = load_exceptions(exc)
    assert result == {
        "check_foo.py": "no test because reasons",
        "check_bar.py": "legacy",
    }


def test_load_exceptions_skips_comments_and_blanks(tmp_path):
    exc = tmp_path / "COVERAGE_EXCEPTIONS.txt"
    exc.write_text("# this is a comment\n\ncheck_foo.py: reason\n")
    result = load_exceptions(exc)
    assert result == {"check_foo.py": "reason"}


def test_load_exceptions_missing_file_returns_empty(tmp_path):
    result = load_exceptions(tmp_path / "nonexistent.txt")
    assert result == {}


# ---------------------------------------------------------------------------
# find_test_file
# ---------------------------------------------------------------------------


def test_find_test_file_direct_match(tmp_path):
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    tf = tests_dir / "test_check_foo.py"
    tf.write_text("# test")
    found = find_test_file("check_foo", tests_dir)
    assert found == tf


def test_find_test_file_in_subdirectory(tmp_path):
    """Test that tests in a subdirectory are found."""
    sub = tmp_path / "tests" / "unit"
    sub.mkdir(parents=True)
    tf = sub / "test_check_bar.py"
    tf.write_text("# test")
    found = find_test_file("check_bar", tmp_path / "tests")
    assert found == tf


def test_find_test_file_not_found_returns_none(tmp_path):
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    found = find_test_file("check_missing", tests_dir)
    assert found is None


def test_find_test_file_adversarial_suffix_does_not_match(tmp_path):
    """test_check_foo_adversarial.py must NOT count as test_check_foo.py."""
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_check_foo_adversarial.py").write_text("# adversarial")
    found = find_test_file("check_foo", tests_dir)
    assert found is None


# ---------------------------------------------------------------------------
# check_coverage — pass cases
# ---------------------------------------------------------------------------


def test_all_covered_returns_pass(tmp_path):
    _make_script(tmp_path, "check_alpha.py")
    _make_test(tmp_path, "test_check_alpha.py")
    _make_exceptions(tmp_path, "")
    result = _run(tmp_path)
    assert result["status"] == "pass"
    assert result["uncovered"] == []
    assert len(result["covered"]) == 1
    assert result["stats"]["total"] == 1


def test_excepted_script_counts_as_pass(tmp_path):
    _make_script(tmp_path, "check_legacy.py")
    _make_exceptions(tmp_path, "check_legacy.py: pre-dates test_check_* naming\n")
    result = _run(tmp_path)
    assert result["status"] == "pass"
    assert result["uncovered"] == []
    assert len(result["excepted"]) == 1
    assert result["excepted"][0]["script"] == "check_legacy.py"


def test_empty_scripts_dir_returns_pass(tmp_path):
    """No scripts → nothing to cover → pass."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "tests").mkdir()
    _make_exceptions(tmp_path, "")
    result = _run(tmp_path)
    assert result["status"] == "pass"
    assert result["stats"]["total"] == 0


def test_covered_entry_contains_test_path(tmp_path):
    _make_script(tmp_path, "check_beta.py")
    tf = _make_test(tmp_path, "test_check_beta.py")
    _make_exceptions(tmp_path, "")
    result = _run(tmp_path)
    assert result["covered"][0]["test"] == str(tf)


def test_script_with_test_in_subdirectory_is_covered(tmp_path):
    _make_script(tmp_path, "check_sub.py")
    _make_test(tmp_path, "test_check_sub.py", subdir="integration")
    _make_exceptions(tmp_path, "")
    result = _run(tmp_path)
    assert result["status"] == "pass"
    assert len(result["covered"]) == 1


# ---------------------------------------------------------------------------
# check_coverage — fail cases
# ---------------------------------------------------------------------------


def test_one_uncovered_script_returns_fail(tmp_path):
    _make_script(tmp_path, "check_orphan.py")
    _make_exceptions(tmp_path, "")
    result = _run(tmp_path)
    assert result["status"] == "fail"
    assert "check_orphan.py" in result["uncovered"]
    assert result["stats"]["uncovered_count"] == 1


def test_missing_exceptions_file_returns_fail(tmp_path):
    """COVERAGE_EXCEPTIONS.txt absent → status fail even if all scripts covered."""
    _make_script(tmp_path, "check_gamma.py")
    _make_test(tmp_path, "test_check_gamma.py")
    # Do NOT create exceptions file
    result = _run(tmp_path)
    assert result["status"] == "fail"
    assert result["_missing_exceptions_file"] is True


# ---------------------------------------------------------------------------
# stats correctness
# ---------------------------------------------------------------------------


def test_stats_counts_are_accurate(tmp_path):
    _make_script(tmp_path, "check_a.py")
    _make_script(tmp_path, "check_b.py")
    _make_script(tmp_path, "check_c.py")
    _make_test(tmp_path, "test_check_a.py")
    _make_exceptions(tmp_path, "check_b.py: no test; reason\n")
    # check_c.py is uncovered
    result = _run(tmp_path)
    assert result["stats"]["total"] == 3
    assert result["stats"]["covered_count"] == 1
    assert result["stats"]["excepted_count"] == 1
    assert result["stats"]["uncovered_count"] == 1


# ---------------------------------------------------------------------------
# main() exit codes and JSON output
# ---------------------------------------------------------------------------


def test_main_exits_0_when_all_covered(tmp_path):
    _make_script(tmp_path, "check_x.py")
    _make_test(tmp_path, "test_check_x.py")
    _make_exceptions(tmp_path, "")
    rc = main(["--root", str(tmp_path), "--json-only"])
    assert rc == 0


def test_main_exits_1_when_uncovered(tmp_path, capsys):
    _make_script(tmp_path, "check_uncov.py")
    _make_exceptions(tmp_path, "")
    rc = main(["--root", str(tmp_path), "--json-only"])
    assert rc == 1
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["status"] == "fail"
    assert "check_uncov.py" in data["uncovered"]


def test_main_json_output_schema(tmp_path, capsys):
    """JSON output must contain all required top-level keys."""
    _make_script(tmp_path, "check_z.py")
    _make_test(tmp_path, "test_check_z.py")
    _make_exceptions(tmp_path, "")
    main(["--root", str(tmp_path), "--json-only"])
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    for key in ("status", "uncovered", "covered", "excepted", "stats"):
        assert key in data
    for key in ("total", "covered_count", "uncovered_count", "excepted_count"):
        assert key in data["stats"]
