import pytest
import subprocess
from unittest.mock import patch
import sys
from scripts.audit_branch_entropy import (
    get_merged_agent_branches,
    get_open_issues,
    parse_issue_number,
    main
)

def test_get_merged_agent_branches(monkeypatch):
    def mock_check_output(cmd, **kwargs):
        if cmd == ['git', 'branch', '-r', '--merged', 'origin/main']:
            return "  origin/HEAD -> origin/main\n  origin/main\n  origin/agent/bot/123-fix\n  origin/agent/other/456-feat\n  origin/feature/abc\n"
        raise subprocess.CalledProcessError(1, cmd)
        
    monkeypatch.setattr(subprocess, 'check_output', mock_check_output)
    
    branches = get_merged_agent_branches()
    assert branches == ['origin/agent/bot/123-fix', 'origin/agent/other/456-feat']

def test_get_open_issues(monkeypatch):
    def mock_check_output(cmd, **kwargs):
        if cmd == ['gh', 'issue', 'list', '--state', 'open', '--json', 'number']:
            return '[{"number": 123}, {"number": 456}]'
        raise subprocess.CalledProcessError(1, cmd)
        
    monkeypatch.setattr(subprocess, 'check_output', mock_check_output)
    
    issues = get_open_issues()
    assert issues == {'123', '456'}

def test_parse_issue_number():
    assert parse_issue_number('origin/agent/gemini-4/351-branch-entropy') == '351'
    assert parse_issue_number('origin/agent/bot/1-a') == '1'
    assert parse_issue_number('origin/agent/bot/no-issue') is None
    assert parse_issue_number('origin/main') is None

def test_main_no_candidates(monkeypatch):
    monkeypatch.setattr('scripts.audit_branch_entropy.get_merged_agent_branches', lambda: ['origin/agent/bot/123-fix'])
    monkeypatch.setattr('scripts.audit_branch_entropy.get_open_issues', lambda: {'123'})
    
    monkeypatch.setattr('sys.argv', ['audit_branch_entropy.py'])
    
    with pytest.raises(SystemExit) as excinfo:
        main()
    assert excinfo.value.code == 0

def test_main_candidates_found(monkeypatch):
    monkeypatch.setattr('scripts.audit_branch_entropy.get_merged_agent_branches', lambda: ['origin/agent/bot/123-fix', 'origin/agent/bot/999-stale'])
    monkeypatch.setattr('scripts.audit_branch_entropy.get_open_issues', lambda: {'123'})
    
    monkeypatch.setattr('sys.argv', ['audit_branch_entropy.py'])
    
    with pytest.raises(SystemExit) as excinfo:
        main()
    assert excinfo.value.code == 2

@patch('subprocess.check_call')
def test_main_delete_force(mock_check_call, monkeypatch):
    monkeypatch.setattr('scripts.audit_branch_entropy.get_merged_agent_branches', lambda: ['origin/agent/bot/999-stale'])
    monkeypatch.setattr('scripts.audit_branch_entropy.get_open_issues', lambda: set())
    
    monkeypatch.setattr('sys.argv', ['audit_branch_entropy.py', '--delete', '--force'])
    
    with pytest.raises(SystemExit) as excinfo:
        main()
    
    assert excinfo.value.code == 2
    mock_check_call.assert_called_once_with(['git', 'push', 'origin', '--delete', 'agent/bot/999-stale', '--force'])
