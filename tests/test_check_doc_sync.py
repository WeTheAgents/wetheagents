from __future__ import annotations

import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parent.parent / "scripts" / "check_doc_sync.py"
SPEC = importlib.util.spec_from_file_location("check_doc_sync", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

find_forbidden_patterns = MODULE.find_forbidden_patterns
find_missing_required_map_entries = MODULE.find_missing_required_map_entries
find_unmapped_local_links = MODULE.find_unmapped_local_links
parse_map_paths = MODULE.parse_map_paths
parse_cli_command_surface = MODULE.parse_cli_command_surface
parse_documented_cli_commands = MODULE.parse_documented_cli_commands
compute_cli_doc_drift = MODULE.compute_cli_doc_drift
find_cli_doc_drift = MODULE.find_cli_doc_drift


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_parse_map_paths_extracts_entries() -> None:
    text = """
| Path | Purpose | Audience |
|------|---------|----------|
| `README.md` | Overview | All |
| `docs/CLI.md` | CLI | Agents |
"""
    assert parse_map_paths(text) == {"README.md", "docs/CLI.md"}


def test_find_missing_required_map_entries_flags_absent_paths() -> None:
    missing = find_missing_required_map_entries({"README.md", "MAP.md"})
    assert any("CONTRIBUTING.md" in item for item in missing)


def test_find_unmapped_local_links_flags_links_outside_map(tmp_path: Path) -> None:
    _write(tmp_path / "README.md", "[CLI](docs/CLI.md)\n")
    _write(tmp_path / "CONTRIBUTING.md", "")
    _write(tmp_path / "AGENT0.md", "")
    _write(tmp_path / "CLAUDE.md", "")
    _write(tmp_path / "docs" / "agent_onboarding_prompt.md", "")
    _write(tmp_path / "docs" / "CLI.md", "")
    failures = find_unmapped_local_links(tmp_path, {"README.md", "CONTRIBUTING.md", "AGENT0.md", "CLAUDE.md", "docs/agent_onboarding_prompt.md"})
    assert failures == ["README.md links to unmapped path: docs/CLI.md"]


def test_find_forbidden_patterns_flags_legacy_strings(tmp_path: Path) -> None:
    _write(tmp_path / "README.md", "Join the sandbox\n")
    _write(tmp_path / "CONTRIBUTING.md", "Signed-off-by\n")
    _write(tmp_path / "AGENT0.md", "Hello World mint\n")
    _write(tmp_path / "docs" / "CLI.md", "wea join\n")
    _write(tmp_path / "docs" / "agent_onboarding_prompt.md", "Hello World\n")
    _write(tmp_path / "MAP.md", "join.yml\n")
    failures = find_forbidden_patterns(tmp_path)
    assert "README.md still contains forbidden pattern: Join the sandbox" in failures
    assert "CONTRIBUTING.md still contains forbidden pattern: Signed-off-by" in failures
    assert "AGENT0.md still contains forbidden pattern: Hello World mint" in failures


# --- Docs-vs-CLI contract -------------------------------------------------

# A minimal build_parser() whose command surface mirrors the required core.
_FIXTURE_CLI_SOURCE = """
import argparse


def build_parser():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("tasks")
    subparsers.add_parser("submit")
    subparsers.add_parser("pr")
    subparsers.add_parser("accept")
    subparsers.add_parser("balance")
    subparsers.add_parser("show")
    task = subparsers.add_parser("task")
    task_subparsers = task.add_subparsers(dest="task_command")
    task_subparsers.add_parser("calc-budget")
    task_subparsers.add_parser("lint")
    task_subparsers.add_parser("template")
    issue = subparsers.add_parser("issue")
    issue_subparsers = issue.add_subparsers(dest="issue_command")
    issue_subparsers.add_parser("edit")
"""

# A docs/CLI.md that documents exactly the required core plus the task group.
_FIXTURE_CLI_DOC_LINES = [
    "# wea CLI Reference",
    "#### `wea tasks`",
    "#### `wea submit ISSUE --file PATH`",
    "#### `wea pr ISSUE --head BRANCH`",
    "#### `wea accept ISSUE PAYEE`",
    "#### `wea balance [AGENT]`",
    "#### `wea show ISSUE`",
    "#### `wea task calc-budget REWARD_TYPE`",
    "#### `wea task lint FILE`",
    "#### `wea task template`",
]
_FIXTURE_CLI_DOC = "\n".join(_FIXTURE_CLI_DOC_LINES) + "\n"


def _write_cli_repo(base: Path, doc_text: str) -> None:
    _write(base / "src" / "wea_cli" / "cli.py", _FIXTURE_CLI_SOURCE)
    _write(base / "docs" / "CLI.md", doc_text)


def test_parse_cli_command_surface_extracts_top_and_task_subcommands() -> None:
    top, task_subs = parse_cli_command_surface(_FIXTURE_CLI_SOURCE)
    assert {"tasks", "submit", "task", "issue"} <= top
    assert task_subs == {"calc-budget", "lint", "template"}
    # Nested non-task subcommands (issue edit) must not leak into task subs.
    assert "edit" not in task_subs


def test_parse_documented_cli_commands_reads_headings() -> None:
    top, task_subs = parse_documented_cli_commands(_FIXTURE_CLI_DOC)
    assert {"tasks", "submit", "task"} <= top
    assert task_subs == {"calc-budget", "lint", "template"}


def test_compute_cli_doc_drift_passes_when_aligned() -> None:
    top, task_subs = parse_cli_command_surface(_FIXTURE_CLI_SOURCE)
    doc_top, doc_task = parse_documented_cli_commands(_FIXTURE_CLI_DOC)
    assert compute_cli_doc_drift(top, task_subs, doc_top, doc_task) == []


def test_compute_cli_doc_drift_flags_removed_command() -> None:
    top, task_subs = parse_cli_command_surface(_FIXTURE_CLI_SOURCE)
    doc_top, doc_task = parse_documented_cli_commands(_FIXTURE_CLI_DOC)
    # Docs mention a command the parser no longer has.
    failures = compute_cli_doc_drift(top, task_subs, doc_top | {"join"}, doc_task)
    assert failures == ["docs/CLI.md documents unknown top-level command: `wea join`"]


def test_compute_cli_doc_drift_flags_removed_task_subcommand() -> None:
    top, task_subs = parse_cli_command_surface(_FIXTURE_CLI_SOURCE)
    doc_top, doc_task = parse_documented_cli_commands(_FIXTURE_CLI_DOC)
    failures = compute_cli_doc_drift(top, task_subs, doc_top, doc_task | {"vanish"})
    assert failures == [
        "docs/CLI.md documents unknown task subcommand: `wea task vanish`"
    ]


def test_compute_cli_doc_drift_flags_omitted_required_command() -> None:
    top, task_subs = parse_cli_command_surface(_FIXTURE_CLI_SOURCE)
    doc_top, doc_task = parse_documented_cli_commands(_FIXTURE_CLI_DOC)
    # Docs drop a required core command.
    failures = compute_cli_doc_drift(top, task_subs, doc_top - {"submit"}, doc_task)
    assert failures == ["docs/CLI.md missing required command section: `wea submit`"]


def test_compute_cli_doc_drift_flags_omitted_required_task_subcommand() -> None:
    top, task_subs = parse_cli_command_surface(_FIXTURE_CLI_SOURCE)
    doc_top, doc_task = parse_documented_cli_commands(_FIXTURE_CLI_DOC)
    failures = compute_cli_doc_drift(top, task_subs, doc_top, doc_task - {"lint"})
    assert failures == [
        "docs/CLI.md missing required task subcommand section: `wea task lint`"
    ]


def test_compute_cli_doc_drift_fails_closed_on_empty_surface() -> None:
    # An empty surface means introspection broke — it must fail, not pass silently.
    doc_top, doc_task = parse_documented_cli_commands(_FIXTURE_CLI_DOC)
    failures = compute_cli_doc_drift(set(), set(), doc_top, doc_task)
    assert failures and "could not extract" in failures[0]


def test_find_cli_doc_drift_passing_case(tmp_path: Path) -> None:
    _write_cli_repo(tmp_path, _FIXTURE_CLI_DOC)
    assert find_cli_doc_drift(tmp_path) == []


def test_find_cli_doc_drift_flags_removed_command(tmp_path: Path) -> None:
    _write_cli_repo(tmp_path, _FIXTURE_CLI_DOC + "#### `wea join`\n")
    failures = find_cli_doc_drift(tmp_path)
    assert any("wea join" in failure for failure in failures)


def test_find_cli_doc_drift_flags_omitted_required_command(tmp_path: Path) -> None:
    trimmed = _FIXTURE_CLI_DOC.replace("#### `wea submit ISSUE --file PATH`\n", "")
    _write_cli_repo(tmp_path, trimmed)
    failures = find_cli_doc_drift(tmp_path)
    assert any("wea submit" in failure for failure in failures)


def test_find_cli_doc_drift_reports_missing_source(tmp_path: Path) -> None:
    _write(tmp_path / "docs" / "CLI.md", _FIXTURE_CLI_DOC)
    failures = find_cli_doc_drift(tmp_path)
    assert failures == ["docs-vs-CLI: CLI source missing: src/wea_cli/cli.py"]


def test_real_repo_has_no_cli_doc_drift() -> None:
    # End-to-end guard against the shipped docs/CLI.md drifting from the real CLI.
    assert find_cli_doc_drift(MODULE.BASE_DIR) == []


def test_main_accepts_root_flag_and_passes_on_repo() -> None:
    assert MODULE.main(["--root", str(MODULE.BASE_DIR)]) == 0


def test_main_root_flag_locates_missing_map(tmp_path: Path) -> None:
    # --root is actually used to locate MAP.md; an empty root must FAIL (return 1).
    assert MODULE.main(["--root", str(tmp_path)]) == 1
