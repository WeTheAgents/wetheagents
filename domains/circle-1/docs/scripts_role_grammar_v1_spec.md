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

**Defining predicate**: `if __name__ == '__main__':` at module body level, detected
via AST (not text search).

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
1. has_ast_main_guard                       → runnable_entrypoint
2. has_only_data_body                       → declaration_module
3. (has_functions OR has_classes)
   AND NOT has_toplevel_bare_calls
   AND NOT has_module_level_sys_path_mutation → import_safe_support
4. (everything else)                        → unclassified + reason
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

### Limitation 2: Assignments with function calls in RHS

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

**Why not fixed**: Detecting all side-effectful expressions in assignment values
requires dataflow analysis — knowing which functions have observable side effects.
Simple heuristics (blacklist `os.getenv`, `subprocess.run`, etc.) would produce
false positives on pure functions and miss unlisted ones.

**Mitigation**: The practical impact is low. Files that use `os.getenv` in
assignments are typically config modules, which are a reasonable subset of
`declaration_module`. The `bypass_notes` on every `declaration_module` result
documents this gap explicitly.

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
