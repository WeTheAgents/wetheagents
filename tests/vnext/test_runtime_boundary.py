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

from wea_vnext import (
    declarations,
    hello_world,
    identity,
    intake,
    migration,
    projection,
    resolution_plan,
)
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
        _executor_version(intake.DraftIssue),
        _executor_version(projection.ProjectionIntent),
    }
    assert versions == {"0_6_3"}
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
    assert intake.DraftIssue is identity._MODULES["intake"].DraftIssue
    assert (
        projection.ProjectionIntent is identity._MODULES["projection"].ProjectionIntent
    )


def test_resolution_plan_facade_is_explicitly_pinned_to_executor_0_8_0() -> None:
    assert _executor_version(resolution_plan.DraftIssue) == "0_8_0"
    assert _executor_version(resolution_plan.PlanStage) == "0_8_0"
    assert _executor_version(resolution_plan.StageSchedule) == "0_8_0"
    assert _executor_version(resolution_plan.LifecycleEvent) == "0_8_0"
    assert resolution_plan.Binding is resolution_plan._MODULES["identity"].Binding
    assert (
        resolution_plan.PlanIntakeState
        is resolution_plan._MODULES["intake"].PlanIntakeState
    )
    assert resolution_plan.load_ruleset().version == "0.8"
    assert resolution_plan._RUNTIME == installed_executor("0.8.0").reference
    assert installed_executor("0.7.0").reference != resolution_plan._RUNTIME


def test_entrypoints_only_expose_the_approved_github_path() -> None:
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
    for name in ("guard-doc-sync.yml", "semgrep.yml", "guard-vnext-boundary.yml"):
        path = Path(".github/workflows") / name
        # This exact trigger filter is data, not an executable vNext entrypoint.
        # Keep scanning the rest of each workflow, including all run steps.
        contents[path] = contents[path].replace('      - "ledger/vnext/**"\n', "")
    allowed = {
        ".github/workflows/tide.yml",
        ".github/workflows/guard-vnext-ledger.yml",
        "src/wea_cli/tide.py",  # Read-only canonical projection and next action.
        "src/wea_cli/task_labels.py",  # Read-only task labels and canonical balance.
        "src/wea_cli/cli.py",  # Command routing and retired-write rejection.
        "scripts/check_invariant.py",  # Read-only replay check.
        "scripts/check_ledger_schema.py",  # Read-only replay check.
    }
    violations = {
        path.as_posix(): "vnext reference"
        for path, content in contents.items()
        if path.as_posix() not in allowed
        if any(
            marker in content.casefold()
            for marker in ("wea_vnext", "wea-vnext", "ledger/vnext", "ledger\\vnext")
        )
    }
    assert not violations
    assert not Path("scripts/tide_vnext.py").exists()


def test_financial_correction_stays_outside_current_runtime_closures() -> None:
    correction = Path("src/wea_vnext/financial_correction.py")
    assert correction.exists()
    protected_surfaces = (
        Path("src/wea_vnext/__init__.py"),
        Path("src/wea_vnext/engine.py"),
        Path("src/wea_vnext/declarations.py"),
        Path("src/wea_vnext/hello_world.py"),
        Path("src/wea_vnext/identity.py"),
        Path("src/wea_vnext/intake.py"),
        Path("src/wea_vnext/migration.py"),
        Path("src/wea_vnext/projection.py"),
        Path("src/wea_vnext/resolution_plan.py"),
        *Path("src/wea_vnext/executors").rglob("*.py"),
        *Path("src/wea_vnext/executors").rglob("manifest.json"),
    )
    violations = {
        str(path): "financial correction reference"
        for path in protected_surfaces
        if "financial_correction" in path.read_text(encoding="utf-8", errors="ignore")
    }
    assert not violations


def test_boundary_guard_runs_on_pull_requests() -> None:
    workflow = Path(".github/workflows/guard-vnext-boundary.yml").read_text(
        encoding="utf-8"
    )
    assert "pull_request:" in workflow
    assert "pytest tests/vnext/test_runtime_boundary.py" in workflow
