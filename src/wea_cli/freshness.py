"""Standalone source preflight for old executables, using only the standard library."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

REFRESH = "Refresh in this checkout: python -m pip install --editable ."


def contract(package: Path, packages: dict[str, Path] | None = None) -> dict[str, Any]:
    digest = hashlib.sha256()
    roots = (
        packages
        if packages is not None
        else {
            directory.name: directory
            for directory in package.parent.iterdir()
            if directory.is_dir() and (directory / "__init__.py").is_file()
        }
    )
    if package.name not in roots:
        raise ValueError("Checkout package inventory is incomplete. " + REFRESH)
    for name, directory in sorted(roots.items()):
        if not (directory / "__init__.py").is_file():
            raise ValueError(f"Required {name} package is missing. " + REFRESH)
        for path in sorted(directory.rglob("*")):
            if path.is_file() and path.suffix in {".py", ".json"}:
                relative = f"{name}/{path.relative_to(directory).as_posix()}"
                digest.update(relative.encode("utf-8") + b"\0")
                digest.update(path.read_bytes() + b"\0")
    return {
        "schema": "wea-cli-contract-1",
        "sha256": digest.hexdigest(),
        "commands": ["report", "push", "tide"],
    }


def installed_contract(packages: dict[str, Path]) -> dict[str, Any]:
    package = Path(__file__).resolve().parent
    return contract(package, {package.name: package, **packages})


def check_checkout(root: Path, invoked: dict[str, Any]) -> None:
    source = root / "src" / "wea_cli"
    if source.is_dir() and invoked != contract(source):
        raise ValueError("Invoked CLI differs from checkout source. " + REFRESH)


def preflight(root: Path, executable: str) -> dict[str, Any]:
    source = root / "src" / "wea_cli"
    if not (source / "cli.py").is_file():
        raise ValueError("Checkout CLI is missing; pass --root to a complete checkout.")
    expected = contract(source)
    resolved = shutil.which(executable)
    if resolved is None:
        raise ValueError("Installed wea executable is missing. " + REFRESH)
    env = os.environ.copy()
    # Do not let the source invocation mask the install being inspected.
    env.pop("PYTHONPATH", None)
    try:
        result = subprocess.run(
            [resolved, "--cli-contract"],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=True,
        )
        actual = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise ValueError(
            "Installed CLI is stale or cannot expose its contract. " + REFRESH
        ) from exc
    if actual != expected:
        raise ValueError("Installed CLI differs from checkout source. " + REFRESH)
    return {
        "status": "current",
        "executable": str(Path(resolved).resolve()),
        "contract": expected,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--executable", default="wea")
    args = parser.parse_args()
    try:
        print(
            json.dumps(preflight(args.root.resolve(), args.executable), sort_keys=True)
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
