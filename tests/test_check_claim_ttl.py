#!/usr/bin/env python3
"""Tests for scripts/check_claim_ttl.py."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_claim_ttl.py"


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT)] + args,
        capture_output=True,
        text=True,
        check=False,
    )


def test_json_file_ok_fresh_claim(tmp_path: Path) -> None:
    """Claim 1 hour ago, TTL 24h — OK."""
    claims_file = tmp_path / "claims.json"
    claims_file.write_text(
        json.dumps([
            {
                "issue": 1,
                "agent": "alice@test",
                "claimed_at": "2026-03-05T10:00:00Z",
            },
        ])
    )
    result = _run(["--json-file", str(claims_file), "--now", "2026-03-05T11:00:00Z"])
    assert result.returncode == 0
    assert "OK" in result.stdout


def test_json_file_fail_expired(tmp_path: Path) -> None:
    """Claim 25h ago, TTL 24h — FAIL."""
    claims_file = tmp_path / "claims.json"
    claims_file.write_text(
        json.dumps([
            {
                "issue": 54,
                "agent": "bob@test",
                "claimed_at": "2026-03-05T00:00:00Z",
            },
        ])
    )
    result = _run([
        "--json-file", str(claims_file),
        "--now", "2026-03-06T01:00:00Z",
        "--ttl-hours", "24",
    ])
    assert result.returncode == 1
    assert "FAIL" in result.stdout
    assert "#54" in result.stdout
    assert "bob@test" in result.stdout
    assert "Remediation" in result.stdout


def test_json_file_custom_ttl(tmp_path: Path) -> None:
    """Claim 13h ago, TTL 12h — FAIL. TTL 24h — OK."""
    claims_file = tmp_path / "claims.json"
    claims_file.write_text(
        json.dumps([
            {"issue": 1, "agent": "alice@test", "claimed_at": "2026-03-05T00:00:00Z"},
        ])
    )
    result_fail = _run([
        "--json-file", str(claims_file),
        "--now", "2026-03-05T13:00:00Z",
        "--ttl-hours", "12",
    ])
    assert result_fail.returncode == 1

    result_ok = _run([
        "--json-file", str(claims_file),
        "--now", "2026-03-05T13:00:00Z",
        "--ttl-hours", "24",
    ])
    assert result_ok.returncode == 0


def test_json_file_empty(tmp_path: Path) -> None:
    """No claims — OK."""
    claims_file = tmp_path / "claims.json"
    claims_file.write_text("[]")
    result = _run(["--json-file", str(claims_file)])
    assert result.returncode == 0


def test_json_file_invalid_timestamp_treated_as_expired(tmp_path: Path) -> None:
    """Malformed timestamp — treat as expired."""
    claims_file = tmp_path / "claims.json"
    claims_file.write_text(
        json.dumps([
            {"issue": 1, "agent": "alice@test", "claimed_at": "not-a-date"},
        ])
    )
    result = _run(["--json-file", str(claims_file), "--now", "2026-03-05T12:00:00Z"])
    assert result.returncode == 1
    assert "#1" in result.stdout


def test_json_file_every_good_claim_exempt_from_ttl(tmp_path: Path) -> None:
    """Claim 25h ago on an every_good task is exempt (no squatting harm)."""
    claims_file = tmp_path / "claims.json"
    claims_file.write_text(
        json.dumps([
            {
                "issue": 99,
                "agent": "bob@test",
                "claimed_at": "2026-03-05T00:00:00Z",
                "mechanic": "every_good",
            },
        ])
    )
    result = _run([
        "--json-file", str(claims_file),
        "--now", "2026-03-06T01:00:00Z",
        "--ttl-hours", "24",
    ])
    assert result.returncode == 0
    assert "OK" in result.stdout


def test_json_file_best_x_claim_exempt_from_ttl(tmp_path: Path) -> None:
    """best_x is also a parallel-submission mechanic, so claims are exempt."""
    claims_file = tmp_path / "claims.json"
    claims_file.write_text(
        json.dumps([
            {
                "issue": 100,
                "agent": "alice@test",
                "claimed_at": "2026-03-05T00:00:00Z",
                "mechanic": "best_x",
            },
        ])
    )
    result = _run([
        "--json-file", str(claims_file),
        "--now", "2026-03-06T01:00:00Z",
        "--ttl-hours", "24",
    ])
    assert result.returncode == 0


def test_json_file_standard_claim_still_enforces_ttl(tmp_path: Path) -> None:
    """Standard mechanic is single-winner — TTL still applies."""
    claims_file = tmp_path / "claims.json"
    claims_file.write_text(
        json.dumps([
            {
                "issue": 101,
                "agent": "carol@test",
                "claimed_at": "2026-03-05T00:00:00Z",
                "mechanic": "standard",
            },
        ])
    )
    result = _run([
        "--json-file", str(claims_file),
        "--now", "2026-03-06T01:00:00Z",
        "--ttl-hours", "24",
    ])
    assert result.returncode == 1
    assert "#101" in result.stdout


def test_json_file_whitespace_only_agent_or_claimed_at_skipped(tmp_path: Path) -> None:
    """Whitespace-only agent or claimed_at rejected after strip."""
    claims_file = tmp_path / "claims.json"
    claims_file.write_text(
        json.dumps([
            {"issue": 1, "agent": "alice@test", "claimed_at": "2026-03-05T10:00:00Z"},
            {"issue": 2, "agent": "   ", "claimed_at": "2026-03-05T10:00:00Z"},
            {"issue": 3, "agent": "bob@test", "claimed_at": "  "},
        ])
    )
    result = _run(["--json-file", str(claims_file), "--now", "2026-03-05T11:00:00Z"])
    assert result.returncode == 0
