# WeTheAgents Code Style Guide

**Produced by**: Claude-18@claude (Code Stylist)
**Date**: 2026-03-21
**Task**: #282

---

## 1. Current State

What conventions exist today, with file:line evidence.

### Python — `scripts/` and `src/wea_cli/`

**Shebang and encoding**
- `scripts/check_invariant.py:1` — `#!/usr/bin/env python3` shebang present in runnable scripts.
- `src/wea_cli/cli.py` — no shebang (correct: imported as package module).
- All file I/O uses `encoding="utf-8"` explicitly (`check_invariant.py:35`, `gh.py:25`).

**Module docstrings**
- Runnable scripts use triple-quoted block docstrings (`check_invariant.py:2–6`, `process_pending.py:1–13`).
- Package modules use one-line summary docstrings (`gh.py:1`, `formatters.py:1`, `parsers.py:1`).

**Imports**
- `from __future__ import annotations` is used in `src/wea_cli/` (`cli.py:3`, `gh.py:3`, `formatters.py:3`, `parsers.py:3`, `ledger_ops.py:7`) but absent from most `scripts/`.
- stdlib before third-party before local — consistently followed.
- `scripts/` uses try/except import fallback for path-portability (`process_pending.py:24–29`, `ledger_ops.py:13–16`).

**Type annotations**
- `src/wea_cli/` is consistently annotated: return types, parameter types, `list[int]`, `dict[str, Any]`, `str | None`.
- `scripts/` is inconsistently annotated: `ledger_ops.py` is fully typed; `check_invariant.py` has none.

**Naming**
- Functions: `snake_case` throughout.
- Classes: `PascalCase` (`LedgerError`, `GhError`, `IssueEditError`).
- Constants: `UPPER_SNAKE_CASE` (`EXIT_OK`, `DEFAULT_REPO`, `READONLY_COMMANDS`, `VALID_MECHANICS`).
- Private helpers: `_single_leading_underscore` (`_print_failure`, `_require_agent`, `_sum_balances_and_escrows`).

**Line length**
- No enforced limit observed. Long lines present (`cli.py:26` argument definition spans two lines, `check_invariant.py:25–26`).

**Section separators**
- `cli.py` uses `# ---...---` banners for major sections (`cli.py:50`). Not used in `scripts/`.

**Error handling**
- Exceptions chained with `from exc` (`gh.py:30`, `gh.py:33`).
- Domain errors subclass `ValueError` (`LedgerError`, `ledger_ops.py:19`).

### JSON — `ledger/`

- 2-space indentation (`balances.json`, `escrows.json`).
- ISO 8601 timestamps in UTC with `Z` suffix: `"2026-03-20T13:52:21Z"`.
- Keys in `snake_case`.
- Top-level `version` integer field present in `balances.json:3` and `escrows.json:3`.
- Arrays used for multi-valued scalars (`"runtime": ["cloud"]`, `balances.json:12`).

### Markdown — `docs/`

- `H1` title at top of every file.
- `H2` for major sections, `H3` for sub-sections.
- Bold for terms-of-art: `**PoD**`, `**Winner Take All**`, `**author**`.
- Code blocks use triple-backtick with explicit language tags (`bash`, `text`, `python`).
- `USE_FLOWS.md` uses tables for structured comparisons.
- Sentence case for headings (e.g., "How to earn"), not Title Case.

### Skill files — `gunnery/skills/`

- YAML front-matter with: `name`, `tags` (array), `origin`, `version`.
- `H1` = skill name, then `## When`, `## Pattern`, `## Anti-pattern`, `## Key Detail`.
- Tags use `[impl, reliability]` style (lowercase, array).

### Genome files — `genomes/`

- `genome_meta.json`: fixed schema with `agent_id`, `generation`, `parent`, `created_at`, `last_snapshot`, `fitness` object, `lineage` array, `mutations` array.
- Mutations record `commit`, `date`, `trigger_issue`, `author`, `sections_changed`, `lines_added`, `lines_removed`, `summary`, `fitness_before`, `fitness_after`.
- Optional `role` field present in some genomes (`Claude-17@claude/genome_meta.json:7`).

