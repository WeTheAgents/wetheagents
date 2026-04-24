"""Role-aware V1 grammar for scripts/ zone (circle-1 module_grammar extension).

Classifies each Python file in scripts/ into one of four role families:
  - runnable_entrypoint: has __main__ guard, callable directly
  - import_safe_support: importable library, no top-level side effects on import
  - declaration_module: constants/tables/schema data; primarily data, no behavior
  - unclassified: doesn't fit cleanly (explicit reason required, NOT a catch-all)

Three non-trivial boundaries implemented:
  1. Import-safety: sys.path.insert/append at module top level outside __main__ guard
  2. Error-boundary: sys.exit() at module top level outside __main__ guard
  3. Data-purity: no function/class definitions (declaration_module qualifier)

The key design constraint: all boundary checks exclude function and class bodies.
A sys.exit inside a function does not execute on import — only module-level code does.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

ROLES: frozenset[str] = frozenset(
    {"runnable_entrypoint", "import_safe_support", "declaration_module", "unclassified"}
)

# ── AST helpers ───────────────────────────────────────────────────────────────


def _is_main_guard(node: ast.stmt) -> bool:
    """Return True if *node* is `if __name__ == '__main__'` (or reversed)."""
    if not isinstance(node, ast.If):
        return False
    test = node.test
    if not isinstance(test, ast.Compare):
        return False
    if len(test.ops) != 1 or not isinstance(test.ops[0], ast.Eq):
        return False
    if len(test.comparators) != 1:
        return False
    left, right = test.left, test.comparators[0]
    return (
        isinstance(right, ast.Constant) and right.value == "__main__"
    ) or (
        isinstance(left, ast.Constant) and left.value == "__main__"
    )


def _is_syspath_mutator(call: ast.expr) -> bool:
    """Return True if *call* is sys.path.insert(...) or sys.path.append(...)."""
    if not isinstance(call, ast.Call):
        return False
    func = call.func
    if not isinstance(func, ast.Attribute) or func.attr not in ("insert", "append"):
        return False
    obj = func.value
    if not isinstance(obj, ast.Attribute) or obj.attr != "path":
        return False
    pkg = obj.value
    return isinstance(pkg, ast.Name) and pkg.id == "sys"


def _is_sysexit_call(call: ast.expr) -> bool:
    """Return True if *call* is sys.exit(...) or SystemExit(...)."""
    if not isinstance(call, ast.Call):
        return False
    func = call.func
    if isinstance(func, ast.Attribute):
        return (
            func.attr == "exit"
            and isinstance(func.value, ast.Name)
            and func.value.id == "sys"
        )
    return isinstance(func, ast.Name) and func.id == "SystemExit"


class _ImportSafetyChecker(ast.NodeVisitor):
    """Visit module-level AST, detecting side effects that fire on import.

    Does NOT descend into FunctionDef/AsyncFunctionDef/ClassDef bodies.
    Skips the ``if __name__ == '__main__'`` guard block entirely.
    Only code that executes at module-load time is inspected.
    """

    def __init__(self) -> None:
        self.has_syspath_mutation: bool = False
        self.has_sysexit: bool = False

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        pass  # function body executes only when called, not on import

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        pass  # class body evaluates at definition time but contains no calls by itself

    def visit_If(self, node: ast.If) -> None:
        if _is_main_guard(node):
            return  # __main__ guard — skip; irrelevant to import-time behavior
        self.generic_visit(node)

    def visit_Expr(self, node: ast.Expr) -> None:
        if isinstance(node.value, ast.Call):
            if _is_syspath_mutator(node.value):
                self.has_syspath_mutation = True
            if _is_sysexit_call(node.value):
                self.has_sysexit = True
        self.generic_visit(node)


# ── Feature extraction ────────────────────────────────────────────────────────


def extract_role_features(path: Path) -> dict[str, Any]:
    """Extract role-relevant features from a single Python file.

    Returns a feature dict. On parse/IO failure, returns ``parse_error=True``.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {"parse_error": True, "error": str(exc)}

    lines = text.splitlines()
    has_shebang = bool(lines) and lines[0].startswith("#!")
    has_future_annotations = "from __future__ import annotations" in text
    has_main_guard = (
        "if __name__ == '__main__'" in text
        or 'if __name__ == "__main__"' in text
    )

    has_module_docstring = False
    has_function = False
    has_class = False

    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return {"parse_error": True, "error": str(exc)}

    if tree.body:
        node0 = tree.body[0]
        has_module_docstring = (
            isinstance(node0, ast.Expr)
            and isinstance(node0.value, ast.Constant)
            and isinstance(node0.value.value, str)
        )

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            has_function = True
        elif isinstance(node, ast.ClassDef):
            has_class = True

    checker = _ImportSafetyChecker()
    checker.visit(tree)

    has_function_or_class = has_function or has_class
    has_only_data = not has_function_or_class

    return {
        "parse_error": False,
        "has_module_docstring": has_module_docstring,
        "has_future_annotations": has_future_annotations,
        "has_shebang": has_shebang,
        "has_main_guard": has_main_guard,
        "has_function": has_function,
        "has_class": has_class,
        "has_function_or_class": has_function_or_class,
        "has_only_data": has_only_data,
        # import-safety boundary (excludes code inside functions/classes/__main__)
        "has_syspath_mutation_at_top_level": checker.has_syspath_mutation,
        # error-boundary (excludes code inside functions/classes/__main__)
        "has_sysexit_at_top_level": checker.has_sysexit,
    }


# ── Classification ────────────────────────────────────────────────────────────

# Priority order matters: runnable_entrypoint is checked first so __main__ always wins.
_CLASSIFICATION_ORDER = [
    "runnable_entrypoint",
    "unclassified",
    "declaration_module",
    "import_safe_support",
]


def classify_role(features: dict[str, Any]) -> dict[str, Any]:
    """Apply role-classification rules to a pre-extracted feature dict.

    Returns ``{"role": <str>, "reason": <str|None>}`` where *reason* is
    mandatory for ``unclassified`` and None otherwise.
    """
    if features.get("parse_error"):
        return {
            "role": "unclassified",
            "reason": f"parse error: {features.get('error', 'unknown')}",
        }

    # Priority 1: runnable_entrypoint — __main__ guard is decisive
    if features["has_main_guard"]:
        return {"role": "runnable_entrypoint", "reason": None}

    # Priority 2: unclassified — import-safety or error-boundary violation
    violations: list[str] = []
    if features["has_syspath_mutation_at_top_level"]:
        violations.append(
            "sys.path mutation at module top level (import-safety violation)"
        )
    if features["has_sysexit_at_top_level"]:
        violations.append(
            "sys.exit call at module top level (error-boundary violation)"
        )
    if violations:
        return {"role": "unclassified", "reason": "; ".join(violations)}

    # Priority 3: declaration_module — import-safe, no functions or classes
    if features["has_only_data"]:
        return {"role": "declaration_module", "reason": None}

    # Priority 4: import_safe_support — import-safe, has functions/classes
    return {"role": "import_safe_support", "reason": None}


def classify_file(path: Path) -> dict[str, Any]:
    """Classify a single Python file by role. Returns a full result dict."""
    features = extract_role_features(path)
    classification = classify_role(features)
    return {
        "file": path.name,
        "path": str(path),
        **classification,
        "features": features,
    }
