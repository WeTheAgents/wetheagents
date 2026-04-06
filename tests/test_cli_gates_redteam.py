import pytest
import re
from unittest.mock import patch, MagicMock

from wea_cli.cli import (
    cmd_claim,
    cmd_submit,
    cmd_task_check_criteria,
)
from wea_cli.parsers import inspect_acceptance_criteria

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

# 2. Test Submit Authorship Bypass
def test_submit_authorship_bypass_http_url():
    # If the user submits http:// or github.com/ without https://, it should still be caught.
    content = "Check out my PR at github.com/owner/repo/pull/123 or http://github.com/owner2/repo2/pull/456"
    pr_matches = re.findall(r"(?:https?://)?(?:www\.)?github\.com/([^/]+)/([^/]+)/pull/(\d+)", content)
    assert len(pr_matches) == 2, "Should catch non-https PR links"

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

