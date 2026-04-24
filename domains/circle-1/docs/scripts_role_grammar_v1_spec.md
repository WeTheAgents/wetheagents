# scripts/ Role Grammar V1 — Spec Rationale

## Purpose

The existing `scripts.json` zone template treats all files in `scripts/` as a single shape: module_docstring + future_annotations + main_guard. This works for the dominant shape (122/131 files) but is wrong for the remaining 9 files — four reusable libraries, one constants module, one import-safety violator, and three `__init__.py` adjacents.

A single template can't express "this file should NOT have a main guard." Role grammar V1 replaces one template with four mutually exclusive role families.

## The Four Roles

### 1. `runnable_entrypoint`

**What it is:** A file callable directly with `python scripts/foo.py`. Has a `if __name__ == '__main__'` guard.

**Dominant pattern in repo:** 125 of 131 non-init files (95%).

**Key signal:** `has_main_guard`. This is the only required check. No other features matter for classification — a runnable entrypoint may have helper functions, constants, argparse usage, and sys.path bootstrapping. Those are expected.

**Why sys.path bootstrapping doesn't disqualify it:** When a script uses `sys.path.insert` at module level to locate siblings (e.g. `score_repo.py`), it's accepting the consequence that importing it would mutate sys.path. That's acceptable for a script not intended to be imported.

---

### 2. `import_safe_support`

**What it is:** A library module — functions and/or classes that other scripts import. No `__main__` guard. No top-level side effects on import.

**Examples:** `io_helpers.py`, `tide_ops.py`, `tide_parser.py`, `ledger_ops.py`.

**Required:** At least one function or class definition.

**Excluded:** `__main__` guard, sys.path mutation outside `__main__`, sys.exit outside `__main__`, and `has_only_data` (which would make it `declaration_module` instead).

**Non-obvious case — `ledger_ops.py`:** Contains a top-level `try/except` import:
```python
try:
    from scripts.economy_constants import SPLIT_TABLE
except ModuleNotFoundError:
    from economy_constants import SPLIT_TABLE
```
This IS import-safe. A try/except import is read-only — it doesn't mutate interpreter state (sys.path, sys.exit, file I/O). The import-safety boundary only flags `sys.path.insert/append` and `sys.exit` calls.

---

### 3. `declaration_module`

**What it is:** A module that is primarily data: constants, lookup tables, schema definitions. No function or class definitions anywhere in the file. No `__main__` guard.

**Example:** `economy_constants.py` — just `SPLIT_TABLE: dict[int, list[int]] = {...}`.

**Required:** `has_only_data` — no `FunctionDef` or `ClassDef` anywhere in the AST.

**Design note:** The `has_only_data` check looks at the full AST, not just module top level. A file with `TABLE = {1: lambda x: x}` would have a `Lambda` node but not a `FunctionDef` — that file would still be `declaration_module`. This is intentional: lambdas in data structures are data, not reusable behavior.

---

### 4. `unclassified`

**What it is:** A file that fails an import-safety boundary, preventing clean membership in the other three roles. Requires an explicit machine-generated reason.

**NOT a catch-all:** A file should only land here if a specific boundary fires. The classifier would need to be modified to extend the set of triggering conditions.

**Current example:** `pipeline_parser.py` — sys.path mutation at module top level without `__main__` guard:
```python
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))  # line 15 — fires on every import
```

**Refactor path:** Move the sys.path bootstrapping inside `if __name__ == '__main__'` (converting to a runnable_entrypoint), or remove it and rely on the caller to configure sys.path (keeping import_safe_support).

---

## Boundary Design Decisions

### Import-safety boundary

Detects `sys.path.insert(...)` or `sys.path.append(...)` at module load time.

**Why only sys.path?** sys.path mutation is the most common and consequential import-time side effect in this codebase. It changes which modules can be found for ALL subsequent imports in the process — a global, persistent state mutation.

**Implementation constraint:** The detector must NOT flag `sys.path` mutations inside function bodies or class bodies. A `sys.path.insert` inside `main()` or `setup()` only runs when that function is called — not on import. The `_ImportSafetyChecker` AST visitor implements this by stopping descent at `FunctionDef` and `AsyncFunctionDef` nodes.

### Error-boundary

Detects `sys.exit(...)` or `SystemExit(...)` at module load time (outside function/class bodies and outside `__main__` guard).

**Why this matters:** A `sys.exit` at module top level terminates the Python process on import. This is a severe violation — it makes the module dangerous to import in any automated pipeline.

**Same exclusion logic applies:** The `_ImportSafetyChecker` visitor also stops descent into function bodies, so `sys.exit` inside `main()` or any other function is NOT flagged.

**Current state:** No files in the repo currently trigger this boundary. The boundary is implemented to catch future regressions.

### Data-purity boundary

The distinction between `declaration_module` and `import_safe_support` is the presence of function/class definitions.

`tide_ops.py` has both a constant (`SPLIT_TABLE`) AND a function (`fib`). It classifies as `import_safe_support` because it has behavior. `economy_constants.py` has only data. The presence of ANY function or class → import_safe_support.

---

## Classification Order (Priority)

1. `runnable_entrypoint` — `__main__` guard is decisive. Checked first because the other rules are irrelevant for runnable scripts.
2. `unclassified` — import-safety or error-boundary violation. Must be checked before declaration/support to prevent masking violations.
3. `declaration_module` — no functions/classes, import-safe.
4. `import_safe_support` — has functions/classes, import-safe. Residual.

---

## Current Inventory Snapshot (2026-04-24)

| Role | Count | Files |
|------|-------|-------|
| `runnable_entrypoint` | 125 | All `check_*.py`, `audit_*.py`, `genome_*.py`, etc. |
| `import_safe_support` | 4 | `io_helpers.py`, `ledger_ops.py`, `tide_ops.py`, `tide_parser.py` |
| `declaration_module` | 1 | `economy_constants.py` |
| `unclassified` | 1 | `pipeline_parser.py` (sys.path mutation, no `__main__`) |

Total: 131 files (excluding `__init__.py`).

---

## Relation to Existing Zone Grammar

The existing `scripts.json` template (Task #780) declares the dominant shape: `module_docstring + future_annotations + main_guard`. Role grammar V1 extends this by:

1. Acknowledging that not all scripts/ files share the dominant shape
2. Formalizing the minority roles as first-class citizens
3. Providing machine-checkable rules for each role that can drive automated conformance scoring

The role grammar does NOT replace the existing template — it operates at a different level of abstraction. The existing template scores _conformance_ of the dominant shape. The role grammar scores _classification_ across all four shapes.

A future iteration could integrate role classification into the `score_module_grammar` function so that per-role conformance rates are reported (e.g., "4/4 import_safe_support files pass their role checks").

---

## Artifacts

| File | Purpose |
|------|---------|
| `scripts/circle1/role_grammar.py` | Core classifier — feature extraction + `classify_file()` |
| `scripts/circle1/scripts_inventory.py` | Scanner harness — CLI tool to classify all scripts/*.py |
| `domains/circle-1/zone_templates/scripts_v1_roles.json` | Machine-checkable role spec |
| `scripts/inventory_scripts_20260424.json` | Deterministic inventory output (2026-04-24) |
| `tests/test_scripts_role_grammar.py` | 24 tests covering all roles + boundary conditions |
