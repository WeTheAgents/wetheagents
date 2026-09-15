"""CLI freshness: detect when an installed/invoked `wea` lags the checkout.

The checked-out repository is the contract. A globally installed ``wea`` can
silently fall behind it and omit current commands (for example ``tide``). An
older executable cannot warn about itself retroactively, so freshness is a
*source-side preflight*: running the checkout's CLI compares three surfaces —

* the **running** CLI (whatever interpreter executed this command),
* the **checkout** contract (read statically from ``<root>/src/wea_cli``), and
* the **installed** ``wea`` found on ``PATH`` (probed as a subprocess),

against the checkout, and prints an actionable refresh path when any of them is
stale. The comparison is intentionally dependency-free and static so it also
works from a bare source tree.
"""

from __future__ import annotations

import ast
import hashlib
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

# Bump this when the top-level `wea` command surface changes (a command is
# added, removed, or renamed). It is the single machine-comparable stamp that a
# stale installed executable is measured against.
CONTRACT_VERSION = 2

_VERSION_RE = re.compile(r"cli-contract\s+(\d+)")
_FINGERPRINT_RE = re.compile(r"cli-fingerprint\s+([0-9a-f]+)")
_USAGE_CHOICES_RE = re.compile(r"\{([a-z0-9,_-]+)\}", re.IGNORECASE)
_CONTRACT_ASSIGN_RE = re.compile(r"^CONTRACT_VERSION\s*=\s*(\d+)", re.MULTILINE)

# This module intentionally imports nothing from `wea_cli` (in particular not
# `wea_cli.cli`): it discovers the CLI surface by reading source *bytes* as data,
# so it stays a leaf module rather than a writer-capable one.


def source_fingerprint(package_dir: Path) -> str:
    """Content hash of the shipped ``wea_cli`` Python bytes in ``package_dir``.

    Fingerprints the actual implementation, not just a hand-maintained version
    stamp, so a same-command but different-bytes (older) CLI is still detected
    as drift. Returns ``""`` when the directory is absent.
    """
    if not package_dir.is_dir():
        return ""
    digest = hashlib.sha256()
    for path in sorted(package_dir.glob("*.py")):
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()[:16]


def version_banner(package_version: str) -> str:
    """The `wea --version` line; freshness parses ``cli-contract`` and fingerprint."""
    fingerprint = source_fingerprint(Path(__file__).resolve().parent)
    return (
        f"wea {package_version} "
        f"(cli-contract {CONTRACT_VERSION}; cli-fingerprint {fingerprint})"
    )


def parse_top_level_commands(cli_source: str) -> set[str]:
    """Extract top-level `wea` subcommands from cli.py source via a static AST walk.

    Mirrors the doc-sync surface extraction: the command names are the string
    literals passed to ``subparsers.add_parser(...)``. Parsing (not importing)
    keeps this usable against an arbitrary checkout without side effects.
    """
    commands: set[str] = set()
    try:
        tree = ast.parse(cli_source)
    except SyntaxError:
        return commands
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr != "add_parser":
            continue
        if not isinstance(func.value, ast.Name) or func.value.id != "subparsers":
            continue
        if not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            commands.add(first.value)
    return commands


def running_contract() -> dict[str, Any]:
    """Contract of the CLI executing this process (source or installed package).

    The running ``cli.py`` sits beside this module; read it by path (as bytes)
    rather than importing ``wea_cli.cli``, keeping freshness a non-writer leaf.
    """
    package_dir = Path(__file__).resolve().parent
    cli_path = package_dir / "cli.py"
    source = (
        cli_path.read_text(encoding="utf-8", errors="replace")
        if cli_path.is_file()
        else ""
    )
    return {
        "version": CONTRACT_VERSION,
        "commands": sorted(parse_top_level_commands(source)),
        "fingerprint": source_fingerprint(package_dir),
    }


def checkout_contract(root: Path) -> dict[str, Any]:
    """Contract read statically from the checked-out repository at ``root``."""
    package_dir = root / "src" / "wea_cli"
    cli_path = package_dir / "cli.py"
    freshness_path = package_dir / "freshness.py"
    if not cli_path.is_file():
        return {"available": False, "reason": f"missing {cli_path.as_posix()}"}
    version = None
    if freshness_path.is_file():
        match = _CONTRACT_ASSIGN_RE.search(
            freshness_path.read_text(encoding="utf-8", errors="replace")
        )
        if match:
            version = int(match.group(1))
    commands = parse_top_level_commands(
        cli_path.read_text(encoding="utf-8", errors="replace")
    )
    return {
        "available": True,
        "version": version,
        "commands": sorted(commands),
        "fingerprint": source_fingerprint(package_dir),
    }


def _probe_env() -> dict[str, str]:
    """Environment for probing the installed `wea`, without source shadowing.

    The documented source invocation sets ``PYTHONPATH=src``; if the probe
    inherited it, the installed entrypoint would import the checkout instead of
    its own (possibly stale) package and always look fresh. Strip it so the
    installed executable is measured as it actually runs.
    """
    return {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}


