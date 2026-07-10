#!/usr/bin/env python3
"""Doc-sync drift checker for the closed ecosystem."""

from __future__ import annotations

import argparse
import ast
import os
import re
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

REQUIRED_MAP_PATHS = {
    "README.md",
    "MAP.md",
    "CONTRIBUTING.md",
    "AGENT0.md",
    "docs/CLI.md",
    "docs/agent_onboarding_prompt.md",
    "agent0/operations.md",
    "agent0/ledger.md",
    "scripts/check_doc_sync.py",
    "src/wea_cli/cli.py",
}

LINK_CHECK_FILES = (
    "README.md",
    "CONTRIBUTING.md",
    "AGENT0.md",
    "CLAUDE.md",
    "docs/agent_onboarding_prompt.md",
)

FORBIDDEN_PATTERNS = {
    "README.md": ["Join the sandbox", "wea join", "LICENSE"],
    "CONTRIBUTING.md": ["wea join", "Signed-off-by", "AGPL"],
    "AGENT0.md": ["onboard.yml", "Hello World mint", "Issues labeled `join`"],
    "docs/CLI.md": ["wea join", "wea hello"],
    "docs/agent_onboarding_prompt.md": ["wea join"],
    "MAP.md": ["join.yml", "onboard.yml", "LICENSE", "PROTOCOL.md"],
}

# --- Docs-vs-CLI contract -------------------------------------------------
# docs/CLI.md is the authoritative CLI reference. These constants back a
# deterministic contract that catches semantic drift between the documented
# command surface and the real `wea` argparse tree, without importing the CLI
# (the integrity-sweep CI runs this checker with no third-party deps installed).

CLI_SOURCE_REL = "src/wea_cli/cli.py"
CLI_DOC_REL = "docs/CLI.md"

# Top-level commands docs/CLI.md must always document. Intentionally a small,
# stable core — the agent task lifecycle. Growing this set is a deliberate act.
REQUIRED_DOCUMENTED_COMMANDS = frozenset(
    {"tasks", "claim", "submit", "pr", "accept", "balance", "show"}
)

# `wea task` subcommands docs/CLI.md must document (the nested-command sample).
REQUIRED_DOCUMENTED_TASK_SUBCOMMANDS = frozenset({"calc-budget", "lint", "template"})

# `#### `wea <cmd> [<sub>] ...`` heading, e.g. `wea task calc-budget REWARD_TYPE`.
# Command tokens are lowercase; positional placeholders (ISSUE, AGENT) are upper.
_CLI_HEADING_RE = re.compile(r"^#+\s+`wea\s+([a-z][\w-]*)(?:\s+([a-z][\w-]*))?")


def parse_cli_command_surface(source: str) -> tuple[set[str], set[str]]:
    """Extract the real `wea` command surface from cli.py source via a static AST walk.

    Returns ``(top_level_commands, task_subcommands)``. Parsing the source (rather
    than importing ``wea_cli.cli``) keeps the checker dependency-free and offline:
    it must pass in the bare integrity-sweep CI where the package is not installed.

    Top-level commands are the string literals passed to ``subparsers.add_parser``;
    task subcommands are those passed to ``task_subparsers.add_parser`` — matching
    the variable names used in ``build_parser()``.
    """
    tree = ast.parse(source)
    top_level: set[str] = set()
    task_subs: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr != "add_parser":
            continue
        if not isinstance(func.value, ast.Name) or not node.args:
            continue
        first = node.args[0]
        if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
            continue
        if func.value.id == "subparsers":
            top_level.add(first.value)
        elif func.value.id == "task_subparsers":
            task_subs.add(first.value)
    return top_level, task_subs


def parse_documented_cli_commands(doc_text: str) -> tuple[set[str], set[str]]:
    """Extract documented commands from docs/CLI.md headings.

    Returns ``(documented_top_level, documented_task_subcommands)``. A command is
    "documented" when it has a ``#### `wea <cmd>...``` heading; for ``wea task
    <sub>`` headings the nested subcommand is recorded as well.
    """
    top_level: set[str] = set()
    task_subs: set[str] = set()
    for line in doc_text.splitlines():
        match = _CLI_HEADING_RE.match(line)
        if not match:
            continue
        command = match.group(1)
        top_level.add(command)
        if command == "task" and match.group(2):
            task_subs.add(match.group(2))
    return top_level, task_subs


