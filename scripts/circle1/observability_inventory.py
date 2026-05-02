"""Observability inventory harness for the scripts/ zone (Circle-1 v0).

Goal: produce a runnable, AST-based inventory of how `scripts/**/*.py`
emits information and mutates outside state. The harness is measurement,
not enforcement: it never fails, never gates, never edits ledger or
issue templates. Agent0 inspects the JSON output to decide whether
follow-up hardening tasks matter.

Channel families (Circle-1 observability_discipline):

    stdout_human       - direct human/CLI output (print, click.echo, sys.stdout.write)
    stderr             - error channel output (print(file=sys.stderr), sys.stderr.write,
                         click.echo(err=True), logging to stderr handlers)
    logging            - logging module usage (getLogger, basicConfig, log calls)
    file_artifact      - structured/text/JSON file writes outside ledger/
    ledger_write       - file writes whose target path is under ledger/
    github_side_effect - gh CLI invocations or HTTP calls to api.github.com
    subprocess_launch  - subprocess.run/Popen/check_output, os.system, os.popen
    network_external   - requests/httpx/urllib HTTP calls (excluding api.github.com)
    ambiguous          - statically visible call shape that may be a side effect
                         but cannot be classified with high confidence

Each detection records: channel, lineno, evidence snippet, reason. Files
that fail to parse are recorded with a parse_error reason; nothing is
silently skipped except __init__.py (excluded by default).

Output JSON shape (stable; see SCHEMA constant):

    {
      "scan_date": "...",
      "harness_version": "v0",
      "root_zone": "scripts",
      "exclude_patterns": ["__init__.py"],
      "channel_taxonomy": {channel: short prose intent},
      "limitations": [...],
      "summary": {
        "total_files": int,
        "files_with_any_channel": int,
        "files_unparseable": int,
        "by_channel": {channel: {"files": int, "occurrences": int}}
      },
      "files": [
        {
          "path": "scripts/...",
          "parse_error": null | "...",
          "channels": [
            {"channel": "...", "lineno": int, "evidence": "...", "reason": "..."}
          ]
        },
        ...
      ]
    }

Usage:

    python scripts/circle1/observability_inventory.py --root . [--output PATH]
    python scripts/circle1/observability_inventory.py --root . --markdown summary.md
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

HARNESS_VERSION = "v0"

CHANNEL_TAXONOMY: dict[str, str] = {
    "stdout_human": (
        "Direct human-readable CLI output: print() without file=, "
        "click.echo without err=True, sys.stdout.write."
    ),
    "stderr": (
        "Error channel output: print(file=sys.stderr), sys.stderr.write, "
        "click.echo(..., err=True)."
    ),
    "logging": (
        "stdlib logging usage: logging.getLogger, logging.basicConfig, "
        "logger.info/.error/etc., logging.<level> module functions."
    ),
    "file_artifact": (
        "File writes outside ledger/: Path.write_text/write_bytes, "
        "open(path, 'w'|'a'|'x'|...), json.dump, file_obj.write."
    ),
    "ledger_write": (
        "File writes whose target path string is under ledger/. "
        "Reported in addition to file_artifact for visibility."
    ),
    "github_side_effect": (
        "GitHub-mutating side effects: subprocess invocations of `gh` CLI, "
        "or HTTP requests targeting api.github.com."
    ),
    "subprocess_launch": (
        "Process launch: subprocess.run/Popen/check_output/check_call/call, "
        "os.system, os.popen, os.exec*."
    ),
    "network_external": (
        "Outbound HTTP via requests / httpx / urllib.request when statically "
        "visible. api.github.com hits are reclassified as github_side_effect."
    ),
    "ambiguous": (
        "Call shape that resembles a side effect but cannot be classified "
        "with high confidence (e.g. dynamic getattr, unresolved variable "
        "as subprocess command)."
    ),
}

LIMITATIONS: list[str] = [
    (
        "AST-only, single-file: dynamic dispatch (getattr, importlib, "
        "callable variables) is not resolved across files. A helper that "
        "wraps subprocess.run inside another module is detected at the "
        "wrapper site, not at the caller."
    ),
    (
        "Aliased imports are best-effort: `import logging as L; L.info(...)` "
        "is detected, but deeply renamed re-exports (`from x import y as z`) "
        "may be missed when the source module is itself a wrapper."
    ),
    (
        "ledger_write classification depends on path strings visible at the "
        "call site. A computed path (variable joined from parts not seen "
        "statically) lands in file_artifact only; ledger_write may "
        "under-report."
    ),
    (
        "github_side_effect detects `gh` as a subprocess argv[0] string and "
        "literal substrings like 'api.github.com'. Wrappers that hide this "
        "(e.g. a custom `gh_run()` helper using a constant defined "
        "elsewhere) are recorded as subprocess_launch only."
    ),
    (
        "Logging detection counts logger calls inside function bodies even "
        "though they only run when the function is invoked. The harness "
        "measures *capability* to emit on a channel, not import-time emission."
    ),
    (
        "Bound-logger detection has two signals. (1) Receivers assigned from "
        "a `logging.getLogger(...)` call (any name — `audit`, `metrics`, "
        "`tracer`, etc.) are tracked and classified accurately. (2) Receivers "
        "with no tracked binding are matched only when the receiver name is "
        "exactly `logger`/`log` or ends in `logger`. This drops false hits on "
        "`dialog.error`, `catalog.warning`. Logger names that do not match "
        "either signal (e.g. parameter `tracer` passed in from another "
        "module) remain a documented miss."
    ),
    (
        "Open-modes: open() with no mode argument defaults to 'r' (read-only) "
        "and is not flagged. Pathlib's Path.read_* are reads, not writes, "
        "and are also not flagged. Only mode strings containing 'w', 'a', "
        "'x', or '+' count as artifact writes."
    ),
    (
        "Test fixtures and tmp_path writes inside scripts/ would be flagged "
        "if any existed. The harness does not distinguish test temp writes "
        "from production artifact writes; that is a callers' concern."
    ),
    (
        "Excludes only __init__.py by default. Nested scripts/ files are "
        "always included. Any other exclusion must be passed explicitly via "
        "--exclude and is reflected in exclude_patterns in the output."
    ),
    (
        "`from X import Y` populates the alias table: bare calls to Y "
        "(e.g. `from subprocess import run; run([...])`, `from logging "
        "import getLogger as gl; gl(__name__)`) resolve through the "
        "canonical-chain machinery into ['subprocess', 'run'] / ['logging', "
        "'getLogger'] and reach the same per-channel classifiers as the "
        "attribute-call form. Star imports (`from X import *`) and relative "
        "imports without a module are skipped — there is no canonical name "
        "to record."
    ),
    (
        "HTTP via long-lived Session/Client objects is not classified: "
        "`s = requests.Session(); s.get(url)` is a chained call whose "
        "receiver chain is broken by Session(). Tail-only fallback only "
        "covers write_text/write_bytes/open — not get/post/etc. — to avoid "
        "false positives on arbitrary `obj.get()` accessors."
    ),
]

# ---------------------------------------------------------------------------
# Detection records
# ---------------------------------------------------------------------------


@dataclass
class Detection:
    channel: str
    lineno: int
    evidence: str
    reason: str

    def to_dict(self) -> dict:
        return {
            "channel": self.channel,
            "lineno": self.lineno,
            "evidence": self.evidence,
            "reason": self.reason,
        }


@dataclass
class FileReport:
    path: str
    parse_error: str | None = None
    channels: list[Detection] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "parse_error": self.parse_error,
            "channels": [d.to_dict() for d in self.channels],
        }


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------


def _attr_chain(node: ast.AST) -> list[str] | None:
    """Return the dotted attribute chain for *node* if it is purely
    Name/Attribute, else None.

    Examples:
        sys.stderr.write -> ["sys", "stderr", "write"]
        x.y              -> ["x", "y"]
        f()              -> None  (Call interrupts the chain)
    """
    parts: list[str] = []
    cur: ast.AST | None = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
        return list(reversed(parts))
    return None


def _evidence_for(node: ast.AST, source_lines: list[str]) -> str:
    """Best-effort short snippet for *node*. Falls back to the first line of
    its line range. Truncated to 160 characters.
    """
    try:
        seg = ast.get_source_segment("\n".join(source_lines), node)
        if seg:
            seg = seg.strip().splitlines()[0]
            return seg[:160]
    except Exception:  # pragma: no cover - defensive
        pass
    lineno = getattr(node, "lineno", 1)
    if 1 <= lineno <= len(source_lines):
        return source_lines[lineno - 1].strip()[:160]
    return ""


def _str_constant(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


# ---------------------------------------------------------------------------
# Visitor
# ---------------------------------------------------------------------------

# Logging level method names. Both the module-level shortcuts
# (logging.info(...)) and bound logger methods (logger.info(...)) use the
# same names, so a single set covers both call shapes.
_LOG_LEVELS = {
    "debug",
    "info",
    "warning",
    "warn",
    "error",
    "exception",
    "critical",
    "log",
}

_SUBPROCESS_FUNCS = {"run", "Popen", "call", "check_call", "check_output"}
_OS_PROCESS_FUNCS = {
    "system",
    "popen",
    "execv",
    "execvp",
    "execvpe",
    "execve",
    "execl",
    "execle",
    "execlp",
    "execlpe",
    "spawnl",
    "spawnle",
    "spawnlp",
    "spawnlpe",
    "spawnv",
    "spawnve",
    "spawnvp",
    "spawnvpe",
}
_HTTP_LIBS = {"requests", "httpx"}
_HTTP_VERBS = {"get", "post", "put", "delete", "patch", "head", "options", "request"}


class ObservabilityVisitor(ast.NodeVisitor):
    def __init__(self, source_lines: list[str], aliases: dict[str, str]) -> None:
        self.source_lines = source_lines
        # local_name -> canonical dotted path. For `import logging` and
        # `import logging as L` the value is just "logging" (single segment).
        # For `from subprocess import run` the value is "subprocess.run"
        # (multi-segment) so canonical-chain machinery can match bare calls
        # to `run(...)` against `_classify_process` etc.
        self.aliases = aliases
        # Local names bound to a logging.getLogger() result. Populated by
        # visit_Assign; consulted by _classify_logging to mark bound-logger
        # calls without relying on substring heuristics.
        self.logger_bindings: set[str] = set()
        self.detections: list[Detection] = []

    # -- helpers ------------------------------------------------------------

    def _emit(self, channel: str, node: ast.AST, reason: str) -> None:
        self.detections.append(
            Detection(
                channel=channel,
                lineno=getattr(node, "lineno", 0),
                evidence=_evidence_for(node, self.source_lines),
                reason=reason,
            )
        )

    def _resolve_root(self, name: str) -> str:
        """Map a local Name id to its canonical module name via the alias
        table built from imports. Falls back to the raw id."""
        return self.aliases.get(name, name)

    def _canonical_chain(self, chain: list[str]) -> list[str]:
        """Resolve the leftmost segment of an attribute chain through the
        alias table. ``L.getLogger`` with ``import logging as L`` becomes
        ``["logging", "getLogger"]``. ``r(...)`` after ``from subprocess
        import run as r`` resolves head ``r`` to ``"subprocess.run"`` and
        expands to ``["subprocess", "run"]``."""
        if not chain:
            return chain
        head = chain[0]
        resolved = self.aliases.get(head, head)
        if "." in resolved:
            return [*resolved.split("."), *chain[1:]]
        return [resolved, *chain[1:]]

    def _has_kw(self, call: ast.Call, name: str) -> ast.expr | None:
        for kw in call.keywords:
            if kw.arg == name:
                return kw.value
        return None

    # -- per-call dispatch --------------------------------------------------

    def visit_Call(self, node: ast.Call) -> None:
        self._classify_call(node)
        self.generic_visit(node)

    def _classify_call(self, call: ast.Call) -> None:
        func = call.func

        # Bare name: print(), open(), getattr(), etc.
        if isinstance(func, ast.Name):
            self._classify_bare_name(call, func.id)
            return

        chain = _attr_chain(func)
        if chain is not None:
            canonical = self._canonical_chain(chain)
            self._classify_attribute_call(call, chain, canonical)
            return

        # Chain is broken by a Call/Subscript/etc.: e.g. Path("p").write_text("x"),
        # subprocess.Popen(...).communicate(), open(...).write(). The leftmost
        # receiver is unresolvable, but the *terminal* method name is still
        # informative. Classify on the tail alone for the small set of
        # methods whose name strongly signals a write channel.
        if isinstance(func, ast.Attribute):
            self._classify_tail_only(call, func.attr)

    # -- bare-name calls (print, open, getattr) ----------------------------

    def _classify_bare_name(self, call: ast.Call, name: str) -> None:
        if name == "print":
            self._classify_print(call)
            return
        if name == "open":
            self._classify_open(call)
            return
        # Route from-imports through the attribute-call dispatcher.
        # `from subprocess import run` followed by `run([...])` resolves to
        # canonical ["subprocess", "run"], so the existing _classify_process
        # branch fires the same way it does for `subprocess.run([...])`.
        canonical = self.aliases.get(name)
        if canonical and "." in canonical:
            chain = canonical.split(".")
            self._classify_attribute_call(call, chain, chain)

    def _classify_print(self, call: ast.Call) -> None:
        file_kw = self._has_kw(call, "file")
        if file_kw is None:
            self._emit(
                "stdout_human",
                call,
                "print() without file= keyword (default: sys.stdout)",
            )
            return
        chain = _attr_chain(file_kw)
        if chain is not None:
            canonical = self._canonical_chain(chain)
            if canonical == ["sys", "stderr"]:
                self._emit("stderr", call, "print(..., file=sys.stderr)")
                return
            if canonical == ["sys", "stdout"]:
                self._emit("stdout_human", call, "print(..., file=sys.stdout)")
                return
        self._emit(
            "ambiguous",
            call,
            "print() with non-sys file= argument (possibly a file handle)",
        )

    def _classify_open(self, call: ast.Call) -> None:
        # open(path, mode='r'). args[0] = path, args[1] = mode (optional).
        mode = self._extract_open_mode_from_args(call, mode_index=1)
        if mode == "?":
            self._emit(
                "ambiguous",
                call,
                "open() with non-literal mode; cannot classify read vs write",
            )
            return
        if mode is None:
            return  # default 'r' — read-only, not flagged
        if any(c in mode for c in ("w", "a", "x", "+")):
            path_str = _str_constant(call.args[0]) if call.args else None
            self._emit(
                "file_artifact",
                call,
                f"open(..., mode={mode!r}) — write/append/exclusive/update mode",
            )
            if path_str and self._is_ledger_path(path_str):
                self._emit(
                    "ledger_write",
                    call,
                    f"open(..., mode={mode!r}) targets ledger path {path_str!r}",
                )

    # -- attribute-call dispatch -------------------------------------------

    def _classify_attribute_call(
        self,
        call: ast.Call,
        original: list[str],
        canonical: list[str],
    ) -> None:
        # logging family
        if self._classify_logging(call, canonical):
            return
        # click / typer
        if self._classify_click_like(call, canonical):
            return
        # sys.stdout / sys.stderr writes
        if self._classify_std_streams(call, canonical):
            return
        # subprocess / os process funcs
        if self._classify_process(call, original, canonical):
            return
        # HTTP libs
        if self._classify_http(call, canonical):
            return
        # Path / json file writes
        if self._classify_path_or_json_write(call, original, canonical):
            return

    def _classify_logging(self, call: ast.Call, canonical: list[str]) -> bool:
        # Module-level: logging.getLogger / logging.basicConfig / logging.info
        if canonical and canonical[0] == "logging" and len(canonical) >= 2:
            tail = canonical[-1]
            if tail in {"getLogger", "basicConfig"}:
                self._emit(
                    "logging", call, f"logging.{tail}() — logging configuration"
                )
                return True
            if tail in _LOG_LEVELS:
                self._emit(
                    "logging", call, f"logging.{tail}() — module-level log emission"
                )
                return True
        # Bound logger: <name>.info(...). Two signals, in order of strength:
        #   1. Tracked binding from `<name> = logging.getLogger(...)`. This
        #      catches `audit.info(...)`, `metrics.error(...)`, `tracer.debug(...)`
        #      which the prior substring heuristic missed.
        #   2. Narrow name heuristic: receiver name is exactly `logger`/`log`
        #      or ends in `logger`. This avoids false-firing on `dialog.error`,
        #      `catalog.warning`, etc., while still catching parameter names
        #      like `audit_logger` whose binding is not local.
        if (
            len(canonical) == 2
            and canonical[1] in _LOG_LEVELS
            and canonical[0]
            not in {
                "logging",
                "sys",
                "os",
                "subprocess",
                "requests",
                "httpx",
                "urllib",
                "json",
            }
        ):
            root_name = canonical[0]
            if root_name in self.logger_bindings:
                self._emit(
                    "logging",
                    call,
                    (
                        f"{root_name}.{canonical[1]}() — bound logger call "
                        "(receiver tracked as logging.getLogger result)"
                    ),
                )
                return True
            lower = root_name.lower()
            if lower in {"logger", "log"} or lower.endswith("logger"):
                self._emit(
                    "logging",
                    call,
                    (
                        f"{root_name}.{canonical[1]}() — bound logger call "
                        "(heuristic: receiver name is logger/<…>logger)"
                    ),
                )
                return True
        return False

    def _classify_click_like(self, call: ast.Call, canonical: list[str]) -> bool:
        if not canonical:
            return False
        root = canonical[0]
        if root in {"click", "typer"} and canonical[-1] in {"echo", "secho"}:
            err_kw = self._has_kw(call, "err")
            if isinstance(err_kw, ast.Constant) and err_kw.value is True:
                self._emit("stderr", call, f"{root}.{canonical[-1]}(err=True)")
            else:
                self._emit(
                    "stdout_human",
                    call,
                    f"{root}.{canonical[-1]}() — CLI human output",
                )
            return True
        return False

    def _classify_std_streams(self, call: ast.Call, canonical: list[str]) -> bool:
        if len(canonical) >= 3 and canonical[0] == "sys":
            if canonical[1] == "stderr" and canonical[2] in {"write", "writelines"}:
                self._emit("stderr", call, "sys.stderr.write(...)")
                return True
            if canonical[1] == "stdout" and canonical[2] in {"write", "writelines"}:
                self._emit("stdout_human", call, "sys.stdout.write(...)")
                return True
        return False

    def _classify_process(
        self,
        call: ast.Call,
        original: list[str],
        canonical: list[str],
    ) -> bool:
        if not canonical:
            return False
        # subprocess.run / Popen / etc.
        if canonical[0] == "subprocess" and canonical[-1] in _SUBPROCESS_FUNCS:
            cmd_first = self._first_command_token(call)
            reason = f"subprocess.{canonical[-1]}(...)"
            self._emit("subprocess_launch", call, reason)
            if cmd_first == "gh":
                self._emit(
                    "github_side_effect",
                    call,
                    "subprocess invocation of `gh` CLI",
                )
            elif cmd_first is None:
                self._emit(
                    "ambiguous",
                    call,
                    "subprocess call with non-literal first command argument; "
                    "cannot determine whether it shells out to gh, git, etc.",
                )
            return True
        # os.system / popen / exec / spawn. The github-trigger first-token
        # check applies uniformly to every entry in _OS_PROCESS_FUNCS that
        # accepts a literal command string. system/popen typically pass the
        # whole command line as a single string ("gh issue list"); exec*/
        # spawn* take an explicit argv0 path that almost never spells "gh"
        # alone, so they fall through harmlessly.
        if canonical[0] == "os" and canonical[-1] in _OS_PROCESS_FUNCS:
            self._emit("subprocess_launch", call, f"os.{canonical[-1]}(...)")
            arg_first = (
                _str_constant(call.args[0]) if call.args else None
            )
            if arg_first and arg_first.strip().split()[:1] == ["gh"]:
                self._emit(
                    "github_side_effect",
                    call,
                    f"os.{canonical[-1]} invokes `gh`",
                )
            return True
        return False

    def _first_command_token(self, call: ast.Call) -> str | None:
        """Return the first command token of a subprocess call, or None
        if it cannot be determined statically.

        Handles both ``subprocess.run("gh issue list", shell=True)`` and
        ``subprocess.run(["gh", "issue", "list"])`` shapes.
        """
        if not call.args:
            return None
        first = call.args[0]
        # List literal: ["gh", ...]
        if isinstance(first, (ast.List, ast.Tuple)):
            if first.elts:
                token = _str_constant(first.elts[0])
                if token is None:
                    return None
                return token.strip().split()[0] if token.strip() else None
            return None
        # String literal: "gh issue list"
        literal = _str_constant(first)
        if literal is not None:
            stripped = literal.strip()
            return stripped.split()[0] if stripped else None
        return None

    def _classify_http(self, call: ast.Call, canonical: list[str]) -> bool:
        if not canonical:
            return False
        root = canonical[0]
        if root in _HTTP_LIBS and canonical[-1] in _HTTP_VERBS:
            url = _str_constant(call.args[0]) if call.args else None
            if url and "api.github.com" in url:
                self._emit(
                    "github_side_effect",
                    call,
                    f"{root}.{canonical[-1]} to api.github.com",
                )
            else:
                self._emit(
                    "network_external",
                    call,
                    f"{root}.{canonical[-1]} HTTP call",
                )
            return True
        # urllib.request.urlopen
        if (
            root == "urllib"
            and len(canonical) >= 2
            and canonical[-1] == "urlopen"
        ):
            url = _str_constant(call.args[0]) if call.args else None
            if url and "api.github.com" in url:
                self._emit(
                    "github_side_effect",
                    call,
                    "urllib.request.urlopen to api.github.com",
                )
            else:
                self._emit(
                    "network_external",
                    call,
                    "urllib.request.urlopen HTTP call",
                )
            return True
        return False

    def _classify_path_or_json_write(
        self,
        call: ast.Call,
        original: list[str],
        canonical: list[str],
    ) -> bool:
        if not canonical:
            return False
        tail = canonical[-1]
        # json.dump(obj, file_obj)
        if canonical[0] == "json" and tail == "dump":
            path_hint = self._guess_path_for_dump(call)
            self._emit(
                "file_artifact",
                call,
                "json.dump(...) writes to a file-like object",
            )
            if path_hint and self._is_ledger_path(path_hint):
                self._emit(
                    "ledger_write",
                    call,
                    f"json.dump(...) targets ledger path {path_hint!r}",
                )
            return True
        # Path-like .write_text / .write_bytes — match on the *method name*.
        # We cannot prove the receiver is a Path; flag it and let evidence
        # speak. False positives are rare because these names are unusual.
        if tail in {"write_text", "write_bytes"}:
            self._emit(
                "file_artifact",
                call,
                f".{tail}(...) — Path-style file write",
            )
            return True
        # path.open("w"|"a"|"x"|...) — attribute-call form of open() where
        # the receiver is a Path-like. Mode lives in args[0] (no path arg
        # because `self` is the receiver).
        if tail == "open":
            mode = self._extract_open_mode_from_args(call, mode_index=0)
            if mode == "?":
                self._emit(
                    "ambiguous",
                    call,
                    f".{'.'.join(original)}(...) — open() with non-literal mode",
                )
                return True
            if mode and any(c in mode for c in ("w", "a", "x", "+")):
                self._emit(
                    "file_artifact",
                    call,
                    f".open(mode={mode!r}) — write/append/exclusive/update mode",
                )
                return True
            # mode is "r" or absent — read-only, not flagged.
        return False

    def _extract_open_mode_from_args(
        self, call: ast.Call, mode_index: int
    ) -> str | None:
        """Return the mode string for an open()-style call, or "?" if a
        non-literal was passed, or None if no mode argument is present."""
        if len(call.args) > mode_index:
            literal = _str_constant(call.args[mode_index])
            return literal if literal is not None else "?"
        mode_kw = self._has_kw(call, "mode")
        if mode_kw is not None:
            literal = _str_constant(mode_kw)
            return literal if literal is not None else "?"
        return None

    def _guess_path_for_dump(self, call: ast.Call) -> str | None:
        """Best-effort: json.dump(obj, fp) — fp is rarely a literal string,
        but if a previous `with open("ledger/...", "w") as fp:` is in scope
        the AST does not carry the binding cheaply. Return None unless the
        second argument is itself a Constant string (extremely rare)."""
        if len(call.args) >= 2:
            return _str_constant(call.args[1])
        return None

    def _is_ledger_path(self, path: str) -> bool:
        norm = path.replace("\\", "/").lstrip("./")
        return norm.startswith("ledger/") or "/ledger/" in norm

    # -- tail-only fallback for chains broken by a Call ---------------------

    def _classify_tail_only(self, call: ast.Call, tail: str) -> None:
        """When the receiver chain contains a Call (e.g. Path('p').write_text),
        the leftmost identifier is unresolvable but the method name is still
        informative. Classify on the tail alone for unambiguous write methods.

        Inner calls (Path('p'), Path('p').open(...)) are still walked by
        generic_visit and classified independently.
        """
        if tail in {"write_text", "write_bytes"}:
            self._emit(
                "file_artifact",
                call,
                f".{tail}(...) — Path-style file write (chained)",
            )
            return
        if tail == "open":
            mode = self._extract_open_mode_from_args(call, mode_index=0)
            if mode == "?":
                self._emit(
                    "ambiguous",
                    call,
                    "chained .open() with non-literal mode",
                )
                return
            if mode and any(c in mode for c in ("w", "a", "x", "+")):
                self._emit(
                    "file_artifact",
                    call,
                    (
                        f"chained .open(mode={mode!r}) — "
                        "write/append/exclusive/update mode"
                    ),
                )

    # -- bare-name resolution from imports ---------------------------------

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            local = alias.asname or alias.name.split(".")[0]
            # For `import a.b.c` without asname, the local name is `a`.
            # We map `a` -> `a` (canonical root). For `import logging as L`,
            # we map `L` -> `logging`.
            canonical_root = alias.name.split(".")[0]
            self.aliases[local] = canonical_root
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        # `from subprocess import run` -> aliases["run"] = "subprocess.run".
        # `from logging import getLogger as gl` -> aliases["gl"] =
        # "logging.getLogger". Bare calls (`run(...)`, `gl(...)`) then
        # resolve through _canonical_chain into ["subprocess", "run"] /
        # ["logging", "getLogger"] and reach the existing per-channel
        # classifiers without a duplicate code path.
        #
        # Star imports and relative imports without a module are skipped:
        # we have no canonical name to record.
        module = node.module
        if module:
            for alias in node.names:
                if alias.name == "*":
                    continue
                local = alias.asname or alias.name
                self.aliases[local] = f"{module}.{alias.name}"
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        # Track `<name> = logging.getLogger(...)` (or via alias / from-import)
        # so receiver-name agnostic bound-logger calls can be classified.
        # Only single-target Name assignments are tracked; tuple unpacking
        # and attribute targets (`self.log = ...`) are out of scope.
        value = node.value
        if isinstance(value, ast.Call):
            canonical = self._canonical_call_chain(value.func)
            if (
                canonical
                and canonical[0] == "logging"
                and canonical[-1] == "getLogger"
            ):
                for tgt in node.targets:
                    if isinstance(tgt, ast.Name):
                        self.logger_bindings.add(tgt.id)
        self.generic_visit(node)

    def _canonical_call_chain(self, func: ast.AST) -> list[str] | None:
        """Resolve the function part of a Call to a canonical dotted chain
        if possible. Used by visit_Assign to recognise getLogger bindings."""
        if isinstance(func, ast.Name):
            mapped = self.aliases.get(func.id)
            if mapped:
                return mapped.split(".")
            return [func.id]
        chain = _attr_chain(func)
        if chain is None:
            return None
        return self._canonical_chain(chain)


# ---------------------------------------------------------------------------
# File scanning
# ---------------------------------------------------------------------------


def scan_file(path: Path, root: Path) -> FileReport:
    rel = str(path.relative_to(root)).replace("\\", "/")
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return FileReport(path=rel, parse_error=f"read error: {exc}")

    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return FileReport(path=rel, parse_error=f"SyntaxError: {exc}")

    source_lines = text.splitlines()
    visitor = ObservabilityVisitor(source_lines=source_lines, aliases={})
    visitor.visit(tree)
    # Stable order: sort by (lineno, channel, evidence) to keep diffs small.
    visitor.detections.sort(key=lambda d: (d.lineno, d.channel, d.evidence))
    return FileReport(path=rel, channels=visitor.detections)


def scan_zone(
    root: Path,
    zone: str = "scripts",
    exclude_patterns: list[str] | None = None,
) -> list[FileReport]:
    exclude_patterns = list(exclude_patterns or ["__init__.py"])
    zone_dir = root / zone
    py_files = sorted(
        p
        for p in zone_dir.rglob("*.py")
        if p.is_file() and not _excluded(p, exclude_patterns)
    )
    return [scan_file(p, root) for p in py_files]


def _excluded(path: Path, patterns: list[str]) -> bool:
    name = path.name
    rel = path.as_posix()
    for pat in patterns:
        if pat == name:
            return True
        if pat in rel:
            return True
    return False


# ---------------------------------------------------------------------------
# Aggregation and output
# ---------------------------------------------------------------------------


def build_inventory(
    reports: list[FileReport],
    scan_date: str,
    root_zone: str,
    exclude_patterns: list[str],
) -> dict:
    by_channel: dict[str, dict[str, int]] = {
        ch: {"files": 0, "occurrences": 0} for ch in CHANNEL_TAXONOMY
    }
    files_with_any = 0
    files_unparseable = 0
    for r in reports:
        if r.parse_error:
            files_unparseable += 1
            continue
        if r.channels:
            files_with_any += 1
        seen_in_file: set[str] = set()
        for det in r.channels:
            entry = by_channel.setdefault(
                det.channel, {"files": 0, "occurrences": 0}
            )
            entry["occurrences"] += 1
            if det.channel not in seen_in_file:
                entry["files"] += 1
                seen_in_file.add(det.channel)

    return {
        "scan_date": scan_date,
        "harness_version": HARNESS_VERSION,
        "root_zone": root_zone,
        "exclude_patterns": exclude_patterns,
        "channel_taxonomy": CHANNEL_TAXONOMY,
        "limitations": LIMITATIONS,
        "summary": {
            "total_files": len(reports),
            "files_with_any_channel": files_with_any,
            "files_unparseable": files_unparseable,
            "by_channel": by_channel,
        },
        "files": [r.to_dict() for r in reports],
    }


def render_markdown_summary(inventory: dict) -> str:
    s = inventory["summary"]
    lines = [
        f"# Observability inventory — {inventory['root_zone']}",
        "",
        f"- scan_date: {inventory['scan_date']}",
        f"- harness_version: {inventory['harness_version']}",
        f"- total_files: {s['total_files']}",
        f"- files_with_any_channel: {s['files_with_any_channel']}",
        f"- files_unparseable: {s['files_unparseable']}",
        "",
        "## Channels",
        "",
        "| channel | files | occurrences |",
        "| --- | ---: | ---: |",
    ]
    for ch in CHANNEL_TAXONOMY:
        row = s["by_channel"].get(ch, {"files": 0, "occurrences": 0})
        lines.append(f"| {ch} | {row['files']} | {row['occurrences']} |")
    lines.extend(
        [
            "",
            "## Known limitations",
            "",
        ]
    )
    for lim in inventory["limitations"]:
        lines.append(f"- {lim}")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Observability inventory for scripts/ (Circle-1 v0)"
    )
    parser.add_argument("--root", default=".", help="Repo root directory")
    parser.add_argument(
        "--zone",
        default="scripts",
        help="Top-level zone directory to scan (default: scripts)",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=None,
        help=(
            "Filename or substring to exclude (repeatable). "
            "Default: __init__.py"
        ),
    )
    parser.add_argument(
        "--scan-date",
        default="2026-05-02",
        help="ISO date to embed in the inventory record",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output JSON file path (default: stdout)",
    )
    parser.add_argument(
        "--markdown",
        default=None,
        help="Optional human-readable markdown summary path",
    )
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"ERROR: not a directory: {root}", file=sys.stderr)
        return 1

    zone_dir = root / args.zone
    if not zone_dir.is_dir():
        # Anti-gaming: a missing or mistyped zone must NOT silently produce
        # total_files=0. An empty inventory is indistinguishable from "zone
        # has no observable channels"; that violates the issue's MUST NOT
        # clause on hidden skipped files.
        print(
            f"ERROR: zone directory not found: {zone_dir} "
            f"(--zone={args.zone!r} relative to {root})",
            file=sys.stderr,
        )
        return 2

    exclude_patterns = args.exclude if args.exclude else ["__init__.py"]
    reports = scan_zone(root, zone=args.zone, exclude_patterns=exclude_patterns)
    inventory = build_inventory(
        reports,
        scan_date=args.scan_date,
        root_zone=args.zone,
        exclude_patterns=exclude_patterns,
    )
    payload = json.dumps(inventory, indent=2)

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(payload + "\n", encoding="utf-8")
        print(f"Saved JSON: {out_path}", file=sys.stderr)
    else:
        print(payload)

    if args.markdown:
        md_path = Path(args.markdown)
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(render_markdown_summary(inventory), encoding="utf-8")
        print(f"Saved markdown: {md_path}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
