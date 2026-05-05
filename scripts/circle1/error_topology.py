#!/usr/bin/env python3
"""Repo-wide Python error-topology census — circle-1 phase 1.

Scans declared Python zones and emits a stable JSON report describing:

  * custom exception class definitions and their declared base names;
  * raise sites of built-in and custom exceptions, with wrap/re-raise context;
  * except clauses with a breadth label (bare, base_exception, broad_exception,
    narrow_specific, narrow_tuple) and a body-disposition label
    (re_raise, swallow, transform, propagate);
  * coarse boundary-surface flags for raise sites in CLI/GitHub-facing
    functions;
  * per-zone counters and a per-zone shared_base_zone_score in {0, 1, 2}
    derived only from mechanical evidence;
  * a repo-wide repo_exception_topology_hint computed as the minimum of the
    per-scored zones (tests excluded).

Output is intended to be diffed checkpoint-to-checkpoint. The summary block
and zone keys are frozen; adding fields requires bumping `tool_version`.

This scanner does not import scanned modules. All inheritance resolution is
purely textual against AST. See domains/circle-1/error_topology/logic.md for
the full spec, redteam notes, and rubric rationale.

Usage:
    python scripts/circle1/error_topology.py
        [--root <path>]
        [--out <path>]
        [--zones zone[,zone...]]
        [--scan-date YYYY-MM-DD]
        [--repo-sha <sha>]
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

# ── Schema version ────────────────────────────────────────────────────────────

TOOL_VERSION = 2

# ── Zone declarations ─────────────────────────────────────────────────────────
#
# A zone is (name, glob, score_in_repo_hint). When `score_in_repo_hint` is
# False, the zone is scanned and reported but its per-zone score does not
# affect the repo-wide minimum. `tests` is reported but excluded from the
# headline because test code legitimately raises and catches in shapes that
# would be wrong in production code.

ZONES: list[tuple[str, str, bool]] = [
    ("src_wea_cli", "src/wea_cli", True),
    ("scripts", "scripts", True),
    ("tests", "tests", False),
]
# Keeping zones disjoint avoids double counting in repo totals. To track a
# sub-surface like scripts/circle1/ over time, filter `findings` by file path
# rather than declaring an overlapping zone.

EXCLUDED_PATHS: list[dict[str, str]] = [
    {
        "path": "domains/",
        "reason": "Domain code (rnaseq, mlb, weather, fast-agent) has its "
                  "own error conventions; not first-party WEA harness.",
    },
    {
        "path": "gunnery/",
        "reason": "Shared tools library; v0 keeps the pilot to harness zones.",
    },
    {
        "path": "agent0_diary/",
        "reason": "Markdown only; no Python files.",
    },
    {
        "path": "ledger/",
        "reason": "Data-only directory; no Python files.",
    },
    {
        "path": "benchmarks/",
        "reason": "Throwaway benchmark scripts; not part of the harness.",
    },
    {
        "path": "wea-advisor-mcp/",
        "reason": "Standalone MCP server; separate dependency surface.",
    },
]

# Top-level directory names that are obvious infrastructure / never-source.
# Used to filter the auto-discovered "unscanned_python_dirs" report so that
# `.git/`, `__pycache__/` etc. don't show up as "missing exclusions".
_INFRA_TOP_LEVEL: frozenset[str] = frozenset({
    "__pycache__",
    ".git",
    ".github",
    ".pytest_cache",
    ".vscode",
    ".idea",
    ".ruff_cache",
    ".mypy_cache",
    "node_modules",
    "venv",
    ".venv",
    "build",
    "dist",
    "tmp_scan",
})

# Built-in exception names the scanner recognizes as exception bases. The list
# is intentionally not exhaustive (no `Warning` family, no asyncio variants);
# anything outside this set still counts as a custom base, which is the
# conservative direction.
_BUILTIN_EXCEPTIONS: frozenset[str] = frozenset({
    "BaseException",
    "Exception",
    "ArithmeticError",
    "AssertionError",
    "AttributeError",
    "BlockingIOError",
    "BrokenPipeError",
    "BufferError",
    "ChildProcessError",
    "ConnectionAbortedError",
    "ConnectionError",
    "ConnectionRefusedError",
    "ConnectionResetError",
    "EOFError",
    "EnvironmentError",
    "FileExistsError",
    "FileNotFoundError",
    "FloatingPointError",
    "GeneratorExit",
    "IOError",
    "ImportError",
    "IndentationError",
    "IndexError",
    "InterruptedError",
    "IsADirectoryError",
    "KeyError",
    "KeyboardInterrupt",
    "LookupError",
    "MemoryError",
    "ModuleNotFoundError",
    "NameError",
    "NotADirectoryError",
    "NotImplementedError",
    "OSError",
    "OverflowError",
    "PermissionError",
    "ProcessLookupError",
    "RecursionError",
    "ReferenceError",
    "RuntimeError",
    "StopAsyncIteration",
    "StopIteration",
    "SyntaxError",
    "SystemError",
    "SystemExit",
    "TabError",
    "TimeoutError",
    "TypeError",
    "UnboundLocalError",
    "UnicodeDecodeError",
    "UnicodeEncodeError",
    "UnicodeError",
    "UnicodeTranslateError",
    "ValueError",
    "ZeroDivisionError",
})

# Heuristic name pattern for "this looks like an exception class" when the
# textual base does not match a known built-in. Used only for class detection
# fallback; not for raise-site classification.
_EXCEPTION_NAME_HINT = ("Error", "Exception", "Warning", "Failure")


# ── Data classes ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CustomClass:
    name: str
    bases: tuple[str, ...]
    file: str
    line: int
    is_placeholder: bool
    zone: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "class",
            "zone": self.zone,
            "file": self.file,
            "line": self.line,
            "name": self.name,
            "bases": list(self.bases),
            "is_placeholder": self.is_placeholder,
        }


@dataclass(frozen=True)
class RaiseSite:
    file: str
    line: int
    exception_name: str
    is_builtin: bool
    in_except: bool
    has_from: bool
    is_re_raise: bool
    in_boundary_function: bool
    function_name: str
    zone: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "raise",
            "zone": self.zone,
            "file": self.file,
            "line": self.line,
            "exception_name": self.exception_name,
            "is_builtin": self.is_builtin,
            "in_except": self.in_except,
            "has_from": self.has_from,
            "is_re_raise": self.is_re_raise,
            "in_boundary_function": self.in_boundary_function,
            "function_name": self.function_name,
        }


@dataclass(frozen=True)
class CatchSite:
    file: str
    line: int
    caught_types: tuple[str, ...]
    breadth: str  # bare | base_exception | broad_exception | narrow_specific | narrow_tuple
    disposition: str  # re_raise | swallow | transform | propagate
    pep654: bool
    zone: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "catch",
            "zone": self.zone,
            "file": self.file,
            "line": self.line,
            "caught_types": list(self.caught_types),
            "breadth": self.breadth,
            "disposition": self.disposition,
            "pep654": self.pep654,
        }


@dataclass
class FileFindings:
    classes: list[CustomClass] = field(default_factory=list)
    raises: list[RaiseSite] = field(default_factory=list)
    catches: list[CatchSite] = field(default_factory=list)
    parse_error: str | None = None


# ── AST helpers ───────────────────────────────────────────────────────────────


def _name_of_node(node: ast.AST | None) -> str:
    """Best-effort textual rendering of a name/attribute/subscript reference."""
    if node is None:
        return ""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_name_of_node(node.value)}.{node.attr}".lstrip(".")
    if isinstance(node, ast.Subscript):
        return _name_of_node(node.value)
    if isinstance(node, ast.Call):
        return _name_of_node(node.func)
    if isinstance(node, ast.Constant):
        return repr(node.value)
    return type(node).__name__


def _bases_of_class(node: ast.ClassDef) -> tuple[str, ...]:
    return tuple(_name_of_node(b) for b in node.bases)


def _is_exception_class(bases: tuple[str, ...], known_custom: set[str]) -> bool:
    """A class is treated as an exception when at least one declared base is
    a known built-in exception, a previously-seen custom exception class, or
    a name matching the exception-name hint suffix."""
    for b in bases:
        # Match either a bare name "RuntimeError" or "module.RuntimeError".
        last = b.rsplit(".", 1)[-1]
        if last in _BUILTIN_EXCEPTIONS:
            return True
        if last in known_custom:
            return True
        if last.endswith(_EXCEPTION_NAME_HINT):
            return True
    return False


def _is_placeholder_class(node: ast.ClassDef) -> bool:
    """Heuristic for an "empty" exception class body: docstring-only, pass-only,
    or docstring + pass."""
    body = list(node.body)
    if not body:
        return True
    only_docstring = (
        len(body) == 1
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    )
    if only_docstring:
        return True
    if len(body) == 1 and isinstance(body[0], ast.Pass):
        return True
    if (
        len(body) == 2
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
        and isinstance(body[1], ast.Pass)
    ):
        return True
    return False


def _classify_breadth(handler: ast.ExceptHandler) -> tuple[str, tuple[str, ...]]:
    if handler.type is None:
        return "bare", ()
    if isinstance(handler.type, ast.Tuple):
        names = tuple(_name_of_node(elt) for elt in handler.type.elts)
        last_segments = {n.rsplit(".", 1)[-1] for n in names}
        # A tuple containing BaseException or Exception is still as broad as
        # the broadest member; classify by that breadth so it isn't hidden as
        # `narrow_tuple` and miscounted in `broad_catch_count`.
        if "BaseException" in last_segments:
            return "base_exception", names
        if "Exception" in last_segments:
            return "broad_exception", names
        return "narrow_tuple", names
    name = _name_of_node(handler.type)
    if name.rsplit(".", 1)[-1] == "BaseException":
        return "base_exception", (name,)
    if name.rsplit(".", 1)[-1] == "Exception":
        return "broad_exception", (name,)
    return "narrow_specific", (name,)


def _classify_disposition(handler: ast.ExceptHandler) -> str:
    """Classify what an except handler does with the caught exception.

    In Python, an except handler that runs to completion without raising
    consumes the caught exception unconditionally. The only way the
    exception leaves the handler is an explicit `raise`. The disposition
    set is therefore:

      - `re_raise` — handler raises the same (bound) exception, or uses
        bare `raise`;
      - `transform` — handler raises a different exception;
      - `swallow` — handler does not raise, regardless of body shape
        (`pass`, `return ...`, logging, list-append, etc.).

    Walking stops at scope boundaries so a `raise` inside a nested
    function, lambda, class, or nested except-handler body is not
    attributed to this handler. Raises inside helper-function calls
    (e.g. `_log_and_raise(exc)`) are NOT detectable from AST and are
    treated as swallows by this v0 scanner; this is documented in
    `domains/circle-1/error_topology/logic.md`.
    """
    body = list(handler.body)
    if not body:
        return "swallow"

    bound_name = handler.name

    raises_found: list[ast.Raise] = []

    def collect_raises(node: ast.AST) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            return
        if isinstance(node, ast.Raise):
            raises_found.append(node)
            return
        if isinstance(node, ast.Try):
            for stmt in node.body + node.orelse + node.finalbody:
                collect_raises(stmt)
            return
        if hasattr(ast, "TryStar") and isinstance(node, getattr(ast, "TryStar")):
            for stmt in node.body + node.orelse + node.finalbody:
                collect_raises(stmt)
            return
        for child in ast.iter_child_nodes(node):
            collect_raises(child)

    for stmt in body:
        collect_raises(stmt)

    if not raises_found:
        return "swallow"

    first = raises_found[0]
    if first.exc is None:
        return "re_raise"
    exc_name = _name_of_node(first.exc)
    if bound_name and exc_name == bound_name:
        return "re_raise"
    return "transform"


# ── Boundary-surface heuristic ────────────────────────────────────────────────


_BOUNDARY_FUNCTION_PREFIXES = ("cmd_", "_cmd_", "handle_")
_BOUNDARY_FUNCTION_SUFFIXES = ("_main",)
_BOUNDARY_FUNCTION_NAMES = frozenset({"main"})
_BOUNDARY_MODULE_HINTS = frozenset({"cli", "gh", "health", "spawn", "release"})


def _is_boundary_function(
    func_name: str,
    module_stem: str,
    module_is_cli: bool = False,
) -> bool:
    if module_is_cli:
        # Any raise inside a CLI module is a user-facing failure surface,
        # because helper raises propagate to main() and out to the terminal.
        return True
    if func_name in _BOUNDARY_FUNCTION_NAMES:
        return True
    if func_name.startswith(_BOUNDARY_FUNCTION_PREFIXES):
        return True
    if any(func_name.endswith(s) for s in _BOUNDARY_FUNCTION_SUFFIXES):
        return True
    if module_stem in _BOUNDARY_MODULE_HINTS:
        return True
    return False


def _module_uses_argparse(tree: ast.Module) -> bool:
    """Detect a real `ArgumentParser(...)` construction anywhere in the module
    — purely textual, no execution. Bare `import argparse` is not enough,
    because library modules sometimes import argparse for type hints without
    being CLI entry points."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = _name_of_node(node.func)
            if name.rsplit(".", 1)[-1] == "ArgumentParser":
                return True
    return False


