from __future__ import annotations

from pathlib import Path

import pytest

from scripts.circle1 import role_grammar


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = ROOT / "domains" / "circle-1" / "zone_templates" / "scripts_v1_roles.json"


@pytest.fixture
def role_template() -> role_grammar.RoleTemplate:
    return role_grammar.load_template(TEMPLATE_PATH)


def _write_fixture(path: Path, body: str) -> Path:
    path.write_text(body.strip() + "\n", encoding="utf-8")
    return path


def _runnable_fixture(tmp_path: Path) -> Path:
    return _write_fixture(
        tmp_path / "runnable.py",
        """
#!/usr/bin/env python3
\"\"\"Runnable fixture.\"\"\"

from __future__ import annotations


def main() -> None:
    return


if __name__ == "__main__":
    main()
""",
    )


def _support_fixture(tmp_path: Path) -> Path:
    return _write_fixture(
        tmp_path / "support.py",
        """
\"\"\"Import-safe support fixture.\"\"\"

from __future__ import annotations


def helper(value: int) -> int:
    return value + 1


class Box:
    value: int

    def __init__(self, value: int) -> None:
        self.value = value
""",
    )


def _declaration_fixture(tmp_path: Path) -> Path:
    return _write_fixture(
        tmp_path / "declaration.py",
        """
\"\"\"Declaration fixture.\"\"\"

from __future__ import annotations

SPLIT_TABLE = {
    1: [100],
    2: [50, 50],
}
SCALE = 10
""",
    )


def _ambiguous_fixture(tmp_path: Path) -> Path:
    return _write_fixture(
        tmp_path / "ambiguous.py",
        """
\"\"\"Ambiguous fixture.\"\"\"

from __future__ import annotations

import json


VALUE = 1
print(\"side effect\")
""",
    )


def test_runnable_entrypoint(role_template: role_grammar.RoleTemplate, tmp_path: Path) -> None:
    file = _runnable_fixture(tmp_path)
    result = role_grammar.classify_script_file(file, role_template, root=ROOT)
    assert result.role == "runnable_entrypoint"
    assert "has_main_entrypoint" in result.matched_predicates
    assert result.reason_if_unclassified is None


def test_import_safe_support(role_template: role_grammar.RoleTemplate, tmp_path: Path) -> None:
    file = _support_fixture(tmp_path)
    result = role_grammar.classify_script_file(file, role_template, root=ROOT)
    assert result.role == "import_safe_support"
    assert "is_import_safe" in result.matched_predicates
    assert "has_no_main_guard" in result.matched_predicates


def test_declaration_module(role_template: role_grammar.RoleTemplate, tmp_path: Path) -> None:
    file = _declaration_fixture(tmp_path)
    result = role_grammar.classify_script_file(file, role_template, root=ROOT)
    assert result.role == "declaration_module"
    assert "is_declaration_shape" in result.matched_predicates
    assert "has_function_or_class_defs" not in result.matched_predicates


def test_ambiguous_file(role_template: role_grammar.RoleTemplate, tmp_path: Path) -> None:
    file = _ambiguous_fixture(tmp_path)
    result = role_grammar.classify_script_file(file, role_template, root=ROOT)
    assert result.role == "unclassified"
    assert result.reason_if_unclassified is not None
    assert result.reason_if_unclassified
    assert "has_top_level_calls" in result.matched_predicates
