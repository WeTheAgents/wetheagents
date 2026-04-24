"""Tests for scripts/circle1/role_grammar.py — V1 role grammar classifier.

Coverage:
  - Each of the four role families via synthetic fixture files
  - Boundary conditions: import-safety (sys.path), error-boundary (sys.exit)
  - Ambiguous edge cases (has functions + __main__, has_only_data with imports)
  - Integration tests against real counterexample files named in the spec
"""

from __future__ import annotations

from pathlib import Path

import pytest

import sys
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.circle1.role_grammar import (  # noqa: E402
    ROLES,
    classify_file,
    classify_role,
    extract_role_features,
)

# ── Synthetic fixture helpers ─────────────────────────────────────────────────

_RUNNABLE = """\
\"\"\"Entrypoint script.\"\"\"

from __future__ import annotations


def main() -> int:
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
"""

_IMPORT_SAFE = """\
\"\"\"Reusable helpers.\"\"\"

from __future__ import annotations


def helper(x: int) -> int:
    return x * 2


def another() -> str:
    return "ok"
"""

_DECLARATION = """\
\"\"\"Shared constants.\"\"\"

from __future__ import annotations

SPLIT_TABLE: dict[int, list[int]] = {
    1: [100],
    2: [70, 30],
}
MAX_SLOTS = 5
"""

_UNCLASSIFIED_SYSPATH = """\
\"\"\"Module with import-safety violation.\"\"\"

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def helper() -> None:
    pass
"""

_UNCLASSIFIED_SYSEXIT = """\
\"\"\"Module that calls sys.exit at top level.\"\"\"

from __future__ import annotations

import sys

sys.exit(1)
"""

# ── Role family tests ─────────────────────────────────────────────────────────


def test_runnable_entrypoint(tmp_path: Path) -> None:
    f = tmp_path / "entrypoint.py"
    f.write_text(_RUNNABLE, encoding="utf-8")
    result = classify_file(f)
    assert result["role"] == "runnable_entrypoint"
    assert result["reason"] is None


def test_import_safe_support(tmp_path: Path) -> None:
    f = tmp_path / "helpers.py"
    f.write_text(_IMPORT_SAFE, encoding="utf-8")
    result = classify_file(f)
    assert result["role"] == "import_safe_support"
    assert result["reason"] is None


def test_declaration_module(tmp_path: Path) -> None:
    f = tmp_path / "constants.py"
    f.write_text(_DECLARATION, encoding="utf-8")
    result = classify_file(f)
    assert result["role"] == "declaration_module"
    assert result["reason"] is None


def test_unclassified_syspath_mutation(tmp_path: Path) -> None:
    f = tmp_path / "bad_module.py"
    f.write_text(_UNCLASSIFIED_SYSPATH, encoding="utf-8")
    result = classify_file(f)
    assert result["role"] == "unclassified"
    assert result["reason"] is not None
    assert "sys.path" in result["reason"].lower()


def test_unclassified_sysexit_at_top(tmp_path: Path) -> None:
    f = tmp_path / "exits_on_import.py"
    f.write_text(_UNCLASSIFIED_SYSEXIT, encoding="utf-8")
    result = classify_file(f)
    assert result["role"] == "unclassified"
    assert result["reason"] is not None
    assert "sys.exit" in result["reason"].lower()


# ── Boundary / edge case tests ────────────────────────────────────────────────


def test_runnable_wins_over_syspath(tmp_path: Path) -> None:
    """A runnable_entrypoint may have sys.path bootstrapping — that is acceptable."""
    f = tmp_path / "runnable_with_path_hack.py"
    f.write_text(
        '"""Script with sys.path bootstrap."""\n'
        "from __future__ import annotations\n"
        "import sys\nfrom pathlib import Path\n"
        "ROOT = Path(__file__).parent\n"
        "if str(ROOT) not in sys.path:\n"
        "    sys.path.insert(0, str(ROOT))\n"
        "def main() -> int:\n    return 0\n"
        'if __name__ == "__main__":\n    raise SystemExit(main())\n',
        encoding="utf-8",
    )
    result = classify_file(f)
    # __main__ guard takes priority — runnable_entrypoint wins
    assert result["role"] == "runnable_entrypoint"


def test_sysexit_inside_function_is_not_flagged(tmp_path: Path) -> None:
    """sys.exit inside a function body must NOT trigger import-safety flag."""
    f = tmp_path / "checker.py"
    f.write_text(
        '"""Checker script with sys.exit inside main()."""\n'
        "from __future__ import annotations\n"
        "import sys\n"
        "def main() -> None:\n"
        "    sys.exit(1)\n"
        'if __name__ == "__main__":\n    main()\n',
        encoding="utf-8",
    )
    result = classify_file(f)
    assert result["role"] == "runnable_entrypoint"
    feats = result["features"]
    assert feats["has_sysexit_at_top_level"] is False


def test_sysexit_inside_main_guard_not_flagged(tmp_path: Path) -> None:
    """sys.exit inside the __main__ guard is NOT an import-safety violation."""
    f = tmp_path / "script.py"
    f.write_text(
        '"""Script."""\nfrom __future__ import annotations\nimport sys\n'
        'if __name__ == "__main__":\n    sys.exit(0)\n',
        encoding="utf-8",
    )
    result = classify_file(f)
    assert result["role"] == "runnable_entrypoint"
    assert result["features"]["has_sysexit_at_top_level"] is False


