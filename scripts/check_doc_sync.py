#!/usr/bin/env python3
"""Doc-sync drift checker for the closed ecosystem."""

from __future__ import annotations

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
    "MAP.md": ["join.yml", "onboard.yml", "LICENSE"],
}


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


def main() -> None:
    errors: list[str] = []
    map_path = BASE_DIR / "MAP.md"
    if not map_path.is_file():
        print("FAIL: MAP.md missing")
        sys.exit(1)

    map_paths = parse_map_paths(map_path.read_text(encoding="utf-8"))
    errors.extend(find_missing_paths(BASE_DIR, map_paths))
    errors.extend(find_missing_required_map_entries(map_paths))
    errors.extend(find_unmapped_local_links(BASE_DIR, map_paths))
    errors.extend(find_forbidden_patterns(BASE_DIR))

    if errors:
        print(f"{len(errors)} doc-sync violation(s) found:\n")
        for error in errors:
            print(f"- {error}")
        print("\nStatus: FAIL")
        sys.exit(1)

    print("All doc-sync checks pass.")
    print("\nStatus: PASS")


if __name__ == "__main__":
    main()
