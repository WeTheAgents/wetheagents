"""Regression coverage for the explicit v1/vNext runtime boundary."""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

import pytest

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 compatibility
    import tomli as tomllib

from wea_vnext import declarations, hello_world, identity, migration, projection
from wea_vnext.engine import RuntimeMismatchError, installed_executor


def _executor_version(value: type[object]) -> str:
    module_name = value.__module__
    prefix = "wea_vnext.executors.v"
    assert module_name.startswith(prefix)
    return module_name.removeprefix(prefix).split(".", 1)[0]


def test_executor_selection_requires_an_explicit_version() -> None:
    parameter = inspect.signature(installed_executor).parameters["version"]
    assert parameter.default is inspect.Parameter.empty


@pytest.mark.parametrize("version", ["0_6_2", "0.6_2", "0_6.2", "00.6.2", "0.06.2"])
def test_executor_selection_rejects_noncanonical_version_aliases(version: str) -> None:
    with pytest.raises(RuntimeMismatchError, match="canonical dotted semver"):
        installed_executor(version)


def test_public_facades_share_one_versioned_executor_closure() -> None:
    versions = {
        _executor_version(identity.Binding),
        _executor_version(hello_world.SystemHelloWorldContract),
        _executor_version(migration.V1IdentityEvidence),
        _executor_version(projection.ProjectionIntent),
    }
    assert versions == {"0_6_2"}
    assert declarations.Declaration is identity._MODULES["declarations"].Declaration
    assert (
        declarations.DeclarationError
        is identity._MODULES["declarations"].DeclarationError
    )
    assert identity.Binding is identity._MODULES["identity"].Binding
    assert (
        hello_world.SystemHelloWorldContract
        is identity._MODULES["identity_hello_world"].SystemHelloWorldContract
    )
    assert (
        migration.V1IdentityEvidence
        is identity._MODULES["identity_migration"].V1IdentityEvidence
    )
    assert (
        projection.ProjectionIntent is identity._MODULES["projection"].ProjectionIntent
    )


def test_pre_activation_entrypoint_surfaces_have_no_literal_vnext_reference() -> None:
    roots = (Path("src/wea_cli"), Path("scripts"), Path(".github/workflows"))
    paths = [
        path
        for root in roots
        for path in root.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    ]
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject.get("project", {})
    entry_points: dict[str, Any] = {
        "scripts": project.get("scripts", {}),
        "gui-scripts": project.get("gui-scripts", {}),
        "entry-points": project.get("entry-points", {}),
    }
    contents = {
        path: path.read_text(encoding="utf-8", errors="ignore") for path in paths
    }
    contents[Path("pyproject.toml:entry-points")] = repr(entry_points)
    violations = {
        str(path): "vnext reference"
        for path, content in contents.items()
        if any(
            marker in content.casefold()
            for marker in ("wea_vnext", "wea-vnext", "ledger/vnext", "ledger\\vnext")
        )
    }
    assert not violations
    assert not Path("scripts/tide_vnext.py").exists()
    assert not Path("ledger/vnext").exists()


def test_boundary_guard_runs_on_pull_requests() -> None:
    workflow = Path(".github/workflows/guard-vnext-boundary.yml").read_text(
        encoding="utf-8"
    )
    assert "pull_request:" in workflow
    assert "pytest tests/vnext/test_runtime_boundary.py" in workflow
