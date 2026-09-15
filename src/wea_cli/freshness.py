"""`wea freshness` — detect a stale installed CLI against the source checkout.

Freshness compares the *content fingerprint* of the shipped runtime — the actual
``.py`` and ``.json`` bytes of the ``wea_cli`` package and the sibling protocol
package (discovered structurally, never imported) — between two places:

- the **checkout** at ``--root`` (its ``src`` tree), and
- the **installed** ``wea`` console script on ``PATH`` (probed as a subprocess in
  a clean environment, so it reports its own installed bytes).

Because it hashes real files, an installed CLI that shares the same command names
but ships older implementation bytes is correctly reported STALE — a constant
epoch or command-name comparison would miss that.

It also solves the "an older executable cannot warn retroactively" problem: an
install that predates this command cannot answer the probe, and that failed probe
is itself the stale signal, surfaced by a source preflight.

This module has no dependency on the vNext protocol package and imports no writer
module, so it stays outside the surface guarded by
``tests/vnext/test_runtime_boundary``.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

# Monotonic contract epoch. Bump this in the same commit whenever the reliable
# command surface changes in a way an installed CLI must be refreshed to match.
# 1: report/push/freshness reliability work for vNext (Task #980).
CONTRACT_EPOCH = 1

# Sentinel used when the packaged distribution metadata is unavailable (for
# example, running straight from a source tree that was never installed).
SOURCE_VERSION = "0+source"

# The console-script name the packaging metadata installs (`pyproject.toml`).
INSTALLED_ENTRYPOINT = "wea"

# The primary CLI package; the sibling protocol package is found structurally.
_CLI_PACKAGE = "wea_cli"

# File suffixes whose bytes define the shipped runtime.
_FINGERPRINT_SUFFIXES = frozenset({".py", ".json"})


def package_version() -> str:
    """Return the installed ``wea-cli`` distribution version, or a source marker."""
    try:
        from importlib.metadata import version

        return version("wea-cli")
    except Exception:
        return SOURCE_VERSION


def _project_package_dirs(src_root: Path) -> list[Path]:
    """Return the project package directories under ``src_root`` to fingerprint.

    Always includes ``wea_cli``; the sibling protocol package is identified by a
    structural marker (an ``engine.py`` module plus an ``executors`` directory)
    so this module never has to name or import it.
    """
    dirs: list[Path] = []
    cli_dir = src_root / _CLI_PACKAGE
    if cli_dir.is_dir():
        dirs.append(cli_dir)
    if not src_root.is_dir():
        return dirs
    for child in sorted(p for p in src_root.iterdir() if p.is_dir()):
        if child.name == _CLI_PACKAGE:
            continue
        if (child / "engine.py").is_file() and (child / "executors").is_dir():
            dirs.append(child)
    return dirs


def fingerprint(src_root: Path) -> str | None:
    """Content fingerprint of the project's shipped runtime files under ``src_root``.

    Returns ``None`` when no project packages are found (nothing to measure).
    """
    dirs = _project_package_dirs(src_root)
    if not dirs:
        return None
    digest = hashlib.sha256()
    for pkg in dirs:
        for path in sorted(pkg.rglob("*")):
            if not path.is_file() or path.suffix not in _FINGERPRINT_SUFFIXES:
                continue
            if "__pycache__" in path.parts:
                continue
            rel = path.relative_to(src_root).as_posix()
            digest.update(rel.encode("utf-8"))
            digest.update(b"\0")
            digest.update(hashlib.sha256(path.read_bytes()).digest())
            digest.update(b"\0")
    return digest.hexdigest()


def _running_src_root() -> Path:
    """The ``src`` root of the runtime executing this process (the installation)."""
    return Path(__file__).resolve().parent.parent


def _contract(commands: list[str], src_root: Path) -> dict[str, Any]:
    return {
        "epoch": CONTRACT_EPOCH,
        "version": package_version(),
        "commands": sorted(commands),
        "fingerprint": fingerprint(src_root),
    }


def checkout_contract(commands: list[str], root: Path) -> dict[str, Any]:
    """Contract for the source checkout at ``root`` (its ``src`` tree)."""
    return _contract(commands, root / "src")


def installed_contract(commands: list[str]) -> dict[str, Any]:
    """Contract for the runtime executing this process (the installation)."""
    return _contract(commands, _running_src_root())


def _decode_probe(stdout: str) -> dict[str, Any] | None:
    """Parse a probed contract from ``wea freshness --emit-contract`` output."""
    text = stdout.strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    if "epoch" not in payload or "commands" not in payload:
        return None
    return payload


def probe_installed(executable: str | None) -> dict[str, Any]:
    """Probe the installed console script for its contract.

    Returns a dict with ``status`` one of ``present`` (contract found),
    ``legacy`` (executable exists but lacks the freshness feature), or
    ``missing`` (no executable on PATH). ``contract`` is populated for
    ``present``; ``path`` is populated for ``present``/``legacy``.
    """
    path = executable or shutil.which(INSTALLED_ENTRYPOINT)
    if not path:
        return {"status": "missing", "path": None, "contract": None}

    # Measure the *actually-installed* package: strip PYTHONPATH so a source
    # preflight (which may run with PYTHONPATH pointing at the checkout) does not
    # contaminate the child and mask a stale install as fresh.
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    try:
        completed = subprocess.run(
            [path, "freshness", "--emit-contract"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
            env=env,
        )
    except OSError as exc:
        return {"status": "legacy", "path": path, "contract": None, "detail": str(exc)}

    if completed.returncode != 0:
        # An older CLI rejects the unknown subcommand/flag (argparse exits 2), or
        # the command is absent entirely. Either way it cannot self-report — that
        # is the retroactive-staleness signal.
        return {"status": "legacy", "path": path, "contract": None}

    contract = _decode_probe(completed.stdout)
    if contract is None:
        return {"status": "legacy", "path": path, "contract": None}
    return {"status": "present", "path": path, "contract": contract}


def compare(source: dict[str, Any], probe: dict[str, Any]) -> dict[str, Any]:
    """Compare the checkout contract against the installed probe."""
    status = probe["status"]
    source_commands = set(source.get("commands", []))

    if status == "missing":
        return {
            "state": "not_installed",
            "fresh": None,
            "reason": (
                f"No `{INSTALLED_ENTRYPOINT}` console script found on PATH. "
                "The source CLI works via `python -m wea_cli.cli`."
            ),
            "missing_commands": sorted(source_commands),
        }

    if status == "legacy":
        return {
            "state": "stale",
            "fresh": False,
            "reason": (
                f"Installed `{INSTALLED_ENTRYPOINT}` ({probe.get('path')}) "
                "predates the freshness contract and cannot report its runtime."
            ),
            "missing_commands": sorted(source_commands),
        }

    installed = probe["contract"]
    installed_commands = set(installed.get("commands", []))
    missing = sorted(source_commands - installed_commands)
    installed_epoch = installed.get("epoch", 0)
    source_epoch = source.get("epoch", 0)
    src_fp = source.get("fingerprint")
    inst_fp = installed.get("fingerprint")

    # Primary signal: real shipped-runtime bytes. Different content -> stale even
    # when the command names and epoch match.
    if src_fp and inst_fp and src_fp != inst_fp:
        return {
            "state": "stale",
            "fresh": False,
            "reason": (
                "Installed runtime bytes differ from the checkout "
                f"(installed {inst_fp[:12]} vs checkout {src_fp[:12]})"
                + (f"; missing commands: {', '.join(missing)}" if missing else "")
                + "."
            ),
            "missing_commands": missing,
        }

    # Secondary signals when a fingerprint is unavailable.
    if installed_epoch < source_epoch or missing:
        return {
            "state": "stale",
            "fresh": False,
            "reason": (
                f"Installed contract epoch {installed_epoch} is behind source epoch "
                f"{source_epoch}"
                + (f"; missing commands: {', '.join(missing)}" if missing else "")
                + "."
            ),
            "missing_commands": missing,
        }

    if installed_epoch > source_epoch:
        return {
            "state": "source_behind",
            "fresh": False,
            "reason": (
                f"Installed contract epoch {installed_epoch} is ahead of source epoch "
                f"{source_epoch}; the checkout is older than the installed CLI."
            ),
            "missing_commands": [],
        }

    return {
        "state": "fresh",
        "fresh": True,
        "reason": (
            f"Installed `{INSTALLED_ENTRYPOINT}` matches the checkout runtime "
            f"(epoch {source_epoch})."
        ),
        "missing_commands": [],
    }


REFRESH_HINT = "python -m pip install --editable ."
SOURCE_PREFLIGHT = "python src/wea_cli/cli.py --root . freshness"


def build_result(
    commands: list[str], root: Path, executable: str | None = None
) -> dict[str, Any]:
    """Compute the full freshness result for the checkout at ``root`` and PATH."""
    source = checkout_contract(commands, root)
    probe = probe_installed(executable)
    comparison = compare(source, probe)
    return {
        "source_contract": source,
        "installed": {
            "status": probe["status"],
            "path": probe.get("path"),
            "contract": probe.get("contract"),
        },
        "comparison": comparison,
        "refresh": {"posix": REFRESH_HINT, "powershell": REFRESH_HINT},
        "source_invocation": SOURCE_PREFLIGHT,
    }


def render(result: dict[str, Any]) -> str:
    """Render a concise human-readable freshness report."""
    source = result["source_contract"]
    installed = result["installed"]
    comparison = result["comparison"]
    src_fp = source.get("fingerprint")
    lines = [
        "wea freshness",
        f"  source (checkout): epoch {source['epoch']}, version {source['version']}, "
        f"fingerprint {src_fp[:12] if src_fp else 'n/a'}",
    ]
    if installed["status"] == "present" and installed["contract"]:
        c = installed["contract"]
        inst_fp = c.get("fingerprint")
        lines.append(
            f"  installed ({installed['path']}): epoch {c.get('epoch')}, "
            f"version {c.get('version')}, fingerprint "
            f"{inst_fp[:12] if inst_fp else 'n/a'}"
        )
    elif installed["status"] == "legacy":
        lines.append(f"  installed ({installed['path']}): legacy, no contract")
    else:
        lines.append("  installed: not found on PATH")

    state = comparison["state"]
    label = {
        "fresh": "FRESH",
        "stale": "STALE",
        "source_behind": "SOURCE BEHIND",
        "not_installed": "NOT INSTALLED",
    }.get(state, state.upper())
    lines.append(f"  status: {label} — {comparison['reason']}")
    if not comparison.get("fresh"):
        lines.append(f"  refresh: {result['refresh']['posix']}  (PowerShell and POSIX)")
        lines.append(
            f"  source preflight without install: {result['source_invocation']}"
        )
    return "\n".join(lines)


def emit_contract(commands: list[str]) -> None:
    """Print the running installation's contract as JSON for a probe."""
    json.dump(installed_contract(commands), sys.stdout, sort_keys=True)
    sys.stdout.write("\n")