# ── File-level scanner ────────────────────────────────────────────────────────


def _current_function(func_stack: list[str]) -> str:
    return func_stack[-1] if func_stack else "<module>"


def scan_file(
    path: Path,
    rel_path: str,
    zone: str,
    known_custom_classes: set[str],
) -> FileFindings:
    """Scan a single Python file and return its findings.

    `known_custom_classes` is mutated as classes are discovered, so callers
    should pass the same set across files within a zone to allow second-pass
    inheritance resolution to recognize cross-file bases.
    """
    findings = FileFindings()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        findings.parse_error = f"read failed: {exc}"
        return findings
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        findings.parse_error = f"syntax error at line {exc.lineno}: {exc.msg}"
        return findings

    module_stem = path.stem
    module_is_cli = _module_uses_argparse(tree)

    # Walk with explicit context tracking (function stack + except depth).
    def visit(node: ast.AST, func_stack: list[str], in_except: int) -> None:
        if isinstance(node, ast.ClassDef):
            bases = _bases_of_class(node)
            if _is_exception_class(bases, known_custom_classes):
                cc = CustomClass(
                    name=node.name,
                    bases=bases,
                    file=rel_path,
                    line=node.lineno,
                    is_placeholder=_is_placeholder_class(node),
                    zone=zone,
                )
                findings.classes.append(cc)
                known_custom_classes.add(node.name)
            for child in ast.iter_child_nodes(node):
                visit(child, func_stack, in_except)
            return

        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for child in ast.iter_child_nodes(node):
                visit(child, func_stack + [node.name], in_except)
            return

        if isinstance(node, ast.Try):
            for stmt in node.body:
                visit(stmt, func_stack, in_except)
            for handler in node.handlers:
                breadth, caught = _classify_breadth(handler)
                disposition = _classify_disposition(handler)
                pep654 = getattr(node, "__class__", None).__name__ == "TryStar"
                findings.catches.append(
                    CatchSite(
                        file=rel_path,
                        line=handler.lineno,
                        caught_types=caught,
                        breadth=breadth,
                        disposition=disposition,
                        pep654=pep654,
                        zone=zone,
                    )
                )
                for stmt in handler.body:
                    visit(stmt, func_stack, in_except + 1)
            for stmt in node.orelse:
                visit(stmt, func_stack, in_except)
            for stmt in node.finalbody:
                visit(stmt, func_stack, in_except)
            return

        # PEP 654 TryStar (Python 3.11+)
        if hasattr(ast, "TryStar") and isinstance(node, getattr(ast, "TryStar")):
            for stmt in node.body:
                visit(stmt, func_stack, in_except)
            for handler in node.handlers:
                breadth, caught = _classify_breadth(handler)
                disposition = _classify_disposition(handler)
                findings.catches.append(
                    CatchSite(
                        file=rel_path,
                        line=handler.lineno,
                        caught_types=caught,
                        breadth=breadth,
                        disposition=disposition,
                        pep654=True,
                        zone=zone,
                    )
                )
                for stmt in handler.body:
                    visit(stmt, func_stack, in_except + 1)
            for stmt in node.orelse:
                visit(stmt, func_stack, in_except)
            for stmt in node.finalbody:
                visit(stmt, func_stack, in_except)
            return

        if isinstance(node, ast.Raise):
            func_name = _current_function(func_stack)
            if node.exc is None:
                exc_name = ""
                is_re = True
                is_builtin = False
            else:
                exc_name = _name_of_node(node.exc)
                last = exc_name.rsplit(".", 1)[-1]
                is_builtin = last in _BUILTIN_EXCEPTIONS
                is_re = False
            findings.raises.append(
                RaiseSite(
                    file=rel_path,
                    line=node.lineno,
                    exception_name=exc_name or "<bare-reraise>",
                    is_builtin=is_builtin,
                    in_except=in_except > 0,
                    has_from=node.cause is not None,
                    is_re_raise=is_re,
                    in_boundary_function=_is_boundary_function(
                        func_name, module_stem, module_is_cli=module_is_cli
                    ),
                    function_name=func_name,
                    zone=zone,
                )
            )
            for child in ast.iter_child_nodes(node):
                visit(child, func_stack, in_except)
            return

        for child in ast.iter_child_nodes(node):
            visit(child, func_stack, in_except)

    visit(tree, [], 0)
    return findings


