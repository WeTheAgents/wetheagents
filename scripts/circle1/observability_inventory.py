"""Circle-1 observability inventory harness for scripts/.

This scanner measures observable output and side-effect channels in Python files
under scripts/. It is advisory inventory only: it does not enforce policy, change
script behavior, or affect Tide/ledger settlement.

Default scope:
  - include: scripts/**/*.py
  - exclude: __init__.py at any depth, reported in skipped_files

JSON schema overview:
  {
    "scan_date": "YYYY-MM-DD",
    "zone": "scripts",
    "harness_version": "v0",
    "scope": {"include": "...", "default_exclusions": [...]},
    "summary": {
      "total_files": 0,
      "files_with_detections": 0,
      "parse_errors": 0,
      "skipped_files": 0,
      "by_channel": {"stdout_cli_output": {"files": 0, "detections": 0}}
    },
    "channels": [{"name": "...", "description": "..."}],
    "limitations": ["..."],
    "files": [
      {
        "path": "scripts/example.py",
        "status": "scanned",
        "channels": [
          {
            "channel": "stdout_cli_output",
            "confidence": "high",
            "reason": "print() writes to stdout by default",
            "evidence": [
              {"line": 10, "col": 4, "symbol": "print", "snippet": "print('ok')"}
            ]
          }
        ]
      }
    ],
    "skipped_files": [{"path": "scripts/__init__.py", "reason": "..."}]
  }

Known limits are emitted in the JSON so future checkpoint consumers can compare
results without mistaking this AST scan for a complete dataflow analysis.
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

CHANNELS: tuple[dict[str, str], ...] = (
    {
        "name": "stdout_cli_output",
        "description": (
            "Human-facing stdout or CLI output such as print() and click.echo()."
        ),
    },
    {
        "name": "stderr_output",
        "description": (
            "Human-facing stderr output such as print(..., file=sys.stderr)."
        ),
    },
    {
        "name": "logging",
        "description": "Python logging calls and logger method calls.",
    },
    {
        "name": "file_artifact_write",
        "description": "Static candidates for file or report artifact creation/writes.",
    },
    {
        "name": "subprocess_launch",
        "description": "Static process launch candidates such as subprocess.run().",
    },
    {
        "name": "ledger_or_protocol_write_candidate",
        "description": "Write candidates targeting ledger/protocol files or paths.",
    },
    {
        "name": "github_comment_side_effect_candidate",
        "description": (
            "GitHub issue/PR/comment side-effect candidates, including gh calls."
        ),
    },
    {
        "name": "network_external_call",
        "description": "HTTP/network calls visible through common client libraries.",
    },
    {
        "name": "unknown_ambiguous_side_effect",
        "description": "Dynamic or unresolved side effects that need human review.",
    },
)

CHANNEL_NAMES = tuple(item["name"] for item in CHANNELS)

LIMITATIONS: tuple[str, ...] = (
    "AST inspection resolves direct import aliases for common output/process "
    "modules, but does not resolve wrapper functions, interprocedural dataflow, "
    "imported-module behavior, or runtime-only path values.",
    "File write detection is strongest for open(..., write-mode), Path.write_*(), "
    "json.dump(), and obvious .write() calls; custom writer abstractions are "
    "classified as ambiguous when the receiver cannot be identified.",
    "Ledger/GitHub classifications are candidates, not proof of mutation. They "
    "are flagged when paths, command arguments, URLs, or method names make the "
    "side-effect target statically visible.",
    "The harness is measurement-only and should not be used as CI enforcement or "
    "as an automatic settlement rule.",
)

_STDOUT_NAMES = {"stdout", "sys.stdout"}
_STDERR_NAMES = {"stderr", "sys.stderr"}
_LOG_METHODS = {
    "debug",
    "info",
    "warning",
    "warn",
    "error",
    "exception",
    "critical",
    "log",
}
_WRITE_MODES = {"w", "a", "x", "+"}
_LEDGER_MARKERS = {
    "balances.json",
    "escrows.json",
    "ledger/history/",
    "idem_keys.json",
    "pending.json",
    "task_index.json",
    "trajectory_mints.json",
}
_NETWORK_PREFIXES = (
    "requests.",
    "httpx.",
    "urllib.request.",
    "aiohttp.",
)
_NETWORK_NAMES = {
    "urlopen",
    "request",
}
_SUBPROCESS_NAMES = {
    "subprocess.run",
    "subprocess.call",
    "subprocess.check_call",
    "subprocess.check_output",
    "subprocess.Popen",
    "asyncio.create_subprocess_exec",
    "asyncio.create_subprocess_shell",
    "os.system",
    "os.execv",
    "os.execve",
    "os.spawnv",
    "os.spawnve",
    "multiprocessing.Process",
}
_SAVE_HELPER_NAMES = {
    "save",
    "save_json",
    "write_json",
    "dump_json",
    "_write_json",
}


@dataclass
class Detection:
    channel: str
    confidence: str
    reason: str
    evidence: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "channel": self.channel,
            "confidence": self.confidence,
            "reason": self.reason,
            "evidence": self.evidence,
        }


def _node_name(node: ast.AST | None, aliases: dict[str, str] | None = None) -> str:
    aliases = aliases or {}
    if isinstance(node, ast.Name):
        return aliases.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        base = _node_name(node.value, aliases)
        return f"{base}.{node.attr}" if base else node.attr
    if isinstance(node, ast.Call):
        return _node_name(node.func, aliases)
    return ""


def _string_value(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "<f-string>"
    return None


def _pathish_text(node: ast.AST | None, bindings: dict[str, str] | None = None) -> str:
    """Best-effort static text for common path expressions."""
    bindings = bindings or {}
    if node is None:
        return ""
    value = _string_value(node)
    if value is not None:
        return value
    if isinstance(node, ast.Name):
        return bindings.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        if node.attr in {"open", "touch", "write_text", "write_bytes"}:
            return _pathish_text(node.value, bindings)
        return _node_name(node)
    if isinstance(node, ast.Call):
        func = _node_name(node.func)
        if func in {"Path", "pathlib.Path"} and node.args:
            return _pathish_text(node.args[0], bindings)
        if func in {"os.path.join", "posixpath.join", "ntpath.join"}:
            parts = [_pathish_text(arg, bindings) for arg in node.args]
            return "/".join(part for part in parts if part)
        return func
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        left = _pathish_text(node.left, bindings)
        right = _pathish_text(node.right, bindings)
        if left and right:
            return f"{left}/{right}"
        return left or right
    if isinstance(node, ast.Subscript):
        return _pathish_text(node.value, bindings)
    return ""


def _lower_pathish(node: ast.AST | None, bindings: dict[str, str] | None = None) -> str:
    return _pathish_text(node, bindings).replace("\\", "/").lower()


def _is_ledger_path_text(text: str) -> bool:
    normalized = text.replace("\\", "/").lower()
    if "/ledger/" in f"/{normalized}/" or normalized.startswith("ledger/"):
        return True
    return any(marker in normalized for marker in _LEDGER_MARKERS)


def _literal_strings(node: ast.AST | None) -> list[str]:
    if node is None:
        return []
    values: list[str] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            values.append(child.value)
    return values


def _call_literal_strings(call: ast.Call) -> list[str]:
    values: list[str] = []
    for arg in call.args:
        values.extend(_literal_strings(arg))
    for keyword in call.keywords:
        values.extend(_literal_strings(keyword.value))
    return values


def _first_arg(call: ast.Call) -> ast.AST | None:
    return call.args[0] if call.args else None


def _mode_arg(call: ast.Call) -> str:
    if len(call.args) >= 2:
        value = _string_value(call.args[1])
        if value is not None:
            return value
    for keyword in call.keywords:
        if keyword.arg == "mode":
            value = _string_value(keyword.value)
            if value is not None:
                return value
    return ""


def _is_write_mode(mode: str) -> bool:
    return any(flag in mode for flag in _WRITE_MODES)


def _keyword(call: ast.Call, name: str) -> ast.AST | None:
    for keyword in call.keywords:
        if keyword.arg == name:
            return keyword.value
    return None


def _is_true_keyword(call: ast.Call, name: str) -> bool:
    node = _keyword(call, name)
    return isinstance(node, ast.Constant) and node.value is True


def _command_invokes_gh(call: ast.Call) -> bool:
    first = _first_arg(call)
    if isinstance(first, (ast.List, ast.Tuple)) and first.elts:
        command = _string_value(first.elts[0])
        return command == "gh"
    command = _string_value(first)
    if command is None:
        return False
    return command == "gh" or command.startswith("gh ")


def _is_network_call(name: str) -> bool:
    if name in _NETWORK_NAMES:
        return True
    return any(name.startswith(prefix) for prefix in _NETWORK_PREFIXES)


def _is_logging_call(name: str) -> bool:
    if name == "logging.getLogger":
        return True
    if name.startswith("logging.") and name.rsplit(".", 1)[-1] in _LOG_METHODS:
        return True
    root = name.split(".", 1)[0].lower()
    return name.rsplit(".", 1)[-1] in _LOG_METHODS and root in {"logger", "log"}


def _looks_like_github_call(name: str, call: ast.Call) -> bool:
    lowered_name = name.lower()
    strings = " ".join(_call_literal_strings(call)).lower()
    if "api.github.com" in strings:
        return True
    if "github" in lowered_name and any(
        word in lowered_name for word in ("comment", "issue", "pr", "pull")
    ):
        return True
    github_comment_methods = (
        "create_comment",
        "create_issue_comment",
        "edit_comment",
        "comment",
    )
    return lowered_name.endswith(github_comment_methods)


def _evidence(
    path: Path, source_text: str, lines: list[str], node: ast.AST, symbol: str
) -> dict[str, Any]:
    line_no = getattr(node, "lineno", 0)
    segment = ast.get_source_segment(source_text, node)
    if segment is not None:
        snippet = " ".join(segment.strip().split())
        if len(snippet) > 240:
            snippet = snippet[:237].rstrip() + "..."
    elif line_no and 1 <= line_no <= len(lines):
        snippet = lines[line_no - 1].strip()
    else:
        snippet = ""
    return {
        "line": line_no,
        "col": getattr(node, "col_offset", 0),
        "symbol": symbol,
        "snippet": snippet,
    }


class ObservabilityVisitor(ast.NodeVisitor):
    def __init__(
        self,
        path: Path,
        source_text: str,
        lines: list[str],
        path_bindings: dict[str, str],
        import_aliases: dict[str, str],
    ) -> None:
        self.path = path
        self.source_text = source_text
        self.lines = lines
        self.path_bindings = path_bindings
        self.import_aliases = import_aliases
        self.detections: list[Detection] = []

    def add(
        self, channel: str, confidence: str, reason: str, node: ast.AST, symbol: str
    ) -> None:
        self.detections.append(
            Detection(
                channel=channel,
                confidence=confidence,
                reason=reason,
                evidence=[
                    _evidence(self.path, self.source_text, self.lines, node, symbol)
                ],
            )
        )

    def visit_Call(self, node: ast.Call) -> None:
        name = _node_name(node.func, self.import_aliases)
        method = name.rsplit(".", 1)[-1] if name else ""
        self._detect_stdout_stderr(node, name)
        self._detect_logging(node, name)
        self._detect_file_write(node, name, method)
        self._detect_subprocess(node, name)
        self._detect_network_and_github(node, name)
        self._detect_unknown(node, name, method)
        self.generic_visit(node)

    def _detect_stdout_stderr(self, node: ast.Call, name: str) -> None:
        if name == "print":
            file_target = _keyword(node, "file")
            target_name = _node_name(file_target, self.import_aliases)
            if target_name in _STDERR_NAMES:
                self.add(
                    "stderr_output",
                    "high",
                    "print(..., file=sys.stderr) writes to stderr",
                    node,
                    name,
                )
            elif target_name in _STDOUT_NAMES or file_target is None:
                self.add(
                    "stdout_cli_output",
                    "high",
                    "print() writes to stdout by default",
                    node,
                    name,
                )
            else:
                self.add(
                    "unknown_ambiguous_side_effect",
                    "medium",
                    "print(..., file=<dynamic>) writes to an unresolved stream",
                    node,
                    name,
                )
            return

        if name in {"sys.stdout.write", "stdout.write"}:
            self.add(
                "stdout_cli_output",
                "high",
                "stdout.write() emits CLI output",
                node,
                name,
            )
        elif name in {"sys.stderr.write", "stderr.write"}:
            self.add(
                "stderr_output",
                "high",
                "stderr.write() emits error-channel output",
                node,
                name,
            )
        elif name in {"click.echo", "click.secho", "typer.echo", "typer.secho"}:
            if _is_true_keyword(node, "err"):
                self.add(
                    "stderr_output",
                    "high",
                    f"{name}(err=True) writes to stderr",
                    node,
                    name,
                )
            else:
                self.add(
                    "stdout_cli_output",
                    "high",
                    f"{name}() writes CLI output",
                    node,
                    name,
                )

    def _detect_logging(self, node: ast.Call, name: str) -> None:
        if _is_logging_call(name):
            self.add("logging", "high", f"{name}() uses Python logging", node, name)

    def _detect_file_write(self, node: ast.Call, name: str, method: str) -> None:
        if name == "open":
            mode = _mode_arg(node)
            if _is_write_mode(mode):
                self.add(
                    "file_artifact_write",
                    "high",
                    f"open(..., mode={mode!r}) opens a writable file handle",
                    node,
                    name,
                )
                self._maybe_add_ledger_write(node, _first_arg(node), name)
            return

        if method == "open":
            mode = _mode_arg(node)
            if _is_write_mode(mode):
                self.add(
                    "file_artifact_write",
                    "medium",
                    f"{name}(..., mode={mode!r}) opens a writable path",
                    node,
                    name,
                )
                self._maybe_add_ledger_write(node, node.func, name)
            return

        if method in {"write_text", "write_bytes", "touch"}:
            self.add(
                "file_artifact_write",
                "high",
                f"{name}() writes or creates a file artifact",
                node,
                name,
            )
            self._maybe_add_ledger_write(node, node.func, name)
            return

        if name in {"json.dump", "yaml.safe_dump", "tomllib.dump"}:
            self.add(
                "file_artifact_write",
                "medium",
                f"{name}() writes structured data to a file-like object",
                node,
                name,
            )
            return

        if method in _SAVE_HELPER_NAMES and node.args:
            target_text = _lower_pathish(node.args[0], self.path_bindings)
            if target_text:
                reason = (
                    f"{name}() writes through a helper to a statically visible path"
                )
                if _is_ledger_path_text(target_text):
                    reason = (
                        f"{name}() writes through a helper to a ledger/protocol path"
                    )
                self.add("file_artifact_write", "medium", reason, node, name)
            if _is_ledger_path_text(target_text):
                self.add(
                    "ledger_or_protocol_write_candidate",
                    "medium",
                    "helper call targets a statically visible ledger/protocol path",
                    node,
                    name,
                )
                return

        if method == "write" and name not in {
            "sys.stdout.write",
            "sys.stderr.write",
            "stdout.write",
            "stderr.write",
        }:
            self.add(
                "unknown_ambiguous_side_effect",
                "medium",
                f"{name}() writes to an unresolved object",
                node,
                name,
            )

    def _maybe_add_ledger_write(
        self, node: ast.Call, target: ast.AST | None, symbol: str
    ) -> None:
        path_text = _lower_pathish(target, self.path_bindings)
        if _is_ledger_path_text(path_text):
            self.add(
                "ledger_or_protocol_write_candidate",
                "high",
                "write call targets a statically visible ledger/protocol path",
                node,
                symbol,
            )

    def _detect_subprocess(self, node: ast.Call, name: str) -> None:
        if name in _SUBPROCESS_NAMES:
            self.add(
                "subprocess_launch",
                "high",
                f"{name}() launches another process",
                node,
                name,
            )
            if _command_invokes_gh(node):
                self.add(
                    "github_comment_side_effect_candidate",
                    "medium",
                    "subprocess command invokes gh; GitHub side-effect candidate",
                    node,
                    name,
                )

    def _detect_network_and_github(self, node: ast.Call, name: str) -> None:
        if _is_network_call(name):
            self.add(
                "network_external_call",
                "high",
                f"{name}() performs a network/external-service call",
                node,
                name,
            )
        if _looks_like_github_call(name, node):
            self.add(
                "github_comment_side_effect_candidate",
                "medium",
                "GitHub/comment side-effect target is visible in call name or URL",
                node,
                name,
            )

    def _detect_unknown(self, node: ast.Call, name: str, method: str) -> None:
        if name in {"eval", "exec", "compile", "importlib.import_module"}:
            self.add(
                "unknown_ambiguous_side_effect",
                "high",
                (
                    f"{name}() can execute or load behavior not visible to "
                    "AST channel rules"
                ),
                node,
                name,
            )
        elif name == "getattr" and len(node.args) >= 2:
            self.add(
                "unknown_ambiguous_side_effect",
                "medium",
                "getattr(...)(...) patterns may hide output or mutation targets",
                node,
                name,
            )
        elif not name and method:
            self.add(
                "unknown_ambiguous_side_effect",
                "low",
                "call target could not be resolved to a stable symbol",
                node,
                method,
            )


def _assignment_targets(node: ast.Assign | ast.AnnAssign) -> list[ast.AST]:
    if isinstance(node, ast.Assign):
        return list(node.targets)
    return [node.target]


def _collect_import_aliases(tree: ast.Module) -> dict[str, str]:
    """Collect direct import aliases for symbol-level channel detection."""
    aliases: dict[str, str] = {}
    tracked_modules = {
        "sys",
        "subprocess",
        "logging",
        "pathlib",
        "os",
        "asyncio",
        "multiprocessing",
    }
    tracked_from_imports = {
        "subprocess": {"run", "call", "check_call", "check_output", "Popen"},
        "logging": {
            "getLogger",
            "debug",
            "info",
            "warning",
            "warn",
            "error",
            "exception",
            "critical",
            "log",
        },
        "sys": {"stdout", "stderr"},
        "pathlib": {"Path"},
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for item in node.names:
                root = item.name.split(".", 1)[0]
                if root in tracked_modules:
                    aliases[item.asname or root] = item.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            module = node.module
            names = tracked_from_imports.get(module, set())
            for item in node.names:
                if item.name in names:
                    aliases[item.asname or item.name] = f"{module}.{item.name}"
    return aliases


def _collect_path_bindings(tree: ast.Module) -> dict[str, str]:
    """Collect simple Name -> path-expression bindings for static path evidence.

    This is intentionally shallow. It handles common script shapes such as:
      LEDGER = ROOT / "ledger"
      bal_path = root / "ledger" / "balances.json"
      history_path = HISTORY / f"{today}.jsonl"

    It does not try to prove path values at runtime; it only preserves visible
    path markers so later write calls can explain why they are ledger candidates.
    """
    bindings: dict[str, str] = {}
    assignments = [
        node for node in ast.walk(tree) if isinstance(node, (ast.Assign, ast.AnnAssign))
    ]
    for _ in range(3):
        changed = False
        for node in assignments:
            value = getattr(node, "value", None)
            if value is None:
                continue
            text = _pathish_text(value, bindings)
            if not text:
                continue
            for target in _assignment_targets(node):
                if isinstance(target, ast.Name) and bindings.get(target.id) != text:
                    bindings[target.id] = text
                    changed = True
        if not changed:
            break
    return bindings


def inspect_file(path: Path, root: Path) -> dict[str, Any]:
    rel_path = str(path.relative_to(root)).replace("\\", "/")
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {
            "path": rel_path,
            "status": "read_error",
            "channels": [
                {
                    "channel": "unknown_ambiguous_side_effect",
                    "confidence": "high",
                    "reason": f"file could not be read: {exc}",
                    "evidence": [],
                }
            ],
        }

    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return {
            "path": rel_path,
            "status": "parse_error",
            "parse_error": str(exc),
            "channels": [
                {
                    "channel": "unknown_ambiguous_side_effect",
                    "confidence": "high",
                    "reason": f"AST parse error: {exc}",
                    "evidence": [],
                }
            ],
        }

    visitor = ObservabilityVisitor(
        path,
        text,
        text.splitlines(),
        _collect_path_bindings(tree),
        _collect_import_aliases(tree),
    )
    visitor.visit(tree)
    channels = sorted(
        (d.as_dict() for d in visitor.detections),
        key=lambda item: (
            item["channel"],
            item["evidence"][0].get("line", 0) if item["evidence"] else 0,
            item["evidence"][0].get("col", 0) if item["evidence"] else 0,
            item["reason"],
        ),
    )
    return {
        "path": rel_path,
        "status": "scanned",
        "channels": channels,
    }


def _empty_channel_counts() -> dict[str, dict[str, int]]:
    return {name: {"files": 0, "detections": 0} for name in CHANNEL_NAMES}


def _summary(
    files: list[dict[str, Any]], skipped_files: list[dict[str, str]]
) -> dict[str, Any]:
    counts = _empty_channel_counts()
    parse_errors = 0
    files_with_detections = 0
    for entry in files:
        channels = entry.get("channels", [])
        if channels:
            files_with_detections += 1
        if entry.get("status") == "parse_error":
            parse_errors += 1
        seen = set()
        for detection in channels:
            channel = detection["channel"]
            counts[channel]["detections"] += 1
            seen.add(channel)
        for channel in seen:
            counts[channel]["files"] += 1
    return {
        "total_files": len(files),
        "files_with_detections": files_with_detections,
        "parse_errors": parse_errors,
        "skipped_files": len(skipped_files),
        "by_channel": counts,
    }


def scan_observability(
    root: Path,
    scan_date: str | None = None,
    include_init: bool = False,
) -> dict[str, Any]:
    """Scan scripts/**/*.py and return a structured observability inventory."""
    root = root.resolve()
    scripts_dir = root / "scripts"
    all_py_files = sorted(p for p in scripts_dir.rglob("*.py") if p.is_file())
    skipped_files: list[dict[str, str]] = []
    py_files: list[Path] = []
    for path in all_py_files:
        if path.name == "__init__.py" and not include_init:
            skipped_files.append(
                {
                    "path": str(path.relative_to(root)).replace("\\", "/"),
                    "reason": (
                        "__init__.py excluded by default; pass --include-init "
                        "to scan it"
                    ),
                }
            )
        else:
            py_files.append(path)

    files = [inspect_file(path, root) for path in py_files]
    return {
        "scan_date": scan_date or date.today().isoformat(),
        "zone": "scripts",
        "harness_version": "v0",
        "scope": {
            "include": "scripts/**/*.py",
            "default_exclusions": ["__init__.py"],
            "include_init": include_init,
        },
        "summary": _summary(files, skipped_files),
        "channels": list(CHANNELS),
        "limitations": list(LIMITATIONS),
        "files": files,
        "skipped_files": skipped_files,
    }


def render_markdown(report: dict[str, Any], max_hot_files: int = 25) -> str:
    lines = [
        "# scripts/ Observability Inventory",
        "",
        f"- scan_date: {report['scan_date']}",
        f"- harness_version: {report['harness_version']}",
        f"- total_files: {report['summary']['total_files']}",
        f"- skipped_files: {report['summary']['skipped_files']}",
        "",
        "## Channel Counts",
        "",
        "| channel | files | detections |",
        "|---|---:|---:|",
    ]
    for channel in CHANNEL_NAMES:
        count = report["summary"]["by_channel"][channel]
        lines.append(f"| {channel} | {count['files']} | {count['detections']} |")
    lines.extend(["", "## Hot Files", ""])
    hot_files = [entry for entry in report["files"] if entry.get("channels")]
    if not hot_files:
        lines.append("No observable channels detected.")
    else:
        shown_files = hot_files[:max_hot_files] if max_hot_files >= 0 else hot_files
        for entry in shown_files:
            channels = sorted({d["channel"] for d in entry["channels"]})
            lines.append(f"- {entry['path']}: {', '.join(channels)}")
        omitted = len(hot_files) - len(shown_files)
        if omitted > 0:
            lines.append(f"- ... {omitted} more files omitted from markdown summary")
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {item}" for item in report["limitations"])
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Circle-1 scripts observability inventory"
    )
    parser.add_argument("--root", default=".", help="Repo root directory")
    parser.add_argument("--output", default=None, help="Optional output path")
    parser.add_argument(
        "--scan-date", default=None, help="ISO date to embed in the report"
    )
    parser.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="json",
        help="Output format; JSON is the checkpointable default",
    )
    parser.add_argument(
        "--include-init",
        action="store_true",
        help="Include __init__.py files instead of reporting them as skipped",
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
    if not (root / "scripts").is_dir():
        print(f"ERROR: scripts directory not found under {root}", file=sys.stderr)
        return 1

    report = scan_observability(
        root, scan_date=args.scan_date, include_init=args.include_init
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
    raise SystemExit(main())
