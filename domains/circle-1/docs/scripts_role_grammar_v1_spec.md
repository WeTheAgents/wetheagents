# scripts/ Role Grammar V1 — Specification

## Overview

This specification defines a role-aware grammar for Python files in `scripts/`.
The existing zone template (`scripts.json`) treats all scripts as a single shape
(runnable + module_docstring + future_annotations). V1 refines this into three
role families that reflect how files are actually used, plus an explicit
`unclassified` bucket for files that don't fit cleanly.

**Implementation**: `scripts/circle1/role_grammar.py`  
**Machine-checkable spec**: `domains/circle-1/zone_templates/scripts_v1_roles.json`  
**Inventory harness**: `scripts/circle1/scripts_inventory.py`

---

## Role Families

### 1. `runnable_entrypoint`

A file whose primary purpose is to be invoked directly from the command line.

**Defining predicate**: `__main__` guard at module body level, detected via AST
(not text search). V1 recognizes both comparison orderings:
- canonical: `if __name__ == '__main__':`
- reversed:  `if '__main__' == __name__:`

Both are semantically identical. AST normalization checks both orderings; neither
is rejected silently. See Bypass 4 for the explicit decision and test.

**Canonical examples**: `check_invariant.py`, `score_repo.py`, `tide.py`

**Shape expectations**: module docstring, `__future__` annotations, main guard,
usually `argparse` or a `main()` function.

---

### 2. `import_safe_support`

A library file providing reusable functions or classes. Safe to import without
triggering module-level side effects.

**Defining predicates** (all must hold):
- No `__main__` guard
- Has at least one function or class definition
- No bare function calls at module top level (`ast.Expr(ast.Call(...))`)
- No `sys.path` mutation in module-level code
- No Call-type decorators on top-level definitions (see Bypass 5)

**Canonical examples**: `io_helpers.py`, `tide_ops.py`, `tide_parser.py`, `ledger_ops.py`

---

### 3. `declaration_module`

A file that is primarily data: constants, lookup tables, schema definitions.
No function or class definitions. No behavior.

**Defining predicate**: module body contains only imports, assignments, and
string constants. Non-trivial if-blocks (containing non-import statements)
disqualify the file. TYPE_CHECKING guards are allowed.

**Canonical examples**: `economy_constants.py`

---

### 4. `unclassified`

A file that does not fit cleanly into any of the three role families.
`unclassified` is NOT a catch-all — every result carries an explicit reason string.

**Canonical example**: `pipeline_parser.py` (has reusable functions but mutates
`sys.path` at module level inside a conditional guard, making it not import-safe).

---

## Classification Algorithm

Priority order (first match wins):

```
1. has_ast_main_guard                         → runnable_entrypoint
2. has_only_data_body                         → declaration_module
3. (has_functions OR has_classes)
   AND NOT has_toplevel_bare_calls
   AND NOT has_module_level_sys_path_mutation
   AND NOT has_decorator_side_effects          → import_safe_support
4. (everything else)                          → unclassified + reason
```

The ordering reflects role exclusivity: a file with a `__main__` guard is
primarily a runnable tool even if it also defines helper functions.

---

## Bypass Analysis and Mitigations

This section documents every identified bypass vector — inputs that would fool
a naive classifier — and whether the implementation closes or documents the gap.

### Bypass 1: `__main__` detection via text search

**Attack**: A file contains the string `if __name__ == '__main__':` inside a
docstring, multi-line string, or comment. Text search returns a false positive
and classifies the file as `runnable_entrypoint`.

**Example**:
```python
EXAMPLE = """
if __name__ == '__main__':
    print("this is documentation, not a guard")
"""

def helper():
    return EXAMPLE
```

**Fix**: AST-based detection. Only `ast.If` nodes directly in `module.body` with
the exact structural pattern `Compare(Name('__name__'), Eq(), Constant('__main__'))`
qualify. String and comment content never appears as AST nodes.

