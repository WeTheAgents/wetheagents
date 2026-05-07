"""Circle-1 error topology census harness.

Scans Python files under configured zones and reports the repo's exception
topology: custom exception classes and their inheritance, raw built-in raises,
broad catches, wrap/re-raise patterns, file-level CLI/GitHub failure surface
flags, per-file ownership, and a stable summary suitable for checkpoint
comparison.

Companion documents in this directory:
  - error_topology_logic.md         — code-free architecture (pre-impl)
  - error_topology_spec_redteam.md  — pre-impl spec + logic redteam
  - error_topology_post_impl_redteam.md — post-impl redteam after code lands
  - ../../src/wea_cli/error_topology_pilot.md — pilot analysis

This harness is advisory inventory only. It does not enforce policy, change
script behavior, or affect Tide/ledger settlement.

Default scope:
  - include: src/wea_cli/**/*.py, scripts/**/*.py
  - exclude: __init__.py at any depth, reported in skipped_files

Use --zones to widen the scope (e.g. ``--zones src/wea_cli,scripts,tests``).

JSON schema overview:
  {
    "scan_date": "YYYY-MM-DD",
    "harness_version": "v0",
    "scope": {"zones": [...], "default_exclusions": [...], "extra_excludes": [...]},
    "summary": {
      "total_files": 0,
      "files_with_detections": 0,
      "parse_errors": 0,
      "skipped_files": 0,
      "by_kind": {"<kind>": {"files": 0, "detections": 0}},
      "by_zone": {"<zone>": {"total_files": 0, "by_kind": {...}, "score_inputs": {...},
                              "exception_topology_score": 0}},
      "exception_topology_score": {"per_zone": {...}, "repo": 0}
    },
    "kinds": [{"name": "...", "description": "..."}],
    "limitations": [...],
    "exception_classes": [{"path": "...", "name": "...", "bases": [...],
                            "line": 0, "has_docstring": false, "zone": "..."}],
    "inheritance": {"<class>": {"bases": [...], "subclasses": [...]}},
    "files": [{"path": "...", "zone": "...", "status": "scanned",
               "file_flags": {...}, "detections": [...]}],
    "skipped_files": [{"path": "...", "reason": "..."}]
  }
"""

from __future__ import annotations

import argparse
import ast
import builtins
import fnmatch
import json
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

HARNESS_VERSION = "v0"

DEFAULT_ZONES: tuple[str, ...] = ("src/wea_cli", "scripts")
DEFAULT_INIT_EXCLUSION = "__init__.py"

KINDS: tuple[dict[str, str], ...] = (
    {
        "name": "custom_exception_class",
        "description": (
            "A class definition whose base list ends in something that looks "
            "like Exception/Error."
        ),
    },
    {
        "name": "raw_builtin_raise_at_boundary",
        "description": (
            "A raise of a Python built-in exception at a user-visible "
            "boundary. Ambiguous failure surface."
        ),
    },
    {
        "name": "custom_raise",
        "description": "A raise of a name that looks like a custom exception class.",
    },
    {
        "name": "broad_catch",
        "description": "except Exception, except BaseException, or bare except:",
    },
    {
        "name": "reraise_chain",
        "description": (
            "Inside an except handler, a raise X(...) [from e]. Records inner "
            "(handler) and outer (raise) class names."
        ),
    },
    {
        "name": "bare_reraise",
        "description": (
            "raise without an operand inside an except handler. "
            "Pure propagation, not a wrap."
        ),
    },
)

KIND_NAMES = tuple(item["name"] for item in KINDS)

# File-level flags (annotations, not detections):
FILE_FLAGS: tuple[str, ...] = ("cli_failure_surface", "github_failure_surface")

LIMITATIONS: tuple[str, ...] = (
    "AST-only census. Dynamic class generation (type(), metaclasses, NewType) "
    "is invisible to this harness and is acknowledged as undercount.",
    "Inheritance graph uses bare class names. Two unrelated classes with the "
    "same name in different files would collide. v1 upgrade: fully-qualified "
    "name resolution with import tracking.",
    "Re-raise/wrap detection records the handler's exception type and the "
    "raise's class name. It does not perform interprocedural dataflow, so it "
    "cannot prove that the wrap reaches a user boundary.",
    "CLI and GitHub failure-surface flags are file-level heuristics. They are "
    "annotations, not topology score inputs.",
    "raw_builtin_raise_at_boundary uses the Python builtins namespace plus a "
    "name-suffix fallback (Error/Exception). Some stdlib classes that feel "
    "built-in (for example _csv.Error) are not in builtins and are reported "
    "as custom_raise with confidence low.",
    "exception_topology_score is computed per zone using the cooling_metrics_v0 "
    "rubric. enforced_check (score 4) is operator-supplied, never auto-detected.",
)

# Built-in exception classes that can be raised. We treat any name in
# `builtins` that ends in "Error" or "Exception" as raw-built-in. We add the
# common base classes that do not match the suffix (Exception, BaseException).
_BUILTIN_EXC_NAMES = {
    name
    for name in dir(builtins)
    if name.endswith("Error") or name.endswith("Exception")
}
_BUILTIN_EXC_NAMES.update({"Exception", "BaseException", "Warning"})

# StopIteration, GeneratorExit, KeyboardInterrupt, SystemExit are flow-control
# adjacent and are normal in production code. They are still tracked when raised
# but do not count as "user-visible boundary errors". Tag with low confidence.
_FLOW_CONTROL = {"StopIteration", "StopAsyncIteration", "GeneratorExit"}
_INTERRUPT_LIKE = {"KeyboardInterrupt", "SystemExit"}


# ── Helpers ──────────────────────────────────────────────────────────────────


