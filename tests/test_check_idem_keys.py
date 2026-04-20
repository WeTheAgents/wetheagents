#!/usr/bin/env python3
"""Tests for check_idem_keys remediation output."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_idem_keys.py"


def _write_idem_file(path: Path, raw_keys: list[str]) -> None:
    keys = {hashlib.sha256(key.encode("utf-8")).hexdigest(): "2026-01-01T00:00:00Z" for key in raw_keys}
    payload = {"version": 1, "keys": keys}
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def test_duplicate_key_prints_remediation(tmp_path: Path) -> None:
    idem_file = tmp_path / "idem_keys.json"
    _write_idem_file(idem_file, ["payment|10|agent@test"])

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--ledger", str(idem_file), "payment|10|agent@test"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "Why it matters" in result.stdout
    assert "Remediation" in result.stdout


def test_duplicate_key_flat_dict_format(tmp_path: Path) -> None:
    """Duplicate detection must work against the current flat-dict format."""
    idem_file = tmp_path / "idem_keys.json"
    # Current real format: keys are top-level entries, values are timestamps
    payload = {
        "version": 5,
        "escrow_create_674_t1_gauntlet": "2026-04-20T12:25:20Z",
        "payment|10|agent@test": "2026-04-20T12:00:00Z",
        "keys": {
            "some_sha256_hash_key_abc123": "2026-04-19T00:00:00Z",
        },
    }
    idem_file.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    # A top-level flat key should be detected as a duplicate
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--ledger", str(idem_file), "escrow_create_674_t1_gauntlet"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1, f"Expected duplicate detection; got: {result.stdout}"
    assert "FAIL" in result.stdout

    # A plain key inside the nested "keys" sub-dict should also be detected
    result2 = subprocess.run(
        [sys.executable, str(SCRIPT), "--ledger", str(idem_file), "some_sha256_hash_key_abc123"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result2.returncode == 1, f"Expected nested-key duplicate detection; got: {result2.stdout}"
    assert "FAIL" in result2.stdout

    # A truly new key must still pass
    result3 = subprocess.run(
        [sys.executable, str(SCRIPT), "--ledger", str(idem_file), "brand_new_key_xyz"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result3.returncode == 0, f"Expected new key to pass; got: {result3.stdout}"
    assert "OK" in result3.stdout


def test_new_key_passes(tmp_path: Path) -> None:
    idem_file = tmp_path / "idem_keys.json"
    _write_idem_file(idem_file, ["payment|10|agent@test"])

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--ledger", str(idem_file), "payment|11|agent@test"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "OK" in result.stdout
