"""Trusted, data-only protection for the GitHub-native writer boundary."""

from __future__ import annotations

import ast
import re
from collections.abc import Mapping
from pathlib import Path

from .common import Block9Error

AGENT0_ID = "agent0@system"


_WRITE_MARKERS = (
    b".write_text(",
    b".write_bytes(",
    b".open(",
    b"open(",
    b"json.dump(",
    b"yaml.dump(",
    b"writeFile",
    b"WriteAllText",
    b"os.WriteFile",
    b"os.replace(",
    b"os.rename(",
    b"shutil.copy",
    b"shutil.move",
    b".rename(",
    b".touch(",
    b"subprocess.",
    b'"git",',
    b"'git',",
    b"gh api",
    b"gh issue",
    b"gh pr",
    b"git push",
    b"git commit",
    b"git update-ref",
    b"/git/refs",
    b"contents: write",
    b"issues: write",
)
_PROTOCOL_TARGET_MARKERS = (
    b"ledger/",
    b"ledger\\",
    b'"ledger"',
    b"'ledger'",
    b"refs/heads/main",
    b"git push",
    b'"git",',
    b"'git',",
    b"gh api",
    b"gh issue",
    b"gh pr",
    b"ADMIN_TOKEN",
    b"GITHUB_TOKEN",
    b"contents: write",
)
_WORKFLOW_CANONICAL_WRITE_PERMISSION = re.compile(
    rb"""(?imx)
    (?: ^ | [{,] ) [\ \t]* [\"']?
    (?: contents | pull-requests )
    [\"']? [\ \t]* : [\ \t]* [\"']? (?: write | write-all ) [\"']?
    (?= [\ \t,}\#\r\n] | $ )
    """
)
_WORKFLOW_EXTERNAL_SECRET = re.compile(
    rb"\$\{\{[\ \t]*secrets\.(?!GITHUB_TOKEN\b)[A-Za-z_][A-Za-z0-9_]*"
)


def _python_module_aliases(path: str) -> tuple[str, ...]:
    if not path.endswith(".py"):
        return ()
    module = path[:-3].replace("/", ".")
    if module.endswith(".__init__"):
        module = module[: -len(".__init__")]
    aliases = {module, module.rsplit(".", 1)[-1]}
    if module.startswith("src."):
        aliases.add(module[4:])
    return tuple(sorted(aliases))


def _python_imports(content: bytes) -> set[str]:
    try:
        tree = ast.parse(content.decode("utf-8"))
    except (UnicodeDecodeError, SyntaxError):
        return set()
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
            imports.update(f"{node.module}.{alias.name}" for alias in node.names)
    return imports


def _is_executable_writer_surface(path: str) -> bool:
    normalized = path.lower()
    excluded = (
        ".agents/",
        ".claude/",
        "agent0_diary/",
        "benchmarks/",
        "data/",
        "deliverables/",
        "docs/",
        "evidence/",
        "genomes/",
        "ledger/",
        "lore/",
        "oled/",
        "research/",
        "tests/",
        "vendor/",
    )
    is_test = "/tests/" in normalized or normalized.startswith(excluded)
    extensionless_source = (
        normalized.startswith((".github/actions/", "scripts/", "src/"))
        and not Path(normalized).suffix
    )
    return (
        not is_test
        and (
            extensionless_source
            or normalized.endswith(
                (
                    ".bat",
                    ".cjs",
                    ".cmd",
                    ".cs",
                    ".go",
                    ".java",
                    ".js",
                    ".mjs",
                    ".php",
                    ".ps1",
                    ".py",
                    ".rb",
                    ".rs",
                    ".sh",
                    ".ts",
                )
            )
        )
    ) or (
        normalized.startswith((".github/workflows/", ".github/actions/"))
        and normalized.endswith((".yml", ".yaml"))
    )


def _workflow_has_canonical_write_permission(path: str, content: bytes) -> bool:
    return path.startswith(".github/workflows/") and bool(
        _WORKFLOW_CANONICAL_WRITE_PERMISSION.search(content)
    )


def _workflow_has_external_secret(path: str, content: bytes) -> bool:
    return path.startswith(".github/workflows/") and bool(
        _WORKFLOW_EXTERNAL_SECRET.search(content)
    )


def _ast_names(node: ast.AST) -> set[str]:
    return {item.id for item in ast.walk(node) if isinstance(item, ast.Name)}