**Status**: CLOSED

---

### Bypass 2: `sys.path` mutation inside a conditional guard

**Attack**: A file uses `if str(root) not in sys.path: sys.path.insert(0, str(root))`
at module level. This is an `ast.If` — not an `ast.Expr(ast.Call(...))` — so a
bare-call check alone would miss it and incorrectly classify the file as
`import_safe_support`.

**Example**:
```python
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))  # ← inside if, not a bare call

def parse(data: str) -> dict:
    return {}
```

**Fix**: `_detect_sys_path_mutation` walks all module-level control flow nodes
(including nested `ast.If` bodies), skipping function and class bodies. Any
`sys.path.insert/append/remove/pop` call anywhere in module-level code triggers
the `has_module_level_sys_path_mutation` flag, disqualifying `import_safe_support`.

**Status**: CLOSED — `pipeline_parser.py` is correctly classified `unclassified`

---

### Bypass 3: Declaration module with conditional non-import behavior

**Attack**: A file contains only named assignments except for one `if`-block
that includes a function call. A naive "no functions" check would classify it
as `declaration_module` because there are no top-level `def` statements.

**Example**:
```python
from __future__ import annotations
import os
ENVIRONMENT = "dev"
if ENVIRONMENT == "production":
    from prod_module import configure
    configure()          # ← behavior inside if, not a definition
CONSTANT = 42
```

**Fix**: `_has_only_data_body` examines every module-level `ast.If` node. If the
if-body contains any statement that is not an import, the file fails the
data-body check. Only two exceptions are allowed: `if TYPE_CHECKING:` (standard
stub-import pattern) and if-blocks whose entire body consists solely of imports.

**Status**: CLOSED

---

### Bypass 4: Reversed `__main__` guard (Point 2 — V1 explicit decision)

**Question**: `if '__main__' == __name__:` is semantically identical to the
canonical form but has the operands reversed. Should V1 recognize it?

**Decision**: V1 **recognizes** the reversed form. Rejecting it silently would
produce a false negative — a runnable script misclassified as `import_safe_support`
or `unclassified`. The canonical form is preferred by style guides, but the reversed
form appears in the wild and must not be a silent failure mode.

**Implementation**: `_is_main_guard_if` checks both orderings: `Name('__name__')
Eq Constant('__main__')` and `Constant('__main__') Eq Name('__name__')`.

**Status**: CLOSED — `TestRunnableEntrypoint::test_reversed_main_guard_recognized`
and `test_reversed_guard_single_quotes` pin this behavior.

---

### Bypass 5: Decorator-time side effects (Point 1 — DETECTED)

**Attack**: A module uses `@register()` or `@app.route('/path')` on a top-level
function or class. These are evaluated as function calls at import time, mutating
the registry/router state. A classifier that only checks for bare `ast.Expr(Call)`
statements misses these because the call is in a decorator position, not a
standalone expression.

**Example**:
```python
@register("handler")
def handle_event(event: dict) -> None:
    ...
```

When Python processes this at import time, it calls `register("handler")` — a
side-effectful operation — before calling the result as a decorator.

**Fix**: `_detect_decorator_side_effects` walks `module.body` checking
`FunctionDef.decorator_list` and `ClassDef.decorator_list` for `ast.Call` nodes.
Any top-level definition with a Call-type decorator sets
`has_decorator_side_effects=True`, disqualifying `import_safe_support`.

**Scope**: Only top-level function/class definitions are scanned. Decorators on
methods nested inside a class body are a separate concern — method decoration is
common (`@staticmethod`, `@property`) and scoping it correctly would require
distinguishing pure decorators from effectful ones.

**V1 limitation**: Bare decorator references without parentheses (`@staticmethod`,
`@property`, `@module.decorator`) are `ast.Name` / `ast.Attribute` nodes, not
`ast.Call`. They do not trigger this predicate. This is correct — a bare reference
is just a name lookup, not a function call, and produces no side effect.

