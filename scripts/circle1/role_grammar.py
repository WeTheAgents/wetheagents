"""Script role grammar and file-level classifier for scripts/ v1.

Classifies Python files in ``scripts/`` into one of:

* ``runnable_entrypoint``
* ``import_safe_support``
* ``declaration_module``
* ``unclassified``

The classifier is template-driven and emits explicit predicate match sets for each
file to keep outcomes inspectable and auditable.
"""

from __future__ import annotations

import argparse
import ast
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal


RoleName = Literal[
    "runnable_entrypoint",
    "import_safe_support",
    "declaration_module",
    "unclassified",
]

Predicate = Callable[["ScriptFileShape"], bool]


@dataclass(frozen=True)
class RoleRule:
    name: str
    description: str
    required_predicates: list[str]
    forbidden_predicates: list[str]


@dataclass(frozen=True)
class RoleTemplate:
    zone: str
    path: str
    version: str
    description: str
    roles: list[RoleRule]


@dataclass(frozen=True)
class ScriptFileShape:
    path: Path
    has_main_guard: bool
    has_main_entrypoint: bool
    has_function_defs: bool
    has_class_defs: bool
    has_top_level_calls: bool
    has_top_level_sys_exit: bool
    is_import_safe: bool
    parse_error: str | None = None

    @property
    def has_no_main_guard(self) -> bool:
        return not self.has_main_guard

    @property
    def has_function_or_class_defs(self) -> bool:
        return self.has_function_defs or self.has_class_defs

    @property
    def is_declaration_shape(self) -> bool:
        return (
            self.parse_error is None
            and self.is_import_safe
            and self.has_no_main_guard
            and not self.has_function_or_class_defs
        )


@dataclass(frozen=True)
class ScriptRoleRecord:
    file: str
    role: str
    matched_predicates: list[str]
    unmatched_predicates: list[str]
    reason_if_unclassified: str | None


def _predicate_has_main_guard(shape: ScriptFileShape) -> bool:
    return shape.has_main_guard


def _predicate_has_main_entrypoint(shape: ScriptFileShape) -> bool:
    return shape.has_main_entrypoint


def _predicate_has_no_main_guard(shape: ScriptFileShape) -> bool:
    return shape.has_no_main_guard


def _predicate_is_import_safe(shape: ScriptFileShape) -> bool:
    return shape.parse_error is None and shape.is_import_safe


def _predicate_has_function_or_class_defs(shape: ScriptFileShape) -> bool:
    return shape.has_function_or_class_defs


def _predicate_is_declaration_shape(shape: ScriptFileShape) -> bool:
    return shape.is_declaration_shape


def _predicate_has_top_level_calls(shape: ScriptFileShape) -> bool:
    return bool(shape.has_top_level_calls)


def _predicate_has_top_level_sys_exit(shape: ScriptFileShape) -> bool:
    return bool(shape.has_top_level_sys_exit)


PREDICATE_REGISTRY: dict[str, Predicate] = {
    "has_main_guard": _predicate_has_main_guard,
    "has_main_entrypoint": _predicate_has_main_entrypoint,
    "has_no_main_guard": _predicate_has_no_main_guard,
    "is_import_safe": _predicate_is_import_safe,
    "has_function_or_class_defs": _predicate_has_function_or_class_defs,
    "is_declaration_shape": _predicate_is_declaration_shape,
    "has_top_level_calls": _predicate_has_top_level_calls,
    "has_top_level_sys_exit": _predicate_has_top_level_sys_exit,
}


def default_template_path(root: Path | None = None) -> Path:
    repo_root = root if root is not None else Path(__file__).resolve().parents[2]
    return repo_root / "domains" / "circle-1" / "zone_templates" / "scripts_v1_roles.json"


def load_template(path: Path) -> RoleTemplate:
    payload = json.loads(path.read_text(encoding="utf-8"))
    roles_data = payload.get("roles", [])
    roles: list[RoleRule] = []
    for role in roles_data:
        roles.append(
            RoleRule(
                name=str(role["name"]),
                description=str(role.get("description", "")),
                required_predicates=_extract_predicates(role.get("required", [])),
                forbidden_predicates=_extract_predicates(role.get("forbidden", [])),
            )
        )

    return RoleTemplate(
        zone=str(payload.get("zone", "scripts")),
        path=str(payload.get("path", "scripts/")),
        version=str(payload.get("version", "")),
        description=str(payload.get("description", "")),
        roles=roles,
    )


def _extract_predicates(items: Any) -> list[str]:
    if not items:
        return []
    names: list[str] = []
    for item in items:
        if isinstance(item, str):
            names.append(item)
        elif isinstance(item, dict):
            name = item.get("machine_check") or item.get("name")
            if name is not None:
                names.append(str(name))
        else:
            names.append(str(item))
    return names