def _node_name(node: ast.AST | None) -> str:
    """Best-effort dotted name for a Name/Attribute/Call node."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _node_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    if isinstance(node, ast.Call):
        return _node_name(node.func)
    return ""


def _short_name(name: str) -> str:
    return name.rsplit(".", 1)[-1] if name else ""


def _is_exception_like(name: str) -> bool:
    short = _short_name(name)
    return short.endswith("Error") or short.endswith("Exception")


def _is_builtin_exc(name: str) -> bool:
    short = _short_name(name)
    return short in _BUILTIN_EXC_NAMES


def _snippet_from(source_text: str, lines: list[str], node: ast.AST) -> str:
    segment = ast.get_source_segment(source_text, node)
    if segment is not None:
        snippet = " ".join(segment.strip().split())
        if len(snippet) > 240:
            snippet = snippet[:237].rstrip() + "..."
        return snippet
    line_no = getattr(node, "lineno", 0)
    if line_no and 1 <= line_no <= len(lines):
        return lines[line_no - 1].strip()
    return ""


def _has_docstring(body: list[ast.stmt]) -> bool:
    if not body:
        return False
    first = body[0]
    return (
        isinstance(first, ast.Expr)
        and isinstance(first.value, ast.Constant)
        and isinstance(first.value.value, str)
    )


def _normalize_zone(zone: str) -> str:
    """Normalize a zone name to a forward-slash, leading-dot-stripped form.

    Examples:
      "."             -> ""        (means: whole repo root)
      "./src/wea_cli" -> "src/wea_cli"
      "src/wea_cli/"  -> "src/wea_cli"
      "src\\wea_cli"  -> "src/wea_cli"
    """
    norm = zone.replace("\\", "/").rstrip("/")
    if norm == "." or norm == "":
        return ""
    if norm.startswith("./"):
        norm = norm[2:]
    return norm


def _zone_for_path(rel_path: str, zones: list[str]) -> str:
    """Return the most-specific configured zone the path belongs to, or 'other'."""
    norm = rel_path.replace("\\", "/")
    matched: str | None = None
    matched_len = -1
    for zone in zones:
        zone_norm = _normalize_zone(zone)
        if zone_norm == "":
            # Whole-repo zone matches everything; prefer it only if no more
            # specific zone wins.
            if matched_len < 0:
                matched = zone  # report under the original zone label
                matched_len = 0
            continue
        if norm == zone_norm or norm.startswith(zone_norm + "/"):
            if len(zone_norm) > matched_len:
                matched = zone_norm
                matched_len = len(zone_norm)
    return matched if matched is not None else "other"


# ── Detection records ───────────────────────────────────────────────────────


@dataclass
class Detection:
    kind: str
    confidence: str
    reason: str
    line: int
    col: int
    symbol: str
    snippet: str
    extra: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        out = {
            "kind": self.kind,
            "confidence": self.confidence,
            "reason": self.reason,
            "line": self.line,
            "col": self.col,
            "symbol": self.symbol,
            "snippet": self.snippet,
        }
        if self.extra:
            out["extra"] = self.extra
        return out


# ── Visitors ────────────────────────────────────────────────────────────────


class FileVisitor(ast.NodeVisitor):
    def __init__(
        self,
        source_text: str,
        lines: list[str],
        known_exc_names: set[str] | None = None,
        tree: ast.Module | None = None,
    ) -> None:
        self.source_text = source_text
        self.lines = lines
        self.detections: list[Detection] = []
        # Class names declared in this file with their bases (short names):
        self.classes: list[dict[str, Any]] = []
        # Stack of currently-active except handler types (short class names list):
        self._handler_stack: list[list[str]] = []
        # Names imported in this file (alias -> module.path) for confidence
        self._imports: dict[str, str] = {}
        # Repo-wide known exception-like class names (short names). Includes
        # classes detected in pass 1 plus their transitive subclasses.
        self.known_exc_names = set(known_exc_names or set())
        # File flags
        self.cli_main_seen = False
        self.argparse_seen = False
        self.click_seen = False
        self.gh_import_seen = False
        self.gh_subprocess_seen = False
        self.github_url_seen = False
        # Pre-collect imports across the whole file so a `raise E()` inside a
        # handler can resolve `E` even when the `from pkg import ... as E`
        # statement appears later in source order (e.g. inside a try body).
        if tree is not None:
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        local = alias.asname or alias.name.split(".", 1)[0]
                        self._imports[local] = alias.name
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    for alias in node.names:
                        local = alias.asname or alias.name
                        self._imports[local] = (
                            f"{module}.{alias.name}" if module else alias.name
                        )

    # --- imports ------------------------------------------------------------

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            local = alias.asname or alias.name.split(".", 1)[0]
            self._imports[local] = alias.name
            if alias.name == "wea_cli.gh" or alias.name.startswith("wea_cli.gh."):
                self.gh_import_seen = True
        if any(alias.name.startswith("argparse") for alias in node.names):
            self.argparse_seen = True
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        if module.startswith("wea_cli.gh") or module == "wea_cli" and any(
            alias.name == "gh" for alias in node.names
        ):
            self.gh_import_seen = True
        if module == "argparse":
            self.argparse_seen = True
        if module.startswith("click"):
            self.click_seen = True
        for alias in node.names:
            local = alias.asname or alias.name
            self._imports[local] = f"{module}.{alias.name}" if module else alias.name
        self.generic_visit(node)

    # --- class defs ---------------------------------------------------------

    def _visit_classdef_isolated(self, node: ast.ClassDef) -> None:
        # Class bodies share the same isolation: a method's raise must not
        # be classified by the enclosing except handler.
        saved_stack = self._handler_stack
        self._handler_stack = []
        try:
            self.generic_visit(node)
        finally:
            self._handler_stack = saved_stack

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        base_names = [_node_name(b) for b in node.bases]
        base_shorts = [_short_name(b) for b in base_names]
        # Detect "looks like an exception" if (a) the class name has an
        # Error/Exception suffix, (b) any base has an Error/Exception suffix,
        # (c) any base is a built-in exception class, or (d) any base is in
        # the repo-wide known exception-like set computed in pass 1.
        is_exc_like = (
            _is_exception_like(node.name)
            or any(_is_exception_like(b) for b in base_names)
            or any(_is_builtin_exc(b) for b in base_names)
            or any(b in self.known_exc_names for b in base_shorts)
        )
        if is_exc_like:
            entry = {
                "name": node.name,
                "bases": [_short_name(b) for b in base_names],
                "line": node.lineno,
                "has_docstring": _has_docstring(node.body),
            }
            self.classes.append(entry)
            self.detections.append(
                Detection(
                    kind="custom_exception_class",
                    confidence="high",
                    reason="class declared with exception-like name or base",
                    line=node.lineno,
                    col=node.col_offset,
                    symbol=node.name,
                    snippet=_snippet_from(self.source_text, self.lines, node)[:160],
                    extra={
                        "bases": entry["bases"],
                        "has_docstring": entry["has_docstring"],
                    },
                )
            )
        # Continue walking inside the class (methods, nested raises) so we still
        # see internal handlers and raises. Use isolated handler-stack scope:
        # method bodies must not be classified by an enclosing except handler.
        self._visit_classdef_isolated(node)

    # --- function defs (CLI surface flag) ----------------------------------

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if node.name == "main":
            self.cli_main_seen = True
        for deco in node.decorator_list:
            name = _node_name(deco).lower()
            if "click" in name or name.endswith(".command") or name.endswith(".group"):
                self.click_seen = True
        # A nested function defined inside an except handler runs later; raises
        # inside it must not be classified as `in_handler`. Save and clear the
        # active handler stack while descending into the function body.
        saved_stack = self._handler_stack
        self._handler_stack = []
        try:
            self.generic_visit(node)
        finally:
            self._handler_stack = saved_stack

    visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]

    # --- try/except --------------------------------------------------------

    def visit_Try(self, node: ast.Try) -> None:
        # Walk handlers manually so we can keep the handler-type stack accurate
        # while visiting nested raises. Then walk body/orelse/finalbody
        # directly — calling generic_visit() on the Try node would re-enter
        # the handlers and double-count every detection inside them.
        for handler in node.handlers:
            self._record_handler(handler)
        for stmt in node.body:
            self.visit(stmt)
        for stmt in node.orelse:
            self.visit(stmt)
        for stmt in node.finalbody:
            self.visit(stmt)

    def _handler_bound_names(self) -> set[str]:
        """Names bound by `except ... as <name>` for any active handler."""
        out: set[str] = set()
        for frame in self._handler_stack:
            bound = frame[1] if isinstance(frame, tuple) and len(frame) == 2 else None
            if bound:
                out.add(bound)
        return out

    def _record_handler(self, handler: ast.ExceptHandler) -> None:
        types = self._handler_types(handler.type)
        bound = handler.name  # name in `except E as NAME:` (may be None)
        # Broad catch detection
        if not types:
            self.detections.append(
                Detection(
                    kind="broad_catch",
                    confidence="high",
                    reason="bare except: catches BaseException including KeyboardInterrupt/SystemExit",
                    line=handler.lineno,
                    col=handler.col_offset,
                    symbol="bare_except",
                    snippet=_snippet_from(self.source_text, self.lines, handler)[:160],
                    extra={"sub_reason": "bare_except"},
                )
            )
        else:
            broad_hits = [t for t in types if t in {"Exception", "BaseException"}]
            if broad_hits:
                self.detections.append(
                    Detection(
                        kind="broad_catch",
                        confidence="high",
                        reason=f"except {', '.join(broad_hits)} swallows broad failure surface",
                        line=handler.lineno,
                        col=handler.col_offset,
                        symbol=broad_hits[0],
                        snippet=_snippet_from(self.source_text, self.lines, handler)[:160],
                        extra={"caught_types": types},
                    )
                )
        # Now walk the body with the handler types + bound name on the stack
        # so nested raises can be classified as reraise_chain / bare_reraise.
        # Tracking the bound name lets us exclude `except ... as TaskError:
        # raise TaskError` from the wrap-pattern detector — that is direct
        # propagation, not a class wrap.
        self._handler_stack.append((types, bound))
        try:
            for stmt in handler.body:
                self.visit(stmt)
        finally:
            self._handler_stack.pop()

    def _handler_types(self, type_node: ast.AST | None) -> list[str]:
        if type_node is None:
            return []
        if isinstance(type_node, ast.Tuple):
            return [_short_name(_node_name(elt)) for elt in type_node.elts if _node_name(elt)]
        name = _node_name(type_node)
        return [_short_name(name)] if name else []

    # --- raises ------------------------------------------------------------

    def visit_Raise(self, node: ast.Raise) -> None:
        in_handler = bool(self._handler_stack)
        if node.exc is None:
            if in_handler:
                self.detections.append(
                    Detection(
                        kind="bare_reraise",
                        confidence="high",
                        reason="raise without operand re-propagates the active exception",
                        line=node.lineno,
                        col=node.col_offset,
                        symbol="raise",
                        snippet=_snippet_from(self.source_text, self.lines, node)[:160],
                        extra={"handler_types": self._handler_stack[-1][0]},
                    )
                )
            self.generic_visit(node)
            return

        raised_name = _node_name(node.exc)
        short = _short_name(raised_name)
        from_clause = node.cause is not None
        # Direct propagation through a handler-bound variable
        # (`except Exception as TaskError: raise TaskError`) is not a class
        # raise. Treat it as direct re-raise: no custom_raise and no
        # reraise_chain. We still record a bare_reraise-style annotation so
        # the propagation isn't invisible.
        is_bound_handler_var = (
            in_handler
            and isinstance(node.exc, ast.Name)
            and short in self._handler_bound_names()
        )
        if is_bound_handler_var:
            self.detections.append(
                Detection(
                    kind="bare_reraise",
                    confidence="high",
                    reason="raise of handler-bound variable propagates the active exception",
                    line=node.lineno,
                    col=node.col_offset,
                    symbol=short,
                    snippet=_snippet_from(self.source_text, self.lines, node)[:160],
                    extra={
                        "handler_types": self._handler_stack[-1][0],
                        "bound_name": short,
                    },
                )
            )
            self.generic_visit(node)
            return

        is_known_custom = short in self.known_exc_names

        # Resolve imported aliases: `from pkg import FooError as E; raise E()`.
        # We always look up the import map (even when the local name itself
        # ends in Error/Exception, e.g. `import FooError as BarError`) so the
        # canonical class name reaches the score logic and matches declared
        # subclass names rather than the local alias.
        alias_resolved = ""
        if not is_known_custom and short in self._imports:
            resolved_full = self._imports[short]
            resolved_short = _short_name(resolved_full)
            if resolved_short and resolved_short != short and (
                _is_exception_like(resolved_short)
                or resolved_short in self.known_exc_names
                or _is_builtin_exc(resolved_short)
            ):
                alias_resolved = resolved_short

        # Flow-control raises (StopIteration, GeneratorExit, KeyboardInterrupt,
        # SystemExit) are real Python built-ins but are normal control flow,
        # not user-facing failure surfaces. Record them under
        # raw_builtin_raise_at_boundary with confidence "low" so they are
        # visible without dominating the score.
        if short in _FLOW_CONTROL | _INTERRUPT_LIKE:
            self.detections.append(
                Detection(
                    kind="raw_builtin_raise_at_boundary",
                    confidence="low",
                    reason=f"raise of flow-control/interrupt class {short!r}",
                    line=node.lineno,
                    col=node.col_offset,
                    symbol=short,
                    snippet=_snippet_from(self.source_text, self.lines, node)[:160],
                    extra={
                        "from_clause": from_clause,
                        "in_handler": in_handler,
                        "flow_control": True,
                    },
                )
            )
            self.generic_visit(node)
            return

        # Classify the raised name
        if _is_builtin_exc(short) or short in {"Exception", "BaseException"}:
            self.detections.append(
                Detection(
                    kind="raw_builtin_raise_at_boundary",
                    confidence="high",
                    reason=f"raise of built-in exception {short!r}",
                    line=node.lineno,
                    col=node.col_offset,
                    symbol=short,
                    snippet=_snippet_from(self.source_text, self.lines, node)[:160],
                    extra={
                        "from_clause": from_clause,
                        "in_handler": in_handler,
                    },
                )
            )
        elif (
            (_is_exception_like(raised_name) or is_known_custom or alias_resolved)
            and short not in _FLOW_CONTROL | _INTERRUPT_LIKE
        ):
            confidence = "low"
            # high if the class is defined in this file
            if any(c["name"] == short for c in self.classes):
                confidence = "high"
            elif is_known_custom:
                confidence = "high"
            elif alias_resolved:
                confidence = "medium"
            elif short in self._imports:
                confidence = "medium"
            # When the raise is via an alias, record the resolved class name
            # as the canonical symbol so downstream score logic compares it
            # against declared subclass names correctly.
            canonical_symbol = alias_resolved or short
            self.detections.append(
                Detection(
                    kind="custom_raise",
                    confidence=confidence,
                    reason="raise of an exception-like custom name",
                    line=node.lineno,
                    col=node.col_offset,
                    symbol=canonical_symbol,
                    snippet=_snippet_from(self.source_text, self.lines, node)[:160],
                    extra={
                        "from_clause": from_clause,
                        "in_handler": in_handler,
                        "raised_name": raised_name,
                        "alias_local_name": short if alias_resolved else None,
                    },
                )
            )
        # else: not an exception-like raise, ignore (e.g. raise self._stored)

        # If we are inside a handler and re-raising a class (not just a
        # captured local variable), this is a wrap pattern. `raise exc` —
        # where `exc` is the bound handler variable — is direct propagation,
        # not a wrap, and is excluded.
        is_class_like_raise = (
            _is_builtin_exc(short)
            or _is_exception_like(raised_name)
            or is_known_custom
            or bool(alias_resolved)
        )
        if in_handler and short and is_class_like_raise:
            self.detections.append(
                Detection(
                    kind="reraise_chain",
                    confidence="high" if from_clause else "medium",
                    reason="raise inside except handler — wrap or rebrand pattern",
                    line=node.lineno,
                    col=node.col_offset,
                    symbol=short,
                    snippet=_snippet_from(self.source_text, self.lines, node)[:160],
                    extra={
                        "inner_types": self._handler_stack[-1][0],
                        "outer": short,
                        "from_clause": from_clause,
                    },
                )
            )

        self.generic_visit(node)

    # --- calls (CLI/GitHub surface flags) ----------------------------------

    def visit_Call(self, node: ast.Call) -> None:
        name = _node_name(node.func)
        if name in {"argparse.ArgumentParser", "ArgumentParser"}:
            self.argparse_seen = True
        if name == "subprocess.run" or name.endswith(".run"):
            for arg in node.args[:1]:
                strings = []
                if isinstance(arg, (ast.List, ast.Tuple)):
                    for elt in arg.elts[:1]:
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                            strings.append(elt.value)
                elif isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    strings.append(arg.value)
                for s in strings:
                    head = s.split(" ", 1)[0]
                    if head == "gh":
                        self.gh_subprocess_seen = True
        for child in ast.walk(node):
            if isinstance(child, ast.Constant) and isinstance(child.value, str):
                if "api.github.com" in child.value:
                    self.github_url_seen = True
                    break
        self.generic_visit(node)


# ── File inspection ─────────────────────────────────────────────────────────


def _parse_file(path: Path) -> tuple[str, ast.Module] | tuple[str, BaseException]:
    """Read and parse a Python file. Returns (text, tree) or (text, error)."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return ("", exc)
    try:
        return (text, ast.parse(text))
    except SyntaxError as exc:
        return (text, exc)