def _probe_installed(wea_path: str) -> dict[str, Any]:
    """Probe the on-PATH `wea` executable for its contract version and commands."""
    report: dict[str, Any] = {"found": True, "path": wea_path}
    env = _probe_env()

    version_run = subprocess.run(
        [wea_path, "--version"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    combined = f"{version_run.stdout}\n{version_run.stderr}"
    match = _VERSION_RE.search(combined)
    if version_run.returncode == 0 and match:
        report["version"] = int(match.group(1))
    else:
        # An older executable predates `--version`/contract reporting entirely.
        report["version"] = None
    fingerprint_match = _FINGERPRINT_RE.search(combined)
    report["fingerprint"] = fingerprint_match.group(1) if fingerprint_match else None

    help_run = subprocess.run(
        [wea_path, "--help"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    commands: set[str] = set()
    choice_match = _USAGE_CHOICES_RE.search(help_run.stdout)
    if choice_match:
        commands = {token for token in choice_match.group(1).split(",") if token}
    report["commands"] = sorted(commands)
    return report


def installed_contract() -> dict[str, Any]:
    """Contract of the `wea` executable on PATH, or ``{"found": False}``."""
    wea_path = shutil.which("wea")
    if not wea_path:
        return {"found": False}
    try:
        return _probe_installed(wea_path)
    except OSError as exc:  # pragma: no cover - platform edge
        return {"found": True, "path": wea_path, "error": str(exc)}


def _evaluate(surface: dict[str, Any], checkout: dict[str, Any]) -> dict[str, Any]:
    """Compare one surface (running/installed) against the checkout contract."""
    checkout_commands = set(checkout.get("commands", []))
    checkout_version = checkout.get("version")
    surface_commands = set(surface.get("commands", []))
    missing = sorted(checkout_commands - surface_commands)

    version_behind = (
        checkout_version is not None
        and surface.get("version") is not None
        and surface["version"] < checkout_version
    )
    version_unknown = surface.get("version") is None
    checkout_fp = checkout.get("fingerprint")
    surface_fp = surface.get("fingerprint")
    # Only a decisive mismatch of two known fingerprints counts as drift; an
    # unreported fingerprint is handled by the version/command signals.
    fingerprint_drift = bool(checkout_fp and surface_fp and surface_fp != checkout_fp)
    stale = bool(missing) or version_behind or version_unknown or fingerprint_drift
    return {
        "version": surface.get("version"),
        "commands": sorted(surface_commands),
        "fingerprint": surface_fp,
        "missing_commands": missing,
        "version_behind": version_behind,
        "version_unknown": version_unknown,
        "fingerprint_drift": fingerprint_drift,
        "stale": stale,
    }


def build_freshness(root: Path) -> dict[str, Any]:
    """Assemble the three-way freshness comparison and an actionable verdict."""
    checkout = checkout_contract(root)
    running = running_contract()
    installed = installed_contract()

    refresh = (
        "Refresh with `python -m pip install --editable .` from the repository "
        "root (PowerShell or POSIX), or invoke the source directly with "
        "`python -m wea_cli.cli ...`."
    )

    result: dict[str, Any] = {
        "checkout": checkout,
        "running": {
            "version": running["version"],
            "commands": running["commands"],
            "fingerprint": running["fingerprint"],
        },
        "installed": installed,
        "refresh": refresh,
    }

    if not checkout.get("available", False):
        result["status"] = "unknown"
        result["drift"] = False
        result["message"] = (
            f"Cannot read the checkout CLI contract: {checkout.get('reason')}."
        )
        return result

    running_eval = _evaluate(running, checkout)
    installed_eval = _evaluate(installed, checkout) if installed.get("found") else None
    result["running_vs_checkout"] = running_eval
    result["installed_vs_checkout"] = installed_eval

    running_stale = running_eval["stale"]
    installed_stale = bool(installed_eval and installed_eval["stale"])
    drift = running_stale or installed_stale
    result["drift"] = drift
    result["status"] = "stale" if drift else "fresh"

    if not drift:
        if not installed.get("found"):
            result["message"] = (
                "Running CLI matches the checkout contract. No installed `wea` on "
                "PATH; use the source invocation."
            )
        else:
            result["message"] = (
                "Running and installed `wea` both match the checkout contract."
            )
        return result

    parts: list[str] = []
    if running_stale:
        reason = (
            "different implementation bytes"
            if running_eval["fingerprint_drift"]
            else f"version {running_eval['version']} vs {checkout.get('version')}"
        )
        parts.append(
            f"The invoked CLI is behind the checkout contract ({reason}; "
            f"missing {running_eval['missing_commands'] or 'none'})."
        )
    if installed_stale and installed_eval is not None:
        if installed_eval["version_unknown"]:
            detail = "cannot report its version"
        elif installed_eval["fingerprint_drift"]:
            detail = "different implementation bytes"
        else:
            detail = f"version {installed_eval['version']} vs {checkout.get('version')}"
        parts.append(
            f"The installed `wea` ({installed.get('path')}) is stale ({detail}; "
            f"missing {installed_eval['missing_commands'] or 'none'})."
        )
    result["message"] = " ".join(parts)
    return result


def render_freshness(report: dict[str, Any]) -> str:
    """Human-readable rendering of :func:`build_freshness`."""
    lines: list[str] = []
    lines.append(f"CLI freshness: {report.get('status', 'unknown').upper()}")
    checkout = report.get("checkout", {})
    if checkout.get("available"):
        lines.append(
            f"  checkout contract: version {checkout.get('version')}, "
            f"{len(checkout.get('commands', []))} commands"
        )
    running = report.get("running", {})
    lines.append(
        f"  invoked CLI: version {running.get('version')}, "
        f"{len(running.get('commands', []))} commands"
    )
    installed = report.get("installed", {})
    if installed.get("found"):
        lines.append(
            f"  installed `wea`: {installed.get('path')} "
            f"(version {installed.get('version')})"
        )
    else:
        lines.append("  installed `wea`: not found on PATH")
    lines.append(f"  {report.get('message', '')}")
    if report.get("drift"):
        lines.append(f"  {report.get('refresh', '')}")
    return "\n".join(lines)