def _ast_strings(node: ast.AST) -> tuple[str, ...]:
    return tuple(
        item.value
        for item in ast.walk(node)
        if isinstance(item, ast.Constant) and type(item.value) is str
    )


def _mentions_protocol_target(node: ast.AST, tainted: set[str]) -> bool:
    if _ast_names(node) & tainted:
        return True
    return any(
        "ledger" in value.lower().replace("\\", "/").split("/")
        or "refs/heads/main" in value
        or ".git/refs" in value.replace("\\", "/")
        for value in _ast_strings(node)
    )


def _call_name(call: ast.Call) -> str:
    parts: list[str] = []
    node: ast.AST = call.func
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _python_protocol_write_calls(tree: ast.AST) -> tuple[ast.Call, ...]:
    tainted: set[str] = set()
    functions = {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            value = node.value
            if value is None or not _mentions_protocol_target(value, tainted):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names = {name for target in targets for name in _ast_names(target)}
            if not names <= tainted:
                tainted.update(names)
                changed = True
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function = functions.get(_call_name(node).split(".")[-1])
            if function is None:
                continue
            parameters = function.args.posonlyargs + function.args.args
            for argument, parameter in zip(node.args, parameters, strict=False):
                if parameter.arg not in tainted and _mentions_protocol_target(
                    argument, tainted
                ):
                    tainted.add(parameter.arg)
                    changed = True

    result: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node)
        strings = tuple(value.lower() for value in _ast_strings(node))
        if name.startswith("subprocess.") or name in {"os.system", "os.popen"}:
            joined = " ".join(strings)
            if any(
                marker in joined
                for marker in (
                    "git push",
                    "git update-ref",
                    "gh api",
                    "gh issue create",
                    "gh issue edit",
                    "gh issue comment",
                    "gh pr create",
                    "gh pr merge",
                )
            ) or ({"git", "push"} <= set(strings)):
                result.append(node)
                continue
        if name in {"write_text", "write_bytes", "touch"} or name.endswith(
            (".write_text", ".write_bytes", ".touch")
        ):
            receiver = node.func.value if isinstance(node.func, ast.Attribute) else node
            if _mentions_protocol_target(receiver, tainted):
                result.append(node)
                continue
        if name in {"open", "Path.open"} or name.endswith(".open"):
            target = (
                node.func.value
                if isinstance(node.func, ast.Attribute)
                else node.args[0]
                if node.args
                else node
            )
            modes = [
                value
                for value in strings
                if any(flag in value for flag in ("w", "a", "x", "+"))
            ]
            if modes and _mentions_protocol_target(target, tainted):
                result.append(node)
                continue
        if name in {"os.replace", "os.rename", "shutil.move", "shutil.copy"}:
            if any(
                _mentions_protocol_target(argument, tainted) for argument in node.args
            ):
                result.append(node)
    return tuple(result)


def _python_has_protocol_write(content: bytes) -> bool:
    try:
        tree = ast.parse(content.decode("utf-8"))
    except (UnicodeDecodeError, SyntaxError):
        return False
    return bool(_python_protocol_write_calls(tree))


def _discover_static_writers(captured: Mapping[str, bytes]) -> set[str]:
    executable = {
        path: content
        for path, content in captured.items()
        if _is_executable_writer_surface(path)
    }
    direct: set[str] = set()
    for path, content in executable.items():
        if path.endswith(".py"):
            if _python_has_protocol_write(content):
                direct.add(path)
        elif _workflow_has_canonical_write_permission(
            path, content
        ) or _workflow_has_external_secret(path, content):
            direct.add(path)
        elif any(marker in content for marker in _WRITE_MARKERS) and any(
            marker in content for marker in _PROTOCOL_TARGET_MARKERS
        ):
            direct.add(path)
    alias_paths: dict[str, set[str]] = {}
    imports_by_path: dict[str, set[str]] = {}
    for path, content in executable.items():
        for alias in _python_module_aliases(path):
            alias_paths.setdefault(alias, set()).add(path)
        if path.endswith(".py"):
            imports_by_path[path] = _python_imports(content)

    discovered = set(direct)
    changed = True
    while changed:
        changed = False
        mutation_aliases = {
            alias for path in discovered for alias in _python_module_aliases(path)
        }
        for path, imported in imports_by_path.items():
            if path in discovered:
                continue
            resolved = {
                candidate
                for name in imported
                for candidate in alias_paths.get(name, ())
            }
            if resolved & discovered or imported & mutation_aliases:
                discovered.add(path)
                changed = True
    return discovered


