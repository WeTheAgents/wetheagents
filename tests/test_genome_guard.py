"""Tests for genome_guard.py — constitution integrity and line-limit checks.

Covers 8 required scenarios:
1. Line limit pass/fail
2. Constitution length detection from template
3. Constitution mismatch produces amendment signal with useful diff output
4. Exact constitution match passes
5. --files mode checks only intended genome files
6. Base template is excluded from validation targets
7. Missing base template fails clearly
8. No genome files exits cleanly
"""

from __future__ import annotations

import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Import the module under test
# ---------------------------------------------------------------------------

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import genome_guard  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TEMPLATE_CONSTITUTION = """\
# Constitution

<!-- CONSTITUTION -->
> **North Star: Guaranteed Software Development.**
---

## Genome
"""

TEMPLATE_LINES = TEMPLATE_CONSTITUTION.splitlines()


def _setup_genomes(
    tmp_path: Path,
    *,
    template_content: str = TEMPLATE_CONSTITUTION,
    agents: dict[str, str] | None = None,
    skip_template: bool = False,
) -> Path:
    """Create a minimal genomes/ tree under tmp_path and return root."""
    root = tmp_path / "repo"
    genomes = root / "genomes"

    if not skip_template:
        base = genomes / "base"
        base.mkdir(parents=True)
        (base / "AGENTS.local.template.md").write_text(
            template_content, encoding="utf-8"
        )

    if agents:
        for name, content in agents.items():
            agent_dir = genomes / name
            agent_dir.mkdir(parents=True, exist_ok=True)
            (agent_dir / "AGENTS.local.md").write_text(content, encoding="utf-8")

    return root


def _run_main(args: list[str], monkeypatch) -> tuple[int, str]:
    """Run genome_guard.main() with given CLI args, return (exit_code, stdout)."""
    monkeypatch.setattr(sys, "argv", ["genome_guard.py"] + args)
    import io

    captured = io.StringIO()
    monkeypatch.setattr(sys, "stdout", captured)
    try:
        genome_guard.main()
        code = 0
    except SystemExit as e:
        code = e.code if e.code is not None else 0
    return code, captured.getvalue()


# ---------------------------------------------------------------------------
# 1. Line limit pass / fail
# ---------------------------------------------------------------------------


class TestLineLimit:
    """Line limit check (MAX_LINES = 120)."""

    def test_line_limit_pass(self) -> None:
        lines = ["line"] * 120
        result = genome_guard.check_line_limit(Path("genomes/alice/AGENTS.local.md"), lines)
        assert result is None

    def test_line_limit_fail(self) -> None:
        lines = ["line"] * 121
        result = genome_guard.check_line_limit(Path("genomes/alice/AGENTS.local.md"), lines)
        assert result is not None
        assert "FAIL" in result
        assert "121" in result
        assert "alice" in result

    def test_line_limit_via_main_pass(self, tmp_path: Path, monkeypatch) -> None:
        # Must match constitution zone + stay within 120 lines
        const_len = genome_guard.get_constitution_length(TEMPLATE_LINES)
        filler_count = 120 - const_len
        content = "\n".join(TEMPLATE_LINES[:const_len] + ["x"] * filler_count)
        root = _setup_genomes(tmp_path, agents={"alice": content})
        code, output = _run_main(["--root", str(root)], monkeypatch)
        assert code == 0
        assert "PASS" in output

    def test_line_limit_via_main_fail(self, tmp_path: Path, monkeypatch) -> None:
        # 121 lines of content (splitlines gives 121 entries)
        content = "\n".join(TEMPLATE_LINES[:4] + ["x"] * 117)
        root = _setup_genomes(tmp_path, agents={"alice": content})
        code, output = _run_main(["--root", str(root)], monkeypatch)
        assert code == 1
        assert "FAIL" in output


# ---------------------------------------------------------------------------
# 2. Constitution length detection from template
# ---------------------------------------------------------------------------