def test_syspath_inside_main_guard_not_flagged(tmp_path: Path) -> None:
    """sys.path.insert inside the __main__ guard is NOT a violation."""
    f = tmp_path / "script.py"
    f.write_text(
        '"""Script."""\nfrom __future__ import annotations\nimport sys\n'
        'if __name__ == "__main__":\n    sys.path.insert(0, ".")\n',
        encoding="utf-8",
    )
    result = classify_file(f)
    assert result["role"] == "runnable_entrypoint"
    assert result["features"]["has_syspath_mutation_at_top_level"] is False


def test_has_function_and_main_is_runnable(tmp_path: Path) -> None:
    """A file with both helper functions AND __main__ is still runnable_entrypoint."""
    f = tmp_path / "hybrid.py"
    f.write_text(
        '"""Hybrid."""\nfrom __future__ import annotations\n'
        "def compute(x: int) -> int:\n    return x\n"
        'if __name__ == "__main__":\n    print(compute(1))\n',
        encoding="utf-8",
    )
    result = classify_file(f)
    assert result["role"] == "runnable_entrypoint"


def test_class_only_module_is_import_safe(tmp_path: Path) -> None:
    """A module with only class definitions (no main) is import_safe_support."""
    f = tmp_path / "models.py"
    f.write_text(
        '"""Domain models."""\nfrom __future__ import annotations\n'
        "class Foo:\n    def __init__(self) -> None:\n        self.x = 1\n",
        encoding="utf-8",
    )
    result = classify_file(f)
    assert result["role"] == "import_safe_support"


def test_only_imports_is_declaration(tmp_path: Path) -> None:
    """A module with only re-exports (no functions/classes) is declaration_module."""
    f = tmp_path / "re_export.py"
    f.write_text(
        '"""Re-exports."""\nfrom __future__ import annotations\n'
        "from pathlib import Path\n"
        "DEFAULT_ROOT = Path(\".\")\n",
        encoding="utf-8",
    )
    result = classify_file(f)
    assert result["role"] == "declaration_module"


def test_both_violations_reported(tmp_path: Path) -> None:
    """A file with both sys.path mutation AND sys.exit reports both in reason."""
    f = tmp_path / "double_bad.py"
    f.write_text(
        '"""Double violation."""\nfrom __future__ import annotations\n'
        "import sys\n"
        "sys.path.insert(0, \".\")\n"
        "sys.exit(1)\n",
        encoding="utf-8",
    )
    result = classify_file(f)
    assert result["role"] == "unclassified"
    assert "sys.path" in result["reason"].lower()
    assert "sys.exit" in result["reason"].lower()


def test_empty_file(tmp_path: Path) -> None:
    """An empty file has no functions, no classes, no __main__ → declaration_module."""
    f = tmp_path / "empty.py"
    f.write_text("", encoding="utf-8")
    result = classify_file(f)
    assert result["role"] == "declaration_module"


def test_roles_constant_is_complete() -> None:
    """ROLES set must contain exactly the four expected role strings."""
    assert ROLES == {"runnable_entrypoint", "import_safe_support", "declaration_module", "unclassified"}


def test_classify_role_accepts_features_dict() -> None:
    """classify_role works correctly when called with a hand-crafted features dict."""
    base = {
        "parse_error": False,
        "has_main_guard": False,
        "has_function_or_class": False,
        "has_only_data": True,
        "has_syspath_mutation_at_top_level": False,
        "has_sysexit_at_top_level": False,
    }
    assert classify_role(base)["role"] == "declaration_module"

    with_main = {**base, "has_main_guard": True}
    assert classify_role(with_main)["role"] == "runnable_entrypoint"

    with_syspath = {**base, "has_syspath_mutation_at_top_level": True}
    assert classify_role(with_syspath)["role"] == "unclassified"


# ── Integration tests against real repo files ─────────────────────────────────

_REAL_SCRIPTS = _ROOT / "scripts"


def test_io_helpers_is_import_safe_support() -> None:
    result = classify_file(_REAL_SCRIPTS / "io_helpers.py")
    assert result["role"] == "import_safe_support", result["reason"]


def test_tide_ops_is_import_safe_support() -> None:
    result = classify_file(_REAL_SCRIPTS / "tide_ops.py")
    assert result["role"] == "import_safe_support", result["reason"]


def test_tide_parser_is_import_safe_support() -> None:
    result = classify_file(_REAL_SCRIPTS / "tide_parser.py")
    assert result["role"] == "import_safe_support", result["reason"]


def test_ledger_ops_is_import_safe_support() -> None:
    result = classify_file(_REAL_SCRIPTS / "ledger_ops.py")
    assert result["role"] == "import_safe_support", result["reason"]


def test_economy_constants_is_declaration_module() -> None:
    result = classify_file(_REAL_SCRIPTS / "economy_constants.py")
    assert result["role"] == "declaration_module", result["reason"]


def test_pipeline_parser_is_unclassified() -> None:
    """pipeline_parser.py has sys.path.insert at module top level without __main__."""
    result = classify_file(_REAL_SCRIPTS / "pipeline_parser.py")
    assert result["role"] == "unclassified"
    assert result["features"]["has_syspath_mutation_at_top_level"] is True


def test_check_invariant_is_runnable_entrypoint() -> None:
    result = classify_file(_REAL_SCRIPTS / "check_invariant.py")
    assert result["role"] == "runnable_entrypoint"


def test_score_repo_is_runnable_entrypoint() -> None:
    """score_repo.py has sys.path mutation AND __main__ — __main__ wins."""
    result = classify_file(_ROOT / "scripts" / "score_repo.py")
    assert result["role"] == "runnable_entrypoint"
    # Confirm that sys.path mutation is detected (it exists outside __main__)
    assert result["features"]["has_syspath_mutation_at_top_level"] is True
