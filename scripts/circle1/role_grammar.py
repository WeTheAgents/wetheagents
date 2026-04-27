"""Role-aware V1 grammar for the scripts/ zone.

Assigns one of four role families to each Python file:

    runnable_entrypoint   — has __main__ guard, callable directly
    import_safe_support   — importable library, no top-level side effects
    declaration_module    — primarily data (constants/tables/schema), no behavior
    unclassified          — explicit reason why no role applies cleanly

For each predicate, bypass vectors and their mitigations are documented inline.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class Role(str, Enum):
    RUNNABLE_ENTRYPOINT = "runnable_entrypoint"
    IMPORT_SAFE_SUPPORT = "import_safe_support"
    DECLARATION_MODULE = "declaration_module"
    UNCLASSIFIED = "unclassified"


@dataclass
class ASTFeatures:
    has_ast_main_guard: bool
    has_functions: bool
    has_classes: bool
    has_toplevel_bare_calls: bool
    has_module_level_sys_path_mutation: bool
    has_decorator_side_effects: bool
    has_only_data_body: bool
    parse_error: bool
    parse_error_reason: str = ""


@dataclass
class RoleResult:
    path: Path
    role: Role
    reasons: list[str] = field(default_factory=list)
    bypass_notes: list[str] = field(default_factory=list)
    features: ASTFeatures | None = None


# ---------------------------------------------------------------------------
# Predicate: runnable_entrypoint
# ---------------------------------------------------------------------------

def _is_main_guard_if(node: ast.stmt) -> bool:
    """True if *node* is a `__main__` guard at the AST level.

    Recognizes both the canonical form and the reversed comparison:
      - canonical:  if __name__ == '__main__':
      - reversed:   if '__main__' == __name__:

    Both are semantically identical. Python style guides prefer the canonical
    form, but the reversed form appears in practice and must not be silently
    rejected. V1 detects both via AST normalization.

    Bypass closed: text search finds this pattern inside string literals or
    comments. AST inspection restricts the match to actual control-flow nodes.
    """
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
    # canonical: __name__ == '__main__'
    if (
        isinstance(left, ast.Name)
        and left.id == "__name__"
        and isinstance(right, ast.Constant)
        and right.value == "__main__"
    ):
        return True
    # reversed: '__main__' == __name__
    if (
        isinstance(left, ast.Constant)
        and left.value == "__main__"
        and isinstance(right, ast.Name)
        and right.id == "__name__"
    ):
        return True
    return False


def _detect_ast_main_guard(tree: ast.Module) -> bool:
    """True if `if __name__ == '__main__':` appears directly in module body."""
    return any(_is_main_guard_if(node) for node in tree.body)


# ---------------------------------------------------------------------------
# Predicate: import_safe_support
# ---------------------------------------------------------------------------

# Definitions only execute when called, not at module import time.
_OPAQUE_DEFS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def _walk_no_defs(node: ast.AST):
    """Yield *node* and all descendants, treating FunctionDef / AsyncFunctionDef /
    ClassDef as opaque: yield them but do not recurse into their bodies.

    This models import-time reachability — code inside a def/class body only
    runs when called, not when the module is imported.
    """
    yield node
    if isinstance(node, _OPAQUE_DEFS):
        return
    for child in ast.iter_child_nodes(node):
        yield from _walk_no_defs(child)


def _detect_toplevel_bare_calls(tree: ast.Module) -> list[ast.Call]:
    """Return bare Call expressions (Expr(Call(...))) reachable at import time.

    Scans module-level statements AND descends into module-level control-flow
    bodies (If, For, While, Try, With, etc.), but treats FunctionDef /
    AsyncFunctionDef / ClassDef as opaque — their bodies run only when called,
    not at import time.

    Bypass closed: the previous implementation only checked statements directly
    in tree.body. Expr(Call) nodes hidden inside module-level control flow
    (e.g. `if flag: logging.basicConfig()`, `for x in items: setup(x)`,
    `try: ...\nexcept E: recover()`) were invisible to bare-call detection and
    could make a file look import-safe when it isn't.
    """
    result = []
    for node in tree.body:
        if isinstance(node, _OPAQUE_DEFS):
            continue
        for child in _walk_no_defs(node):
            if isinstance(child, ast.Expr) and isinstance(child.value, ast.Call):
                result.append(child.value)
    return result


def _is_sys_path_mutating_call(call: ast.Call) -> bool:
    """True if *call* targets sys.path.insert / append / remove / pop."""
    func = call.func
    if not isinstance(func, ast.Attribute):
        return False
    if func.attr not in ("insert", "append", "remove", "pop"):
        return False
    obj = func.value
    if not isinstance(obj, ast.Attribute) or obj.attr != "path":
        return False
    return isinstance(obj.value, ast.Name) and obj.value.id == "sys"


def _detect_sys_path_mutation(tree: ast.Module) -> bool:
    """True if sys.path is mutated anywhere in module-level code.

    Bypass closed: a naive bare-call check misses sys.path.insert inside a
    conditional guard (e.g. `if str(root) not in sys.path: sys.path.insert(…)`).

    Fix: use _walk_no_defs to scan all module-level control flow while treating
    FunctionDef / AsyncFunctionDef / ClassDef as opaque. A sys.path call nested
    inside `if True:\n    def init():\n        sys.path.append(...)` lives inside
    a def body — not reachable at import time — and must NOT be flagged.
    """
    for node in tree.body:
        if isinstance(node, _OPAQUE_DEFS):
            continue  # path edits inside top-level def/class bodies are scoped
        for child in _walk_no_defs(node):
            if isinstance(child, ast.Call) and _is_sys_path_mutating_call(child):
                return True
    return False


def _detect_decorator_side_effects(tree: ast.Module) -> bool:
    """True if any top-level function or class has a Call-type decorator.

    A decorator like @register() is evaluated as a function call at import time,
    so it constitutes a module-level side effect. We check only top-level
    FunctionDef / AsyncFunctionDef / ClassDef nodes (not nested ones), because
    nested definitions execute only when the outer function is called, not at
    import time.

    Bypass closed: bare decorator references (`@register`, no parentheses) are
    ast.Name or ast.Attribute nodes, not ast.Call — they are not calls and do
    not trigger this predicate. Only `@register()` (with parentheses) counts.
    """
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            for decorator in node.decorator_list:
                if isinstance(decorator, ast.Call):
                    return True
    return False


# ---------------------------------------------------------------------------
# Predicate: declaration_module
# ---------------------------------------------------------------------------

def _if_test_is_call_free(node: ast.If) -> bool:
    """True if the if-test expression contains no ast.Call nodes.

    Allowed test shapes: Constant, Name, Attribute, BoolOp / UnaryOp / Compare
    composed of those leaves. Any ast.Call in the condition means the test
    itself executes code at import time.

    Example disqualified: `if pathlib.Path('x').exists():` — the `.exists()`
      call executes at import time even if the body is imports-only.
    Example allowed:      `if sys.version_info >= (3, 10):` — pure comparison,
      no function call.
    """
    return not any(isinstance(child, ast.Call) for child in ast.walk(node.test))


def _if_body_is_imports_only(node: ast.If) -> bool:
    """True if every statement in node.body and node.orelse is an import
    AND the test expression contains no ast.Call nodes.

    Bypass closed: `if pathlib.Path('x').exists(): import y` has a Call in the
    test expression — the condition itself executes at import time even though
    the body is imports-only. The fix: require _if_test_is_call_free before
    accepting the block as declaration-safe.

    Allowed test shapes: Constant, Name, Attribute, BoolOp / UnaryOp / Compare
    composed of those leaves — no ast.Call anywhere in the condition.
    """
    if not _if_test_is_call_free(node):
        return False
    all_stmts = node.body + node.orelse
    return all(isinstance(s, (ast.Import, ast.ImportFrom)) for s in all_stmts)


_PURE_DATA_TYPES = (ast.Import, ast.ImportFrom, ast.Assign, ast.AnnAssign)


def _has_only_data_body(tree: ast.Module) -> bool:
    """True if module body contains only imports, assignments, and string constants.

    Bypass closed (conditional non-import behavior): a config file may contain
    only named assignments (passes a naive "no functions" check) but also have
    an if-block with a side-effectful call inside it, e.g.:
        if ENV == 'prod':
            from prod_module import configure
            configure()          # ← behavior, not declaration
    We reject any ast.If whose body contains non-import statements.

    Bypass closed (TYPE_CHECKING guard with calls): an earlier version used
    `_is_type_checking_guard(node) OR _if_body_is_imports_only(node)` which
    allowed any `if TYPE_CHECKING:` block unconditionally. This means calls
    inside a TYPE_CHECKING guard would pass. The fix: use only
    `_if_body_is_imports_only`, which correctly handles TYPE_CHECKING guards
    (their body is imports-only in all valid uses) without the OR escape hatch.

    Known limitation: assignments like `X = os.getenv('VAR')` contain a Call
    inside the assignment value (ast.Assign.value is an ast.Call). This passes
    the data-body check. Detecting all side-effectful RHS expressions requires
    dataflow analysis and knowledge of which functions have side effects —
    infeasible statically without a type database.
    """
    for node in tree.body:
        if isinstance(node, _PURE_DATA_TYPES):
            continue
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            continue  # module docstring or bare string literal
        if isinstance(node, ast.If):
            if _if_body_is_imports_only(node):
                continue
            return False  # non-trivial conditional at module level
        return False  # any other statement type
    return True


# ---------------------------------------------------------------------------
# Feature extraction
# ---------------------------------------------------------------------------

def extract_ast_features(path: Path) -> ASTFeatures:
    """Parse *path* and compute all role predicates."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return ASTFeatures(
            has_ast_main_guard=False,
            has_functions=False,
            has_classes=False,
            has_toplevel_bare_calls=False,
            has_module_level_sys_path_mutation=False,
            has_decorator_side_effects=False,
            has_only_data_body=False,
            parse_error=True,
            parse_error_reason=str(exc),
        )

    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return ASTFeatures(
            has_ast_main_guard=False,
            has_functions=False,
            has_classes=False,
            has_toplevel_bare_calls=False,
            has_module_level_sys_path_mutation=False,
            has_decorator_side_effects=False,
            has_only_data_body=False,
            parse_error=True,
            parse_error_reason=str(exc),
        )

    has_functions = any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        for node in ast.walk(tree)
    )
    has_classes = any(isinstance(node, ast.ClassDef) for node in ast.walk(tree))

    return ASTFeatures(
        has_ast_main_guard=_detect_ast_main_guard(tree),
        has_functions=has_functions,
        has_classes=has_classes,
        has_toplevel_bare_calls=bool(_detect_toplevel_bare_calls(tree)),
        has_module_level_sys_path_mutation=_detect_sys_path_mutation(tree),
        has_decorator_side_effects=_detect_decorator_side_effects(tree),
        has_only_data_body=_has_only_data_body(tree),
        parse_error=False,
    )


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