def compute_cli_doc_drift(
    surface_top: set[str],
    surface_task: set[str],
    documented_top: set[str],
    documented_task: set[str],
    *,
    required_top: frozenset[str] = REQUIRED_DOCUMENTED_COMMANDS,
    required_task: frozenset[str] = REQUIRED_DOCUMENTED_TASK_SUBCOMMANDS,
) -> list[str]:
    """Compare documented commands against the real parser surface.

    Two drift directions are flagged:
    - stale docs: a documented command that no longer exists in the parser
      (a renamed or removed command left behind in docs/CLI.md);
    - omitted docs: a required core command missing from docs/CLI.md.
    """
    failures: list[str] = []

    # Fail closed: an empty surface means introspection broke, not that the CLI
    # has no commands. Never let that pass silently as "no drift".
    if not surface_top:
        failures.append(
            f"docs-vs-CLI: could not extract any command surface from {CLI_SOURCE_REL}"
        )
        return failures

    for command in sorted(documented_top - surface_top):
        failures.append(
            f"docs/CLI.md documents unknown top-level command: `wea {command}`"
        )
    for sub in sorted(documented_task - surface_task):
        failures.append(
            f"docs/CLI.md documents unknown task subcommand: `wea task {sub}`"
        )
    for command in sorted(required_top - documented_top):
        failures.append(
            f"docs/CLI.md missing required command section: `wea {command}`"
        )
    for sub in sorted(required_task - documented_task):
        failures.append(
            f"docs/CLI.md missing required task subcommand section: `wea task {sub}`"
        )
    return failures


def find_cli_doc_drift(base_dir: Path) -> list[str]:
    """Load the CLI source and reference under ``base_dir`` and report doc drift."""
    cli_source_path = base_dir / CLI_SOURCE_REL
    cli_doc_path = base_dir / CLI_DOC_REL
    if not cli_source_path.is_file():
        return [f"docs-vs-CLI: CLI source missing: {CLI_SOURCE_REL}"]
    if not cli_doc_path.is_file():
        return [f"docs-vs-CLI: CLI reference missing: {CLI_DOC_REL}"]

    try:
        surface_top, surface_task = parse_cli_command_surface(
            cli_source_path.read_text(encoding="utf-8")
        )
    except SyntaxError as exc:
        return [f"docs-vs-CLI: cannot parse {CLI_SOURCE_REL}: {exc}"]

    documented_top, documented_task = parse_documented_cli_commands(
        cli_doc_path.read_text(encoding="utf-8")
    )
    return compute_cli_doc_drift(
        surface_top, surface_task, documented_top, documented_task
    )


def parse_map_paths(text: str) -> set[str]:
    paths: set[str] = set()
    for line in text.splitlines():
        match = re.match(r"^\|\s*`([^`]+)`\s*\|", line)
        if match:
            paths.add(match.group(1))
    return paths


def find_missing_paths(base_dir: Path, map_paths: set[str]) -> list[str]:
    failures: list[str] = []
    for rel_path in sorted(map_paths):
        abs_path = base_dir / rel_path
        if rel_path.endswith("/"):
            if not abs_path.is_dir():
                failures.append(f"MAP entry missing directory: {rel_path}")
        elif not abs_path.is_file():
            failures.append(f"MAP entry missing file: {rel_path}")
    return failures


def find_missing_required_map_entries(map_paths: set[str]) -> list[str]:
    return [f"MAP missing required active path: {path}" for path in sorted(REQUIRED_MAP_PATHS - map_paths)]


def find_unmapped_local_links(base_dir: Path, map_paths: set[str]) -> list[str]:
    failures: list[str] = []
    link_re = re.compile(r"\[[^\]]+\]\(([^)#]+)")
    for rel_path in LINK_CHECK_FILES:
        text = (base_dir / rel_path).read_text(encoding="utf-8")
        source_dir = (base_dir / rel_path).parent
        for raw_target in link_re.findall(text):
            if raw_target.startswith(("http://", "https://", "#", "mailto:")):
                continue
            normalized = os.path.normpath(os.path.join(source_dir, raw_target))
            target_rel = os.path.relpath(normalized, base_dir).replace("\\", "/")
            if target_rel not in map_paths:
                failures.append(f"{rel_path} links to unmapped path: {target_rel}")
    return failures


def find_forbidden_patterns(base_dir: Path) -> list[str]:
    failures: list[str] = []
    for rel_path, patterns in FORBIDDEN_PATTERNS.items():
        text = (base_dir / rel_path).read_text(encoding="utf-8")
        for pattern in patterns:
            if pattern in text:
                failures.append(f"{rel_path} still contains forbidden pattern: {pattern}")
    return failures


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Doc-sync drift checker for the closed ecosystem."
    )
    parser.add_argument(
        "--root",
        default=None,
        help="Repository root used to locate MAP.md, docs, and source files "
        "(default: the checker's own repository).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    base_dir = Path(args.root).resolve() if args.root else BASE_DIR

    errors: list[str] = []
    map_path = base_dir / "MAP.md"
    if not map_path.is_file():
        print(f"FAIL: MAP.md missing under {base_dir}")
        return 1

    map_paths = parse_map_paths(map_path.read_text(encoding="utf-8"))
    errors.extend(find_missing_paths(base_dir, map_paths))
    errors.extend(find_missing_required_map_entries(map_paths))
    errors.extend(find_unmapped_local_links(base_dir, map_paths))
    errors.extend(find_forbidden_patterns(base_dir))
    errors.extend(find_cli_doc_drift(base_dir))

    if errors:
        print(f"{len(errors)} doc-sync violation(s) found:\n")
        for error in errors:
            print(f"- {error}")
        print("\nStatus: FAIL")
        return 1

    print("All doc-sync checks pass.")
    print("\nStatus: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
