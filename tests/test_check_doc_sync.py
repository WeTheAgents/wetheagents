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
