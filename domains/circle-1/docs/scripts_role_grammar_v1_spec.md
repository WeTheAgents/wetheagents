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
| `tide_parser.py` | FAIL (no main guard) | `import_safe_support` | Has dataclasses + functions; module-level `re.compile()` calls are assignments (`ast.Assign`), not bare expressions |
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

## Predicate Summary

| Predicate | Source | Detection method |
|---|---|---|
| `has_main_guard` | zone_grammar.py + role_grammar.py | Text match |
| `has_argparse` | zone_grammar.py + role_grammar.py | Text match |
| `has_shebang` | zone_grammar.py + role_grammar.py | First-line prefix |
| `has_module_docstring` | zone_grammar.py + role_grammar.py | AST: first node is string constant |
| `has_future_annotations` | zone_grammar.py + role_grammar.py | Text match |
| `has_function` | zone_grammar.py + role_grammar.py | AST walk for FunctionDef/AsyncFunctionDef |
| `has_class` | zone_grammar.py + role_grammar.py | AST walk for ClassDef |
| `has_sys_path_mutation` | role_grammar.py (new) | Text match for sys.path.insert/append |
| `has_top_level_call` | role_grammar.py (new) | AST: Expr(Call) at module body, after docstring |
| `has_import_side_effect` | role_grammar.py (new) | OR of above two |
