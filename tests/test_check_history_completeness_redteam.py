"""
Red Team adversarial tests for history completeness.
These tests verify that `check_history_completeness.py` (or equivalent)
correctly detects bypass vectors where ledger state exists but history entries
are obfuscated, malformed, or hidden.

Issue #636
"""

import os
import json
import subprocess
import pytest
from pathlib import Path

def run_checker(ledger_dir: Path) -> subprocess.CompletedProcess:
    """Run the check_history_completeness.py script against a synthetic ledger."""
    checker_script = Path(__file__).parent.parent / "scripts" / "check_history_completeness.py"
    if not checker_script.exists():
        pytest.skip("Checker script not implemented yet (Issue #633)")
    
    # Run the script. To allow it to read our synthetic ledger instead of the real one,
    # we copy the script to a temporary directory along with the synthetic ledger,
    # so that BASE_DIR resolution naturally points to our temp directory.
    # We do this because WeTheAgents scripts typically hardcode LEDGER_DIR = BASE_DIR / "ledger".
    
    script_content = checker_script.read_text(encoding="utf-8")
    temp_script_dir = ledger_dir.parent / "scripts"
    temp_script_dir.mkdir(exist_ok=True)
    temp_script = temp_script_dir / "check_history_completeness.py"
    temp_script.write_text(script_content, encoding="utf-8")
    
    return subprocess.run(
        ["python", str(temp_script)],
        capture_output=True,
        text=True
    )

def setup_synthetic_ledger(tmp_path: Path, balances: dict, escrows: dict, history_lines: list, history_filename: str = "2026-03-01.jsonl", idem_keys: dict | None = None):
    """Set up a synthetic ledger directory structure."""
    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()
    history_dir = ledger_dir / "history"
    history_dir.mkdir()

    (ledger_dir / "balances.json").write_text(json.dumps(balances))
    (ledger_dir / "escrows.json").write_text(json.dumps({"active": escrows, "version": 1}))
    (ledger_dir / "trajectory_mints.json").write_text(json.dumps({"mints": [], "trajectories": {}, "total_minted": 0}))
    (ledger_dir / "idem_keys.json").write_text(json.dumps(idem_keys or {}))

    if history_lines:
        hist_file = history_dir / history_filename
        with open(hist_file, "w", encoding="utf-8") as f:
            for line in history_lines:
                f.write(line + "\n")

    return ledger_dir

def test_bypass_multiline_json(tmp_path: Path):
    """
    Bypass Vector 1: Multi-line JSON.
    The naive reconciliation script skips lines with JSONDecodeError.
    If an adversary writes a valid JSON entry over multiple lines,
    it might be silently ignored by the checker while manual inspection
    might see it as valid. The completeness checker MUST catch that the ledger
    has a change without a valid single-line history entry.
    """
    balances = {
        "agents": {
            "Agent1@test": {
                "total_earned": 100,
                "total_spent": 0
            }
        }
    }
    # Multiline JSON string, which fails naive line-by-line json.loads
    bad_history = '{\n"type": "payment",\n"agent": "Agent1@test",\n"amount": 100\n}'
    
    ledger_dir = setup_synthetic_ledger(
        tmp_path,
        balances=balances,
        escrows={},
        history_lines=[bad_history],
        idem_keys={"accept|1|Agent1@test": "2026-01-01T00:00:00Z"},
    )

    result = run_checker(ledger_dir)
    assert result.returncode != 0, "Checker failed to detect multi-line JSON bypass"

def test_bypass_wrong_file_extension(tmp_path: Path):
    """
    Bypass Vector 2: Wrong file extension.
    An adversary writes a completely valid history entry but puts it in a file
    named `2026-03-01.json` instead of `.jsonl`.
    The checker must notice the ledger has state that is completely unaccounted for
    in the valid `.jsonl` files.
    """
    balances = {
        "agents": {
            "Agent1@test": {
                "total_earned": 100,
                "total_spent": 0
            }
        }
    }
    valid_history = '{"type": "payment", "agent": "Agent1@test", "amount": 100}'
    
    ledger_dir = setup_synthetic_ledger(
        tmp_path,
        balances=balances,
        escrows={},
        history_lines=[valid_history],
        history_filename="2026-03-01.json",  # wrong extension!
        idem_keys={"accept|1|Agent1@test": "2026-01-01T00:00:00Z"},
    )

    result = run_checker(ledger_dir)
    assert result.returncode != 0, "Checker failed to detect wrong file extension bypass"

