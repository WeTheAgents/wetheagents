import os
import sys
from unittest.mock import patch

import pytest

from scripts.ledger_health_report import build_report, main

@pytest.fixture
def temp_workspace(tmp_path):
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()
    return tmp_path, scripts_dir, ledger_dir

def create_script(scripts_dir, name, content):
    script_path = scripts_dir / name
    script_path.write_text(content, encoding="utf-8")
    return script_path

def test_trusts_exit_code_over_output(temp_workspace):
    """
    Vector: A check script outputs {"status": "fail"} but incorrectly exits with 0. 
    Blind spot: Reporter trusts the exit code and marks as PASS, ignoring the JSON error.
    """
    _, scripts_dir, _ = temp_workspace
    create_script(scripts_dir, "check_false_pass.py", 'import sys\nprint(\'{"status": "fail"}\')\nsys.exit(0)')
    
    report, all_passed = build_report(scripts_dir)
    assert all_passed is True
    assert report["overall"] == "PASS"
    assert report["checks"][0]["status"] == "PASS"

def test_exit_2_hides_failure(temp_workspace):
    """
    Vector: A malicious check script deliberately exits 2 (SKIP) to hide a failure.
    Blind spot: If another check passes, the overall status is PASS, silently ignoring the malicious script.
    """
    _, scripts_dir, _ = temp_workspace
    create_script(scripts_dir, "check_good.py", 'import sys\nsys.exit(0)')
    create_script(scripts_dir, "check_malicious_skip.py", 'import sys\nprint("I am failing")\nsys.exit(2)')
    
    report, all_passed = build_report(scripts_dir)
    assert all_passed is True
    assert report["overall"] == "PASS"
    statuses = {c["name"]: c["status"] for c in report["checks"]}
    assert statuses["check_malicious_skip.py"] == "SKIP"

def test_ignores_subdirectories(temp_workspace):
    """
    Vector: A check script is placed in a subdirectory (e.g. scripts/domain/check_foo.py).
    Blind spot: The reporter glob only searches the top level of scripts/, so it silently
    ignores checks in subdirectories.
    """
    _, scripts_dir, _ = temp_workspace
    sub_dir = scripts_dir / "domain"
    sub_dir.mkdir()
    create_script(sub_dir, "check_hidden.py", 'import sys\nsys.exit(1)')
    create_script(scripts_dir, "check_ok.py", 'import sys\nsys.exit(0)')
    
    report, all_passed = build_report(scripts_dir)
    assert all_passed is True
    assert report["overall"] == "PASS"
    assert len(report["checks"]) == 1
    assert report["checks"][0]["name"] == "check_ok.py"

def test_massive_output_memory_exhaustion(temp_workspace):
    """
    Vector: A script prints an enormous amount of output.
    Blind spot: subprocess.run buffers everything in memory. We test that it captures the full
    output and doesn't truncate, which could lead to DoS/OOM on a real runner.
    """
    _, scripts_dir, _ = temp_workspace
    create_script(scripts_dir, "check_spam.py", 'import sys\nprint("SPAM\\n" * 1000)\nsys.exit(1)')
    
    report, all_passed = build_report(scripts_dir)
    assert all_passed is False
    assert len(report["checks"][0]["summary"]) > 0

def test_unhandled_exception_captured(temp_workspace):
    """
    Vector: A script raises an unhandled Python exception.
    Behavior: Reporter handles this correctly, marking as FAIL and capturing the traceback.
    """
    _, scripts_dir, _ = temp_workspace
    create_script(scripts_dir, "check_exception.py", 'raise ValueError("Boom")')
    
    report, all_passed = build_report(scripts_dir)
    assert all_passed is False
    assert report["checks"][0]["status"] == "FAIL"
    assert "Traceback" in report["checks"][0]["summary"]

def test_empty_output_handled(temp_workspace):
    """
    Vector: A script exits 1 with completely empty output.
    Behavior: Reporter handles this gracefully with "(no output)".
    """
    _, scripts_dir, _ = temp_workspace
    create_script(scripts_dir, "check_empty.py", 'import sys\nsys.exit(1)')
    
    report, all_passed = build_report(scripts_dir)
    assert all_passed is False
    assert report["checks"][0]["summary"] == "(no output)"

def test_timeout_handled(temp_workspace):
    """
    Vector: A script hangs indefinitely.
    Behavior: Reporter handles this via timeout and marks as FAIL.
    """
    _, scripts_dir, _ = temp_workspace
    create_script(scripts_dir, "check_hang.py", 'import time\ntime.sleep(10)')
    
    with patch("scripts.ledger_health_report._CHECK_TIMEOUT", 0.1):
        report, all_passed = build_report(scripts_dir)
        
    assert all_passed is False
    assert report["checks"][0]["status"] == "FAIL"
    assert "(timed out" in report["checks"][0]["summary"]

def test_empty_scripts_dir(temp_workspace):
    """
    Vector: The scripts directory contains no checks.
    Behavior: Reporter correctly marks overall status as FAIL (no vacuous PASS).
    """
    _, scripts_dir, _ = temp_workspace
    
    report, all_passed = build_report(scripts_dir)
    assert all_passed is False
    assert report["overall"] == "FAIL"
    assert "No check_*.py scripts found" in report["error"]

def test_read_only_output_dir(temp_workspace):
    """
    Vector: The ledger directory is read-only.
    Blind spot: Reporter crashes ungracefully with PermissionError instead of clean error.
    """
    tmp_path, scripts_dir, _ = temp_workspace
    create_script(scripts_dir, "check_ok.py", 'import sys\nsys.exit(0)')
    
    with patch("pathlib.Path.write_text", side_effect=PermissionError("Permission denied")):
        with pytest.raises(PermissionError):
            main(["--root", str(tmp_path)])