class TestConstitutionLength:
    """get_constitution_length finds the --- delimiter."""

    def test_delimiter_found(self) -> None:
        length = genome_guard.get_constitution_length(TEMPLATE_LINES)
        # Lines before the first "---"
        expected = next(
            i for i, line in enumerate(TEMPLATE_LINES) if line.strip() == "---"
        )
        assert length == expected

    def test_no_delimiter(self) -> None:
        lines = ["# Constitution", "Some text", "More text"]
        assert genome_guard.get_constitution_length(lines) == 3

    def test_delimiter_at_start(self) -> None:
        lines = ["---", "body"]
        assert genome_guard.get_constitution_length(lines) == 0


# ---------------------------------------------------------------------------
# 3. Constitution mismatch produces amendment signal with diff
# ---------------------------------------------------------------------------


class TestConstitutionMismatch:
    """Mismatch between agent constitution and template produces amendment signal."""

    def test_mismatch_returns_amendment_signal(self) -> None:
        const_len = genome_guard.get_constitution_length(TEMPLATE_LINES)
        agent_lines = list(TEMPLATE_LINES)
        agent_lines[1] = "<!-- CHANGED -->"

        result = genome_guard.check_constitution(
            Path("genomes/alice/AGENTS.local.md"),
            agent_lines,
            TEMPLATE_LINES,
            const_len,
        )
        assert result is not None
        assert "AMENDMENT SIGNAL" in result
        assert "alice" in result

    def test_diff_output_shows_both_sides(self) -> None:
        const_len = genome_guard.get_constitution_length(TEMPLATE_LINES)
        agent_lines = list(TEMPLATE_LINES)
        agent_lines[0] = "# Modified Constitution"

        result = genome_guard.check_constitution(
            Path("genomes/alice/AGENTS.local.md"),
            agent_lines,
            TEMPLATE_LINES,
            const_len,
        )
        assert "template:" in result
        assert "agent:" in result
        assert "# Constitution" in result
        assert "# Modified Constitution" in result

    def test_mismatch_via_main(self, tmp_path: Path, monkeypatch) -> None:
        agent_content = TEMPLATE_CONSTITUTION.replace(
            "# Constitution", "# Changed Constitution"
        )
        root = _setup_genomes(tmp_path, agents={"alice": agent_content})
        code, output = _run_main(["--root", str(root)], monkeypatch)
        assert code == 1
        assert "AMENDMENT SIGNAL" in output
        assert "Differences" in output


# ---------------------------------------------------------------------------
# 4. Exact constitution match passes
# ---------------------------------------------------------------------------


class TestExactMatch:
    """Agent whose constitution zone matches the template exactly passes."""

    def test_exact_match_function(self) -> None:
        const_len = genome_guard.get_constitution_length(TEMPLATE_LINES)
        # Agent has same constitution zone + extra genome content
        agent_lines = TEMPLATE_LINES + ["## My custom section", "stuff"]
        result = genome_guard.check_constitution(
            Path("genomes/alice/AGENTS.local.md"),
            agent_lines,
            TEMPLATE_LINES,
            const_len,
        )
        assert result is None

    def test_exact_match_via_main(self, tmp_path: Path, monkeypatch) -> None:
        # Agent content = template content + extra genome lines
        agent_content = TEMPLATE_CONSTITUTION + "\n## My Section\nCustom content\n"
        root = _setup_genomes(tmp_path, agents={"alice": agent_content})
        code, output = _run_main(["--root", str(root)], monkeypatch)
        assert code == 0
        assert "PASS" in output


# ---------------------------------------------------------------------------
# 5. --files mode checks only intended genome files
# ---------------------------------------------------------------------------