def _collect_class_decls(tree: ast.Module) -> list[dict[str, Any]]:
    """First-pass collection of class declarations from an AST module."""
    out: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            out.append(
                {
                    "name": node.name,
                    "bases": [_short_name(_node_name(b)) for b in node.bases],
                    "line": node.lineno,
                }
            )
    return out


def _expand_exception_like_names(decls: list[dict[str, Any]]) -> set[str]:
    """Compute the repo-wide set of exception-like class names by transitive
    inheritance. A class is exception-like if any base is a built-in exception,
    has an Error/Exception suffix, or is itself exception-like (fixed-point)."""
    by_name: dict[str, list[str]] = {}
    for d in decls:
        by_name.setdefault(d["name"], []).extend(d["bases"])
    known: set[str] = set()
    for name, bases in by_name.items():
        if _is_exception_like(name) or any(
            _is_exception_like(b) or _is_builtin_exc(b) for b in bases
        ):
            known.add(name)
    # Iterate to fixed point: a class becomes exception-like if any base is
    # already known.
    changed = True
    while changed:
        changed = False
        for name, bases in by_name.items():
            if name in known:
                continue
            if any(b in known for b in bases):
                known.add(name)
                changed = True
    return known


def inspect_file(
    path: Path,
    root: Path,
    zones: list[str],
    known_exc_names: set[str] | None = None,
    cached: tuple[str, ast.Module] | None = None,
) -> dict[str, Any]:
    rel_path = str(path.relative_to(root)).replace("\\", "/")
    zone = _zone_for_path(rel_path, zones)
    if cached is not None:
        text, tree = cached
    else:
        parsed = _parse_file(path)
        if isinstance(parsed[1], BaseException):
            err = parsed[1]
            status = "read_error" if isinstance(err, OSError) else "parse_error"
            return {
                "path": rel_path,
                "zone": zone,
                "status": status,
                "error": str(err),
                "detections": [],
                "file_flags": {flag: False for flag in FILE_FLAGS},
            }
        text, tree = parsed
    visitor = FileVisitor(
        text,
        text.splitlines(),
        known_exc_names=known_exc_names,
        tree=tree,
    )
    visitor.visit(tree)
    detections = sorted(
        (d.as_dict() for d in visitor.detections),
        key=lambda item: (item["line"], item["col"], item["kind"], item["symbol"]),
    )
    # File-level surface flags. A file is a failure surface when it either
    # raises an exception locally OR imports/uses a helper that can propagate
    # one. Removing the local-raise requirement lets us catch delegated
    # surfaces (e.g. files that call wea_cli.gh helpers and let GhError
    # propagate) without requiring them to also raise inline.
    cli_flag = bool(
        visitor.cli_main_seen or visitor.click_seen or visitor.argparse_seen
    )
    gh_flag = bool(
        visitor.gh_import_seen
        or visitor.gh_subprocess_seen
        or visitor.github_url_seen
    )
    return {
        "path": rel_path,
        "zone": zone,
        "status": "scanned",
        "detections": detections,
        "file_flags": {
            "cli_failure_surface": cli_flag,
            "github_failure_surface": gh_flag,
        },
        "_classes": visitor.classes,  # internal; stripped before emission
    }


