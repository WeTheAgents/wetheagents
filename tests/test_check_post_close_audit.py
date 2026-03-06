from __future__ import annotations

from scripts.check_post_close_audit import run_audit


def test_run_audit_clean_case() -> None:
    issues = [
        {
            "number": 79,
            "title": "Clean close",
            "labels": [{"name": "task"}, {"name": "paid"}],
        }
    ]

    violations = run_audit(
        days=7,
        repo="WeTheAgents/wetheagents",
        issue_fetcher=lambda days, repo: issues,
        issue_timeline_fetcher=lambda issue, repo: [
            {"source": {"issue": {"number": 123, "pull_request": {"url": "https://example/pr/123"}}}}
        ],
        pr_fetcher=lambda pr, repo: {
            "number": pr,
            "mergedAt": "2026-03-06T10:00:00Z",
            "baseRefName": "main",
        },
        follow_up_fetcher=lambda issue, repo: [],
    )

    assert violations == []


def test_run_audit_reports_multiple_violations() -> None:
    issues = [
        {
            "number": 80,
            "title": "Broken close",
            "labels": [{"name": "task"}],
        }
    ]

    violations = run_audit(
        days=7,
        repo="WeTheAgents/wetheagents",
        issue_fetcher=lambda days, repo: issues,
        issue_timeline_fetcher=lambda issue, repo: [
            {"source": {"issue": {"number": 124, "pull_request": {"url": "https://example/pr/124"}}}}
        ],
        pr_fetcher=lambda pr, repo: {
            "number": pr,
            "mergedAt": "",
            "baseRefName": "feature",
        },
        follow_up_fetcher=lambda issue, repo: [{"number": 999, "title": "Follow-up", "url": "https://example/999"}],
    )

    kinds = {violation.violation_type for violation in violations}
    assert "missing-paid-label" in kinds
    assert "linked-pr-not-merged" in kinds
    assert "open-follow-up" in kinds
