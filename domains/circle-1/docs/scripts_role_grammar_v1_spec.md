# scripts/ Role Grammar V1 — Signal Specification

## Problem

The original `scripts.json` template mandates a single shape for every file in `scripts/`:
module docstring + `from __future__ import annotations` + `if __name__ == '__main__'`.

This correctly describes runnable CLI tools but incorrectly rejects valid support modules that
live in `scripts/` precisely because they are imported by those tools. Files like
`io_helpers.py`, `tide_parser.py`, `ledger_ops.py`, and `economy_constants.py` fail the
one-shape template despite being well-structured Python.

## Solution: Three Role Families

| Role | Primary signal | Secondary signals |
|---|---|---|
| `runnable_entrypoint` | `has_main_guard = True` | `has_argparse`, `has_shebang` |
| `import_safe_support` | No main guard, has functions/classes, no import side effects | `has_module_docstring`, `has_future_annotations` |
| `declaration_module` | No main guard, no functions, no classes, no import side effects | `has_module_docstring`, `has_future_annotations` |
| `unclassified` | No main guard, has import side effects | — |

## Boundary Rationale

### Boundary 1: Main Guard (`has_main_guard`)

**Why chosen**: The `if __name__ == '__main__':` guard is the canonical Python signal that a
module is intended for direct execution. It is unambiguous (text match on a fixed pattern),
deterministic, and already present in the existing grammar. It becomes the primary decision
boundary because it cleanly separates the execution model: runnable tools vs importable code.

**Evidence**: Every file in `scripts/` that is meant to be invoked as `python scripts/check_*.py`
has this guard. No importable support module should have it.

**V1 Deliberate Acceptance — Reversed Comparison Shape**: The predicate also accepts the
syntactically equivalent reversed form `if "__main__" == __name__:`. Both forms are semantically
identical; Python evaluates them the same way. V1 intentionally accepts either shape because
the AST comparison check normalises both operand orders: it accepts `left=Name("__name__"),
comp=Constant("__main__")` and `left=Constant("__main__"), comp=Name("__name__")`. Treating the
reversed form as a non-entrypoint would be a false negative with no safety benefit.

### Boundary 2: Import Safety (`has_import_side_effect`)

**Why chosen**: This is the non-trivial boundary required by the task spec. A file with no main
guard that nonetheless executes code at import time (sys.path mutations, bare function calls at
module scope) cannot be classified as either `import_safe_support` or `declaration_module`
because callers cannot safely import it without triggering those side effects.

**Sub-predicates**:
- `has_sys_path_mutation`: detects `sys.path.insert` or `sys.path.append` in the file. These
  calls at module top level modify the interpreter's module search path for all subsequent
  imports in the process — a global side effect.
- `has_top_level_call`: detects bare `ast.Expr` nodes at module scope whose value is an
  `ast.Call`. These are function calls that run unconditionally on import.

**Scope clarification**: Both predicates are text/AST searches across the whole file. For files
that already have a `__main__` guard (runnable_entrypoint), the side-effect predicates are
computed but do not affect the role assignment — the main guard takes priority. This avoids
false positives for scripts that legitimately do `sys.path.insert` inside their main block or
as a top-level import fixup before `if __name__ == '__main__'` (e.g., `score_repo.py`).

**Evidence**: `pipeline_parser.py` has `if str(SRC) not in sys.path: sys.path.insert(...)` at
module top level without a main guard. Importing it modifies the interpreter's search path —
making it unsafe to import from test environments or other scripts without side effects.

**V1 Limitation — Decorator Calls**: `decorator_list` entries in `FunctionDef` and `ClassDef`
nodes are **not** scanned for `ast.Call` nodes. A decorator like `@register()` or `@app.route("/")`
executes at import time and could have real side effects. However, V1 cannot safely distinguish
these from structurally identical but side-effect-free decorators like `@dataclass()` or
`@functools.lru_cache()` without an explicit allowlist of known-safe callables. The consequence:
a file whose only import-time execution is a call-decorated function or class classifies as
`import_safe_support` (if it has other functions/classes) or `declaration_module` (if it does
not), not `unclassified`. V2 should add a `has_decorator_call_side_effect` predicate with an
allowlist of safe decorators (e.g., `staticmethod`, `classmethod`, `property`, `dataclass`,
`lru_cache`) and flag any decorator `Call` whose callable is not on the list.

**V1 Limitation — Assignment-Call Side Effects**: `has_top_level_call` only detects bare
`ast.Expr(Call)` nodes — function calls used solely for their side effect (result discarded).
Module-level assignments like `CONFIG = os.getenv("DB_URL")`, `LOGGER = logging.getLogger(__name__)`,
or `_PATTERN = re.compile(r"...")` are `ast.Assign` nodes whose value is a `Call`. The value is
captured into a name, so the AST shape differs from a bare call, and V1 does not flag them.
This is tolerated in V1 because:
1. Assignment-calls have a visible, named result — they signal that the return value matters, not
   just the side effect, which is the predominant safe pattern (e.g., `re.compile`).
