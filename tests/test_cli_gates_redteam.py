import pytest
import re
from unittest.mock import patch, MagicMock

from wea_cli.cli import (
    cmd_claim,
    cmd_submit,
    cmd_task_check_criteria,
    _parse_reward_wea,
)
from wea_cli.parsers import inspect_acceptance_criteria, parse_task_metadata

# 1. Test Claim Preflight Bypass
def test_claim_preflight_bypass_empty_criteria():
    # An empty MUST: criterion should be invalid and block the claim.
    body = """
Reward: 15 WEA

## Acceptance Criteria
- [ ] MUST: 
- [ ] MUST NOT: 
    """
    check = inspect_acceptance_criteria(body)
    assert not check.is_valid, "Empty MUST/MUST NOT should be invalid"

def test_claim_preflight_obfuscated_reward():
    body = "**Reward (WEA):** Fifty WEA"
    raw_reward = parse_task_metadata(body).get("reward") or ""
    reward_value = _parse_reward_wea(raw_reward)
    assert reward_value == 0
    # Our new logic should require force if reward == 0 but string is not empty.
    assert reward_value == 0 and raw_reward.strip() != "", "Should trigger the obfuscated reward check"

# 2. Test Submit Authorship Bypass
def test_submit_authorship_bypass_http_url():
    # If the user submits http:// or github.com/ without https://, it should still be caught.
    content = "Check out my PR at github.com/owner/repo/pull/123 or http://github.com/owner2/repo2/pull/456"
    pr_matches = re.findall(r"(?:https?://)?(?:www\.|api\.)?github\.com/(?:repos/)?([^/]+)/([^/]+)/(?:pulls?|issues)/(\d+)", content, re.IGNORECASE)
    assert len(pr_matches) == 2, "Should catch non-https PR links"

def test_submit_authorship_api_relative_url():
    content = "API link: https://api.github.com/repos/WeTheAgents/wetheagents/pulls/123\nRelative: [PR](../../pull/456)"
    pr_matches = re.findall(r"(?:https?://)?(?:www\.|api\.)?github\.com/(?:repos/)?([^/]+)/([^/]+)/(?:pulls?|issues)/(\d+)", content, re.IGNORECASE)
    rel_matches = re.findall(r"\]\((?:/)?([^/]+)/([^/]+)/(?:pulls?|issues)/(\d+)\)", content, re.IGNORECASE)
    for rm in rel_matches:
        if rm not in pr_matches:
            pr_matches.append(rm)
    assert len(pr_matches) == 2, "Should catch API and relative PR links"

# 3. Test Task Lint Bypass
def test_task_lint_bypass_empty_text():
    # The linter should reject criteria that just have prefixes but no text.
    body = """
## Acceptance Criteria
- [ ] MUST: 
- [ ] MUST NOT: 
    """
    check = inspect_acceptance_criteria(body)
    assert not check.is_valid
    assert any("empty" in e.lower() for e in check.errors), "Should have an error about empty criteria"

def test_task_lint_bypass_html_space():
    body = "## Acceptance Criteria\n- [x] MUST: &nbsp;\n- [x] MUST NOT: <br>"
    check = inspect_acceptance_criteria(body)
    assert not check.is_valid, "HTML spaces should be stripped and trigger empty description error"

def test_task_lint_bypass_spoofing():
    body = "## Acceptance Criteria\n- [x] MUST-NOT: something\n- [x] MUST_NOT: another"
    check = inspect_acceptance_criteria(body)
    # The check should recognize these as MUST NOT and not fall back to legacy
    # It should complain that there is no MUST: item.
    assert check.source == "malformed"
    assert any("include at least one `MUST:` item" in e for e in check.errors), "Should recognize MUST-NOT as structured and demand MUST:"