# ── Aggregation / scoring ───────────────────────────────────────────────────


def _empty_kind_counts() -> dict[str, dict[str, int]]:
    return {name: {"files": 0, "detections": 0} for name in KIND_NAMES}


def _accumulate_kind_counts(
    counts: dict[str, dict[str, int]], detections: list[dict[str, Any]]
) -> None:
    seen_kinds: set[str] = set()
    for det in detections:
        kind = det["kind"]
        if kind not in counts:
            continue
        counts[kind]["detections"] += 1
        seen_kinds.add(kind)
    for kind in seen_kinds:
        counts[kind]["files"] += 1


def _build_inheritance(
    files: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, list[str]]]]:
    flat: list[dict[str, Any]] = []
    graph: dict[str, dict[str, list[str]]] = {}
    for entry in files:
        for cls in entry.get("_classes", []):
            row = {
                "path": entry["path"],
                "zone": entry["zone"],
                "name": cls["name"],
                "bases": cls["bases"],
                "line": cls["line"],
                "has_docstring": cls["has_docstring"],
            }
            flat.append(row)
            node = graph.setdefault(cls["name"], {"bases": [], "subclasses": []})
            for base in cls["bases"]:
                if base and base not in node["bases"]:
                    node["bases"].append(base)
                base_node = graph.setdefault(base, {"bases": [], "subclasses": []})
                if cls["name"] not in base_node["subclasses"]:
                    base_node["subclasses"].append(cls["name"])
    flat.sort(key=lambda r: (r["path"], r["line"]))
    # Sort subclasses/bases lists for stable diffs.
    for node in graph.values():
        node["bases"] = sorted(node["bases"])
        node["subclasses"] = sorted(node["subclasses"])
    return flat, graph


