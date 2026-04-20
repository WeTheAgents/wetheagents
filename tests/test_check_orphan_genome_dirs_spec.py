"""Boundary spec tests for scripts/check_orphan_genome_dirs.py.

Encodes the full behavioural contract for edge inputs:

  (a) empty genomes/ dir — PASS
  (b) base/ dir excluded from orphan consideration — PASS
  (c) agent with genome dir AND registered in balances.json — PASS
  (d) agent with genome dir but NOT in balances.json — FAIL
  (e) balances.json absent — PASS (skip gracefully)
  (f) genome_meta.json absent from genome dir — still counted as orphan dir
  (g) agent name containing @, -, digits — exact-match normalization is correct
  (h) multiple orphan dirs — all reported
  (i) case-sensitive match — directory with different capitalisation = FAIL
  (j) balances.json with zero agents — all genome dirs are orphans
  (k) single genome dir matching the sole registered agent — PASS
  (l) mixed registered / unregistered dirs — only orphans reported
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from scripts.check_orphan_genome_dirs import run_check


# ── helpers ───────────────────────────────────────────────────────────────────


def _write_balances(root: Path, agents: dict[str, Any]) -> None:
    path = root / "ledger" / "balances.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"version": 1, "agents": agents}),
        encoding="utf-8",
    )


def _make_genome_dir(root: Path, name: str, *, with_meta: bool = True) -> None:
    d = root / "genomes" / name
    d.mkdir(parents=True, exist_ok=True)
    if with_meta:
        (d / "genome_meta.json").write_text("{}", encoding="utf-8")


def _zero_agent() -> dict[str, Any]:
    """Agent payload with no tasks or earnings — does not trigger missing-genome check."""
    return {"tasks_completed": 0, "total_earned": 0}


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Minimal repo skeleton: genomes/ created, ledger/ absent until test adds it."""
    (tmp_path / "genomes").mkdir()
    return tmp_path


# ── (a) empty genomes/ dir ────────────────────────────────────────────────────


def test_spec_a_empty_genomes_dir_passes(repo: Path) -> None:
    """No subdirectories in genomes/ → zero orphans → PASS."""
    _write_balances(repo, {})

    report, exit_code = run_check(repo)

    assert exit_code == 0
    assert report["status"] == "PASS"
    assert report["orphan_genome_dirs"] == []


def test_spec_a_files_in_genomes_root_are_ignored(repo: Path) -> None:
    """Plain files directly under genomes/ are not treated as genome dirs."""
    _write_balances(repo, {})
    # Create a plain file, not a directory
    (repo / "genomes" / "README.txt").write_text("not a genome dir\n", encoding="utf-8")

    report, exit_code = run_check(repo)

    assert exit_code == 0
    assert report["status"] == "PASS"
    assert report["orphan_genome_dirs"] == []


# ── (b) base/ dir excluded ────────────────────────────────────────────────────


def test_spec_b_base_dir_excluded_passes(repo: Path) -> None:
    """genomes/base/ is always skipped — never an orphan regardless of registration."""
    _write_balances(repo, {})
    _make_genome_dir(repo, "base")

    report, exit_code = run_check(repo)

    assert exit_code == 0
    assert report["status"] == "PASS"
    assert report["orphan_genome_dirs"] == []


def test_spec_b_base_excluded_even_with_other_orphans(repo: Path) -> None:
    """base/ skipped while other non-registered dirs are still flagged."""
    _write_balances(repo, {})
    _make_genome_dir(repo, "base")
    _make_genome_dir(repo, "stranger@void")

    report, exit_code = run_check(repo)

    assert exit_code == 1
    assert report["status"] == "FAIL"
    agent_dirs = [o["agent_dir"] for o in report["orphan_genome_dirs"]]
    assert "base" not in agent_dirs
    assert "stranger@void" in agent_dirs


# ── (c) registered agent with genome dir ─────────────────────────────────────


