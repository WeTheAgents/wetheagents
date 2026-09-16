"""Compare the invoked CLI and PATH installation to this checkout's contract."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from . import __version__

REFRESH = "From this checkout run: python -m pip install --editable ."


def fingerprint(package: Path, runtime_files: list[Path]) -> str:
    digest = hashlib.sha256()
    paths = sorted(package.glob("*.py"))
    if not paths:
        raise ValueError(
            "Checkout CLI source is missing. Select the repository with --root."
        )
    paths += runtime_files
    for path in paths:
        digest.update(path.relative_to(package.parent).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
    return digest.hexdigest()


def version_info(runtime_files: list[Path]) -> dict[str, str]:
    return {
        "schema": "wea-cli-version-1",
        "version": __version__,
        "fingerprint": fingerprint(Path(__file__).parent, runtime_files),
    }


def check(
    root: Path, invoked: dict[str, str], runtime_files: list[Path]
) -> dict[str, Any]:
    expected = fingerprint(root / "src/wea_cli", runtime_files)
    installed: dict[str, Any] | None = None
    executable = shutil.which("wea")
    if executable:
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        try:
            result = subprocess.run(
                [executable, "--version"],
                cwd=Path(executable).resolve().parent,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
                check=False,
            )
            if result.returncode == 0:
                value = json.loads(result.stdout)
                if (
                    isinstance(value, dict)
                    and value.get("schema") == "wea-cli-version-1"
                ):
                    installed = value
        except (OSError, subprocess.TimeoutExpired, ValueError):
            pass  # Explicit unknown/stale result below; never a successful fallback.
    current = invoked["fingerprint"] == expected
    installed_current = (
        installed is not None and installed.get("fingerprint") == expected
    )
    return {
        "schema": "wea-cli-freshness-1",
        "status": "current" if current and installed_current else "stale_or_missing",
        "checkout_fingerprint": expected,
        "invoked": invoked,
        "invoked_matches_checkout": current,
        "installed": installed,
        "installed_matches_checkout": installed_current,
        "refresh": REFRESH,
        "source_preflight": "python -m wea_cli.cli --root . freshness",
    }