# ── Zone scanner ──────────────────────────────────────────────────────────────


def _zone_files(root: Path, glob_dir: str) -> list[Path]:
    base = root / glob_dir
    if not base.is_dir():
        return []
    return sorted(p for p in base.rglob("*.py") if p.is_file())


def scan_zone(
    root: Path,
    zone_name: str,
    glob_dir: str,
) -> tuple[list[FileFindings], list[str]]:
    """Two-pass scan of a zone:
       1. discover all class names (so second pass can resolve cross-file bases);
       2. produce findings.
    """
    paths = _zone_files(root, glob_dir)

    # First pass: collect class names that look like exception classes,
    # iterated to fixpoint so transitive chains are caught regardless of
    # file order (e.g. Base extends RuntimeError, Mid extends Base, Leaf
    # extends Mid — three files, three rounds of discovery).
    parsed: list[ast.Module] = []
    for path in paths:
        try:
            parsed.append(ast.parse(path.read_text(encoding="utf-8")))
        except (OSError, SyntaxError):
            continue

    known: set[str] = set()
    changed = True
    while changed:
        changed = False
        for tree in parsed:
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and node.name not in known:
                    if _is_exception_class(_bases_of_class(node), known):
                        known.add(node.name)
                        changed = True

    # Second pass: real scan. Share `known` across files (no copy) so a
    # discovery made while scanning one file is visible to the next.
    rel_paths: list[str] = []
    findings_list: list[FileFindings] = []
    for path in paths:
        rel = path.relative_to(root).as_posix()
        rel_paths.append(rel)
        findings_list.append(scan_file(path, rel, zone_name, known))
    return findings_list, rel_paths


