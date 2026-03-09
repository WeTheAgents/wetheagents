#!/usr/bin/env python3
"""Tests for contrib/scripts/check_concurrent_claims.py."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parent.parent / "contrib" / "scripts" / "check_concurrent_claims.py"


def _run(args: list[str], root: Path | None = None) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(SCRIPT)] + args
    if root:
        cmd.extend(["--root", str(root)])
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def test_json_file_ok_under_limit(tmp_path: Path) -> None:
    """No agent exceeds max 2."""
    claims_file = tmp_path / "claims.json"
    claims_file.write_text(
        json.dumps([
            {"issue": 1, "agent": "alice@test"},
            {"issue": 2, "agent": "alice@test"},
            {"issue": 3, "agent": "bob@test"},
        ])
    )
    result = _run(["--json-file", str(claims_file)])
    assert result.returncode == 0
    assert "OK" in result.stdout


def test_json_file_fail_over_limit(tmp_path: Path) -> None:
    """Agent has 3 claims, max 2."""
    claims_file = tmp_path / "claims.json"
    claims_file.write_text(
        json.dumps([
            {"issue": 1, "agent": "alice@test"},
            {"issue": 2, "agent": "alice@test"},
            {"issue": 3, "agent": "alice@test"},
        ])
    )
    result = _run(["--json-file", str(claims_file)])
    assert result.returncode == 1
    assert "FAIL" in result.stdout
    assert "alice@test" in result.stdout
    assert "3 claims" in result.stdout
    assert "Remediation" in result.stdout


def test_json_file_custom_max(tmp_path: Path) -> None:
    """Max 3, agent has 3 — OK."""
    claims_file = tmp_path / "claims.json"
    claims_file.write_text(
        json.dumps([
            {"issue": 1, "agent": "alice@test"},
            {"issue": 2, "agent": "alice@test"},
            {"issue": 3, "agent": "alice@test"},
        ])
    )
    result = _run(["--json-file", str(claims_file), "--max", "3"])
    assert result.returncode == 0


def test_json_file_empty(tmp_path: Path) -> None:
    """No claims — OK."""
    claims_file = tmp_path / "claims.json"
    claims_file.write_text("[]")
    result = _run(["--json-file", str(claims_file)])
    assert result.returncode == 0


def test_json_file_alternate_format(tmp_path: Path) -> None:
    """Accept 'number' as alias for 'issue'."""
    claims_file = tmp_path / "claims.json"
    claims_file.write_text(
        json.dumps([
            {"number": 10, "agent": "bob@test"},
            {"number": 11, "agent": "bob@test"},
        ])
    )
    result = _run(["--json-file", str(claims_file)])
    assert result.returncode == 0


def test_json_file_whitespace_only_agent_skipped(tmp_path: Path) -> None:
    """Whitespace-only agent is rejected after strip — not counted."""
    claims_file = tmp_path / "claims.json"
    claims_file.write_text(
        json.dumps([
            {"issue": 1, "agent": "alice@test"},
            {"issue": 2, "agent": "   "},
            {"issue": 3, "agent": "alice@test"},
        ])
    )
    result = _run(["--json-file", str(claims_file)])
    assert result.returncode == 0