**Status**: CLOSED — `TestImportSafeSupport::test_bypass_decorator_call_disqualifies_import_safe`,
`test_decorator_bare_name_still_import_safe`, `test_decorator_call_on_class_disqualifies`.
ASTFeatures unit tests: `TestASTFeatures::test_decorator_call_detected`,
`test_decorator_bare_name_not_detected`, `test_decorator_call_inside_function_not_detected`.

---

## Self-Roast Findings (Post-Implementation)

Three bypass vectors were enumerated after initial implementation. One was fixed
during self-roast; two are documented as known limitations.

### Roast Finding 1: TYPE_CHECKING guard with calls (FIXED)

**Attack**: The original implementation used `_is_type_checking_guard(node) OR
_if_body_is_imports_only(node)` in `_has_only_data_body`. This allowed any
`if TYPE_CHECKING:` block unconditionally — so calls hidden inside it would
pass and a file would be misclassified as `declaration_module`:
```python
if TYPE_CHECKING:
    from some_module import configure
    configure()   # call inside TYPE_CHECKING — should disqualify
CONSTANT = 42
```

**Fix**: Removed the OR escape hatch. Now only `_if_body_is_imports_only(node)`
is used, which correctly handles TYPE_CHECKING guards (legitimate use always has
imports-only body) without the bypass path.

**Status**: FIXED — see `TestDeclarationModule::test_bypass_type_checking_guard_with_calls`

### Roast Finding 2: Unusual `__main__` comparison via variable (NOT FIXED)

**Attack**: `if __name__ == _MAIN_CONSTANT:` where `_MAIN_CONSTANT = "__main__"`.
Our AST check requires `test.comparators[0]` to be `ast.Constant(value="__main__")`.
A `Name` reference passes the structural check but fails the constant-value check,
causing a false negative (file not classified as runnable_entrypoint).

**Why not fixed**: This pattern is non-standard. Python style guides and all files
in this codebase use the literal string directly. Tracking variable values requires
dataflow analysis. The practical risk is minimal.

### Roast Finding 3: Dynamic sys.path mutation via getattr (NOT FIXED)

**Attack**: `getattr(sys, "path").insert(0, "src")` — dynamic attribute access
that is semantically equivalent to `sys.path.insert(0, "src")`. Our
`_is_sys_path_mutating_call` checks for `ast.Attribute` on `sys.path` directly;
a `getattr` call produces `ast.Call(func=ast.Name("getattr"), ...)`, which does
not match the structural pattern.

**Why not fixed**: Dynamic attribute access is not used in any file in this repo.
The pattern is obfuscated and would be caught by a code reviewer. Adding detection
for all dynamic access patterns would significantly increase complexity.

---

## Known Limitations (Not Fixed)

### Limitation 1: Import-time side effects from imported modules

**Vector**: A file is perfectly import-safe by our predicates — no bare calls,
no sys.path mutation — but it imports module `X` whose own module-level code
has side effects (e.g., `import side_effectful_module`).

**Example**:
```python
from __future__ import annotations
import some_module_with_side_effects  # triggers side effects at import

def helper():
    return "result"
```

**Why not fixed**: Detecting this requires knowing the implementation of every
imported module. This is not statically possible without a call graph or type
database. The classifier correctly identifies the file as `import_safe_support`
based on its own code — the limitation is documented in `bypass_notes`.

**Mitigation**: Code reviewers should audit third-party and internal imports of
support modules for side-effectful dependencies.

---

### Limitation 2: Assignments with function calls in RHS (Point 3 — V1 documented)

**Vector**: A declaration-like file has assignments where the right-hand side
calls a function, e.g. `DB_URL = os.getenv("DATABASE_URL", "sqlite:///dev.db")`.
The body is still classified as `has_only_data_body` because the call is inside
an `ast.Assign` node, not an `ast.Expr` node.