# ── Inheritance graph ─────────────────────────────────────────────────────────


def _shared_base_score(
    classes: list[CustomClass],
    cross_zone_known: set[str] | None = None,
    cross_zone_direct: dict[str, set[str]] | None = None,
) -> int:
    """Mechanical part of the v0 rubric, capped at 2.

       0 — no custom exception classes
       1 — custom classes exist but no shared custom base
       2 — at least one custom base is the (transitive) parent of >=2 classes
           in the zone, AND that base is itself defined in any scanned class
           set (textually). The base may be defined in another file or in
           another scanned zone; that is the point of cross-file/cross-zone
           resolution.

    `cross_zone_known` is the set of every class name defined across all
    scanned zones. `cross_zone_direct` is the same merged inheritance map
    so transitive resolution can chase a base name into another zone. When
    both are None, the function falls back to zone-local resolution.
    """
    if not classes:
        return 0

    # Map class name -> direct (textual) bases. Multiple classes with the same
    # name in different files collapse; that is acceptable for v0.
    direct: dict[str, set[str]] = {}
    for c in classes:
        # last-segment normalization: "wea_cli.errors.WeaCliError" -> "WeaCliError"
        bases = {b.rsplit(".", 1)[-1] for b in c.bases}
        direct.setdefault(c.name, set()).update(bases)

    # Combine local + cross-zone maps for transitive resolution.
    merged: dict[str, set[str]] = {k: set(v) for k, v in direct.items()}
    if cross_zone_direct:
        for k, v in cross_zone_direct.items():
            merged.setdefault(k, set()).update(v)
    defined = set(merged.keys())
    if cross_zone_known:
        defined |= cross_zone_known

    # For score 2 we need >=2 classes whose ancestor chain (within `defined`)
    # contains a common custom (non-builtin) base.
    def ancestors(name: str, seen: set[str]) -> set[str]:
        if name in seen:
            return set()
        seen.add(name)
        out: set[str] = set()
        for b in merged.get(name, set()):
            if b in _BUILTIN_EXCEPTIONS:
                continue
            out.add(b)
            out |= ancestors(b, seen)
        return out

    base_users: dict[str, set[str]] = {}
    for cname in direct:
        for anc in ancestors(cname, set()):
            # Only count bases defined in the scanned set, so an external
            # base imported from outside the scan doesn't trigger a
            # false-positive "shared base" score.
            if anc in defined:
                base_users.setdefault(anc, set()).add(cname)

    for users in base_users.values():
        if len(users) >= 2:
            return 2
    return 1