def test_spec_c_registered_agent_with_genome_passes(repo: Path) -> None:
    """Genome dir whose name exactly matches a registered agent → PASS."""
    _write_balances(repo, {"Claude-5@claude": _zero_agent()})
    _make_genome_dir(repo, "Claude-5@claude")

    report, exit_code = run_check(repo)

    assert exit_code == 0
    assert report["status"] == "PASS"
    assert report["orphan_genome_dirs"] == []


# ── (d) genome dir not in balances.json ──────────────────────────────────────


def test_spec_d_unregistered_genome_dir_fails(repo: Path) -> None:
    """Genome dir whose name does NOT appear in balances.json → FAIL."""
    _write_balances(repo, {"Claude-5@claude": _zero_agent()})
    _make_genome_dir(repo, "Ghost-99@ghost")  # not in balances

    report, exit_code = run_check(repo)

    assert exit_code == 1
    assert report["status"] == "FAIL"
    agent_dirs = [o["agent_dir"] for o in report["orphan_genome_dirs"]]
    assert "Ghost-99@ghost" in agent_dirs
    assert "Claude-5@claude" not in agent_dirs


# ── (e) balances.json absent ─────────────────────────────────────────────────


def test_spec_e_missing_balances_skips_gracefully(tmp_path: Path) -> None:
    """When balances.json is absent the check is skipped: exit 0, status PASS."""
    (tmp_path / "genomes").mkdir()
    _make_genome_dir(tmp_path, "Claude-5@claude")
    # Intentionally: no ledger/ or balances.json

    report, exit_code = run_check(tmp_path)

    assert exit_code == 0
    assert report["status"] == "PASS"


def test_spec_e_missing_balances_does_not_raise(tmp_path: Path) -> None:
    """No exception is raised when balances.json is absent."""
    (tmp_path / "genomes").mkdir()

    try:
        report, exit_code = run_check(tmp_path)
    except Exception as exc:
        pytest.fail(f"run_check raised {type(exc).__name__}: {exc}")

    assert "status" in report


# ── (f) genome dir without genome_meta.json ───────────────────────────────────


def test_spec_f_genome_dir_without_meta_is_still_detected(repo: Path) -> None:
    """A genome dir with NO genome_meta.json is still counted and can be an orphan."""
    _write_balances(repo, {})
    _make_genome_dir(repo, "Phantom-7@claude", with_meta=False)
    # Confirm no genome_meta.json
    assert not (repo / "genomes" / "Phantom-7@claude" / "genome_meta.json").exists()

    report, exit_code = run_check(repo)

    assert exit_code == 1
    agent_dirs = [o["agent_dir"] for o in report["orphan_genome_dirs"]]
    assert "Phantom-7@claude" in agent_dirs


def test_spec_f_genome_dir_with_meta_registered_still_passes(repo: Path) -> None:
    """Registered dir WITH genome_meta.json → PASS (baseline for (f))."""
    _write_balances(repo, {"Phantom-7@claude": _zero_agent()})
    _make_genome_dir(repo, "Phantom-7@claude", with_meta=True)

    report, exit_code = run_check(repo)

    assert exit_code == 0
    assert report["orphan_genome_dirs"] == []


# ── (g) agent name with @/-/digits ────────────────────────────────────────────


def test_spec_g_at_hyphen_digits_match_correctly(repo: Path) -> None:
    """Agent IDs containing @, -, and digits are matched exactly without transformation."""
    _write_balances(repo, {"Claude-5@claude": _zero_agent()})
    _make_genome_dir(repo, "Claude-5@claude")

    report, exit_code = run_check(repo)

    assert exit_code == 0
    assert report["status"] == "PASS"
    assert report["orphan_genome_dirs"] == []


def test_spec_g_complex_ids_multiple_agents(repo: Path) -> None:
    """Multiple agents with complex IDs all matched — no false positives."""
    _write_balances(repo, {
        "Codex-19@codex": _zero_agent(),
        "gemini-4@google": _zero_agent(),
        "cursor-3@cursor": _zero_agent(),
    })
    _make_genome_dir(repo, "Codex-19@codex")
    _make_genome_dir(repo, "gemini-4@google")
    _make_genome_dir(repo, "cursor-3@cursor")

    report, exit_code = run_check(repo)

    assert exit_code == 0
    assert report["orphan_genome_dirs"] == []