2. Blanket detection without a side-effect-free callable allowlist would generate false positives
   for safe idioms (`logging.getLogger`, `os.getenv`, `re.compile`) that are nearly universal in
   real-world support modules.
V2 should introduce a `has_assignment_call_side_effect` predicate that flags assignment-calls
whose callable is **not** on an explicit safe-callable allowlist (e.g., `re.compile`, `re.sub`,
`logging.getLogger`, `os.getenv`, `os.environ.get`, `int`, `str`, `Path`).

### Boundary 3: Behavior vs. Data (`has_function OR has_class`)

**Why chosen**: Among import-safe files (no main guard, no side effects), the distinction
between a reusable library and a pure data module is whether behavior (functions, classes)
is defined. This boundary is cheap to check via AST walk and is semantically meaningful:
a `declaration_module` is a configuration artifact (can be replaced with JSON/TOML);
an `import_safe_support` module encapsulates logic.

**Evidence**:
- `economy_constants.py` (top-level only): `SPLIT_TABLE` dict, zero functions → `declaration_module`
- `io_helpers.py`: `load_json`, `save_json`, `now_iso` functions → `import_safe_support`
- `tide_ops.py`: `SPLIT_TABLE` dict + multiple helper functions → `import_safe_support`
  (presence of any function is sufficient; having both data and behavior is normal for support libs)

## Counterexample Resolution

| File | Old template verdict | V1 role | Reason |
|---|---|---|---|
| `io_helpers.py` | FAIL (no main guard) | `import_safe_support` | Has functions, no side effects |
| `tide_ops.py` | FAIL (no main guard) | `import_safe_support` | Has functions, no side effects |
| `tide_parser.py` | FAIL (no main guard) | `import_safe_support` | Has dataclasses + functions; module-level `re.compile()` calls are `ast.Assign`, not bare `ast.Expr(Call)` — V1 assignment-call limitation applies |
| `ledger_ops.py` | FAIL (no main guard) | `import_safe_support` | Has functions, `try/except ImportError` is an import not a call |
| `pipeline_parser.py` | FAIL (no main guard) | `unclassified` | `sys.path.insert` at module top level |
| `economy_constants.py` | FAIL (no main guard) | `declaration_module` | Only `SPLIT_TABLE` dict, no functions |

## What Stays Unclassified

`unclassified` is not a success bucket. A file lands there only when:
1. It has no `__main__` guard (so it's not a runnable tool), AND
2. It has a top-level side effect (so it cannot be safely imported)

The expected `unclassified` files are those that include sys.path manipulation at module level
as a workaround for import path issues — a pattern that should be refactored to use proper
package structure or conftest.py setup.

## Inventory Policy (V1)

The inventory script (`scripts/circle1/scripts_inventory.py`) uses `scripts_dir.rglob("*.py")`
to discover files, excluding `__init__.py`. This is a **deliberate V1 policy**, not an undeclared
widening of the task text's "scripts/*.py" phrase.

**Why recursive**: `scripts/` contains subdirectories (currently `circle1/`) that hold support
modules integral to the grammar system itself. A flat `scripts/*.py` glob would miss
`scripts/circle1/role_grammar.py`, `scripts/circle1/scripts_inventory.py`, and
`scripts/circle1/zone_grammar.py` — the very files that implement the grammar — producing an
inventory that fails to account for a significant portion of the scripts zone.

**Scope of inventory**: All `.py` files reachable from `scripts/` recursively, excluding package
markers (`__init__.py`). This includes `scripts/circle1/*.py`, `scripts/check_*.py`, and any
future subdirectory scripts.

**Relation to task text**: The task text said "scripts/*.py except __init__.py". V1 treats this
as stating the root intent (scan the scripts/ tree, skip init markers) rather than a literal
flat-glob restriction. A literal flat glob produces an obviously incomplete inventory that
defeats the purpose of the tool.

## Predicate Summary

| Predicate | Source | Detection method |
|---|---|---|
| `has_main_guard` | zone_grammar.py + role_grammar.py | AST: Compare(Name("__name__"), Eq, Constant("__main__")) — both operand orders accepted |
| `has_argparse` | zone_grammar.py + role_grammar.py | Text match |
| `has_shebang` | zone_grammar.py + role_grammar.py | First-line prefix |
| `has_module_docstring` | zone_grammar.py + role_grammar.py | AST: first node is string constant |
| `has_future_annotations` | zone_grammar.py + role_grammar.py | Text match |
| `has_function` | zone_grammar.py + role_grammar.py | AST walk for FunctionDef/AsyncFunctionDef |
| `has_class` | zone_grammar.py + role_grammar.py | AST walk for ClassDef |
| `has_sys_path_mutation` | role_grammar.py (new) | AST: sys.path.insert/append Call at module body |
| `has_top_level_call` | role_grammar.py (new) | AST: bare Expr(Call) at module body, after docstring |
| `has_import_side_effect` | role_grammar.py (new) | OR of above two |
| `has_decorator_call` | **NOT detected in V1** | V1 limitation — see Boundary 2 |
| `has_assignment_call_side_effect` | **NOT detected in V1** | V1 limitation — see Boundary 2 |
