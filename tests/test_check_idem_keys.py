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
