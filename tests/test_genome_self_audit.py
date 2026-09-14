"""Tests for scripts/genome_self_audit.py.

Covers:
  - _parse_sections: section parsing
  - _section_order: section ordering
  - check_agent: all 8 per-agent checks
  - run: full integration (pass/fail/warn aggregation)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.genome_self_audit import (
    CONSTITUTION_MARKER,
    PRESUBMISSION_CHECKLIST_ITEM,
    REQUIRED_SECTIONS,
    STALE_PLACEHOLDERS,
    _parse_sections,
    _section_order,
    check_agent,
    run,
)


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

_VALID_GENOME = f"""\
<!-- CONSTITUTION -->
> **North Star: Guaranteed Software Development.**

## Principles

1. Test principle.

---

## Role
The Specialist. Does things precisely.

## Instructions

**Before starting work:**
- Run `{PRESUBMISSION_CHECKLIST_ITEM}` to verify tests pass.

Step 1: read the spec.
Step 2: implement it.

## Pre-submission
**Output contract checklist:**
- [ ] `{PRESUBMISSION_CHECKLIST_ITEM}` passes.
- [ ] `python scripts/check_invariant.py` passes.

## Examples
Here is a good example of task completion.

## Memory
- Lesson 1: always read the spec first.
"""


def _make_repo(
    tmp_path: Path,
    agent_ids: list[str],
) -> Path:
    """Create a minimal valid repo under tmp_path. Returns repo root."""
    ledger = tmp_path / "ledger"
    ledger.mkdir()
    balances = {
        "version": 1,
        "agents": {
            aid: {"balance": 0, "github_username": "test"}
            for aid in agent_ids
        },
    }
    (ledger / "balances.json").write_text(json.dumps(balances), encoding="utf-8")

    genomes = tmp_path / "genomes"
    genomes.mkdir()
    return tmp_path


def _make_agent_genome(
    genomes_dir: Path,
    agent_id: str,
    content: str = _VALID_GENOME,
    meta: dict | None = None,
) -> None:
    """Write AGENTS.local.md (and optionally genome_meta.json) for agent_id."""
    agent_dir = genomes_dir / agent_id
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "AGENTS.local.md").write_text(content, encoding="utf-8")
    if meta is not None:
        (agent_dir / "genome_meta.json").write_text(json.dumps(meta), encoding="utf-8")


# ---------------------------------------------------------------------------
# Unit tests: _parse_sections
# ---------------------------------------------------------------------------


class TestParseSections:
    def test_constitution_only(self) -> None:
        text = "Preamble text here\nSecond line."
        sections = _parse_sections(text)
        assert "__constitution__" in sections
        assert "Preamble text here" in sections["__constitution__"]
        assert len(sections) == 1

    def test_single_section(self) -> None:
        text = "Preamble\n\n## Role\nI am a specialist.\n"
        sections = _parse_sections(text)
        assert "Role" in sections
        assert "I am a specialist." in sections["Role"]

    def test_multiple_sections(self) -> None:
        text = "Preamble\n\n## Role\nRole body.\n\n## Memory\nMemory body.\n"
        sections = _parse_sections(text)
        assert sections["Role"] == "Role body."
        assert sections["Memory"] == "Memory body."
        assert sections["__constitution__"] == "Preamble"

    def test_empty_section_body(self) -> None:
        text = "## Role\n\n## Instructions\nSome instructions."
        sections = _parse_sections(text)
        assert sections["Role"] == ""
        assert "Some instructions." in sections["Instructions"]

    def test_valid_genome_parses_all_sections(self) -> None:
        sections = _parse_sections(_VALID_GENOME)
        for name in REQUIRED_SECTIONS:
            assert name in sections, f"Missing section: {name}"


# ---------------------------------------------------------------------------
# Unit tests: _section_order
# ---------------------------------------------------------------------------


class TestSectionOrder:
    def test_correct_order(self) -> None:
        text = "Preamble\n## Role\n## Instructions\n## Pre-submission\n## Examples\n## Memory\n"
        order = _section_order(text)
        assert order == ["Role", "Instructions", "Pre-submission", "Examples", "Memory"]

    def test_wrong_order(self) -> None:
        text = "## Memory\n## Role\n## Instructions\n"
        order = _section_order(text)
        assert order == ["Memory", "Role", "Instructions"]

    def test_no_sections(self) -> None:
        text = "Just a preamble, no sections."
        order = _section_order(text)
        assert order == []


# ---------------------------------------------------------------------------
# Tests: check_agent — constitution check
# ---------------------------------------------------------------------------


class TestCheckAgentConstitution:
    def test_constitution_present(self, tmp_path: Path) -> None:
        genomes_dir = tmp_path / "genomes"
        _make_agent_genome(genomes_dir, "Claude-1@claude")
        results = check_agent("Claude-1@claude", genomes_dir)
        check = next(r for r in results if r["check"] == "constitution_present")
        assert check["status"] == "PASS"

    def test_constitution_missing(self, tmp_path: Path) -> None:
        genomes_dir = tmp_path / "genomes"
        content = "No North Star here.\n\n## Role\nSomething.\n## Instructions\nStuff.\n## Pre-submission\npytest.\n## Examples\nEx.\n## Memory\nMem."
        _make_agent_genome(genomes_dir, "Claude-1@claude", content=content)
        results = check_agent("Claude-1@claude", genomes_dir)
        check = next(r for r in results if r["check"] == "constitution_present")
        assert check["status"] == "FAIL"
        assert CONSTITUTION_MARKER in check["detail"]


# ---------------------------------------------------------------------------
# Tests: check_agent — required sections
# ---------------------------------------------------------------------------


class TestCheckAgentRequiredSections:
    def test_all_sections_present(self, tmp_path: Path) -> None:
        genomes_dir = tmp_path / "genomes"
        _make_agent_genome(genomes_dir, "Claude-2@claude")
        results = check_agent("Claude-2@claude", genomes_dir)
        check = next(r for r in results if r["check"] == "required_sections_present")
        assert check["status"] == "PASS"

    def test_missing_role_section(self, tmp_path: Path) -> None:
        genomes_dir = tmp_path / "genomes"
        content = f"Preamble with {CONSTITUTION_MARKER}\n\n## Instructions\nStuff.\n## Pre-submission\n{PRESUBMISSION_CHECKLIST_ITEM}\n## Examples\nEx.\n## Memory\nMem."
        _make_agent_genome(genomes_dir, "Claude-2@claude", content=content)
        results = check_agent("Claude-2@claude", genomes_dir)
        check = next(r for r in results if r["check"] == "required_sections_present")
        assert check["status"] == "FAIL"
        assert "Role" in check["detail"]

    def test_missing_multiple_sections(self, tmp_path: Path) -> None:
        genomes_dir = tmp_path / "genomes"
        content = f"Preamble with {CONSTITUTION_MARKER}\n\n## Role\nI am here."
        _make_agent_genome(genomes_dir, "Claude-2@claude", content=content)
        results = check_agent("Claude-2@claude", genomes_dir)
        check = next(r for r in results if r["check"] == "required_sections_present")
        assert check["status"] == "FAIL"


# ---------------------------------------------------------------------------
# Tests: check_agent — section order
# ---------------------------------------------------------------------------


class TestCheckAgentSectionOrder:
    def test_correct_order_passes(self, tmp_path: Path) -> None:
        genomes_dir = tmp_path / "genomes"
        _make_agent_genome(genomes_dir, "Claude-3@claude")
        results = check_agent("Claude-3@claude", genomes_dir)
        check = next(r for r in results if r["check"] == "section_order")
        assert check["status"] == "PASS"

    def test_wrong_order_fails(self, tmp_path: Path) -> None:
        genomes_dir = tmp_path / "genomes"
        # Memory before Role
        content = f"""\
{CONSTITUTION_MARKER}