def _zone_score_inputs(
    zone: str,
    flat_classes: list[dict[str, Any]],
    detections_by_zone: dict[str, list[dict[str, Any]]],
    enforced_check: str | None,
) -> dict[str, Any]:
    """Compute the inputs that feed `exception_topology_score` for a zone."""
    zone_classes = [c for c in flat_classes if c["zone"] == zone]
    classes_by_name = {c["name"]: c for c in zone_classes}
    # Set of all declared custom exception class names across the repo. Used
    # to filter out built-in base names like RuntimeError when looking for
    # "shared base" hierarchy signals.
    all_custom_class_names = {c["name"] for c in flat_classes}
    # Map each zone-local class to its zone-local bases (direct only).
    base_to_subs: dict[str, list[str]] = {}
    for c in zone_classes:
        for base in c["bases"]:
            if base in classes_by_name:
                base_to_subs.setdefault(base, []).append(c["name"])
    # Transitive descendants in the zone-local hierarchy. For a multi-level
    # tree A -> B -> C, descendants[A] = {B, C}. Used for padded/documented
    # usage checks so a base whose only raises happen at a leaf still counts.
    base_to_descendants: dict[str, set[str]] = {}
    def _zone_descendants(base: str, seen: set[str] | None = None) -> set[str]:
        if seen is None:
            seen = set()
        if base in seen:
            return set()
        seen.add(base)
        out: set[str] = set()
        for child in base_to_subs.get(base, []):
            out.add(child)
            out.update(_zone_descendants(child, seen))
        return out
    for base in list(classes_by_name.keys()):
        base_to_descendants[base] = _zone_descendants(base)
    # zone-local shared bases: bases with >= 2 transitive zone-local
    # descendants. A multi-level tree where a base has one direct child but
    # multiple grandchildren still counts.
    shared_zone_bases = sorted(
        base for base in classes_by_name if len(base_to_descendants.get(base, set())) >= 2
    )
    # repo-level shared bases relevant to *this* zone: custom bases (declared
    # somewhere in the scan) whose subclasses span >= 2 zones AND at least one
    # of those subclasses lives in the current zone. Built-in bases like
    # RuntimeError are excluded — they are universal, not a repo-level
    # hierarchy signal. Restricting the list to the zone's hierarchy prevents
    # an unrelated cross-zone base elsewhere from inflating this zone's score.
    repo_base_to_zones: dict[str, set[str]] = {}
    for c in flat_classes:
        for base in c["bases"]:
            if base not in all_custom_class_names:
                continue
            repo_base_to_zones.setdefault(base, set()).add(c["zone"])
    repo_shared_bases = sorted(
        base
        for base, zone_set in repo_base_to_zones.items()
        if len(zone_set) >= 2 and zone in zone_set
    )
    # zone-local raises and repo-wide raises (for score-3 documented-usage check)
    raised_names: set[str] = set()
    for det in detections_by_zone.get(zone, []):
        if det["kind"] in {"custom_raise", "raw_builtin_raise_at_boundary"}:
            raised_names.add(det["symbol"])
    repo_raised_names: set[str] = set()
    for zone_dets in detections_by_zone.values():
        for det in zone_dets:
            if det["kind"] in {"custom_raise", "raw_builtin_raise_at_boundary"}:
                repo_raised_names.add(det["symbol"])
    # padded_hierarchy: a zone-local shared base whose name never appears as a
    # raised symbol in the zone, and none of its transitive descendants are
    # raised either. Walking descendants (not just direct children) avoids
    # marking multi-level hierarchies as padded when only leaves are raised.
    padded = sorted(
        base
        for base in shared_zone_bases
        if base not in raised_names
        and not any(d in raised_names for d in base_to_descendants.get(base, set()))
    )
    # zone-local documented_bases: shared zone base with docstring + raised use
    documented_bases = []
    for base in shared_zone_bases:
        cls = classes_by_name.get(base)
        if cls and cls["has_docstring"]:
            descendants = base_to_descendants.get(base, set())
            if base in raised_names or any(d in raised_names for d in descendants):
                documented_bases.append(base)
    # repo-level documented bases relevant to this zone: a custom base in
    # `repo_shared_bases` whose declaring class (anywhere in the scan) has a
    # docstring, and at least one of its subclasses is raised **in this
    # zone**. The zone-local usage requirement avoids inflating zone B's
    # score when only zone A raises the hierarchy. A single subclass per zone
    # still counts as repo-level hierarchy, but zone B must observe an active
    # failure path of its own to score 3.
    repo_documented_bases = []
    flat_by_name = {c["name"]: c for c in flat_classes}
    # Direct children of each base across the whole repo.
    repo_base_subclasses: dict[str, list[str]] = {}
    for c in flat_classes:
        for base in c["bases"]:
            if base not in all_custom_class_names:
                continue
            repo_base_subclasses.setdefault(base, []).append(c["name"])
    # Transitive descendants across the whole repo (used for usage checks).
    def _repo_descendants(base: str, seen: set[str] | None = None) -> set[str]:
        if seen is None:
            seen = set()
        if base in seen:
            return set()
        seen.add(base)
        out: set[str] = set()
        for child in repo_base_subclasses.get(base, []):
            out.add(child)
            out.update(_repo_descendants(child, seen))
        return out
    # Per-zone classes mapped to their direct repo bases.
    classes_in_zone = {c["name"] for c in flat_classes if c["zone"] == zone}
    for base in repo_shared_bases:
        decl = flat_by_name.get(base)
        if not decl or not decl["has_docstring"]:
            continue
        repo_descendants = _repo_descendants(base)
        zone_descendants = repo_descendants & classes_in_zone
        # A base counts toward zone-X's score 3 only when zone-X has either
        # the base itself or one of its transitive descendants raised locally.
        zone_uses_hierarchy = (
            base in raised_names
            or any(d in raised_names for d in zone_descendants)
        )
        if zone_uses_hierarchy:
            repo_documented_bases.append(base)
    repo_documented_bases.sort()
    return {
        "custom_exception_classes": len(zone_classes),
        "shared_zone_bases": shared_zone_bases,
        "repo_shared_bases": repo_shared_bases,
        "documented_bases": documented_bases,
        "repo_documented_bases": repo_documented_bases,
        "padded_hierarchy_bases": padded,
        "enforced_check": enforced_check,
        "raised_class_names": sorted(raised_names),
    }


