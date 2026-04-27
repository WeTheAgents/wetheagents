"""V1 role grammar for the scripts/ zone.

Classifies Python files into one of three role families:
- runnable_entrypoint: has __main__ guard, designed for direct execution
- import_safe_support: importable library; no top-level side effects on import
- declaration_module: primarily constants/tables/schema data; no behavior

Files that don't cleanly fit any family are labelled 'unclassified'.

Boundaries applied (beyond docstring / future / main guard):
1. Import safety  — no top-level side effects (sys.path mutations, bare calls)
2. Behavior check — has functions or classes (separates support from declaration)

All boundary checks use AST rather than text search to avoid false positives when
this module scans itself.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

ROLES = ("runnable_entrypoint", "import_safe_support", "declaration_module", "unclassified")


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------

def _is_main_guard(node: ast.stmt) -> bool:
    """Return True if *node* is the canonical `if __name__ == '__main__':` guard."""
    if not isinstance(node, ast.If):
        return False
    test = node.test
    if not isinstance(test, ast.Compare):
        return False
    if len(test.ops) != 1 or not isinstance(test.ops[0], ast.Eq):
        return False
    left, comparators = test.left, test.comparators
    if len(comparators) != 1:
        return False
    comp = comparators[0]
    return (
        (isinstance(left, ast.Name) and left.id == "__name__"
         and isinstance(comp, ast.Constant) and comp.value == "__main__")
        or
        (isinstance(comp, ast.Name) and comp.id == "__name__"
         and isinstance(left, ast.Constant) and left.value == "__main__")
    )


def _is_sys_path_call(node: ast.AST) -> bool:
    """Return True if *node* is an actual sys.path.insert / sys.path.append call."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if not isinstance(func, ast.Attribute):
        return False
    if func.attr not in ("insert", "append"):
        return False
    if not isinstance(func.value, ast.Attribute):
        return False
    if func.value.attr != "path":
        return False
    return isinstance(func.value.value, ast.Name) and func.value.value.id == "sys"


# ---------------------------------------------------------------------------
# Feature detection
# ---------------------------------------------------------------------------

def extended_file_features(path: Path) -> dict[str, Any]:
    """Detect shape features needed for V1 role classification.

    Superset of zone_grammar.file_features; adds import-safety signals.
    All major signals are AST-based to avoid false positives when this module
    scans itself.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}

    lines = text.splitlines()
    has_shebang = bool(lines) and lines[0].startswith("#!")
    # Text search for import-statement level features is safe: these strings
    # don't appear as literals in this file itself.
    has_future = "from __future__ import annotations" in text

    has_docstring = False
    has_class = False
    has_function = False
    function_count = 0
    has_main_guard = False
    has_argparse = False
    has_top_level_call = False      # bare Expr(Call) at module level, outside main guard
    has_sys_path_mutation = False   # actual sys.path.insert/append call outside main guard

    try:
        tree = ast.parse(text)

        # Module docstring: first body node is a string-constant expression
        if tree.body:
            node0 = tree.body[0]
            has_docstring = (
                isinstance(node0, ast.Expr)
                and isinstance(node0.value, ast.Constant)
                and isinstance(node0.value.value, str)
            )

        # Walk full tree for class/function presence and argparse usage
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                has_class = True
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                has_function = True
                function_count += 1
            # argparse detection: look for an ast.Attribute whose attr is
            # ArgumentParser and whose value is a Name 'argparse'
            if (
                isinstance(node, ast.Attribute)
                and node.attr == "ArgumentParser"
                and isinstance(node.value, ast.Name)
                and node.value.id == "argparse"
            ):
                has_argparse = True

        # Scan top-level body statements for main guard, side-effect calls
        for i, stmt in enumerate(tree.body):
            # Docstring: skip (already handled above)
            if i == 0 and isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
                continue

            if _is_main_guard(stmt):
                has_main_guard = True
                continue  # mutations inside the main guard are NOT side effects

            # Bare expression-call at module top level
            if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
                has_top_level_call = True

            # sys.path mutation in this top-level statement.
            # Skip module-level function/class defs: a function that internally
            # calls sys.path.insert is not a side effect on import.
            if not isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                for node in ast.walk(stmt):
                    if _is_sys_path_call(node):
                        has_sys_path_mutation = True
                        break
            # V1 limitation: decorator_list of FunctionDef/ClassDef is NOT scanned for
            # ast.Call nodes. @register() executes at import time but cannot be safely
            # distinguished from benign @dataclass() without an allowlist. See spec: Boundary 2.

    except SyntaxError:
        pass

    has_import_side_effect = has_sys_path_mutation or has_top_level_call

    return {
        "has_module_docstring": has_docstring,
        "has_future_annotations": has_future,
        "has_main_guard": has_main_guard,
        "has_shebang": has_shebang,
        "has_argparse": has_argparse,
        "has_class": has_class,
        "has_function": has_function,
        "function_count": function_count,
        "has_top_level_call": has_top_level_call,
        "has_sys_path_mutation": has_sys_path_mutation,
        "has_import_side_effect": has_import_side_effect,
    }


# ---------------------------------------------------------------------------
# Role classification
# ---------------------------------------------------------------------------

def classify_role(features: dict[str, Any]) -> dict[str, Any]:
    """Assign a role label to a file given its computed features.

    Priority order:
      1. runnable_entrypoint — __main__ guard (even if side effects present)
      2. unclassified        — no main guard but has import side effects
      3. declaration_module  — no functions, no classes, no side effects
      4. import_safe_support — has functions/classes, no side effects

    Returns a dict with:
      role              : one of ROLES
      matched_predicates: list of predicate names that drove the assignment
      failure_reasons   : list of reasons when role is unclassified or ambiguous
    """
    matched: list[str] = []
    failures: list[str] = []

    # 1. Runnable entrypoint — main guard wins regardless of other signals
    if features.get("has_main_guard"):
        matched.append("has_main_guard")
        if features.get("has_argparse"):
            matched.append("has_argparse")
        return {"role": "runnable_entrypoint", "matched_predicates": matched, "failure_reasons": failures}

    matched.append("no_main_guard")

    # 2. Unclassified — has side effects but no main guard
    if features.get("has_import_side_effect"):
        if features.get("has_sys_path_mutation"):
            failures.append("has_sys_path_mutation: mutates sys.path at module level")
        if features.get("has_top_level_call"):
            failures.append("has_top_level_call: bare function call at module top level")
        return {"role": "unclassified", "matched_predicates": matched, "failure_reasons": failures}

    matched.append("no_import_side_effect")

    # 3. Declaration module — data only, no behavior
    if not features.get("has_function") and not features.get("has_class"):
        matched.append("no_functions_no_classes")
        return {"role": "declaration_module", "matched_predicates": matched, "failure_reasons": failures}

    # 4. Import-safe support — behavior, importable
    matched.append("has_functions_or_classes")
    return {"role": "import_safe_support", "matched_predicates": matched, "failure_reasons": failures}


def classify_file(path: Path) -> dict[str, Any]:
    """Full per-file classification: features + role assignment."""
    features = extended_file_features(path)
    role_result = classify_role(features)
    return {
        "file": str(path),
        "role": role_result["role"],
        "matched_predicates": role_result["matched_predicates"],
        "failure_reasons": role_result["failure_reasons"],
        "features": features,
    }