## Memory
Old lesson.

## Role
My role.

## Instructions
Do stuff.

## Pre-submission
{PRESUBMISSION_CHECKLIST_ITEM}

## Examples
An example.
"""
        _make_agent_genome(genomes_dir, "Claude-3@claude", content=content)
        results = check_agent("Claude-3@claude", genomes_dir)
        check = next(r for r in results if r["check"] == "section_order")
        assert check["status"] == "FAIL"


# ---------------------------------------------------------------------------
# Tests: check_agent — stale placeholders
# ---------------------------------------------------------------------------


class TestCheckAgentStalePlaceholders:
    def test_no_stale_placeholders_passes(self, tmp_path: Path) -> None:
        genomes_dir = tmp_path / "genomes"
        _make_agent_genome(genomes_dir, "Claude-4@claude")
        results = check_agent("Claude-4@claude", genomes_dir)
        check = next(r for r in results if r["check"] == "no_stale_placeholders")
        assert check["status"] == "PASS"

    def test_stale_placeholder_detected(self, tmp_path: Path) -> None:
        genomes_dir = tmp_path / "genomes"
        stale_comment = STALE_PLACEHOLDERS[0]  # e.g., "<!-- Your specialization"
        content = _VALID_GENOME.replace("The Specialist. Does things precisely.", stale_comment + " -->")
        _make_agent_genome(genomes_dir, "Claude-4@claude", content=content)
        results = check_agent("Claude-4@claude", genomes_dir)
        check = next(r for r in results if r["check"] == "no_stale_placeholders")
        assert check["status"] == "FAIL"
        assert stale_comment in check["detail"]

    def test_exact_generation_zero_template_is_allowed(self, tmp_path: Path) -> None:
        genomes_dir = tmp_path / "genomes"
        template = (
            Path(__file__).resolve().parent.parent
            / "genomes"
            / "base"
            / "AGENTS.local.template.md"
        ).read_text(encoding="utf-8")
        base_dir = genomes_dir / "base"
        base_dir.mkdir(parents=True)
        (base_dir / "AGENTS.local.template.md").write_text(
            template, encoding="utf-8"
        )
        meta = {
            "agent_id": "New@agent",
            "generation": 0,
            "parent": None,
            "role": "unassigned",
            "lineage": [],
            "mutations": [],
        }
        _make_agent_genome(
            genomes_dir, "New@agent", content=template, meta=meta
        )

        results = check_agent("New@agent", genomes_dir)

        check = next(r for r in results if r["check"] == "no_stale_placeholders")
        assert check["status"] == "PASS"
        assert "generation-zero" in check["detail"]


# ---------------------------------------------------------------------------
# Tests: check_agent — role non-empty
# ---------------------------------------------------------------------------


class TestCheckAgentRoleNonEmpty:
    def test_non_empty_role_passes(self, tmp_path: Path) -> None:
        genomes_dir = tmp_path / "genomes"
        _make_agent_genome(genomes_dir, "Claude-5@claude")
        results = check_agent("Claude-5@claude", genomes_dir)
        check = next(r for r in results if r["check"] == "role_non_empty")
        assert check["status"] == "PASS"

    def test_empty_role_fails(self, tmp_path: Path) -> None:
        genomes_dir = tmp_path / "genomes"
        content = _VALID_GENOME.replace(
            "The Specialist. Does things precisely.",
            "",
        )
        _make_agent_genome(genomes_dir, "Claude-5@claude", content=content)
        results = check_agent("Claude-5@claude", genomes_dir)
        check = next(r for r in results if r["check"] == "role_non_empty")
        assert check["status"] == "FAIL"


# ---------------------------------------------------------------------------
# Tests: check_agent — meta_agent_id_match
# ---------------------------------------------------------------------------


class TestCheckAgentMetaConsistency:
    def test_matching_agent_id_passes(self, tmp_path: Path) -> None:
        genomes_dir = tmp_path / "genomes"
        meta = {"agent_id": "Claude-6@claude", "fitness": {}, "mutations": []}
        _make_agent_genome(genomes_dir, "Claude-6@claude", meta=meta)
        results = check_agent("Claude-6@claude", genomes_dir)
        check = next(r for r in results if r["check"] == "meta_agent_id_match")
        assert check["status"] == "PASS"

    def test_mismatched_agent_id_fails(self, tmp_path: Path) -> None:
        genomes_dir = tmp_path / "genomes"
        meta = {"agent_id": "Claude-WRONG@claude", "fitness": {}, "mutations": []}
        _make_agent_genome(genomes_dir, "Claude-6@claude", meta=meta)
        results = check_agent("Claude-6@claude", genomes_dir)
        check = next(r for r in results if r["check"] == "meta_agent_id_match")
        assert check["status"] == "FAIL"
        assert "WRONG" in check["detail"]

    def test_missing_meta_warns(self, tmp_path: Path) -> None:
        genomes_dir = tmp_path / "genomes"
        _make_agent_genome(genomes_dir, "Claude-6@claude")  # no meta kwarg
        results = check_agent("Claude-6@claude", genomes_dir)
        check = next(r for r in results if r["check"] == "meta_agent_id_match")
        assert check["status"] == "WARN"


# ---------------------------------------------------------------------------
# Tests: check_agent — missing AGENTS.local.md
# ---------------------------------------------------------------------------


class TestCheckAgentMissingFile:
    def test_missing_agents_local_md_fails_fast(self, tmp_path: Path) -> None:
        genomes_dir = tmp_path / "genomes"
        # Create directory but no AGENTS.local.md
        agent_dir = genomes_dir / "Claude-7@claude"
        agent_dir.mkdir(parents=True)
        results = check_agent("Claude-7@claude", genomes_dir)
        readable_check = next(r for r in results if r["check"] == "agents_local_md_readable")
        assert readable_check["status"] == "FAIL"
        # Should not produce any other checks (fail-fast)
        assert len(results) == 1


# ---------------------------------------------------------------------------
# Tests: run() integration
# ---------------------------------------------------------------------------


class TestRunIntegration:
    def test_run_passes_with_valid_genomes(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path, ["Claude-1@claude", "Claude-2@claude"])
        for aid in ["Claude-1@claude", "Claude-2@claude"]:
            meta = {"agent_id": aid, "fitness": {}, "mutations": []}
            _make_agent_genome(repo / "genomes", aid, meta=meta)

        report, passed = run(repo)
        assert passed is True
        assert report["status"] == "PASS"
        assert "FAIL" not in report["summary"]

    def test_run_checks_vnext_only_identity(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path, [])
        state_path = repo / "ledger" / "vnext" / "tide-state.json"
        state_path.parent.mkdir(parents=True)
        state_path.write_text(
            json.dumps(
                {"schema": "wea-tide-state-2", "balances": {"New@agent": 0}}
            ),
            encoding="utf-8",
        )
        meta = {"agent_id": "New@agent", "fitness": {}, "mutations": []}
        _make_agent_genome(repo / "genomes", "New@agent", meta=meta)

        report, passed = run(repo)

        assert passed is True
        assert {c["agent"] for c in report["checks"]} == {"New@agent"}

    def test_run_fails_with_broken_genome(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path, ["Claude-1@claude"])
        # Write a genome missing required sections
        content = "Some preamble without constitution.\n\n## Role\nOK role."
        _make_agent_genome(repo / "genomes", "Claude-1@claude", content=content)

        report, passed = run(repo)
        assert passed is False
        assert report["status"] == "FAIL"

    def test_run_missing_balances_json(self, tmp_path: Path) -> None:
        # No ledger/ directory
        report, passed = run(tmp_path)
        assert passed is False
        assert "balances.json" in report["summary"]

    def test_run_agent_filter(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path, ["Claude-1@claude", "Claude-2@claude"])
        meta1 = {"agent_id": "Claude-1@claude", "fitness": {}, "mutations": []}
        _make_agent_genome(repo / "genomes", "Claude-1@claude", meta=meta1)
        # Claude-2 has no genome dir (would fail)

        report, passed = run(repo, agents_filter=["Claude-1@claude"])
        assert passed is True
        agents_checked = {c["agent"] for c in report["checks"]}
        assert "Claude-1@claude" in agents_checked
        assert "Claude-2@claude" not in agents_checked

    def test_run_skips_agent0(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path, ["agent0@system", "Claude-1@claude"])
        meta = {"agent_id": "Claude-1@claude", "fitness": {}, "mutations": []}
        _make_agent_genome(repo / "genomes", "Claude-1@claude", meta=meta)
        # agent0 has no genome dir — must not cause a FAIL

        report, passed = run(repo)
        agents_checked = {c["agent"] for c in report["checks"]}
        assert "agent0@system" not in agents_checked
        assert passed is True

    def test_run_orphan_genome_warns(self, tmp_path: Path) -> None:
        # Ghost directory: genomes/Phantom@ghost/ but no balance entry
        repo = _make_repo(tmp_path, ["Claude-1@claude"])
        meta = {"agent_id": "Claude-1@claude", "fitness": {}, "mutations": []}
        _make_agent_genome(repo / "genomes", "Claude-1@claude", meta=meta)

        # Create orphan directory
        phantom_dir = repo / "genomes" / "Phantom@ghost"
        phantom_dir.mkdir()

        report, passed = run(repo)
        # Orphan is WARN, not FAIL
        assert passed is True
        orphan_checks = [c for c in report["checks"] if c["check"] == "orphan_genome"]
        assert len(orphan_checks) == 1
        assert orphan_checks[0]["status"] == "WARN"
        assert "Phantom@ghost" in orphan_checks[0]["detail"]

    def test_run_summary_counts(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path, ["Claude-1@claude"])
        # Valid genome → all PASS + WARN for missing meta
        _make_agent_genome(repo / "genomes", "Claude-1@claude")  # no meta

        report, _ = run(repo)
        summary = report["summary"]
        assert "PASS" in summary
        assert "WARN" in summary