# ── Summary ───────────────────────────────────────────────────────────────────


def _zone_summary(
    classes: list[CustomClass],
    raises: list[RaiseSite],
    catches: list[CatchSite],
    cross_zone_known: set[str] | None = None,
    cross_zone_direct: dict[str, set[str]] | None = None,
) -> dict[str, Any]:
    return {
        "custom_class_count": len(classes),
        "placeholder_class_count": sum(1 for c in classes if c.is_placeholder),
        "raw_builtin_raise_count": sum(
            1 for r in raises if r.is_builtin and not r.is_re_raise
        ),
        "wrap_raise_count": sum(
            1 for r in raises if r.in_except and not r.is_re_raise
        ),
        "re_raise_count": sum(1 for r in raises if r.is_re_raise),
        "broad_catch_count": sum(
            1 for c in catches if c.breadth in ("broad_exception", "base_exception")
        ),
        "bare_catch_count": sum(1 for c in catches if c.breadth == "bare"),
        "swallowed_catch_count": sum(
            1 for c in catches if c.disposition == "swallow"
        ),
        "boundary_raise_count": sum(
            1 for r in raises if r.in_boundary_function
        ),
        "shared_base_zone_score": _shared_base_score(
            classes,
            cross_zone_known=cross_zone_known,
            cross_zone_direct=cross_zone_direct,
        ),
    }