_BYPASS_MAIN: list[str] = [
    "Bypass closed: text search for 'if __name__' matches inside strings or comments; "
    "AST restricts detection to actual module-level If nodes.",
    "V1 policy: both canonical (`if __name__ == '__main__':`) and reversed "
    "(`if '__main__' == __name__:`) comparison forms are recognized; AST normalization "
    "checks both orderings of the equality.",
]

_BYPASS_IMPORT_SAFE: list[str] = [
    "Bypass closed: Call-type decorators (@register(), @app.route('/'), etc.) on "
    "top-level functions/classes execute the decorator expression at import time. "
    "Detected by scanning FunctionDef/AsyncFunctionDef/ClassDef.decorator_list for "
    "ast.Call nodes; files with these decorators are classified unclassified, not "
    "import_safe_support.",
    "Known limitation: any 'import X' at module level may execute X's module-level "
    "side effects at import time; detecting this requires knowing X's implementation.",
]

_BYPASS_DECLARATION: list[str] = [
    "Known limitation (V1): assignments like X = os.getenv('VAR') contain a function "
    "call in the RHS expression but still pass this check. "
    "V1 tolerates this because: (a) detecting side-effectful RHS expressions requires "
    "dataflow analysis or a type database to know which functions are pure; "
    "(b) the practical impact is low — RHS-call patterns in this codebase are config "
    "reads (os.getenv, int(), str()) that are observably side-effect-free. "
    "V2 mitigation path: a side-effect-free callable allowlist (os.getenv, "
    "os.environ.get, int, str, etc.), or type-stub annotations marking callables "
    "@pure, would allow safe detection without false positives.",
    "Bypass closed: if-test expressions containing ast.Call are rejected "
    "(e.g. `if pathlib.Path('x').exists(): import y` disqualifies because the "
    "condition itself calls a function at import time). Allowed test shapes: "
    "Constant, Name, Attribute, BoolOp/UnaryOp/Compare on those leaves — no "
    "Call anywhere in the condition.",
]


