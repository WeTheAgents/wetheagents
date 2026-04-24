# Scripts role grammar v1 spec

This document defines `scripts/` role classification rules used by
`scripts/circle1/role_grammar.py` and the inventory harness.

## Roles

### `runnable_entrypoint`

File is classified here when it has a `__main__` guard with a callable body.
The role is intentionally narrow so only directly executable scripts land here.

### `import_safe_support`

File is classified as reusable support when it is import-safe, contains reusable
logic (`def`/`class`), and has no `__main__` entrypoint.

### `declaration_module`

File is classified here when it has no `__main__` guard and is import-safe,
with a data/schema/constant-first shape (no top-level helper definitions).

### `unclassified`

Files that do not match exactly one role are explicitly labeled `unclassified`
with a reason string. This is explicit and not a fallback success bucket.

## Why each predicate exists

- `has_main_entrypoint` — required to avoid counting modules that only have a
  `__main__` label but no callable path.
- `has_no_main_guard` — prevents runnable-style files from being treated as
  import helpers or declarations.
- `is_import_safe` — enforces import-time boundary checks:
  no module-level function calls in executed paths, and no `sys.exit`-style
  top-level termination paths.
- `has_function_or_class_defs` — identifies behavioral modules (`import_safe_support`).
- `is_declaration_shape` — identifies constant/schema modules where runtime
  behavior is intended to be importable data.
- `has_top_level_calls` — captured for auditing and ambiguity reporting when a
  file falls into `unclassified`.
- `has_top_level_sys_exit` — explicit marker for `sys.exit` at module level.

## Output semantics

Each file emits:

- `file`
- `role`
- `matched_predicates`
- `unmatched_predicates`
- `reason_if_unclassified`

`unclassified` entries must include `reason_if_unclassified`.