def _repo_hint(per_zone: dict[str, dict[str, Any]]) -> int:
    """Repo-wide mechanical hint: minimum of per-zone scores among zones with
    at least one custom class. Zones with zero custom classes are not signal."""
    candidates: list[int] = []
    for zone_name, summary in per_zone.items():
        if not _zone_counts_for_repo_hint(zone_name):
            continue
        if summary["custom_class_count"] == 0:
            continue
        candidates.append(int(summary["shared_base_zone_score"]))
    return min(candidates) if candidates else 0


def _zone_counts_for_repo_hint(zone_name: str) -> bool:
    for declared_name, _glob, counts in ZONES:
        if declared_name == zone_name:
            return counts
    return False


# ── Top-level scan ────────────────────────────────────────────────────────────


def run_scan(
    root: Path,
    selected_zones: list[str] | None = None,
    scan_date: str | None = None,
    repo_sha: str | None = None,
) -> dict[str, Any]:
    """Run the full scan and return the report dict."""
    declared = [(n, g, c) for (n, g, c) in ZONES]
    if selected_zones is not None:
        wanted = set(selected_zones)
        declared = [z for z in declared if z[0] in wanted]

    per_zone_findings: dict[str, FileFindings] = {}
    parse_errors: list[dict[str, str]] = []
    findings_list: list[dict[str, Any]] = []
    summary: dict[str, Any] = {"zones": {}, "repo": {}}

    repo_class_total = 0
    repo_raises_total = 0
    repo_catches_total = 0
    repo_raw_builtin = 0
    repo_wrap = 0
    repo_re_raise = 0
    repo_broad_catch = 0
    repo_bare_catch = 0
    repo_swallowed = 0
    repo_boundary_raise = 0

    # First, collect all zone findings so cross-zone class names are
    # available before any per-zone score is computed. This lets a zone
    # claim score 2 when its custom errors share a base defined in another
    # scanned zone (for example, scripts/ classes extending WeaCliError
    # defined in src/wea_cli/errors.py).
    zone_collected: dict[str, dict[str, Any]] = {}
    for (zone_name, glob_dir, _counts) in declared:
        zone_findings, rel_paths = scan_zone(root, zone_name, glob_dir)
        zone_classes: list[CustomClass] = []
        zone_raises: list[RaiseSite] = []
        zone_catches: list[CatchSite] = []
        for ff, rel in zip(zone_findings, rel_paths):
            if ff.parse_error is not None:
                parse_errors.append({"path": rel, "error": ff.parse_error})
                continue
            zone_classes.extend(ff.classes)
            zone_raises.extend(ff.raises)
            zone_catches.extend(ff.catches)
        zone_collected[zone_name] = {
            "classes": zone_classes,
            "raises": zone_raises,
            "catches": zone_catches,
        }

    # Build cross-zone known names + cross-zone direct-base map.
    cross_zone_known: set[str] = set()
    cross_zone_direct: dict[str, set[str]] = {}
    for collected in zone_collected.values():
        for c in collected["classes"]:
            cross_zone_known.add(c.name)
            cross_zone_direct.setdefault(c.name, set()).update(
                b.rsplit(".", 1)[-1] for b in c.bases
            )

    for (zone_name, _glob_dir, _counts) in declared:
        collected = zone_collected[zone_name]
        zone_classes = collected["classes"]
        zone_raises = collected["raises"]
        zone_catches = collected["catches"]

        z_summary = _zone_summary(
            zone_classes,
            zone_raises,
            zone_catches,
            cross_zone_known=cross_zone_known,
            cross_zone_direct=cross_zone_direct,
        )
        summary["zones"][zone_name] = z_summary

        repo_class_total += z_summary["custom_class_count"]
        repo_raises_total += len(zone_raises)
        repo_catches_total += len(zone_catches)
        repo_raw_builtin += z_summary["raw_builtin_raise_count"]
        repo_wrap += z_summary["wrap_raise_count"]
        repo_re_raise += z_summary["re_raise_count"]
        repo_broad_catch += z_summary["broad_catch_count"]
        repo_bare_catch += z_summary["bare_catch_count"]
        repo_swallowed += z_summary["swallowed_catch_count"]
        repo_boundary_raise += z_summary["boundary_raise_count"]

        for c in zone_classes:
            findings_list.append(c.to_dict())
        for r in zone_raises:
            findings_list.append(r.to_dict())
        for c in zone_catches:
            findings_list.append(c.to_dict())

    summary["repo"] = {
        "custom_class_count": repo_class_total,
        "raise_site_count": repo_raises_total,
        "catch_site_count": repo_catches_total,
        "raw_builtin_raise_count": repo_raw_builtin,
        "wrap_raise_count": repo_wrap,
        "re_raise_count": repo_re_raise,
        "broad_catch_count": repo_broad_catch,
        "bare_catch_count": repo_bare_catch,
        "swallowed_catch_count": repo_swallowed,
        "boundary_raise_count": repo_boundary_raise,
        "repo_exception_topology_hint": _repo_hint(summary["zones"]),
    }

    findings_list.sort(
        key=lambda f: (
            f.get("zone", ""),
            f.get("file", ""),
            int(f.get("line", 0) or 0),
            f.get("kind", ""),
        )
    )

    return {
        "tool_version": TOOL_VERSION,
        "scan_date": scan_date or date.today().isoformat(),
        "repo_sha": repo_sha or "",
        "scope": [
            {"name": n, "glob": g, "counts_in_repo_hint": c}
            for (n, g, c) in declared
        ],
        "excluded_paths": list(EXCLUDED_PATHS),
        "unscanned_python_dirs": _discover_unscanned_python_dirs(root, declared),
        "parse_errors": parse_errors,
        "summary": summary,
        "findings": findings_list,
    }


