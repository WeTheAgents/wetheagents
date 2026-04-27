"""Tests for scripts/circle1/role_grammar.py — role families and bypass scenarios.

Test structure:
    TestRunnableEntrypoint  — canonical cases + bypass scenarios (string/comment)
    TestImportSafeSupport   — canonical cases + bypass scenarios (sys.path in guard)
    TestDeclarationModule   — canonical cases + bypass scenarios (conditional behavior)
    TestUnclassified        — explicit reason requirement
    TestCanonicalFiles      — integration tests against real repo files
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from scripts.circle1.role_grammar import Role, RoleResult, classify_role, extract_ast_features


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def py_file(tmp_path: Path):
    """Write a Python snippet to a temp file and return its path."""
    def _write(src: str, name: str = "module.py") -> Path:
        p = tmp_path / name
        p.write_text(textwrap.dedent(src), encoding="utf-8")
        return p
    return _write


def _assert_role(result: RoleResult, expected: Role, msg: str = "") -> None:
    detail = f"got role={result.role!r}, reasons={result.reasons!r}"
    assert result.role == expected, f"{msg} — {detail}"


# ---------------------------------------------------------------------------
# runnable_entrypoint
# ---------------------------------------------------------------------------

class TestRunnableEntrypoint:
    def test_canonical_double_quotes(self, py_file):
        p = py_file("""\
            \"\"\"A runnable script.\"\"\"
            from __future__ import annotations
            def main() -> int:
                return 0
            if __name__ == "__main__":
                raise SystemExit(main())
        """)
        _assert_role(classify_role(p), Role.RUNNABLE_ENTRYPOINT)

    def test_canonical_single_quotes(self, py_file):
        p = py_file("""\
            \"\"\"Script.\"\"\"
            if __name__ == '__main__':
                pass
        """)
        _assert_role(classify_role(p), Role.RUNNABLE_ENTRYPOINT)

    def test_bypass_main_in_string_literal(self, py_file):
        """BYPASS CLOSED: text search finds __main__ inside a string; AST does not.

        A naive text-search implementation would wrongly classify this file
        as runnable_entrypoint because the pattern appears in EXAMPLE_CODE.
        AST-based detection sees no module-level If node with the pattern.
        """
        p = py_file("""\
            \"\"\"Support library that documents the __main__ idiom.\"\"\"
            from __future__ import annotations

            EXAMPLE_CODE = '''
            if __name__ == '__main__':
                print("this is inside a string, not a real guard")
            '''

            def helper() -> str:
                return EXAMPLE_CODE
        """)
        result = classify_role(p)
        assert result.role != Role.RUNNABLE_ENTRYPOINT, (
            "BYPASS NOT CLOSED: __main__ inside a string literal should not "
            "trigger runnable_entrypoint classification. "
            f"Got: role={result.role!r}, reasons={result.reasons!r}"
        )

    def test_bypass_main_in_comment(self, py_file):
        """BYPASS CLOSED: text search finds __main__ in commented-out code; AST does not."""
        p = py_file("""\
            \"\"\"Support library.\"\"\"
            from __future__ import annotations

            # if __name__ == '__main__':  <-- commented out, not a real guard
            def helper() -> int:
                return 42
        """)
        result = classify_role(p)
        assert result.role != Role.RUNNABLE_ENTRYPOINT, (
            "BYPASS NOT CLOSED: __main__ in a comment should not trigger "
            "runnable_entrypoint classification."
        )

    def test_bypass_main_guard_inside_function_not_module_level(self, py_file):
        """Main guard inside a function body is not a module-level guard."""
        p = py_file("""\
            \"\"\"Support module.\"\"\"
            from __future__ import annotations

            def setup() -> None:
                if __name__ == '__main__':  # inside function body
                    pass
        """)
        result = classify_role(p)
        assert result.role != Role.RUNNABLE_ENTRYPOINT, (
            "Main guard inside a function body must not be detected as module-level guard."
        )

    def test_has_bypass_notes(self, py_file):
        """runnable_entrypoint results must carry bypass documentation."""
        p = py_file("""\
            if __name__ == '__main__':
                pass
        """)
        result = classify_role(p)
        assert result.role == Role.RUNNABLE_ENTRYPOINT
        assert result.bypass_notes, "runnable_entrypoint must document its bypass vector"
        combined = " ".join(result.bypass_notes).lower()
        assert "string" in combined or "comment" in combined or "text search" in combined

    def test_reversed_main_guard_recognized(self, py_file):
        """V1 policy (Point 2): reversed guard `if '__main__' == __name__:` is recognized.

        Both comparison orderings are semantically identical. V1 normalizes both
        via AST inspection instead of rejecting the reversed form silently.
        """
        p = py_file("""\
            \"\"\"A script using the reversed guard form.\"\"\"
            from __future__ import annotations

            def main() -> int:
                return 0

            if "__main__" == __name__:
                raise SystemExit(main())
        """)
        result = classify_role(p)
        _assert_role(result, Role.RUNNABLE_ENTRYPOINT, "reversed guard must be recognized")

    def test_reversed_guard_single_quotes(self, py_file):
        """Reversed guard with single-quoted string is also recognized."""
        p = py_file("""\
            if '__main__' == __name__:
                pass
        """)
        _assert_role(classify_role(p), Role.RUNNABLE_ENTRYPOINT)


# ---------------------------------------------------------------------------
# import_safe_support
# ---------------------------------------------------------------------------

class TestImportSafeSupport:
    def test_canonical_functions_only(self, py_file):
        p = py_file("""\
            \"\"\"I/O helpers.\"\"\"
            from __future__ import annotations
            import json
            from pathlib import Path

            def load_json(path: Path) -> dict:
                return json.loads(path.read_text())

            def save_json(path: Path, data: dict) -> None:
                path.write_text(json.dumps(data, indent=2))
        """)
        _assert_role(classify_role(p), Role.IMPORT_SAFE_SUPPORT)

    def test_canonical_class_only(self, py_file):
        p = py_file("""\
            \"\"\"Support module.\"\"\"
            from __future__ import annotations

            class Helper:
                def work(self) -> int:
                    return 0
        """)
        _assert_role(classify_role(p), Role.IMPORT_SAFE_SUPPORT)

    def test_try_except_import_allowed(self, py_file):
        """try/except import fallback at module level does not disqualify import-safe."""
        p = py_file("""\
            \"\"\"Module with import fallback.\"\"\"
            from __future__ import annotations
            try:
                from scripts.economy_constants import SPLIT_TABLE
            except ModuleNotFoundError:
                from economy_constants import SPLIT_TABLE  # type: ignore

            def compute(n: int) -> list[int]:
                return SPLIT_TABLE.get(n, [])
        """)
        _assert_role(classify_role(p), Role.IMPORT_SAFE_SUPPORT)

    def test_bypass_sys_path_insert_inside_if_guard(self, py_file):
        """BYPASS CLOSED: sys.path.insert inside an if-guard is not a bare call.

        A bare-call detection check (ast.Expr(ast.Call)) would miss this pattern
        because the call is inside ast.If, not ast.Expr. Our implementation
        scans all module-level control flow for sys.path mutations.
        """
        p = py_file("""\
            \"\"\"Parser with sys.path setup — looks import-safe but isn't.\"\"\"
            from __future__ import annotations
            import sys
            from pathlib import Path

            _ROOT = Path(__file__).resolve().parents[1]
            if str(_ROOT) not in sys.path:
                sys.path.insert(0, str(_ROOT))  # inside if, not a bare call

            def parse(data: str) -> dict:
                return {}
        """)
        result = classify_role(p)
        assert result.role != Role.IMPORT_SAFE_SUPPORT, (
            "BYPASS NOT CLOSED: sys.path.insert inside an if-guard should "
            "disqualify import_safe_support. "
            f"Got: role={result.role!r}, reasons={result.reasons!r}"
        )
        # Verify the specific reason is reported
        combined_reasons = " ".join(result.reasons).lower()
        assert "sys.path" in combined_reasons or "path" in combined_reasons or "mutation" in combined_reasons

    def test_bypass_bare_toplevel_call(self, py_file):
        """BYPASS CLOSED: file with a bare call at module level is not import-safe."""
        p = py_file("""\
            \"\"\"Not import-safe — calls basicConfig at module level.\"\"\"
            from __future__ import annotations
            import logging

            logging.basicConfig(level=logging.DEBUG)  # bare call for side effects

            def helper() -> None:
                pass
        """)
        result = classify_role(p)
        assert result.role != Role.IMPORT_SAFE_SUPPORT

    def test_bypass_sys_path_append_inside_if(self, py_file):
        """sys.path.append inside if is also caught (not just .insert)."""
        p = py_file("""\
            \"\"\"Uses sys.path.append.\"\"\"
            from __future__ import annotations
            import sys
            from pathlib import Path
            _SRC = str(Path(__file__).parent)
            if _SRC not in sys.path:
                sys.path.append(_SRC)
            def work() -> int:
                return 1
        """)
        result = classify_role(p)
        assert result.role != Role.IMPORT_SAFE_SUPPORT

    def test_known_limitation_import_side_effects_documented(self, py_file):
        """KNOWN LIMITATION: importing a module with side effects cannot be detected.

        The classifier correctly identifies this file as import_safe_support
        because its OWN code has no side effects. The imported module's behavior
        is opaque. This limitation is documented in bypass_notes.
        """
        p = py_file("""\
            \"\"\"Imports a module that has side effects — we cannot detect this.\"\"\"
            from __future__ import annotations
            import some_module_that_happens_to_have_side_effects  # noqa: F401

            def helper() -> str:
                return "result"
        """)
        result = classify_role(p)
        # This IS a documented limitation: the classifier says import_safe_support
        assert result.role == Role.IMPORT_SAFE_SUPPORT, (
            "This is the known limitation: we cannot detect imported-module side effects. "
            f"Got: {result.role!r}"
        )
        # The limitation must be documented in bypass_notes
        combined = " ".join(result.bypass_notes).lower()
        assert "import" in combined and ("side effect" in combined or "side-effect" in combined), (
            "bypass_notes must document the import-side-effects limitation"
        )

    def test_bypass_decorator_call_disqualifies_import_safe(self, py_file):
        """BYPASS CLOSED (Point 1): @register() at module level executes at import time.

        A module with Call-type decorators on top-level definitions is NOT
        import_safe_support — the decorator expression executes at import time,
        mutating whatever state the decorator touches. V1 detects this by scanning
        FunctionDef/ClassDef.decorator_list for ast.Call nodes.
        """
        p = py_file("""\
            \"\"\"Module using a registry decorator — import-time side effect.\"\"\"
            from __future__ import annotations

            REGISTRY = {}

            def register(name):
                def _dec(fn):
                    REGISTRY[name] = fn
                    return fn
                return _dec

            @register("do_thing")
            def do_thing() -> None:
                pass
        """)
        result = classify_role(p)
        assert result.role != Role.IMPORT_SAFE_SUPPORT, (
            "BYPASS NOT CLOSED: @register() executes at import time and must "
            "disqualify import_safe_support. "
            f"Got: role={result.role!r}, reasons={result.reasons!r}"
        )
        combined_reasons = " ".join(result.reasons).lower()
        assert "decorator" in combined_reasons or "import" in combined_reasons, (
            "Unclassified reason must mention decorator side effect"
        )

    def test_decorator_bare_name_still_import_safe(self, py_file):
        """Bare decorator reference (@staticmethod, not a Call) does not disqualify.

        Only Call-type decorators (@register()) count as import-time side effects.
        Bare name decorators (@staticmethod, @property) are attribute lookups, not calls.
        """
        p = py_file("""\
            \"\"\"Module using built-in non-call decorators.\"\"\"
            from __future__ import annotations

            class MyClass:
                @staticmethod
                def util() -> int:
                    return 0

            def helper() -> str:
                return "ok"
        """)
        result = classify_role(p)
        _assert_role(result, Role.IMPORT_SAFE_SUPPORT, "@staticmethod should not disqualify")

    def test_decorator_call_on_class_disqualifies(self, py_file):
        """Call-type decorator on a top-level class also disqualifies import_safe."""
        p = py_file("""\
            \"\"\"Module with decorated class.\"\"\"
            from __future__ import annotations

            def dataclass_like(cls):
                return cls

            @dataclass_like()
            class Config:
                value: int = 0
        """)
        result = classify_role(p)
        assert result.role != Role.IMPORT_SAFE_SUPPORT, (
            "@dataclass_like() on a class executes at import time; must not be import_safe. "
            f"Got: role={result.role!r}"
        )


# ---------------------------------------------------------------------------
# declaration_module
# ---------------------------------------------------------------------------

class TestDeclarationModule:
    def test_canonical_annotated_dict(self, py_file):
        p = py_file("""\
            \"\"\"Economy constants.\"\"\"
            from __future__ import annotations

            SPLIT_TABLE: dict[int, list[int]] = {
                1: [100],
                2: [70, 30],
            }
            MAX_REWARD = 500
        """)
        _assert_role(classify_role(p), Role.DECLARATION_MODULE)

    def test_pure_imports(self, py_file):
        """A file with only imports is declarative."""
        p = py_file("""\
            \"\"\"Re-exports.\"\"\"
            from __future__ import annotations
            from typing import Any, Dict, List
        """)
        _assert_role(classify_role(p), Role.DECLARATION_MODULE)

    def test_type_checking_guard_is_allowed(self, py_file):
        """TYPE_CHECKING import guard is a standard pattern — allowed in declaration modules."""
        p = py_file("""\
            \"\"\"Constants with TYPE_CHECKING imports.\"\"\"
            from __future__ import annotations
            from typing import TYPE_CHECKING

            if TYPE_CHECKING:
                from some_module import SomeType

            TIMEOUT = 30
        """)
        _assert_role(classify_role(p), Role.DECLARATION_MODULE)

    def test_if_imports_only_allowed(self, py_file):
        """An if-block that contains only imports is allowed (conditional platform imports)."""
        p = py_file("""\
            \"\"\"Platform-conditional imports.\"\"\"
            from __future__ import annotations
            import sys

            if sys.platform == "win32":
                import winreg
            else:
                import posix

            PLATFORM = sys.platform
        """)
        _assert_role(classify_role(p), Role.DECLARATION_MODULE)

    def test_bypass_conditional_non_import_behavior(self, py_file):
        """BYPASS CLOSED: a naive 'no def statements' check misses a call inside an if-block.

        This file has no top-level def or class. A naive classifier would scan for
        FunctionDef nodes, find none, and classify it as declaration_module.
        Our check inspects the contents of every module-level if-block and rejects
        any that contain non-import statements (including function calls).
        """
        p = py_file("""\
            \"\"\"Looks like declarations but has conditional behavior.\"\"\"
            from __future__ import annotations
            import os

            ENVIRONMENT = "dev"

            if ENVIRONMENT == "production":
                from prod_module import configure
                configure()   # ← side-effect call inside if body

            CONSTANT = 42
        """)
        result = classify_role(p)
        assert result.role != Role.DECLARATION_MODULE, (
            "BYPASS NOT CLOSED: a file with a non-import call inside an if-block "
            "should NOT be classified as declaration_module. "
            f"Got: role={result.role!r}, reasons={result.reasons!r}"
        )

    def test_bypass_if_with_assignment_inside(self, py_file):
        """Even a plain assignment inside an if disqualifies declaration_module."""
        p = py_file("""\
            \"\"\"Config-like file with conditional assignment.\"\"\"
            from __future__ import annotations

            FLAG = True
            if FLAG:
                EXTRA = "something"  # ← assignment inside if

            CONSTANT = 99
        """)
        result = classify_role(p)
        assert result.role != Role.DECLARATION_MODULE

    def test_bypass_type_checking_guard_with_calls(self, py_file):
        """BYPASS CLOSED (self-roast fix): calls inside if TYPE_CHECKING: must not pass.

        An earlier version used `_is_type_checking_guard OR _if_body_is_imports_only`,
        meaning any if TYPE_CHECKING: block was unconditionally allowed. A file could
        hide side-effectful calls under a TYPE_CHECKING guard and be misclassified as
        declaration_module. Fix: use _if_body_is_imports_only exclusively; it
        correctly handles TYPE_CHECKING guards whose body is imports-only.
        """
        p = py_file("""\
            \"\"\"Constants with abused TYPE_CHECKING guard.\"\"\"
            from __future__ import annotations
            from typing import TYPE_CHECKING

            if TYPE_CHECKING:
                from some_module import configure
                configure()   # ← call inside TYPE_CHECKING — should disqualify

            CONSTANT = 42
        """)
        result = classify_role(p)
        assert result.role != Role.DECLARATION_MODULE, (
            "BYPASS NOT CLOSED: calls inside if TYPE_CHECKING: should disqualify "
            "declaration_module. "
            f"Got: role={result.role!r}, reasons={result.reasons!r}"
        )

    def test_known_limitation_assignment_with_call(self, py_file):
        """KNOWN LIMITATION: X = os.getenv('VAR') passes the data-body check.

        This is a documented limitation. Detecting side-effectful expressions
        in RHS values requires dataflow analysis. The classifier classifies
        this as declaration_module and documents the gap in bypass_notes.
        """
        p = py_file("""\
            \"\"\"Looks like declarations but calls functions in RHS.\"\"\"
            from __future__ import annotations
            import os

            DB_URL = os.getenv("DATABASE_URL", "sqlite:///dev.db")
            TIMEOUT = int(os.environ.get("TIMEOUT", "30"))
        """)
        result = classify_role(p)
        # This IS the documented limitation: classified as declaration_module
        assert result.role == Role.DECLARATION_MODULE, (
            "This is the known limitation: X = os.getenv() passes the check. "
            f"Got: {result.role!r}"
        )
        # The limitation must be documented
        combined = " ".join(result.bypass_notes).lower()
        assert "call" in combined or "rhs" in combined or "dataflow" in combined, (
            "bypass_notes must document the assignment-with-call limitation"
        )

    def test_has_bypass_notes(self, py_file):
        p = py_file("CONSTANT = 42\n")
        result = classify_role(p)
        assert result.role == Role.DECLARATION_MODULE
        assert result.bypass_notes, "declaration_module must carry bypass documentation"


# ---------------------------------------------------------------------------
# unclassified
# ---------------------------------------------------------------------------

class TestUnclassified:
    def test_pipeline_parser_pattern(self, py_file):
        """A file with reusable functions AND sys.path mutation is unclassified."""
        p = py_file("""\
            \"\"\"Parser with sys.path setup.\"\"\"
            from __future__ import annotations
            import sys
            from pathlib import Path

            _ROOT = Path(__file__).resolve().parents[1]
            if str(_ROOT) not in sys.path:
                sys.path.insert(0, str(_ROOT))

            def parse(data: str) -> dict:
                return {}

            class Result:
                pass
        """)
        result = classify_role(p)
        _assert_role(result, Role.UNCLASSIFIED, "sys.path mutation + functions")

    def test_unclassified_never_has_empty_reasons(self, py_file):
        """Unclassified is not a silent catch-all — it must always carry explicit reasons."""
        p = py_file("""\
            \"\"\"Weird module.\"\"\"
            from __future__ import annotations
            import logging

            logging.basicConfig()  # bare call - side effect
            CONSTANT = 42
        """)
        result = classify_role(p)
        # Whatever the role, it must have reasons
        assert result.reasons, f"Got role {result.role!r} but reasons list is empty"

    def test_bare_toplevel_call_with_functions_is_unclassified(self, py_file):
        """Functions + bare call = unclassified (not import_safe_support)."""
        p = py_file("""\
            \"\"\"Bad module.\"\"\"
            from __future__ import annotations
            import os

            os.makedirs("/tmp/workdir", exist_ok=True)  # bare call

            def helper() -> str:
                return "done"
        """)
        result = classify_role(p)
        _assert_role(result, Role.UNCLASSIFIED, "bare call + functions")

    def test_unclassified_reason_mentions_specific_cause(self, py_file):
        """Unclassified reasons must name the specific disqualifying feature."""
        p = py_file("""\
            \"\"\"Parser.\"\"\"
            from __future__ import annotations
            import sys
            _SRC = "src"
            if _SRC not in sys.path:
                sys.path.insert(0, _SRC)
            def work() -> int:
                return 0
        """)
        result = classify_role(p)
        assert result.role == Role.UNCLASSIFIED
        combined = " ".join(result.reasons).lower()
        # Must mention sys.path or mutation specifically
        assert "sys.path" in combined or "mutation" in combined or "path" in combined


# ---------------------------------------------------------------------------
# ASTFeatures unit tests
# ---------------------------------------------------------------------------

class TestASTFeatures:
    def test_main_guard_detected(self, py_file):
        p = py_file("if __name__ == '__main__': pass\n")
        f = extract_ast_features(p)
        assert f.has_ast_main_guard is True

    def test_main_guard_in_string_not_detected(self, py_file):
        p = py_file("X = \"if __name__ == '__main__': pass\"\n")
        f = extract_ast_features(p)
        assert f.has_ast_main_guard is False

    def test_sys_path_in_if_detected(self, py_file):
        p = py_file("""\
            import sys
            if True:
                sys.path.insert(0, "src")
        """)
        f = extract_ast_features(p)
        assert f.has_module_level_sys_path_mutation is True

    def test_sys_path_in_function_not_detected(self, py_file):
        """sys.path mutation inside a function body is scoped — not a module-level concern."""
        p = py_file("""\
            import sys
            def setup():
                sys.path.insert(0, "src")
        """)
        f = extract_ast_features(p)
        assert f.has_module_level_sys_path_mutation is False

    def test_bare_call_detected(self, py_file):
        p = py_file("""\
            import logging
            logging.basicConfig()
        """)
        f = extract_ast_features(p)
        assert f.has_toplevel_bare_calls is True

    def test_assigned_call_not_bare(self, py_file):
        """X = func() is an Assign, not a bare Expr(Call) — not flagged as bare call."""
        p = py_file("""\
            import re
            PATTERN = re.compile(r"\\d+")
        """)
        f = extract_ast_features(p)
        assert f.has_toplevel_bare_calls is False

    def test_only_data_body_true(self, py_file):
        p = py_file("""\
            \"\"\"Constants.\"\"\"
            from __future__ import annotations
            TIMEOUT: int = 30
            NAME = "wea"
        """)
        f = extract_ast_features(p)
        assert f.has_only_data_body is True

    def test_only_data_body_false_with_function(self, py_file):
        p = py_file("""\
            def helper(): pass
            CONSTANT = 1
        """)
        f = extract_ast_features(p)
        assert f.has_only_data_body is False

    def test_only_data_body_false_with_non_import_if(self, py_file):
        p = py_file("""\
            FLAG = True
            if FLAG:
                X = 1
        """)
        f = extract_ast_features(p)
        assert f.has_only_data_body is False

    def test_parse_error_handled(self, py_file):
        p = py_file("def broken(\n")
        f = extract_ast_features(p)
        assert f.parse_error is True
        assert f.parse_error_reason

    def test_decorator_call_detected(self, py_file):
        """has_decorator_side_effects is True when a Call-type decorator is present."""
        p = py_file("""\
            def reg(name):
                return lambda fn: fn

            @reg("x")
            def fn() -> None:
                pass
        """)
        f = extract_ast_features(p)
        assert f.has_decorator_side_effects is True

    def test_decorator_bare_name_not_detected(self, py_file):
        """has_decorator_side_effects is False for bare-name decorators (no call)."""
        p = py_file("""\
            class C:
                @staticmethod
                def fn() -> None:
                    pass
        """)
        f = extract_ast_features(p)
        assert f.has_decorator_side_effects is False

    def test_decorator_call_inside_function_not_detected(self, py_file):
        """Decorated nested functions do not count — they run only when outer is called."""
        p = py_file("""\
            def factory():
                @some_decorator()
                def inner() -> None:
                    pass
                return inner

            def helper() -> str:
                return "ok"
        """)
        f = extract_ast_features(p)
        assert f.has_decorator_side_effects is False


# ---------------------------------------------------------------------------
# Integration: canonical repo files
# ---------------------------------------------------------------------------

class TestCanonicalFiles:
    """Verify the grammar classifies real repo files correctly.

    These tests serve as regression guards: if a canonical file changes role,
    these tests will fail and force an explicit decision.
    """

    @pytest.fixture(autouse=True)
    def _find_repo_root(self):
        here = Path(__file__).resolve().parent
        root = here.parent
        while root != root.parent:
            if (root / "scripts").is_dir() and (root / "ledger").is_dir():
                self._root = root
                return
            root = root.parent
        pytest.skip("Repo root not found — skipping integration tests")

    def _classify(self, rel_path: str) -> RoleResult:
        p = self._root / rel_path
        if not p.exists():
            pytest.skip(f"File not found: {rel_path}")
        return classify_role(p)

    def test_io_helpers_is_import_safe(self):
        result = self._classify("scripts/io_helpers.py")
        _assert_role(result, Role.IMPORT_SAFE_SUPPORT, "io_helpers.py")

    def test_ledger_ops_is_import_safe(self):
        result = self._classify("scripts/ledger_ops.py")
        _assert_role(result, Role.IMPORT_SAFE_SUPPORT, "ledger_ops.py")

    def test_tide_ops_is_import_safe(self):
        result = self._classify("scripts/tide_ops.py")
        _assert_role(result, Role.IMPORT_SAFE_SUPPORT, "tide_ops.py")

    def test_tide_parser_is_import_safe(self):
        result = self._classify("scripts/tide_parser.py")
        _assert_role(result, Role.IMPORT_SAFE_SUPPORT, "tide_parser.py")

    def test_economy_constants_is_declaration(self):
        result = self._classify("scripts/economy_constants.py")
        _assert_role(result, Role.DECLARATION_MODULE, "economy_constants.py")

    def test_pipeline_parser_is_unclassified(self):
        result = self._classify("scripts/pipeline_parser.py")
        _assert_role(result, Role.UNCLASSIFIED, "pipeline_parser.py")
        assert result.reasons, "pipeline_parser.py unclassified result must have reasons"

    def test_check_invariant_is_runnable(self):
        result = self._classify("scripts/check_invariant.py")
        _assert_role(result, Role.RUNNABLE_ENTRYPOINT, "check_invariant.py")

    def test_score_repo_is_runnable(self):
        result = self._classify("scripts/score_repo.py")
        _assert_role(result, Role.RUNNABLE_ENTRYPOINT, "score_repo.py")

    def test_zone_grammar_is_import_safe(self):
        result = self._classify("scripts/circle1/zone_grammar.py")
        _assert_role(result, Role.IMPORT_SAFE_SUPPORT, "zone_grammar.py")


# ---------------------------------------------------------------------------
# Inventory policy
# ---------------------------------------------------------------------------

class TestInventoryPolicy:
    """Pin the deliberate V1 inventory policy: recursive scan of scripts/."""

    def test_recursive_scan_includes_subdirectory_files(self, tmp_path):
        """V1 policy (Point 4): scan is recursive — scripts/ subdirectories are included.

        The task spec said `scripts/*.py except __init__.py`, but the implementation
        scans recursively with rglob. Recursive is the correct operational choice
        because scripts/ already contains subdirectories (circle1/, etc.) with
        classifiable Python files. This test pins the recursive behavior as deliberate.
        """
        from scripts.circle1.scripts_inventory import scan_scripts

        # Set up a mock scripts/ tree with files at root and in a subdir
        scripts_dir = tmp_path / "scripts"
        (scripts_dir / "sub").mkdir(parents=True)
        (scripts_dir / "top_level.py").write_text(
            "if __name__ == '__main__':\n    pass\n", encoding="utf-8"
        )
        (scripts_dir / "sub" / "helper.py").write_text(
            "def helper():\n    return 1\n", encoding="utf-8"
        )
        (scripts_dir / "__init__.py").write_text("", encoding="utf-8")

        inventory = scan_scripts(tmp_path, scan_date="2026-01-01")
        paths = {e["path"] for e in inventory["files"]}

        assert any("top_level.py" in p for p in paths), (
            "Root-level scripts must be included"
        )
        assert any("sub/helper.py" in p or "sub\\helper.py" in p for p in paths), (
            "Subdirectory files must be included (recursive scan)"
        )
        assert not any("__init__.py" in p for p in paths), (
            "__init__.py must be excluded from inventory"
        )

    def test_init_py_excluded_at_all_levels(self, tmp_path):
        """__init__.py files in any subdirectory are excluded from inventory."""
        from scripts.circle1.scripts_inventory import scan_scripts

        scripts_dir = tmp_path / "scripts"
        (scripts_dir / "sub").mkdir(parents=True)
        (scripts_dir / "__init__.py").write_text("", encoding="utf-8")
        (scripts_dir / "sub" / "__init__.py").write_text("", encoding="utf-8")
        (scripts_dir / "sub" / "util.py").write_text("def f(): pass\n", encoding="utf-8")

        inventory = scan_scripts(tmp_path, scan_date="2026-01-01")
        for entry in inventory["files"]:
            assert "__init__" not in entry["path"], (
                f"__init__.py must not appear in inventory: {entry['path']}"
            )


# ---------------------------------------------------------------------------
# Fix A — nested side effects in control-flow bodies
# ---------------------------------------------------------------------------

class TestNestedSideEffects:
    """Fix A: _detect_toplevel_bare_calls must find Expr(Call) inside control-flow."""

    def test_bare_call_inside_if_is_unclassified(self, py_file):
        """Fix A: `if True: bare_call()` contains an import-time bare call."""
        p = py_file("if True:\n    bare_call()\n")
        _assert_role(classify_role(p), Role.UNCLASSIFIED)

    def test_bare_call_inside_for_is_unclassified(self, py_file):
        """Fix A: `for x in []: setup()` contains an import-time bare call."""
        p = py_file("for x in []:\n    setup()\n")
        _assert_role(classify_role(p), Role.UNCLASSIFIED)

    def test_bare_call_inside_function_not_detected(self, py_file):
        """Fix A: a bare call inside a FunctionDef body is NOT import-time.

        Calls inside a def only execute when the def is called, never at
        import time. The file should classify as import_safe_support.
        """
        p = py_file("def fn():\n    side_effect()\n")
        f = extract_ast_features(p)
        assert f.has_toplevel_bare_calls is False, (
            "Bare call inside function body must not be detected as import-time"
        )
        _assert_role(classify_role(p), Role.IMPORT_SAFE_SUPPORT)

    def test_bare_call_in_except_handler_is_unclassified(self, py_file):
        """Fix A: a bare call in an except-handler body is an import-time bare call."""
        p = py_file("try:\n    pass\nexcept Exception:\n    recovery()\n")
        _assert_role(classify_role(p), Role.UNCLASSIFIED)

    def test_ast_features_bare_call_in_if_detected(self, py_file):
        """Fix A: has_toplevel_bare_calls is True for `if True: bare_call()`."""
        p = py_file("if True:\n    bare_call()\n")
        f = extract_ast_features(p)
        assert f.has_toplevel_bare_calls is True

    def test_ast_features_bare_call_in_for_detected(self, py_file):
        """Fix A: has_toplevel_bare_calls is True for `for x in []: setup()`."""
        p = py_file("for x in []:\n    setup()\n")
        f = extract_ast_features(p)
        assert f.has_toplevel_bare_calls is True

    def test_ast_features_bare_call_in_except_detected(self, py_file):
        """Fix A: has_toplevel_bare_calls is True for a bare call in except body."""
        p = py_file("try:\n    pass\nexcept Exception:\n    recovery()\n")
        f = extract_ast_features(p)
        assert f.has_toplevel_bare_calls is True


# ---------------------------------------------------------------------------
# Fix B — sys.path inside nested def must not be flagged
# ---------------------------------------------------------------------------

class TestNestedDefSysPath:
    """Fix B: sys.path call inside a def that lives inside a module-level if
    is NOT module-level code and must NOT trigger has_module_level_sys_path_mutation.
    """

    def test_sys_path_in_nested_def_not_flagged(self, py_file):
        """Fix B: sys.path inside `if True: def init(): sys.path.append(...)` → import_safe."""
        p = py_file("""\
            import sys

            if True:
                def init():
                    sys.path.append('x')

            def helper():
                return 1
        """)
        f = extract_ast_features(p)
        assert f.has_module_level_sys_path_mutation is False, (
            "Fix B: sys.path inside a nested def is not module-level"
        )
        _assert_role(classify_role(p), Role.IMPORT_SAFE_SUPPORT)

    def test_sys_path_direct_in_if_still_flagged(self, py_file):
        """Fix B regression guard: sys.path directly inside if body is still caught."""
        p = py_file("""\
            import sys

            if True:
                sys.path.insert(0, 'x')

            def helper():
                return 1
        """)
        f = extract_ast_features(p)
        assert f.has_module_level_sys_path_mutation is True, (
            "Fix B regression: direct sys.path.insert inside if must still be detected"
        )
        _assert_role(classify_role(p), Role.UNCLASSIFIED)


# ---------------------------------------------------------------------------
# Fix C — if-test with Call disqualifies declaration_module
# ---------------------------------------------------------------------------

class TestIfTestCallCheck:
    """Fix C: _if_body_is_imports_only must reject if-tests that contain ast.Call."""

    def test_if_test_with_call_disqualifies_declaration(self, py_file):
        """Fix C: `if pathlib.Path('x').exists(): import y` must NOT be declaration_module.

        The `.exists()` call in the test condition executes at import time even
        though the body is imports-only.
        """
        p = py_file(
            "import pathlib\n"
            "if pathlib.Path('x').exists():\n"
            "    import os\n"
        )
        result = classify_role(p)
        assert result.role != Role.DECLARATION_MODULE, (
            "Fix C: Call in if-test disqualifies declaration_module. "
            f"Got: {result.role!r}, reasons={result.reasons!r}"
        )

    def test_if_test_compare_on_attribute_still_allowed(self, py_file):
        """Fix C negative: `if sys.version_info >= (3, 10): import x` is still allowed.

        Compare on Attribute with no ast.Call in the test — the test is a
        pure comparison, safe for declaration_module.
        """
        p = py_file(
            "import sys\n"
            "if sys.version_info >= (3, 10):\n"
            "    import importlib\n"
        )
        _assert_role(classify_role(p), Role.DECLARATION_MODULE,
                     "version_info compare (no Call) must still be allowed")

    def test_ast_features_if_test_call_disqualifies_data_body(self, py_file):
        """Fix C: has_only_data_body is False when if-test contains a Call."""
        p = py_file(
            "import pathlib\n"
            "if pathlib.Path('x').exists():\n"
            "    import os\n"
        )
        f = extract_ast_features(p)
        assert f.has_only_data_body is False, (
            "Fix C: Call in if-test must set has_only_data_body=False"
        )