def _is_main_guard_condition(test: ast.AST) -> bool:
    if not isinstance(test, ast.Compare):
        return False
    if len(test.ops) != 1 or len(test.comparators) != 1:
        return False
    if not isinstance(test.ops[0], ast.Eq):
        return False

    left_is_name = isinstance(test.left, ast.Name) and test.left.id == "__name__"
    right_is_main = isinstance(test.comparators[0], ast.Constant) and test.comparators[0].value == "__main__"
    if left_is_name and right_is_main:
        return True

    right_is_name = isinstance(test.comparators[0], ast.Name) and test.comparators[0].id == "__name__"
    left_is_main = isinstance(test.left, ast.Constant) and test.left.value == "__main__"
    return right_is_name and left_is_main


def _is_type_checking_guard(test: ast.AST) -> bool:
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    if isinstance(test, ast.Attribute):
        return (
            isinstance(test.value, ast.Name)
            and test.value.id == "typing"
            and test.attr == "TYPE_CHECKING"
        )
    return False


def _is_sys_exit_call(node: ast.Call) -> bool:
    func = node.func
    if isinstance(func, ast.Attribute):
        return (
            isinstance(func.value, ast.Name)
            and func.value.id == "sys"
            and func.attr == "exit"
        )
    if isinstance(func, ast.Name):
        return func.id == "exit"
    return False


def _contains_call(node: ast.AST) -> tuple[bool, bool]:
    """Return (has_call, has_sys_exit_call) for *node*.

    Function/class/lambda bodies are skipped because their inner code executes on
    runtime invocation, not during import.
    """

    has_call = False
    has_sys_exit = False
    stack: list[ast.AST] = [node]
    while stack:
        current = stack.pop()
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        if isinstance(current, ast.Call):
            has_call = True
            if _is_sys_exit_call(current):
                has_sys_exit = True
            continue
        stack.extend(ast.iter_child_nodes(current))
    return has_call, has_sys_exit


def _statement_is_import_safe(statement: ast.stmt) -> bool:
    if isinstance(
        statement,
        (
            ast.Import,
            ast.ImportFrom,
            ast.FunctionDef,
            ast.AsyncFunctionDef,
            ast.ClassDef,
            ast.Pass,
        ),
    ):
        return True

    if isinstance(statement, ast.Assign):
        has_call, _ = _contains_call(statement.value)
        return not has_call

    if isinstance(statement, ast.AnnAssign):
        has_call = False
        if statement.value is not None:
            value_call, _ = _contains_call(statement.value)
            has_call = has_call or value_call
        return not has_call

    if isinstance(statement, ast.AugAssign):
        has_call_target, _ = _contains_call(statement.target)
        has_call_value, _ = _contains_call(statement.value)
        return not (has_call_target or has_call_value)

    if isinstance(statement, ast.Expr):
        has_call, _ = _contains_call(statement.value)
        return not has_call

    if isinstance(statement, ast.If):
        if _is_main_guard_condition(statement.test) or _is_type_checking_guard(statement.test):
            return True
        test_has_call, _ = _contains_call(statement.test)
        if test_has_call:
            return False
        return all(_statement_is_import_safe(stmt) for stmt in statement.body) and all(
            _statement_is_import_safe(stmt) for stmt in statement.orelse
        )

    if isinstance(statement, ast.Try):
        return all(_statement_is_import_safe(stmt) for stmt in statement.body) and all(
            _statement_is_import_safe(stmt)
            for h in statement.handlers
            for stmt in h.body
        ) and all(_statement_is_import_safe(stmt) for stmt in statement.orelse) and all(
            _statement_is_import_safe(stmt) for stmt in statement.finalbody
        )

    return False


def _scan_main_and_import_shape(tree: ast.Module) -> tuple[bool, bool, bool, bool, bool, bool, bool]:
    has_main_guard = False
    has_main_entrypoint = False
    has_function_defs = False
    has_class_defs = False
    has_top_level_calls = False
    has_top_level_sys_exit = False
    is_import_safe = True

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            has_function_defs = True
        elif isinstance(node, ast.ClassDef):
            has_class_defs = True
        elif isinstance(node, ast.If) and _is_main_guard_condition(node.test):
            has_main_guard = True
            for stmt in node.body:
                if _contains_call(stmt)[0]:
                    has_main_entrypoint = True
                    break

        node_safe = _statement_is_import_safe(node)
        if not node_safe:
            is_import_safe = False

        node_has_call, node_has_exit = _contains_call(node)
        if node_has_call:
            has_top_level_calls = True
        if node_has_exit:
            has_top_level_sys_exit = True

    return (
        has_main_guard,
        has_main_entrypoint,
        has_function_defs,
        has_class_defs,
        has_top_level_calls,
        has_top_level_sys_exit,
        is_import_safe,
    )