def _score_from_inputs(score_inputs: dict[str, Any]) -> int:
    """Apply the v0 cooling_metrics rubric.

    The order matters: a documented repo-level common base scores 3 (or 4 with
    enforcement) regardless of whether the base has zone-local fan-out, because
    the rubric describes the *repo* shape, not a per-zone hierarchy fan-out.
    """
    n_classes = score_inputs["custom_exception_classes"]
    if n_classes == 0:
        return 0
    repo_documented = score_inputs.get("repo_documented_bases") or []
    if repo_documented:
        if score_inputs["enforced_check"]:
            return 4
        return 3
    shared_zone = [
        b
        for b in score_inputs["shared_zone_bases"]
        if b not in score_inputs["padded_hierarchy_bases"]
    ]
    if not shared_zone:
        return 1
    # zone-local hierarchy with usage but no documented repo-level base
    return 2


def _build_summary(
    files: list[dict[str, Any]],
    skipped_files: list[dict[str, str]],
    flat_classes: list[dict[str, Any]],
    zones: list[str],
    enforced_check: str | None,
) -> dict[str, Any]:
    by_kind = _empty_kind_counts()
    parse_errors = 0
    files_with_detections = 0
    detections_by_zone: dict[str, list[dict[str, Any]]] = {}
    for entry in files:
        if entry.get("status") == "parse_error":
            parse_errors += 1
        detections = entry.get("detections", [])
        if detections:
            files_with_detections += 1
        _accumulate_kind_counts(by_kind, detections)
        detections_by_zone.setdefault(entry["zone"], []).extend(detections)

    by_zone: dict[str, Any] = {}
    # Use normalized zone labels in the summary so `--zones ./src` and
    # `--zones src/` produce identical checkpoint JSON. Drop empty-string
    # ("." normalized) so it appears under its original spelling label
    # already assigned to file entries.
    normalized_zones: list[str] = []
    for z in zones:
        normed = _normalize_zone(z)
        # If a zone normalizes to "" (whole-repo "."), keep the original label
        # because that's how files were tagged.
        normalized_zones.append(z if normed == "" else normed)
    all_zones = sorted(set([entry["zone"] for entry in files]) | set(normalized_zones))
    per_zone_score: dict[str, int] = {}
    for zone in all_zones:
        zone_files = [entry for entry in files if entry["zone"] == zone]
        zone_kind_counts = _empty_kind_counts()
        for entry in zone_files:
            _accumulate_kind_counts(zone_kind_counts, entry.get("detections", []))
        score_inputs = _zone_score_inputs(
            zone, flat_classes, detections_by_zone, enforced_check
        )
        score = _score_from_inputs(score_inputs)
        per_zone_score[zone] = score
        by_zone[zone] = {
            "total_files": len(zone_files),
            "files_with_detections": sum(
                1 for e in zone_files if e.get("detections")
            ),
            "by_kind": zone_kind_counts,
            "score_inputs": score_inputs,
            "exception_topology_score": score,
        }
    # Repo aggregate: minimum across non-empty zones (a single zone with no
    # hierarchy cannot be hidden by a strong neighbour).
    non_empty = [
        per_zone_score[z]
        for z in per_zone_score
        if by_zone[z]["total_files"] > 0
    ]
    repo_score = min(non_empty) if non_empty else 0
    return {
        "total_files": len(files),
        "files_with_detections": files_with_detections,
        "parse_errors": parse_errors,
        "skipped_files": len(skipped_files),
        "by_kind": by_kind,
        "by_zone": by_zone,
        "exception_topology_score": {
            "per_zone": per_zone_score,
            "repo": repo_score,
        },
    }