def _discover_canonical_workflows(captured: Mapping[str, bytes]) -> set[str]:
    return {
        path
        for path, content in captured.items()
        if _workflow_has_canonical_write_permission(path, content)
        or _workflow_has_external_secret(path, content)
    }


_GITHUB_NATIVE_PINNED_FILES = {
    ".github/workflows/access.yml",
    ".github/workflows/tide.yml",
    ".github/workflows/guard-vnext-ledger.yml",
    "pyproject.toml",
    "src/wea_vnext/__init__.py",
    "src/wea_vnext/block9/__init__.py",
    "src/wea_vnext/block9/common.py",
    "src/wea_vnext/block9/github_native.py",
    "src/wea_vnext/block9/migration.py",
    "src/wea_vnext/block9/writer.py",
    "src/wea_vnext/engine.py",
    "src/wea_vnext/domain_access.py",
    "src/wea_vnext/access_control.py",
    "src/wea_vnext/access_protocol.py",
    "src/wea_vnext/access_github.py",
    "src/wea_cli/access.py",
    "src/wea_vnext/tide/__main__.py",
    "src/wea_vnext/tide/__init__.py",
    "src/wea_vnext/tide/activation.py",
    "src/wea_vnext/tide/collection.py",
    "src/wea_vnext/tide/github.py",
    "src/wea_vnext/tide/ledger.py",
    "src/wea_vnext/tide/records.py",
    "src/wea_vnext/tide/replay.py",
    "src/wea_vnext/executors/v0_8_0/canonical.py",
}


def validate_writer_boundary_sources(
    trusted: Mapping[str, bytes],
    candidate: Mapping[str, bytes],
) -> None:
    """Reject a source candidate that changes the GitHub writer boundary.

    The trusted pull-request workflow supplies bytes from Git objects. Candidate
    source is never imported or executed.
    """

    if not isinstance(trusted, Mapping) or not isinstance(candidate, Mapping):
        raise Block9Error("writer-boundary sources must be mappings")
    trusted = dict(trusted)
    candidate = dict(candidate)
    if any(
        type(path) is not str or type(content) is not bytes
        for path, content in trusted.items()
    ):
        raise Block9Error("trusted writer-boundary source is invalid")
    if any(
        type(path) is not str or type(content) is not bytes
        for path, content in candidate.items()
    ):
        raise Block9Error("candidate writer-boundary source is invalid")
    trusted_writers = _discover_static_writers(trusted)
    candidate_writers = _discover_static_writers(candidate)
    added_writers = sorted(candidate_writers - trusted_writers)
    if added_writers:
        detail = added_writers[0]
        raise Block9Error(f"candidate writer universe changed: {detail}")
    # A legacy writer-capable file may be deleted to retire it. During the
    # private pilot it may not be edited in place: static analysis cannot prove
    # that a changed writer did not redirect its existing authority to vNext.
    changed_existing_writers = sorted(
        path
        for path in trusted_writers
        if path in candidate and trusted[path] != candidate[path]
    )
    if changed_existing_writers:
        raise Block9Error(
            "existing writer boundary source changed: " + changed_existing_writers[0]
        )
    if not _GITHUB_NATIVE_PINNED_FILES <= trusted.keys():
        raise Block9Error("trusted GitHub-native guard files are incomplete")
    trusted_canonical = _discover_canonical_workflows(trusted)
    candidate_canonical = _discover_canonical_workflows(candidate)
    if candidate_canonical != trusted_canonical:
        changed = sorted(candidate_canonical ^ trusted_canonical)
        detail = changed[0] if changed else "unknown"
        raise Block9Error(f"candidate canonical workflow set changed: {detail}")
    protected = trusted_canonical | candidate_canonical | _GITHUB_NATIVE_PINNED_FILES
    protected |= {
        path
        for path in trusted
        if path.startswith(("src/wea_vnext/executors/", "src/wea_vnext/rulesets/"))
    }
    for path in sorted(protected):
        if trusted.get(path) != candidate.get(path):
            raise Block9Error(f"candidate writer boundary changed: {path}")