class TestFilesMode:
    """--files flag filters to only the specified files."""

    def test_files_checks_only_specified(self, tmp_path: Path, monkeypatch) -> None:
        agent_ok = TEMPLATE_CONSTITUTION + "\n## OK agent\n"
        agent_bad = TEMPLATE_CONSTITUTION.replace("# Constitution", "# WRONG")
        root = _setup_genomes(
            tmp_path,
            agents={"alice": agent_ok, "bob": agent_bad},
        )
        alice_path = str(root / "genomes" / "alice" / "AGENTS.local.md")

        # Only check alice (who is OK) — should pass despite bob being bad
        code, output = _run_main(
            ["--root", str(root), "--files", alice_path], monkeypatch
        )
        assert code == 0
        assert "PASS" in output
        assert "1 agent(s)" in output

    def test_files_detects_failure_in_listed_file(self, tmp_path: Path, monkeypatch) -> None:
        agent_bad = TEMPLATE_CONSTITUTION.replace("# Constitution", "# WRONG")
        root = _setup_genomes(tmp_path, agents={"bob": agent_bad})
        bob_path = str(root / "genomes" / "bob" / "AGENTS.local.md")
        code, output = _run_main(
            ["--root", str(root), "--files", bob_path], monkeypatch
        )
        assert code == 1
        assert "AMENDMENT SIGNAL" in output

    def test_files_non_genome_files_ignored(self, tmp_path: Path, monkeypatch) -> None:
        root = _setup_genomes(tmp_path, agents={"alice": TEMPLATE_CONSTITUTION})
        # Pass a non-genome file — should be filtered out → 0 genome files
        code, output = _run_main(
            ["--root", str(root), "--files", "src/main.py"], monkeypatch
        )
        assert code == 0
        assert "No agent genome files found" in output


# ---------------------------------------------------------------------------
# 6. Base template is excluded from validation targets
# ---------------------------------------------------------------------------


class TestBaseExcluded:
    """genomes/base/ template is never validated as an agent genome."""

    def test_base_excluded_in_glob_mode(self, tmp_path: Path, monkeypatch) -> None:
        # Create base template that also has an AGENTS.local.md (unusual but possible)
        root = _setup_genomes(tmp_path, agents={"alice": TEMPLATE_CONSTITUTION})
        base_dir = root / "genomes" / "base"
        base_dir.mkdir(parents=True, exist_ok=True)
        (base_dir / "AGENTS.local.md").write_text(
            "# Not a real agent", encoding="utf-8"
        )

        code, output = _run_main(["--root", str(root)], monkeypatch)
        # Should only check alice, not base
        assert "1 agent(s)" in output

    def test_base_excluded_in_files_mode(self, tmp_path: Path, monkeypatch) -> None:
        root = _setup_genomes(tmp_path, agents={"alice": TEMPLATE_CONSTITUTION})
        base_path = str(root / "genomes" / "base" / "AGENTS.local.md")
        alice_path = str(root / "genomes" / "alice" / "AGENTS.local.md")

        code, output = _run_main(
            ["--root", str(root), "--files", base_path, alice_path], monkeypatch
        )
        # base should be filtered out, only alice checked
        assert "1 agent(s)" in output

    def test_base_excluded_even_with_agents_local_name(self, tmp_path: Path, monkeypatch) -> None:
        """AGENTS.local.md under genomes/base/ is still excluded in --files mode."""
        root = _setup_genomes(tmp_path)
        fake_base = root / "genomes" / "base" / "AGENTS.local.md"
        fake_base.write_text("# whatever\n", encoding="utf-8")
        code, output = _run_main(
            ["--root", str(root), "--files", str(fake_base)], monkeypatch
        )
        assert code == 0
        assert "No agent genome files found" in output


# ---------------------------------------------------------------------------
# 7. Missing base template fails clearly
# ---------------------------------------------------------------------------


class TestMissingTemplate:
    """Missing base template causes immediate exit with clear error."""

    def test_missing_template_exits_1(self, tmp_path: Path, monkeypatch) -> None:
        root = _setup_genomes(tmp_path, skip_template=True)
        code, output = _run_main(["--root", str(root)], monkeypatch)
        assert code == 1
        assert "FAIL" in output
        assert "Base template not found" in output


# ---------------------------------------------------------------------------
# 8. No genome files exits cleanly
# ---------------------------------------------------------------------------


class TestNoGenomeFiles:
    """When no agent genome files exist, exit cleanly with code 0."""

    def test_no_genomes_exits_0(self, tmp_path: Path, monkeypatch) -> None:
        root = _setup_genomes(tmp_path)  # template exists but no agents
        code, output = _run_main(["--root", str(root)], monkeypatch)
        assert code == 0
        assert "No agent genome files found" in output

    def test_no_genomes_files_mode(self, tmp_path: Path, monkeypatch) -> None:
        root = _setup_genomes(tmp_path)
        code, output = _run_main(
            ["--root", str(root), "--files", "README.md"], monkeypatch
        )
        assert code == 0
        assert "No agent genome files found" in output