# ── File walking ────────────────────────────────────────────────────────────


def _iter_zone_files(
    root: Path,
    zones: list[str],
    extra_excludes: list[str],
    include_init: bool,
) -> tuple[list[Path], list[dict[str, str]]]:
    py_files: list[Path] = []
    skipped: list[dict[str, str]] = []
    seen: set[Path] = set()
    root_resolved = root.resolve()
    for zone in zones:
        zone_norm = _normalize_zone(zone)
        zone_dir = (root_resolved if zone_norm == "" else root_resolved / zone_norm).resolve()
        # Reject zones that escape the repo root (e.g. `..`, absolute paths).
        # The census is repo-relative by contract; out-of-root scans would
        # crash later at relative_to() and would silently scan files the
        # operator did not intend to include.
        try:
            zone_dir.relative_to(root_resolved)
        except ValueError:
            skipped.append(
                {
                    "path": zone,
                    "reason": (
                        f"zone resolves outside the root ({zone_dir}); "
                        "zones must be repo-relative paths under --root"
                    ),
                }
            )
            continue
        if not zone_dir.is_dir():
            skipped.append(
                {
                    "path": zone,
                    "reason": f"zone directory not found under {root}",
                }
            )
            continue
        for path in sorted(zone_dir.rglob("*.py")):
            if path in seen or not path.is_file():
                continue
            rel = str(path.relative_to(root)).replace("\\", "/")
            if path.name == DEFAULT_INIT_EXCLUSION and not include_init:
                skipped.append(
                    {
                        "path": rel,
                        "reason": "__init__.py excluded by default; pass --include-init",
                    }
                )
                continue
            excluded = False
            for pattern in extra_excludes:
                if fnmatch.fnmatch(rel, pattern):
                    skipped.append(
                        {
                            "path": rel,
                            "reason": f"matched --exclude pattern {pattern!r}",
                        }
                    )
                    excluded = True
                    break
            if excluded:
                continue
            seen.add(path)
            py_files.append(path)
    return py_files, skipped


def _check_exclude_patterns_used(
    extra_excludes: list[str], skipped: list[dict[str, str]]
) -> list[str]:
    """Return any --exclude patterns that did not match anything."""
    used: set[str] = set()
    for entry in skipped:
        reason = entry.get("reason", "")
        if reason.startswith("matched --exclude pattern "):
            patt = reason.split("matched --exclude pattern ")[1].strip().strip("'\"")
            used.add(patt)
    return [p for p in extra_excludes if p not in used]


# ── Public entry points ─────────────────────────────────────────────────────


def scan(
    root: Path,
    zones: list[str] | None = None,
    extra_excludes: list[str] | None = None,
    include_init: bool = False,
    scan_date: str | None = None,
    enforced_check: str | None = None,
) -> dict[str, Any]:
    """Scan zones and return a structured error topology census."""
    root = root.resolve()
    zones = list(zones) if zones else list(DEFAULT_ZONES)
    extra_excludes = list(extra_excludes or [])
    py_files, skipped_files = _iter_zone_files(
        root, zones, extra_excludes, include_init
    )
    # Pass 1: parse every file once and collect class declarations.
    parsed_cache: dict[Path, tuple[str, ast.Module]] = {}
    parse_failures: dict[Path, dict[str, Any]] = {}
    all_decls: list[dict[str, Any]] = []
    for path in py_files:
        result = _parse_file(path)
        if isinstance(result[1], BaseException):
            err = result[1]
            status = "read_error" if isinstance(err, OSError) else "parse_error"
            rel_path = str(path.relative_to(root)).replace("\\", "/")
            parse_failures[path] = {
                "path": rel_path,
                "zone": _zone_for_path(rel_path, zones),
                "status": status,
                "error": str(err),
                "detections": [],
                "file_flags": {flag: False for flag in FILE_FLAGS},
            }
            continue
        parsed_cache[path] = result  # type: ignore[assignment]
        all_decls.extend(_collect_class_decls(result[1]))
    known_exc_names = _expand_exception_like_names(all_decls)

    # Pass 2: full inspection with the known set available.
    files: list[dict[str, Any]] = []
    for path in py_files:
        if path in parse_failures:
            files.append(parse_failures[path])
            continue
        files.append(
            inspect_file(
                path,
                root,
                zones,
                known_exc_names=known_exc_names,
                cached=parsed_cache.get(path),
            )
        )
    flat_classes, inheritance = _build_inheritance(files)
    summary = _build_summary(files, skipped_files, flat_classes, zones, enforced_check)
    # Strip the internal `_classes` field before emission.
    public_files = [
        {k: v for k, v in entry.items() if not k.startswith("_")} for entry in files
    ]
    public_files.sort(key=lambda e: e["path"])
    skipped_files.sort(key=lambda e: e["path"])

    unused_excludes = _check_exclude_patterns_used(extra_excludes, skipped_files)

    return {
        "scan_date": scan_date or date.today().isoformat(),
        "harness_version": HARNESS_VERSION,
        "scope": {
            "zones": zones,
            "default_exclusions": [DEFAULT_INIT_EXCLUSION],
            "extra_excludes": extra_excludes,
            "unused_extra_excludes": unused_excludes,
            "include_init": include_init,
            "enforced_check": enforced_check,
        },
        "summary": summary,
        "kinds": list(KINDS),
        "limitations": list(LIMITATIONS),
        "exception_classes": flat_classes,
        "inheritance": dict(sorted(inheritance.items())),
        "files": public_files,
        "skipped_files": skipped_files,
    }