def test_bypass_case_sensitivity(tmp_path: Path):
    """
    Bypass Vector 3: Case sensitivity and trailing spaces in type.
    Adversary writes `Payment ` or `PAYMENT` to evade exact string matching in checker.
    The checker must enforce exact matches or fail.
    """
    balances = {
        "agents": {
            "Agent1@test": {
                "total_earned": 100,
                "total_spent": 0
            }
        }
    }
    # Trailing space in type
    tricky_history = '{"type": "payment ", "agent": "Agent1@test", "amount": 100}'
    
    ledger_dir = setup_synthetic_ledger(
        tmp_path,
        balances=balances,
        escrows={},
        history_lines=[tricky_history],
        idem_keys={"accept|1|Agent1@test": "2026-01-01T00:00:00Z"},
    )

    result = run_checker(ledger_dir)
    assert result.returncode != 0, "Checker failed to detect case/space bypass"

def test_bypass_shared_history_entry(tmp_path: Path):
    """
    Bypass Vector 4: Array/Batch wrapper.
    Adversary wraps multiple operations in a single history entry.
    If the checker strictly expects 1:1 mapping, it should fail.
    """
    balances = {
        "agents": {
            "Agent1@test": {
                "total_earned": 100,
                "total_spent": 0
            },
            "Agent2@test": {
                "total_earned": 100,
                "total_spent": 0
            }
        }
    }
    # Wrapping in a list inside a single line
    batch_history = '{"type": "batch", "events": [{"type": "payment", "agent": "Agent1@test", "amount": 100}, {"type": "payment", "agent": "Agent2@test", "amount": 100}]}'
    
    ledger_dir = setup_synthetic_ledger(
        tmp_path,
        balances=balances,
        escrows={},
        history_lines=[batch_history],
        idem_keys={
            "accept|1|Agent1@test": "2026-01-01T00:00:00Z",
            "accept|2|Agent2@test": "2026-01-01T00:00:00Z",
        },
    )

    result = run_checker(ledger_dir)
    assert result.returncode != 0, "Checker failed to detect batch entry bypass"

def test_bypass_partial_escrow_write(tmp_path: Path):
    """
    Bypass Vector 5: Partial writes.
    Escrow created in ledger but no matching history entry.
    """
    escrows = {
        "escrow_1": {
            "amount": 50,
            "agent": "Agent1@test",
            "status": "pending"
        }
    }
    # History has NO entry for this escrow
    ledger_dir = setup_synthetic_ledger(
        tmp_path,
        balances={},
        escrows=escrows,
        history_lines=[],
        idem_keys={"escrow_create_1_standard": "2026-01-01T00:00:00Z"},
    )

    result = run_checker(ledger_dir)
    assert result.returncode != 0, "Checker failed to detect missing escrow history entry"

def test_bypass_future_timestamp(tmp_path: Path):
    """
    Bypass Vector 6: Timestamp/Date evasion.
    Adversary writes a valid entry but puts it in a file outside the expected
    date ranges (e.g. year 2099) so chronological checkers might ignore it,
    or it might break strict chronological ordering checks.
    """
    balances = {
        "agents": {
            "Agent1@test": {
                "total_earned": 100,
                "total_spent": 0
            }
        }
    }
    valid_history = '{"type": "payment", "agent": "Agent1@test", "amount": 100}'
    
    ledger_dir = setup_synthetic_ledger(
        tmp_path,
        balances=balances,
        escrows={},
        history_lines=[valid_history],
        history_filename="2099-01-01.jsonl",  # Future date
        idem_keys={"accept|1|Agent1@test": "2026-01-01T00:00:00Z"},
    )

    result = run_checker(ledger_dir)
    # The checker should either fail because it refuses future dates,
    # or if it accepts it, another check must ensure strict chronological ordering.
    # Completeness must map to validly-timed history files.
    assert result.returncode != 0, "Checker failed to flag abnormal timestamp bypass"
