"""Tests for scripts/unified_ledger_health_report.py."""

from __future__ import annotations

import json
from pathlib import Path

from scripts import unified_ledger_health_report as report_mod


def _result(script: str, status: str, first_line: str = "ok") -> dict:
    return {
        "script": script,
        "exit_code": {"pass": 0, "skip": 2, "fail": 1}[status],
        "status": status,
        "passed": status == "pass",
        "skipped": status == "skip",
        "first_line": first_line,
        "stdout": first_line,
        "stderr": "",
    }


def test_load_description_reads_first_docstring_line(monkeypatch) -> None:
    script = Path("check_example.py")
    monkeypatch.setattr(
        Path,
        "read_text",
        lambda self, encoding="utf-8": '"""Example check.\n\nMore detail here.\n"""\nprint("hello")\n',
    )

    assert report_mod.load_description(script) == "Example check"


def test_build_report_marks_critical_when_core_check_fails() -> None:
    results = [
        _result("check_invariant.py", "fail", "FAIL: invariant broken"),
        _result("check_claim_ttl.py", "pass"),
    ]
    report = report_mod.build_report(results, {
        "check_invariant.py": "Economy invariant checker",
        "check_claim_ttl.py": "Claim freshness check",
    })

    assert report["overall_status"] == "CRITICAL"
    assert report["failed"] == 1
    assert report["domains"][0]["name"] == "Economy"
    assert "check_invariant.py" in report["domains"][0]["failed"]


def test_build_report_marks_partial_when_only_skips_exist() -> None:
    results = [
        _result("check_pr_scope.py", "skip", "usage: provide --files"),
        _result("check_claim_ttl.py", "pass"),
    ]

    report = report_mod.build_report(results, {})

    assert report["overall_status"] == "PARTIAL"
    assert report["failed"] == 0
    assert report["skipped"] == 1


def test_build_report_marks_github_failures_as_blocked() -> None:
    results = [
        _result("check_issue_ledger_sync.py", "fail", "Error fetching GitHub issues"),
        _result("check_claim_ttl.py", "pass"),
    ]

    report = report_mod.build_report(results, {})

    assert report["overall_status"] == "PARTIAL"
    assert report["failed"] == 0
    assert report["blocked"] == 1
    assert report["blocked_checks"][0]["script"] == "check_issue_ledger_sync.py"


def test_render_report_includes_domain_dashboard_and_failures() -> None:
    report = report_mod.build_report(
        [
            _result("check_cross_file_integrity.py", "fail", "FAIL: orphaned escrow"),
            _result("check_claim_ttl.py", "pass"),
            _result("check_pr_scope.py", "skip", "usage: provide --files"),
        ],
        {
            "check_cross_file_integrity.py": "Cross-file integrity checks beyond the core supply invariant",
            "check_claim_ttl.py": "Claim freshness check",
            "check_pr_scope.py": "PR scope validation",
        },
    )

    rendered = report_mod.render_report(report)

    assert "Overall safety status: CRITICAL" in rendered
    assert "Domain dashboard:" in rendered
    assert "check_cross_file_integrity.py" in rendered
    assert "Environment-blocked checks:" in rendered
    assert "Context-only checks skipped:" in rendered


def test_main_json_output_uses_discovered_checks(monkeypatch, capsys) -> None:
    scripts_dir = Path("fake_scripts")
    check_a = scripts_dir / "check_a.py"
    check_b = scripts_dir / "check_b.py"

    monkeypatch.setattr(report_mod, "discover_checks", lambda _path: [check_a, check_b])
    monkeypatch.setattr(report_mod, "load_description", lambda script: f"{script.stem} description")
    monkeypatch.setattr(
        report_mod,
        "run_check",
        lambda script: _result(script.name, "pass", f"{script.name} ok"),
    )

    rc = report_mod.main(["--scripts-dir", str(scripts_dir), "--json"])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["overall_status"] == "HEALTHY"
    assert payload["passed"] == 2
    assert payload["blocked"] == 0
