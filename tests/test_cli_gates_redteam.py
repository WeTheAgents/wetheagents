import pytest
import argparse
from wea_cli.cli import cmd_claim, cmd_submit, cmd_task_check_criteria, EXIT_DOMAIN_ERROR, EXIT_RUNTIME_ERROR, EXIT_OK
from wea_cli.gh import GhError

@pytest.fixture
def mock_root(tmp_path):
    ledger = tmp_path / "ledger"
    ledger.mkdir()
    (ledger / "balances.json").write_text('{"agents": {"test_agent": {"github_username": "tester"}}}')
    return tmp_path

def test_gate1_claim_force_blocked(monkeypatch, mock_root, capsys):
    # Test that --force is blocked for high reward tasks
    monkeypatch.setattr("wea_cli.cli._load_acceptance_criteria_check", lambda i, r: ({"body": "### Reward (WEA)\n\n10"}, type("Check", (), {"is_valid": False, "criteria": [], "errors": ["invalid"], "source": "test", "machine_criteria": [], "human_criteria": []}), None))
    monkeypatch.setattr("wea_cli.cli.resolve_repo_root", lambda r: mock_root)
    monkeypatch.setattr("wea_cli.cli.resolve_agent", lambda a: "test_agent")
    
    args = argparse.Namespace(issue=1, repo="test/repo", plain=False, agent="test_agent", force=True, dry_run=True)
    
    exit_code = cmd_claim(args)
    captured = capsys.readouterr().out
    
    assert exit_code == EXIT_DOMAIN_ERROR
    assert "strictly require valid acceptance criteria" in captured
    assert "force is not allowed" in captured

def test_gate2_submit_gherror_bypass_fixed(monkeypatch, mock_root, capsys):
    # Test that if a PR link throws GhError (e.g. an issue link), valid_prs_found is not wrongly incremented
    monkeypatch.setattr("wea_cli.cli.resolve_repo_root", lambda r: mock_root)
    monkeypatch.setattr("wea_cli.cli._load_acceptance_criteria_check", lambda i, r: ({"body": "task"}, type("Check", (), {"is_valid": True, "criteria": [], "errors": [], "source": "test", "machine_criteria": [], "human_criteria": []}), None))
    
    def mock_view_pr(pr_number, repo):
        raise GhError("Not a PR")
        
    monkeypatch.setattr("wea_cli.gh.view_pr", mock_view_pr)
    
    submission_path = mock_root / "sub.md"
    submission_path.write_text("## Work\n\nhttps://github.com/WeTheAgents/wetheagents/issues/123\n\n## Agent\n\ntest_agent@test")
    
    args = argparse.Namespace(file=str(submission_path), issue=1, repo="WeTheAgents/wetheagents", root=str(mock_root), agent="test_agent", dry_run=True)
    
    exit_code = cmd_submit(args)
    captured = capsys.readouterr().out
    
    assert exit_code == EXIT_DOMAIN_ERROR
    assert "none target the expected repository" in captured

def test_gate2_submit_author_none_crash_fixed(monkeypatch, mock_root, capsys):
    # Test that a PR without author login does not crash
    monkeypatch.setattr("wea_cli.cli.resolve_repo_root", lambda r: mock_root)
    monkeypatch.setattr("wea_cli.cli._load_acceptance_criteria_check", lambda i, r: ({"body": "task"}, type("Check", (), {"is_valid": True, "criteria": [], "errors": [], "source": "test", "machine_criteria": [], "human_criteria": []}), None))
    
    def mock_view_pr(pr_number, repo):
        return {"author": None, "state": "OPEN", "isDraft": False, "body": "#1"}
        
    monkeypatch.setattr("wea_cli.gh.view_pr", mock_view_pr)
    
    submission_path = mock_root / "sub.md"
    submission_path.write_text("## Work\n\nhttps://github.com/WeTheAgents/wetheagents/pull/123\n\n## Agent\n\ntest_agent@test")
    
    args = argparse.Namespace(file=str(submission_path), issue=1, repo="WeTheAgents/wetheagents", root=str(mock_root), agent="test_agent", dry_run=True)
    
    exit_code = cmd_submit(args)
    captured = capsys.readouterr().out
    
    assert exit_code == EXIT_DOMAIN_ERROR
    assert "authored by @" in captured

def test_gate3_lint_format_check(monkeypatch, mock_root, capsys):
    # Test that cmd_task_check_criteria runs format validation and fails if format check fails
    body = "### Verification Criteria\n- [x] MUST: foo" # missing blank line, fails format check
    monkeypatch.setattr("wea_cli.cli._load_acceptance_criteria_check", lambda i, r: ({"number": 1, "body": body}, type("Check", (), {"is_valid": True, "criteria": [], "errors": [], "source": "test", "machine_criteria": [], "human_criteria": []}), None))
    monkeypatch.setattr("wea_cli.cli.resolve_repo_root", lambda r: mock_root)
    
    args = argparse.Namespace(issue=1, repo="test/repo", root=str(mock_root))
    
    # Needs scripts to be importable
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(".").resolve()))
    
    exit_code = cmd_task_check_criteria(args)
    captured = capsys.readouterr().out
    
    # check that we caught format validation failures
    assert exit_code == EXIT_DOMAIN_ERROR
    assert "Task format validation failed:" in captured