**Example**:
```python
from __future__ import annotations
import os
DB_URL = os.getenv("DATABASE_URL", "sqlite:///dev.db")
TIMEOUT = int(os.environ.get("TIMEOUT", "30"))
```

This is classified as `declaration_module` despite calling functions.

**Why tolerated in V1**:

1. **Dataflow analysis required.** Determining whether `os.getenv(...)` has
   observable side effects requires knowing the function's contract — information
   not available from the AST alone without a type database or call-graph analysis.

2. **Low practical impact.** RHS-call patterns in this codebase are config reads
   (`os.getenv`, `os.environ.get`, `int()`, `str()`). These functions read
   environment state but do not mutate shared mutable state, making them
   observably side-effect-free for classification purposes.

3. **Heuristic blacklists are fragile.** An allowlist approach (permit
   `os.getenv`, reject `subprocess.run`) would miss unlisted pure functions,
   produce false positives, and require ongoing maintenance.

**V2 mitigation path**:

- **Side-effect-free callable allowlist**: Enumerate known-pure functions
  (`os.getenv`, `os.environ.get`, `int`, `str`, `float`, `bool`, `len`, etc.)
  and permit only those in assignment RHS positions.
- **Type-stub annotations**: Extend the PEP 526 / stub ecosystem with a
  `@pure` marker; classifiers check stubs rather than maintaining their own
  allowlist.
- **Restrict `declaration_module` to literal-only RHS**: Accept only `ast.Constant`,
  `ast.List`, `ast.Dict`, `ast.Tuple` in assignment values — effectively limiting
  the role to true compile-time constants. This is the safest V2 option but
  would reclassify some legitimate config modules.

**Test pinning the limitation**: `TestDeclarationModule::test_known_limitation_assignment_with_call`
asserts that `X = os.getenv(...)` classifies as `declaration_module` and that
`bypass_notes` documents the gap. This test is a canary: if V2 changes this
behavior, the test will fail and force an explicit decision.

---

## V1 Inventory Policy (Point 4)

### Scan scope: recursive

**Background**: The original task brief said `scripts/*.py except __init__.py`.
The V1 harness (`scripts/circle1/scripts_inventory.py`) scans recursively using
`scripts_dir.rglob("*.py")`.

**Deliberate decision**: Recursive scanning is the correct V1 policy, not an
accident. The `scripts/` directory already contains classifiable Python files
in subdirectories (`scripts/circle1/role_grammar.py`, `scripts/circle1/zone_grammar.py`,
etc.). A flat scan would silently skip these files, creating a gap between what
the grammar covers and what gets reported.

**Exclusions**: `__init__.py` files at any nesting level are excluded. These are
package markers, not scripts, and carry no role within the grammar.

**Implication**: Any Python file added anywhere under `scripts/` — at root level
or in a subdirectory — is automatically included in the next inventory run.
Adding a new subdirectory under `scripts/` requires no harness changes.

**Test pinning the policy**: `TestInventoryPolicy::test_recursive_scan_includes_subdirectory_files`
asserts that files in a subdirectory of `scripts/` appear in the inventory.
`test_init_py_excluded_at_all_levels` asserts that `__init__.py` files are
excluded at all nesting levels.

---

## Relation to Existing `scripts.json` Template

The V1 roles grammar is additive: `scripts.json` defines the dominant shape for
the zone as a whole (module_docstring + future_annotations + main_guard). V1
refines this by acknowledging that not all files in `scripts/` are runnable —
`io_helpers.py`, `ledger_ops.py`, `economy_constants.py` etc. serve as support
libraries and data modules respectively.

The `declared` score in `score_module_grammar` will rise from 1 (ad hoc) to ≥3
(repeatable) once `scripts_v1_roles.json` is registered as the canonical template.
The `exercised` score will reflect conformance across all three role families.