### `.claude/commands/`

- Markdown files only. No YAML front-matter (unlike `gunnery/skills/`).
- First heading `# /command-name — short description`.
- Imperative prose instructions.

### `pyproject.toml`

- `setuptools` build backend.
- `requires-python = ">=3.10"`.
- `ruff>=0.4` in `dev` extras — present but unconfigured (no `[tool.ruff]` section).
- No `[tool.ruff.lint]`, no `[tool.mypy]`, no `[tool.pytest.ini_options]`.

---

## 2. Inconsistencies Found

| # | Inconsistency | Evidence |
|---|--------------|----------|
| 1 | `from __future__ import annotations` used in `src/wea_cli/` but absent in `scripts/` | `cli.py:3` vs `check_invariant.py` (absent) |
| 2 | Type annotations inconsistently applied in `scripts/` | `ledger_ops.py` fully typed; `check_invariant.py` untyped |
| 3 | Section separator style (`# ---`) only in `cli.py`, not standardized across modules | `cli.py:50` |
| 4 | Ruff listed as dev dependency but no `[tool.ruff]` config in `pyproject.toml` | `pyproject.toml:14` |
| 5 | `.claude/commands/` files lack YAML front-matter; `gunnery/skills/` files have it | `bushido.md:1` vs `atomic-file-writes.md:1–6` |
| 6 | Script-mode try/except import fallback pattern not documented; inconsistently applied | `process_pending.py:24–29` |
| 7 | No `.editorconfig` — indentation rules not machine-enforced | (absent) |
| 8 | No `[tool.pytest.ini_options]` or `[tool.mypy]` in `pyproject.toml` | `pyproject.toml` |
| 9 | `genome_meta.json` `role` field appears in some agents, absent in others | `Claude-17@claude` has it; `Claude-1@claude` does not |

---

## 3. Recommended Unified Style

### Python

**Target**: Python 3.10+. Use all 3.10+ syntax freely (`X | Y` unions, structural pattern matching where appropriate).

**Formatting**
- Line length: **88 characters** (ruff/black default).
- Indentation: 4 spaces, no tabs.
- `from __future__ import annotations` at the top of **every** Python file (both `scripts/` and `src/wea_cli/`).
- One blank line between top-level function definitions inside a class; two blank lines between top-level definitions in a module.

**Imports order** (enforced by ruff `isort`):
1. `__future__`
2. stdlib
3. third-party
4. local (`scripts.*` or `wea_cli.*`)

**Type annotations**
- Required in all `src/wea_cli/` modules.
- Required in all new `scripts/` code. Existing scripts annotated incrementally.
- Use `from typing import Any` rather than bare `dict` when heterogeneous.
- Prefer `list[T]`, `dict[K, V]`, `X | None` over `Optional[X]`, `List[T]`.

**Naming**
- `snake_case` for functions, variables, module names.
- `PascalCase` for classes.
- `UPPER_SNAKE_CASE` for module-level constants.
- `_leading_underscore` for private/internal functions.

**Docstrings**
- All public functions and classes get a one-line docstring minimum.
- Module-level docstring required on every file.
- Use triple-double-quotes `"""`. Never `'''`.

**Error handling**
- Always chain exceptions: `raise SomeError("...") from exc`.
- Domain errors subclass `ValueError` and live in the module that owns the domain.

**Section separators** (for long modules > ~150 lines):
```python
# ---------------------------------------------------------------------------
# Section title
# ---------------------------------------------------------------------------
```
Use consistently when a module has multiple logical groups (as in `cli.py`). Do not use in short modules.

**Script portability import pattern** (required in `scripts/` that are also importable):
```python
try:
    from scripts.module import symbol
except ModuleNotFoundError:  # pragma: no cover - script execution fallback
    from module import symbol
```

### JSON

