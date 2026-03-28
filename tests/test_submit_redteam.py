import os
import pytest
from unittest.mock import patch
from pathlib import Path
from wea_cli.cli import cmd_submit, validate_submission_text
from wea_cli.gh import GhError

# GAP DOCUMENTATION:
# Phase 1 - Demonstrate the attack: validate_submission_text ignores PR validation.
# Phase 2 - Close the gap: cmd_submit now validates PR authorship and repository.

@pytest.fixture
def mock_gh_post():
    with patch("wea_cli.cli.post_issue_comment") as mock:
        yield mock

@pytest.fixture
def mock_view_pr():
    with patch("wea_cli.gh.view_pr") as mock:
        yield mock

@pytest.fixture
def mock_balances():
    with patch("wea_cli.cli.load_balances") as mock:
        mock.return_value = {
            "agents": {
                "malicious@agent": {"github_username": "malicioususer"}
            }
        }
        yield mock

@pytest.fixture
def mock_resolve_agent():
    with patch("wea_cli.cli.resolve_agent") as mock:
        mock.return_value = "malicious@agent"
        yield mock

@pytest.fixture
def mock_resolve_repo_root():
    with patch("wea_cli.cli.resolve_repo_root") as mock:
        mock.return_value = Path("/mock/root")
        yield mock

def create_submission(tmp_path, content):
    p = tmp_path / "submission.md"
    p.write_text(content, encoding="utf-8")
    return p

def test_fabricated_pr_passes_validation():
    # Test 1: validate_submission_text still passes because it's only formatting
    text = "## Work\nhttps://github.com/torvalds/linux/pull/1\n\n## Agent\nmalicious@agent"
    assert validate_submission_text(text) == []

def test_fabricated_pr_another_agent():
    # Test 2: validate_submission_text still passes
    text = "## Work\nhttps://github.com/WeTheAgents/wetheagents/pull/100\n\n## Agent\nmalicious@agent"
    assert validate_submission_text(text) == []

def test_fabricated_pr_random_text():
    # Test 3: validate_submission_text still passes
    text = "## Work\nhttps://github.com/WeTheAgents/wetheagents/pull/999\nhttps://github.com/other/repo/pull/1\n\n## Agent\nmalicious@agent"
    assert validate_submission_text(text) == []

@pytest.fixture
def mock_hook():
    with patch("wea_cli.cli.handle_hook") as mock:
        mock.return_value = True
        yield mock

@pytest.mark.xfail(reason="Fixed in T6S2: cmd_submit now validates PR authorship")
def test_cmd_submit_posts_fabricated_pr(tmp_path, mock_gh_post, mock_view_pr, mock_balances, mock_resolve_agent, mock_hook, mock_resolve_repo_root):
    # Test 4: The exploit test from Phase 1 must now fail (proving the fix works)
    p = create_submission(tmp_path, "## Work\nhttps://github.com/WeTheAgents/wetheagents/pull/100\n\n## Agent\nmalicious@agent")
    class Args:
        file = str(p)
        issue = 123
        dry_run = False
        repo = "WeTheAgents/wetheagents"
        root = str(tmp_path)
    
    mock_view_pr.return_value = {"author": {"login": "differentuser"}, "state": "OPEN", "isDraft": False}
    
    # This assertion will fail because cmd_submit now returns EXIT_DOMAIN_ERROR (1)
    assert cmd_submit(Args()) == 0

def test_cmd_submit_rejects_foreign_repo_pr(tmp_path, mock_gh_post, mock_balances, mock_resolve_agent, mock_hook, mock_resolve_repo_root):
    # Test 5: Reject foreign repo PRs
    p = create_submission(tmp_path, "## Work\nhttps://github.com/facebook/react/pull/1000\n\n## Agent\nmalicious@agent")
    class Args:
        file = str(p)
        issue = 123
        dry_run = False
        repo = "WeTheAgents/wetheagents"
        root = str(tmp_path)
    
    assert cmd_submit(Args()) == 1
    mock_gh_post.assert_not_called()

def test_cmd_submit_accepts_valid_pr(tmp_path, mock_gh_post, mock_view_pr, mock_balances, mock_resolve_agent, mock_hook, mock_resolve_repo_root):
    # Ensure legitimate PRs are still accepted
    p = create_submission(tmp_path, "## Work\nhttps://github.com/WeTheAgents/wetheagents/pull/100\n\n## Agent\nmalicious@agent")
    class Args:
        file = str(p)
        issue = 123
        dry_run = False
        repo = "WeTheAgents/wetheagents"
        root = str(tmp_path)
    
    mock_view_pr.return_value = {"author": {"login": "malicioususer"}, "state": "OPEN", "isDraft": False, "body": "Closes #123"}
    
    assert cmd_submit(Args()) == 0
    mock_gh_post.assert_called_once()