def render_markdown(report: dict[str, Any], max_hot_files: int = 25) -> str:
    summary = report["summary"]
    score = summary["exception_topology_score"]
    lines = [
        "# Error Topology Census",
        "",
        f"- scan_date: {report['scan_date']}",
        f"- harness_version: {report['harness_version']}",
        f"- zones: {', '.join(report['scope']['zones'])}",
        f"- total_files: {summary['total_files']}",
        f"- skipped_files: {summary['skipped_files']}",
        f"- parse_errors: {summary['parse_errors']}",
        "",
        "## Topology Score (cooling_metrics_v0 rubric, 0..4)",
        "",
        f"- repo (min over non-empty zones): {score['repo']}",
    ]
    for zone, value in sorted(score["per_zone"].items()):
        lines.append(f"- {zone}: {value}")
    lines.extend(["", "## Kind Counts", "", "| kind | files | detections |", "|---|---:|---:|"])
    for kind in KIND_NAMES:
        c = summary["by_kind"][kind]
        lines.append(f"| {kind} | {c['files']} | {c['detections']} |")
    lines.extend(["", "## Per-zone breakdown", ""])
    for zone, info in sorted(summary["by_zone"].items()):
        lines.append(f"### {zone} (score {info['exception_topology_score']})")
        lines.append("")
        lines.append(f"- total_files: {info['total_files']}")
        lines.append(f"- files_with_detections: {info['files_with_detections']}")
        si = info["score_inputs"]
        lines.append(f"- custom_exception_classes: {si['custom_exception_classes']}")
        lines.append(f"- shared_zone_bases: {si['shared_zone_bases']}")
        lines.append(f"- repo_shared_bases: {si['repo_shared_bases']}")
        lines.append(f"- documented_bases: {si['documented_bases']}")
        lines.append(f"- padded_hierarchy_bases: {si['padded_hierarchy_bases']}")
        lines.append(f"- enforced_check: {si['enforced_check']}")
        lines.append("")
    lines.extend(["## Hot files", ""])
    hot = [e for e in report["files"] if e.get("detections")]
    hot.sort(key=lambda e: -len(e["detections"]))
    if not hot:
        lines.append("No detections.")
    else:
        for entry in hot[:max_hot_files]:
            kinds = sorted({d["kind"] for d in entry["detections"]})
            flags = sorted(k for k, v in entry["file_flags"].items() if v)
            tag = f" [{', '.join(flags)}]" if flags else ""
            lines.append(f"- {entry['path']}: {len(entry['detections'])} ({', '.join(kinds)}){tag}")
        omitted = len(hot) - min(max_hot_files, len(hot))
        if omitted > 0:
            lines.append(f"- ... {omitted} more files omitted from markdown summary")
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {item}" for item in report["limitations"])
    return "\n".join(lines) + "\n"


# ── CLI ────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Circle-1 error topology census harness"
    )
    parser.add_argument("--root", default=".", help="Repo root directory")
    parser.add_argument("--output", default=None, help="Optional output path")
    parser.add_argument(
        "--scan-date", default=None, help="ISO date to embed in the report"
    )
    parser.add_argument(
        "--zones",
        default=",".join(DEFAULT_ZONES),
        help=(
            "Comma-separated list of repo-relative zones to scan. "
            "Default: src/wea_cli,scripts"
        ),
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        help=(
            "fnmatch pattern (repo-relative path) to exclude. May be passed "
            "multiple times. An unused pattern is reported in the JSON."
        ),
    )
    parser.add_argument(
        "--include-init",
        action="store_true",
        help="Include __init__.py files instead of reporting them as skipped",
    )
    parser.add_argument(
        "--enforced-check",
        default=None,
        help=(
            "Path or label of an operator-supplied enforcement artifact. "
            "Required for exception_topology_score = 4."
        ),
    )
    parser.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="json",
        help="Output format; JSON is the checkpointable default",
    )
    parser.add_argument(
        "--max-hot-files",
        type=int,
        default=25,
        help="Maximum hot files shown in markdown summary; JSON is unaffected",
    )
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"ERROR: not a directory: {root}", file=sys.stderr)
        return 1
    zones = [z.strip() for z in args.zones.split(",") if z.strip()]
    if not zones:
        print("ERROR: --zones produced an empty zone list", file=sys.stderr)
        return 1
    missing = []
    out_of_root = []
    for z in zones:
        norm = _normalize_zone(z)
        candidate = (root if norm == "" else root / norm).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            out_of_root.append(z)
            continue
        if not candidate.is_dir():
            missing.append(z)
    if out_of_root:
        print(
            f"ERROR: zones must be repo-relative paths under --root; "
            f"these escape: {out_of_root}",
            file=sys.stderr,
        )
        return 1
    if missing:
        print(
            f"ERROR: zone directories not found under {root}: {missing}",
            file=sys.stderr,
        )
        return 1

    report = scan(
        root,
        zones=zones,
        extra_excludes=list(args.exclude),
        include_init=args.include_init,
        scan_date=args.scan_date,
        enforced_check=args.enforced_check,
    )

    if report["summary"]["parse_errors"] > 0:
        print(
            f"WARNING: {report['summary']['parse_errors']} files failed to "
            f"parse; see entries with status=parse_error under files[] in the "
            f"JSON output",
            file=sys.stderr,
        )
    if report["scope"]["unused_extra_excludes"]:
        print(
            f"WARNING: --exclude patterns matched no files: "
            f"{report['scope']['unused_extra_excludes']}",
            file=sys.stderr,
        )

    payload = (
        json.dumps(report, indent=2, sort_keys=True)
        if args.format == "json"
        else render_markdown(report, max_hot_files=args.max_hot_files)
    )
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            payload + ("" if payload.endswith("\n") else "\n"), encoding="utf-8"
        )
        print(f"Saved: {output_path}", file=sys.stderr)
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
