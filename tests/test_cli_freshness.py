"""Regression coverage for CLI freshness detection.

The comparison is exercised with synthetic checkout roots and a monkeypatched
installed probe so the tests are hermetic and do not depend on whatever `wea`
happens to be on the test machine's PATH. A subprocess test confirms the real
``--version`` banner an older executable is measured against.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import pytest

from wea_cli import cli, freshness


def test_freshness_is_classified_read_only() -> None:
    # Read-only classification lets `wea freshness` run under a Tide halt and
    # against a bare checkout without a ledger (the source-side preflight case).
    assert cli.is_readonly_command("freshness", argparse.Namespace()) is True


def _make_checkout(
    root: Path, *, contract_version: int, extra_commands: list[str]
) -> None:
    """Write a minimal src/wea_cli/{cli.py,freshness.py} contract into ``root``."""
    pkg = root / "src" / "wea_cli"
    pkg.mkdir(parents=True)
    base = [
        'p.add_parser("tide")',
        'subparsers.add_parser("report")',
        'subparsers.add_parser("push")',
        'subparsers.add_parser("freshness")',
    ]
    for command in extra_commands:
        base.append(f'subparsers.add_parser("{command}")')
    body = "def build_parser():\n    " + "\n    ".join(base) + "\n"
    (pkg / "cli.py").write_text(body, encoding="utf-8")
    (pkg / "freshness.py").write_text(
        f"CONTRACT_VERSION = {contract_version}\n", encoding="utf-8"
    )


def test_parse_top_level_commands_reads_subparser_literals() -> None:
    source = (
        "def build_parser():\n"
        '    subparsers.add_parser("report")\n'
        '    subparsers.add_parser("push")\n'
        '    task_subparsers.add_parser("lint")\n'  # nested, must be ignored
    )
    assert freshness.parse_top_level_commands(source) == {"report", "push"}


def test_probe_env_strips_pythonpath(monkeypatch: pytest.MonkeyPatch) -> None:
    # The installed probe must not inherit the source PYTHONPATH, or the
    # installed executable would import the checkout and always look fresh.
    monkeypatch.setenv("PYTHONPATH", "src")
    env = freshness._probe_env()
    assert "PYTHONPATH" not in env


# The real repository root, so running and checkout resolve the same package
# bytes (version, commands, and fingerprint all match) for the "fresh" cases.
REPO_ROOT = Path(freshness.__file__).resolve().parents[2]


def test_version_banner_contains_contract_and_fingerprint() -> None:
    banner = freshness.version_banner("0.2.0")
    assert banner.startswith("wea 0.2.0 ")
    assert f"cli-contract {freshness.CONTRACT_VERSION}" in banner
    assert "cli-fingerprint " in banner


def test_source_fingerprint_changes_with_bytes(tmp_path: Path) -> None:
    pkg = tmp_path / "wea_cli"
    pkg.mkdir()
    (pkg / "cli.py").write_text("a = 1\n", encoding="utf-8")
    first = freshness.source_fingerprint(pkg)
    (pkg / "cli.py").write_text("a = 2\n", encoding="utf-8")
    assert freshness.source_fingerprint(pkg) != first
    assert freshness.source_fingerprint(tmp_path / "absent") == ""


def test_checkout_contract_reads_version_and_commands(tmp_path: Path) -> None:
    _make_checkout(tmp_path, contract_version=5, extra_commands=["extra"])
    contract = freshness.checkout_contract(tmp_path)
    assert contract["available"] is True
    assert contract["version"] == 5
    assert "extra" in contract["commands"]


def test_freshness_fresh_when_running_matches_and_installed_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Against the real checkout the running package matches byte for byte.
    monkeypatch.setattr(freshness, "installed_contract", lambda: {"found": False})
    report = freshness.build_freshness(REPO_ROOT)
    assert report["status"] == "fresh"
    assert report["drift"] is False
    assert report["running_vs_checkout"]["fingerprint_drift"] is False
    assert "No installed `wea`" in report["message"]


def test_freshness_flags_running_behind_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Checkout advertises a higher contract version and an extra command the
    # running CLI does not have -> the invoked CLI is stale.
    _make_checkout(
        tmp_path,
        contract_version=freshness.CONTRACT_VERSION + 10,
        extra_commands=["brand-new-command"],
    )
    monkeypatch.setattr(freshness, "installed_contract", lambda: {"found": False})

    report = freshness.build_freshness(tmp_path)
    assert report["status"] == "stale"
    assert report["drift"] is True
    assert "brand-new-command" in report["running_vs_checkout"]["missing_commands"]
    assert "pip install --editable ." in report["refresh"]


def test_freshness_flags_installed_missing_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An installed wea that predates `tide` and cannot report its version.
    monkeypatch.setattr(
        freshness,
        "installed_contract",
        lambda: {
            "found": True,
            "path": "/usr/bin/wea",
            "version": None,
            "commands": ["tasks", "submit"],
            "fingerprint": None,
        },
    )
    report = freshness.build_freshness(REPO_ROOT)
    assert report["status"] == "stale"
    assert report["drift"] is True
    # The invoked CLI matches the real checkout; only the installed one is stale.
    assert report["running_vs_checkout"]["stale"] is False
    installed_eval = report["installed_vs_checkout"]
    assert "tide" in installed_eval["missing_commands"]
    assert installed_eval["version_unknown"] is True


def test_freshness_flags_installed_fingerprint_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Same version and commands but different implementation bytes -> stale.
    checkout = freshness.checkout_contract(REPO_ROOT)
    monkeypatch.setattr(
        freshness,
        "installed_contract",
        lambda: {
            "found": True,
            "path": "/usr/bin/wea",
            "version": checkout["version"],
            "commands": checkout["commands"],
            "fingerprint": "deadbeefdeadbeef",
        },
    )
    report = freshness.build_freshness(REPO_ROOT)
    assert report["drift"] is True
    installed_eval = report["installed_vs_checkout"]
    assert installed_eval["fingerprint_drift"] is True
    assert installed_eval["missing_commands"] == []


def test_freshness_unknown_when_checkout_unreadable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(freshness, "installed_contract", lambda: {"found": False})
    report = freshness.build_freshness(tmp_path)  # no src/wea_cli under tmp_path
    assert report["status"] == "unknown"
    assert report["drift"] is False


# --- subprocess integration --------------------------------------------------


def test_version_flag_reports_contract_stamp() -> None:
    import os

    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(freshness.__file__).resolve().parents[1])
    env["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run(
        [sys.executable, "-m", "wea_cli.cli", "--version"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0
    assert f"cli-contract {freshness.CONTRACT_VERSION}" in result.stdout