def classify_role(path: Path) -> RoleResult:
    """Classify *path* into one of four role families.

    Classification order:
        1. runnable_entrypoint — has __main__ guard (checked first; many scripts
           also have helper functions, but the guard defines the primary role)
        2. declaration_module  — body is purely declarative data
        3. import_safe_support — reusable definitions, no module-level side effects
        4. unclassified        — explicit reason why no role matched cleanly
    """
    features = extract_ast_features(path)

    if features.parse_error:
        return RoleResult(
            path=path,
            role=Role.UNCLASSIFIED,
            reasons=[f"AST parse error: {features.parse_error_reason}"],
            features=features,
        )

    # 1. runnable_entrypoint
    if features.has_ast_main_guard:
        return RoleResult(
            path=path,
            role=Role.RUNNABLE_ENTRYPOINT,
            reasons=["__main__ guard detected at module level via AST"],
            bypass_notes=_BYPASS_MAIN,
            features=features,
        )

    # 2. declaration_module
    if features.has_only_data_body:
        return RoleResult(
            path=path,
            role=Role.DECLARATION_MODULE,
            reasons=["Module body contains only imports, assignments, and string constants"],
            bypass_notes=_BYPASS_DECLARATION,
            features=features,
        )

    # 3. import_safe_support
    if (
        (features.has_functions or features.has_classes)
        and not features.has_toplevel_bare_calls
        and not features.has_module_level_sys_path_mutation
        and not features.has_decorator_side_effects
    ):
        return RoleResult(
            path=path,
            role=Role.IMPORT_SAFE_SUPPORT,
            reasons=[
                "Has reusable definitions (functions or classes)",
                "No bare function calls at module top level",
                "No sys.path mutation in module-level code",
            ],
            bypass_notes=_BYPASS_IMPORT_SAFE,
            features=features,
        )

    # 4. unclassified — always with an explicit reason
    reasons: list[str] = []
    if features.has_module_level_sys_path_mutation:
        reasons.append("module-level sys.path mutation detected (inside control flow, not a bare call)")
    if features.has_toplevel_bare_calls:
        reasons.append("bare function calls at module top level (called for side effects)")
    if features.has_decorator_side_effects:
        reasons.append(
            "Call-type decorators on top-level definitions execute at import time "
            "(e.g. @register(), @app.route('/')) — import-time side effect"
        )
    if not features.has_functions and not features.has_classes and not features.has_only_data_body:
        reasons.append("no functions, no classes, and body is not purely declarative")
    if not reasons:
        reasons.append("no classifiable pattern matched")

    return RoleResult(
        path=path,
        role=Role.UNCLASSIFIED,
        reasons=reasons,
        features=features,
    )