- 2-space indentation (matches existing).
- Keys: `snake_case`.
- Timestamps: ISO 8601 UTC with `Z` suffix.
- Top-level `version` integer on all ledger files.
- No trailing commas.

### Markdown

- `H1` title at top of every file (one per file).
- `H2` for major sections.
- Sentence case for all headings.
- Bold for domain terms: `**WEA**`, `**PoD**`, `**Agent0**`.
- Code blocks always specify a language tag.
- Tables for structured comparisons (use `USE_FLOWS.md` as the model).
- No trailing whitespace.

### Skill files (`gunnery/skills/`)

Required YAML front-matter:
```yaml
---
name: kebab-case-name
tags: [tag1, tag2]
origin: AgentId@platform, Task #N
version: N
---
```

Required sections: `## When`, `## Pattern`, `## Anti-pattern`.

### Command files (`.claude/commands/`)

- No YAML front-matter (these are prose instructions, not reusable skills).
- First line: `# /command-name — one-line description`.
- Sections: `## What`, `## Procedure`, `## Important`.

### Genome files (`genomes/`)

`genome_meta.json` must include the `role` field for all new agents. Existing agents without it are grandfathered.

---

## 4. Tooling Config

### `pyproject.toml` additions

Add to `pyproject.toml`:

```toml
[tool.ruff]
line-length = 88
target-version = "py310"

[tool.ruff.lint]
select = [
    "E",   # pycodestyle errors
    "W",   # pycodestyle warnings
    "F",   # pyflakes
    "I",   # isort
    "UP",  # pyupgrade
    "B",   # flake8-bugbear
    "RUF", # ruff-specific
]
ignore = [
    "B008",  # do not perform function calls in argument defaults
]

[tool.ruff.lint.isort]
known-first-party = ["wea_cli", "scripts"]

[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
python_functions = ["test_*"]
```

### `.editorconfig`

Create `.editorconfig` at repo root:

```ini
root = true

[*]
end_of_line = lf
insert_final_newline = true
trim_trailing_whitespace = true
charset = utf-8

[*.py]
indent_style = space
indent_size = 4

[*.{json,toml,yaml,yml}]
indent_style = space
indent_size = 2

[*.md]
trim_trailing_whitespace = false

[Makefile]
indent_style = tab
```

### `ruff.toml` (alternative standalone config)

If a standalone file is preferred over embedding in `pyproject.toml`:

```toml
line-length = 88
target-version = "py310"

[lint]
select = ["E", "W", "F", "I", "UP", "B", "RUF"]
ignore = ["B008"]

[lint.isort]
known-first-party = ["wea_cli", "scripts"]
```

---

## 5. Migration Plan

### Quick wins (do now, < 1 hour each)

1. **Add `[tool.ruff]` config to `pyproject.toml`** — zero code changes, immediate lint enforcement on new code.
2. **Add `.editorconfig`** — IDEs and editors pick this up automatically, prevents future drift.
3. **Add `from __future__ import annotations` to `scripts/`** — mechanical change, no logic impact.
4. **Add `role` field to genome files missing it** — trivial JSON edit.

### Medium term (per-PR, as files are touched)

5. **Annotate `scripts/` functions** — add type annotations to any script modified in a PR. Follows the "boy scout rule": leave it better than you found it.
6. **Add missing module docstrings** — any file opened for editing gets a docstring if absent.
7. **Normalize section separators** — add `# ---` banners to `scripts/` files over 150 lines on next touch.

### Long term (dedicated cleanup PRs)

8. **Run `ruff --fix` across all Python files** — auto-fixes imports and pyupgrade issues. Do in a single dedicated commit with no logic changes so it's easy to review.
9. **Add `mypy` or `pyright` to CI** — after type annotations are more complete.
10. **Enforce skill front-matter schema** — add a CI check (`scripts/check_skill_format.py`) that validates all `gunnery/skills/*.md` files have required front-matter keys.
11. **Add `.claude/commands/` front-matter** — if commands grow into a formal library, add YAML front-matter matching skill format for discoverability.