# ── (h) multiple orphan dirs ─────────────────────────────────────────────────


def test_spec_h_multiple_orphans_all_reported(repo: Path) -> None:
    """All orphan directories are reported, not just the first."""
    _write_balances(repo, {})
    _make_genome_dir(repo, "A-1@x")
    _make_genome_dir(repo, "B-2@y")
    _make_genome_dir(repo, "C-3@z")

    report, exit_code = run_check(repo)

    assert exit_code == 1
    agent_dirs = [o["agent_dir"] for o in report["orphan_genome_dirs"]]
    assert "A-1@x" in agent_dirs
    assert "B-2@y" in agent_dirs
    assert "C-3@z" in agent_dirs
    assert len(report["orphan_genome_dirs"]) == 3


# ── (i) case-sensitive matching ───────────────────────────────────────────────


def test_spec_i_uppercase_dir_vs_lowercase_registration_fails(repo: Path) -> None:
    """Directory 'claude-5@claude' does NOT match registration 'Claude-5@claude'."""
    _write_balances(repo, {"Claude-5@claude": _zero_agent()})
    _make_genome_dir(repo, "claude-5@claude")  # lowercase leading 'c'

    report, exit_code = run_check(repo)

    assert exit_code == 1
    assert report["status"] == "FAIL"
    agent_dirs = [o["agent_dir"] for o in report["orphan_genome_dirs"]]
    assert "claude-5@claude" in agent_dirs


def test_spec_i_exact_case_match_passes(repo: Path) -> None:
    """Exact same capitalisation → PASS (contrast with case mismatch test)."""
    _write_balances(repo, {"Claude-5@claude": _zero_agent()})
    _make_genome_dir(repo, "Claude-5@claude")  # exact case

    report, exit_code = run_check(repo)

    assert exit_code == 0
    assert report["status"] == "PASS"


# ── (j) balances.json with zero agents ───────────────────────────────────────


def test_spec_j_zero_agents_all_dirs_are_orphans(repo: Path) -> None:
    """agents={} means every genome dir is an orphan."""
    _write_balances(repo, {})
    _make_genome_dir(repo, "Claude-5@claude")
    _make_genome_dir(repo, "Codex-2@codex")

    report, exit_code = run_check(repo)

    assert exit_code == 1
    assert report["status"] == "FAIL"
    assert len(report["orphan_genome_dirs"]) == 2


# ── (k) single dir matches sole agent ────────────────────────────────────────


def test_spec_k_single_dir_matching_sole_agent_passes(repo: Path) -> None:
    """Exactly one genome dir, exactly one registered agent, exact match → PASS."""
    _write_balances(repo, {"Codex-2@codex": {"tasks_completed": 1, "total_earned": 10}})
    _make_genome_dir(repo, "Codex-2@codex")

    report, exit_code = run_check(repo)

    assert exit_code == 0
    assert report["status"] == "PASS"
    assert report["orphan_genome_dirs"] == []


# ── (l) mixed registered / unregistered ──────────────────────────────────────


def test_spec_l_mixed_dirs_only_orphans_reported(repo: Path) -> None:
    """Registered dirs are silent; only unregistered dirs appear in orphan list."""
    _write_balances(repo, {
        "Claude-5@claude": {"tasks_completed": 1, "total_earned": 10},
        "Codex-2@codex": {"tasks_completed": 0, "total_earned": 5},
    })
    _make_genome_dir(repo, "Claude-5@claude")   # registered
    _make_genome_dir(repo, "Codex-2@codex")     # registered
    _make_genome_dir(repo, "Ghost-99@ghost")    # orphan

    report, exit_code = run_check(repo)

    assert exit_code == 1
    assert report["status"] == "FAIL"
    agent_dirs = [o["agent_dir"] for o in report["orphan_genome_dirs"]]
    assert agent_dirs == ["Ghost-99@ghost"]
