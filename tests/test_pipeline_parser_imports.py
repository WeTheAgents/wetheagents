"""Import contracts, isolated from pytest and machine-wide editable installs."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
IMPORT_PROBE = """
import importlib
import json
import sys

module_name, import_root, dependency_root = sys.argv[1:]
sys.path[:0] = [import_root, import_root]
if dependency_root:
    sys.path.append(dependency_root)
before = sys.path.copy()
error = None
module_origin = dependency_origin = None
try:
    parser = importlib.import_module(module_name)
    support = importlib.import_module('wea_cli.pipeline_support')
    module_origin = parser.__file__
    dependency_origin = support.__file__
except ModuleNotFoundError as exc:
    error = exc.name
print(json.dumps(dict(before=before, after=sys.path, error=error,
                     module_origin=module_origin,
                     dependency_origin=dependency_origin)))
"""


def _import_probe(module_name: str, dependency_root: str, cwd: Path) -> dict:
    import_root = ROOT if module_name.startswith("scripts.") else ROOT / "scripts"
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-c", IMPORT_PROBE,
         module_name, str(import_root), dependency_root],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )
    # Retain complete paths and origins in verbose test evidence, even on failure.
    print(result.stdout)
    return json.loads(result.stdout)


@pytest.mark.parametrize("module_name", ["scripts.pipeline_parser", "pipeline_parser"])
@pytest.mark.parametrize("layout", ["source", "source-alias", "installed-layout"])
def test_import_preserves_path_and_dependency_origin(
    module_name: str, layout: str, tmp_path: Path,
) -> None:
    dependency_root = ROOT / "src"
    if layout == "installed-layout":
        dependency_root = tmp_path / "site-packages"
        shutil.copytree(
            ROOT / "src" / "wea_cli", dependency_root / "wea_cli",
            ignore=shutil.ignore_patterns("__pycache__"),
        )
    dependency_entry = str(dependency_root)
    if layout == "source-alias":
        # A valid source path spelling that differs from the parser's old insert.
        dependency_entry += "/."

    result = _import_probe(module_name, dependency_entry, tmp_path)

    assert result["error"] is None
    assert result["after"] == result["before"]
    assert Path(result["module_origin"]).resolve() == ROOT / "scripts/pipeline_parser.py"
    assert Path(result["dependency_origin"]).resolve() == (
        dependency_root / "wea_cli/pipeline_support.py"
    )


@pytest.mark.parametrize("module_name", ["scripts.pipeline_parser", "pipeline_parser"])
def test_missing_dependency_does_not_bootstrap_source_path(
    module_name: str, tmp_path: Path,
) -> None:
    result = _import_probe(module_name, "", tmp_path)

    assert result["error"] == "wea_cli"
    assert result["after"] == result["before"]
