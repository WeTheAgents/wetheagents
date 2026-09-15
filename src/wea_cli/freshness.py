"""`wea freshness` — detect a stale installed CLI against the source checkout.

The running process computes its own CLI *contract* (an epoch, the packaged
version, and the sorted command surface). When invoked from the source checkout
(``python -m wea_cli.cli freshness``) that contract is the checkout contract. The
command then probes the ``wea`` console script on ``PATH`` as a subprocess and
compares it against the running contract.

This solves the "an older executable cannot acquire a warning retroactively"
problem: an installed ``wea`` that predates this feature cannot warn about being
stale, but a source preflight can still detect it — the probe of an old
executable fails (the ``freshness`` command is missing), which is itself the
stale signal.

This module intentionally has no dependency on the vNext protocol package, so it
stays outside the writer surface guarded by ``tests/vnext/test_runtime_boundary``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
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


def package_version() -> str:
    """Return the installed ``wea-cli`` distribution version, or a source marker."""
    try:
        from importlib.metadata import version

        return version("wea-cli")
    except Exception:
        return SOURCE_VERSION


def local_contract(commands: list[str]) -> dict[str, Any]:
    """Build the contract for the code executing in this process.

    ``commands`` is the sorted top-level command surface supplied by the caller
    (the CLI parser owns the authoritative list; passing it keeps this module
    free of a circular import on ``wea_cli.cli``).
    """
    return {
        "epoch": CONTRACT_EPOCH,
        "version": package_version(),
        "commands": sorted(commands),
    }


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
    # preflight (which runs with PYTHONPATH pointing at the checkout) does not
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
    """Compare the running (checkout) contract against the installed probe."""
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
                "predates the freshness contract and cannot report its command surface."
            ),
            "missing_commands": sorted(source_commands),
        }

    installed = probe["contract"]
    installed_commands = set(installed.get("commands", []))
    missing = sorted(source_commands - installed_commands)
    installed_epoch = installed.get("epoch", 0)
    source_epoch = source.get("epoch", 0)

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
            f"Installed `{INSTALLED_ENTRYPOINT}` matches the checkout contract "
            f"(epoch {source_epoch})."
        ),
        "missing_commands": [],
    }


REFRESH_HINT_POSIX = "python -m pip install --editable ."
REFRESH_HINT_POWERSHELL = "python -m pip install --editable ."


def build_result(commands: list[str], executable: str | None = None) -> dict[str, Any]:
    """Compute the full freshness result for the current process and PATH."""
    source = local_contract(commands)
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
        "refresh": {
            "posix": REFRESH_HINT_POSIX,
            "powershell": REFRESH_HINT_POWERSHELL,
        },
        "source_invocation": "python -m wea_cli.cli",
    }


def render(result: dict[str, Any]) -> str:
    """Render a concise human-readable freshness report."""
    source = result["source_contract"]
    installed = result["installed"]
    comparison = result["comparison"]
    lines = [
        "wea freshness",
        f"  source (checkout): epoch {source['epoch']}, version {source['version']}",
    ]
    if installed["status"] == "present" and installed["contract"]:
        c = installed["contract"]
        lines.append(
            f"  installed ({installed['path']}): epoch {c.get('epoch')}, "
            f"version {c.get('version')}"
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
        lines.append(
            "  refresh: "
            + result["refresh"]["posix"]
            + "  (PowerShell and POSIX use the same command)"
        )
        lines.append(
            "  source preflight without install: python -m wea_cli.cli freshness"
        )
    return "\n".join(lines)


def emit_contract(commands: list[str]) -> None:
    """Print the running contract as JSON for a source preflight probe."""
    json.dump(local_contract(commands), sys.stdout, sort_keys=True)
    sys.stdout.write("\n")
