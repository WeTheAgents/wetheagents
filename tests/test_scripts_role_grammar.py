"""Tests for V1 scripts/ role grammar.

Each role family is tested from a purpose-built fixture.
Ambiguous cases (unclassified) are also covered.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.circle1.role_grammar import (
    classify_file,
    classify_role,
    extended_file_features,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


RUNNABLE = '''\
"""Check something."""

from __future__ import annotations

import argparse
import sys


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root")
    args = parser.parse_args()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''

IMPORT_SAFE = '''\
"""Shared I/O helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def save_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2))
'''

DECLARATION = '''\
"""Economy constants."""

from __future__ import annotations

SPLIT_TABLE: dict[int, list[int]] = {
    1: [100],
    2: [70, 30],
    3: [50, 30, 20],
}
'''

UNCLASSIFIED_SYS_PATH = '''\
"""Parser that mutates sys.path at import time."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def parse(text: str) -> dict:
    return {}
'''

UNCLASSIFIED_BARE_CALL = '''\
"""Module with bare top-level call."""

from __future__ import annotations

import logging

logging.basicConfig(level=logging.DEBUG)


def helper() -> None:
    pass
'''

AMBIGUOUS_BOTH_DATA_AND_FUNCS = '''\
"""Mixed: has constants and functions but no main guard and no side effects."""

from __future__ import annotations

TIMEOUT = 30

DEFAULTS: dict[str, int] = {"retries": 3, "timeout": TIMEOUT}


def get_timeout() -> int:
    return TIMEOUT
'''


# ---------------------------------------------------------------------------
# Role: runnable_entrypoint
# ---------------------------------------------------------------------------

class TestRunnableEntrypoint:
    def test_has_main_guard_detected(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "check_thing.py", RUNNABLE)
        features = extended_file_features(p)
        assert features["has_main_guard"] is True

    def test_classified_as_runnable(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "check_thing.py", RUNNABLE)
        result = classify_file(p)
        assert result["role"] == "runnable_entrypoint"

    def test_has_main_guard_in_matched_predicates(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "check_thing.py", RUNNABLE)
        result = classify_file(p)
        assert "has_main_guard" in result["matched_predicates"]

    def test_no_failure_reasons(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "check_thing.py", RUNNABLE)
        result = classify_file(p)
        assert result["failure_reasons"] == []

    def test_main_guard_wins_over_sys_path(self, tmp_path: Path) -> None:
        # runnable script with top-level sys.path fixup (common pattern)
        content = RUNNABLE.replace(
            '"""Check something."""\n',
            '"""Check something."""\nimport sys\nsys.path.insert(0, "src")\n',
        )
        p = _write(tmp_path, "script_with_path_fixup.py", content)
        result = classify_file(p)
        assert result["role"] == "runnable_entrypoint"


# ---------------------------------------------------------------------------
# Role: import_safe_support
# ---------------------------------------------------------------------------

class TestImportSafeSupport:
    def test_has_function_detected(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "io_helpers.py", IMPORT_SAFE)
        features = extended_file_features(p)
        assert features["has_function"] is True

    def test_classified_as_import_safe(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "io_helpers.py", IMPORT_SAFE)
        result = classify_file(p)
        assert result["role"] == "import_safe_support"

    def test_no_main_guard_in_matched(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "io_helpers.py", IMPORT_SAFE)
        result = classify_file(p)
        assert "no_main_guard" in result["matched_predicates"]

    def test_no_failure_reasons(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "io_helpers.py", IMPORT_SAFE)
        result = classify_file(p)
        assert result["failure_reasons"] == []

    def test_mixed_data_and_funcs_is_support(self, tmp_path: Path) -> None:
        # Constants + functions together = import_safe_support (any function is enough)
        p = _write(tmp_path, "mixed.py", AMBIGUOUS_BOTH_DATA_AND_FUNCS)
        result = classify_file(p)
        assert result["role"] == "import_safe_support"

    def test_regex_compile_at_module_level_is_safe(self, tmp_path: Path) -> None:
        content = '''\
"""Parser with module-level compiled patterns."""

from __future__ import annotations

import re

_CLAIM = re.compile(r"^claim\\s+(\\S+)", re.IGNORECASE)


def parse(text: str) -> str | None:
    m = _CLAIM.search(text)
    return m.group(1) if m else None
'''
        p = _write(tmp_path, "parser.py", content)
        result = classify_file(p)
        # re.compile() is an assignment (ast.Assign), not a bare Expr(Call)
        assert result["role"] == "import_safe_support"


# ---------------------------------------------------------------------------
# Role: declaration_module
# ---------------------------------------------------------------------------

class TestDeclarationModule:
    def test_no_functions_detected(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "economy_constants.py", DECLARATION)
        features = extended_file_features(p)
        assert features["has_function"] is False
        assert features["has_class"] is False

    def test_classified_as_declaration(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "economy_constants.py", DECLARATION)
        result = classify_file(p)
        assert result["role"] == "declaration_module"

    def test_no_functions_no_classes_in_matched(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "economy_constants.py", DECLARATION)
        result = classify_file(p)
        assert "no_functions_no_classes" in result["matched_predicates"]

    def test_type_alias_only_is_declaration(self, tmp_path: Path) -> None:
        content = '''\
"""Type aliases for the ledger."""

from __future__ import annotations

AgentId = str
Balance = int
IdemKey = str
'''
        p = _write(tmp_path, "types.py", content)
        result = classify_file(p)
        assert result["role"] == "declaration_module"


# ---------------------------------------------------------------------------
# Role: unclassified
# ---------------------------------------------------------------------------

class TestUnclassified:
    def test_sys_path_mutation_detected(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "bad_parser.py", UNCLASSIFIED_SYS_PATH)
        features = extended_file_features(p)
        assert features["has_sys_path_mutation"] is True
        assert features["has_import_side_effect"] is True

    def test_sys_path_file_is_unclassified(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "bad_parser.py", UNCLASSIFIED_SYS_PATH)
        result = classify_file(p)
        assert result["role"] == "unclassified"

    def test_failure_reasons_populated(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "bad_parser.py", UNCLASSIFIED_SYS_PATH)
        result = classify_file(p)
        assert any("sys_path" in r for r in result["failure_reasons"])

    def test_bare_call_is_unclassified(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "bare_call.py", UNCLASSIFIED_BARE_CALL)
        result = classify_file(p)
        assert result["role"] == "unclassified"

    def test_bare_call_failure_reason(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "bare_call.py", UNCLASSIFIED_BARE_CALL)
        result = classify_file(p)
        assert any("top_level_call" in r for r in result["failure_reasons"])


# ---------------------------------------------------------------------------
# classify_role: feature dict interface
# ---------------------------------------------------------------------------

class TestClassifyRoleInterface:
    def test_main_guard_true_is_runnable(self) -> None:
        result = classify_role({"has_main_guard": True})
        assert result["role"] == "runnable_entrypoint"

    def test_no_main_no_side_effect_no_behavior_is_declaration(self) -> None:
        result = classify_role({
            "has_main_guard": False,
            "has_import_side_effect": False,
            "has_function": False,
            "has_class": False,
        })
        assert result["role"] == "declaration_module"

    def test_no_main_no_side_effect_has_function_is_support(self) -> None:
        result = classify_role({
            "has_main_guard": False,
            "has_import_side_effect": False,
            "has_function": True,
            "has_class": False,
        })
        assert result["role"] == "import_safe_support"

    def test_no_main_side_effect_is_unclassified(self) -> None:
        result = classify_role({
            "has_main_guard": False,
            "has_import_side_effect": True,
            "has_sys_path_mutation": True,
            "has_top_level_call": False,
            "has_function": True,
        })
        assert result["role"] == "unclassified"


# ---------------------------------------------------------------------------
# Real-file smoke tests on known counterexamples
# ---------------------------------------------------------------------------

class TestRealCounterexamples:
    """Verify the known counterexample files from the task spec are classified correctly."""

    @pytest.fixture
    def repo_root(self) -> Path:
        return Path(__file__).resolve().parents[1]

    def test_io_helpers_is_support(self, repo_root: Path) -> None:
        p = repo_root / "scripts" / "io_helpers.py"
        if not p.exists():
            pytest.skip("io_helpers.py not found")
        assert classify_file(p)["role"] == "import_safe_support"

    def test_tide_ops_is_support(self, repo_root: Path) -> None:
        p = repo_root / "scripts" / "tide_ops.py"
        if not p.exists():
            pytest.skip("tide_ops.py not found")
        assert classify_file(p)["role"] == "import_safe_support"

    def test_tide_parser_is_support(self, repo_root: Path) -> None:
        p = repo_root / "scripts" / "tide_parser.py"
        if not p.exists():
            pytest.skip("tide_parser.py not found")
        assert classify_file(p)["role"] == "import_safe_support"

    def test_ledger_ops_is_support(self, repo_root: Path) -> None:
        p = repo_root / "scripts" / "ledger_ops.py"
        if not p.exists():
            pytest.skip("ledger_ops.py not found")
        assert classify_file(p)["role"] == "import_safe_support"

    def test_economy_constants_is_declaration(self, repo_root: Path) -> None:
        p = repo_root / "scripts" / "economy_constants.py"
        if not p.exists():
            pytest.skip("economy_constants.py not found")
        assert classify_file(p)["role"] == "declaration_module"

    def test_pipeline_parser_is_unclassified(self, repo_root: Path) -> None:
        p = repo_root / "scripts" / "pipeline_parser.py"
        if not p.exists():
            pytest.skip("pipeline_parser.py not found")
        assert classify_file(p)["role"] == "unclassified"

    def test_check_agent_slot_is_runnable(self, repo_root: Path) -> None:
        p = repo_root / "scripts" / "check_agent_slot_integrity.py"
        if not p.exists():
            pytest.skip("check_agent_slot_integrity.py not found")
        assert classify_file(p)["role"] == "runnable_entrypoint"


# ---------------------------------------------------------------------------
# Point 2: Reversed main guard — deliberate V1 acceptance
# ---------------------------------------------------------------------------

class TestReversedMainGuard:
    """V1 intentionally accepts `if "__main__" == __name__:` alongside canonical form."""

    REVERSED_GUARD = '''\
"""Entrypoint with reversed main guard comparison."""

from __future__ import annotations


def main() -> int:
    return 0


if "__main__" == __name__:
    raise SystemExit(main())
'''

    def test_reversed_guard_has_main_guard(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "reversed.py", self.REVERSED_GUARD)
        features = extended_file_features(p)
        assert features["has_main_guard"] is True

    def test_reversed_guard_classifies_as_runnable(self, tmp_path: Path) -> None:
        # V1 deliberately accepts `"__main__" == __name__` (reversed operand order).
        p = _write(tmp_path, "reversed.py", self.REVERSED_GUARD)
        result = classify_file(p)
        assert result["role"] == "runnable_entrypoint"

    def test_reversed_guard_in_matched_predicates(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "reversed.py", self.REVERSED_GUARD)
        result = classify_file(p)
        assert "has_main_guard" in result["matched_predicates"]


# ---------------------------------------------------------------------------
# Point 1: Decorator-call side effects — V1 documented limitation
# ---------------------------------------------------------------------------

class TestDecoratorCallLimitation:
    """V1 limitation: Call nodes in decorator_list are not flagged as import side effects.

    A file with only @register()-style decorators and no bare Expr(Call) statements
    will NOT be classified as unclassified — the limitation is intentional and documented
    in the spec (Boundary 2: Decorator-Call Limitation).
    """

    DECORATOR_CALL = '''\
"""Module that registers a handler via a call-decorator."""

from __future__ import annotations


_REGISTRY: list = []


def register():
    """Decorator factory that records the decorated function."""
    def _deco(fn):
        _REGISTRY.append(fn)
        return fn
    return _deco


@register()
def my_handler() -> None:
    pass
'''

    def test_decorator_call_not_flagged_as_top_level_call(self, tmp_path: Path) -> None:
        # @register() is in decorator_list, not a bare ast.Expr(Call) — not detected by V1
        p = _write(tmp_path, "decorated.py", self.DECORATOR_CALL)
        features = extended_file_features(p)
        assert features["has_top_level_call"] is False

    def test_decorator_call_not_flagged_as_side_effect(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "decorated.py", self.DECORATOR_CALL)
        features = extended_file_features(p)
        assert features["has_import_side_effect"] is False

    def test_decorator_call_classifies_as_import_safe(self, tmp_path: Path) -> None:
        # V1 limitation: @register() is undetected → file classifies as import_safe_support
        # because it has functions and no detected side effects.
        p = _write(tmp_path, "decorated.py", self.DECORATOR_CALL)
        result = classify_file(p)
        assert result["role"] == "import_safe_support"


# ---------------------------------------------------------------------------
# Point 3: Assignment-call limitation — V1 documented behaviour
# ---------------------------------------------------------------------------

class TestAssignmentCallLimitation:
    """V1 limitation: module-level assignment-calls are ast.Assign nodes, not ast.Expr(Call).

    os.getenv(), logging.getLogger(), re.compile(), etc. are captured into names,
    so they don't match the bare-call detection and are NOT flagged as side effects.
    This is documented in the spec (Boundary 2: Assignment-Call Side Effects).
    """

    ASSIGNMENT_CALLS_WITH_FUNCS = '''\
"""Config sourced from environment — common support module pattern."""

from __future__ import annotations

import logging
import os

DB_URL: str = os.getenv("DB_URL", "sqlite://")
LOGGER = logging.getLogger(__name__)
MAX_RETRIES: int = int(os.getenv("MAX_RETRIES", "3"))


def get_url() -> str:
    return DB_URL
'''

    ASSIGNMENT_CALLS_DATA_ONLY = '''\
"""Pure constants sourced from environment."""

from __future__ import annotations

import os

DB_URL: str = os.getenv("DB_URL", "sqlite://")
DEBUG: bool = os.getenv("DEBUG", "").lower() == "true"
'''

    def test_os_getenv_not_flagged_as_side_effect(self, tmp_path: Path) -> None:
        # os.getenv() in assignment is ast.Assign — V1 limitation, not detected
        p = _write(tmp_path, "config.py", self.ASSIGNMENT_CALLS_WITH_FUNCS)
        features = extended_file_features(p)
        assert features["has_top_level_call"] is False
        assert features["has_import_side_effect"] is False

    def test_assignment_call_with_funcs_is_import_safe(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "config.py", self.ASSIGNMENT_CALLS_WITH_FUNCS)
        result = classify_file(p)
        # V1 limitation: os.getenv + logging.getLogger in assignments don't trigger unclassified
        assert result["role"] == "import_safe_support"

    def test_assignment_call_data_only_is_declaration(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "env_constants.py", self.ASSIGNMENT_CALLS_DATA_ONLY)
        result = classify_file(p)
        # V1 limitation: even os.getenv() in assignments doesn't trigger unclassified
        assert result["role"] == "declaration_module"


# ---------------------------------------------------------------------------
# Point 4: Inventory policy — recursive rglob is deliberate V1 choice
# ---------------------------------------------------------------------------

class TestInventoryPolicy:
    """V1 inventory policy: rglob covers all .py files under scripts/ recursively."""

    def test_recursive_scan_includes_subdirectory_files(self, tmp_path: Path) -> None:
        from scripts.circle1.scripts_inventory import scan_scripts

        scripts = tmp_path / "scripts"
        scripts.mkdir()
        subdir = scripts / "circle1"
        subdir.mkdir()
        (subdir / "__init__.py").write_text("")

        root_file = scripts / "check_something.py"
        root_file.write_text('if __name__ == "__main__": pass\n')

        sub_file = subdir / "helper.py"
        sub_file.write_text('def helper(): pass\n')

        records = scan_scripts(tmp_path)
        file_names = [Path(r["file"]).name for r in records]

        # Recursive scan finds both root and subdirectory files
        assert "check_something.py" in file_names
        assert "helper.py" in file_names

    def test_init_py_excluded_from_scan(self, tmp_path: Path) -> None:
        from scripts.circle1.scripts_inventory import scan_scripts

        scripts = tmp_path / "scripts"
        scripts.mkdir()
        (scripts / "__init__.py").write_text("# package marker\n")
        (scripts / "check_thing.py").write_text('if __name__ == "__main__": pass\n')

        records = scan_scripts(tmp_path)
        file_names = [Path(r["file"]).name for r in records]

        assert "__init__.py" not in file_names
        assert "check_thing.py" in file_names

    def test_flat_scripts_only_no_subdirs_still_works(self, tmp_path: Path) -> None:
        from scripts.circle1.scripts_inventory import scan_scripts

        scripts = tmp_path / "scripts"
        scripts.mkdir()
        (scripts / "check_a.py").write_text('if __name__ == "__main__": pass\n')
        (scripts / "helpers.py").write_text('def fn(): pass\n')

        records = scan_scripts(tmp_path)
        assert len(records) == 2