def _discover_unscanned_python_dirs(
    root: Path,
    declared: list[tuple[str, str, bool]],
) -> list[dict[str, Any]]:
    """Auto-discover top-level directories that contain Python files but are
    neither scanned nor in EXCLUDED_PATHS. Surfaces drift so a new top-level
    Python area cannot quietly slip out of the census between checkpoints."""
    if not root.is_dir():
        return []
    scanned_top = {Path(g).parts[0] for (_n, g, _c) in declared}
    excluded_top = {entry["path"].rstrip("/") for entry in EXCLUDED_PATHS}
    unscanned: list[dict[str, Any]] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        name = child.name
        if name in scanned_top or name in excluded_top:
            continue
        if name in _INFRA_TOP_LEVEL or name.startswith("."):
            continue
        py_count = sum(1 for _ in child.rglob("*.py"))
        if py_count == 0:
            continue
        unscanned.append({"path": f"{name}/", "py_file_count": py_count})
    return unscanned


# ── CLI ───────────────────────────────────────────────────────────────────────


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    p.add_argument("--root", default=".", help="Repo root (default: cwd).")
    p.add_argument("--out", default=None, help="Output JSON path (default: stdout).")
    p.add_argument(
        "--zones",
        default=None,
        help="Comma-separated zone names to scan (default: all declared).",
    )
    p.add_argument("--scan-date", default=None, help="Override scan date (YYYY-MM-DD).")
    p.add_argument("--repo-sha", default=None, help="Override recorded repo SHA.")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(list(argv if argv is not None else sys.argv[1:]))

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"ERROR: --root not found: {root}", file=sys.stderr)
        return 1

    selected = None
    if args.zones:
        selected = [z.strip() for z in args.zones.split(",") if z.strip()]
        declared_names = {n for (n, _g, _c) in ZONES}
        unknown = [z for z in selected if z not in declared_names]
        if unknown:
            print(f"ERROR: unknown zones: {unknown}", file=sys.stderr)
            return 1

    report = run_scan(
        root,
        selected_zones=selected,
        scan_date=args.scan_date,
        repo_sha=args.repo_sha,
    )

    payload = json.dumps(report, indent=2, sort_keys=False)
    if args.out:
        Path(args.out).write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