def inspect_script(path: Path) -> ScriptFileShape:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return ScriptFileShape(
            path=path,
            has_main_guard=False,
            has_main_entrypoint=False,
            has_function_defs=False,
            has_class_defs=False,
            has_top_level_calls=False,
            has_top_level_sys_exit=False,
            is_import_safe=False,
            parse_error=f"I/O error reading file: {exc.strerror}",
        )

    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return ScriptFileShape(
            path=path,
            has_main_guard=False,
            has_main_entrypoint=False,
            has_function_defs=False,
            has_class_defs=False,
            has_top_level_calls=False,
            has_top_level_sys_exit=False,
            is_import_safe=False,
            parse_error=f"SyntaxError on line {exc.lineno}: {exc.msg}",
        )

    (
        has_main_guard,
        has_main_entrypoint,
        has_function_defs,
        has_class_defs,
        has_top_level_calls,
        has_top_level_sys_exit,
        is_import_safe,
    ) = _scan_main_and_import_shape(tree)

    return ScriptFileShape(
        path=path,
        has_main_guard=has_main_guard,
        has_main_entrypoint=has_main_entrypoint,
        has_function_defs=has_function_defs,
        has_class_defs=has_class_defs,
        has_top_level_calls=has_top_level_calls,
        has_top_level_sys_exit=has_top_level_sys_exit,
        is_import_safe=is_import_safe,
    )


def _build_reason(shape: ScriptFileShape) -> str | None:
    if shape.parse_error:
        return shape.parse_error

    reasons: list[str] = []
    if shape.has_main_guard and not shape.has_main_entrypoint:
        reasons.append("main guard present without callable entrypoint")
    if shape.has_top_level_calls:
        reasons.append("module-level callable side effects present")
    if shape.has_top_level_sys_exit:
        reasons.append("sys.exit callable at module level")
    if not reasons:
        reasons.append("did not match a role predicate set")
    return "; ".join(reasons)


def evaluate_predicates(shape: ScriptFileShape) -> dict[str, bool]:
    return {name: fn(shape) for name, fn in PREDICATE_REGISTRY.items()}


def classify_script_file(path: Path, template: RoleTemplate, *, root: Path | None = None) -> ScriptRoleRecord:
    shape = inspect_script(path)
    predicate_values = evaluate_predicates(shape)

    predicate_names = sorted(predicate_values.keys())
    matched_predicates = [name for name in predicate_names if predicate_values[name]]
    unmatched_predicates = [name for name in predicate_names if not predicate_values[name]]

    matching_roles: list[str] = []
    for role in template.roles:
        if all(predicate_values.get(pred, False) for pred in role.required_predicates) and not any(
            predicate_values.get(pred, False) for pred in role.forbidden_predicates
        ):
            matching_roles.append(role.name)

    if len(matching_roles) == 1:
        role = matching_roles[0]
        reason = None
    elif matching_roles:
        role = "unclassified"
        reason = f"ambiguous role match: {', '.join(sorted(matching_roles))}"
    else:
        role = "unclassified"
        reason = _build_reason(shape)

    if root is not None:
        try:
            rel_file = path.resolve().relative_to(root.resolve())
        except ValueError:
            rel_file = path
    else:
        rel_file = path

    return ScriptRoleRecord(
        file=rel_file.as_posix(),
        role=role,
        matched_predicates=matched_predicates,
        unmatched_predicates=unmatched_predicates,
        reason_if_unclassified=reason,
    )


def classify_all_scripts(root: Path, template: RoleTemplate) -> list[ScriptRoleRecord]:
    scripts_dir = root / "scripts"
    py_files = sorted(
        (
            p
            for p in scripts_dir.rglob("*.py")
            if p.is_file() and "__pycache__" not in p.parts
        ),
        key=lambda p: p.as_posix(),
    )
    return [classify_script_file(p, template, root=root) for p in py_files]


def build_inventory_payload(root: Path, template: RoleTemplate, scan_date: str) -> dict[str, Any]:
    results = classify_all_scripts(root, template)
    summary: dict[str, int] = {}
    for item in results:
        summary[item.role] = summary.get(item.role, 0) + 1

    return {
        "scan_date": scan_date,
        "zone": template.zone,
        "root": str(root),
        "template": template.path,
        "summary": summary,
        "files": [
            {
                "file": item.file,
                "role": item.role,
                "matched_predicates": item.matched_predicates,
                "unmatched_predicates": item.unmatched_predicates,
                "reason_if_unclassified": item.reason_if_unclassified,
            }
            for item in results
        ],
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scan scripts/ with role grammar v1")
    parser.add_argument("--root", default=".", help="Repo root")
    parser.add_argument(
        "--template",
        default=str(default_template_path()),
        help="Path to scripts role grammar JSON template",
    )
    parser.add_argument("--out", default=None, help="Optional output path")
    parser.add_argument("--scan-date", default="2026-04-24", help="Date tag for inventory")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = Path(args.root).resolve()
    template = load_template(Path(args.template))
    payload = build_inventory_payload(root, template, args.scan_date)
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote: {out_path}")
    else:
        print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
