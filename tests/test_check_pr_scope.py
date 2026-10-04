"""Tests for check_pr_scope — protected path enforcement."""

import os

import pytest

from scripts.check_pr_scope import check_scope, has_bypass_label


class TestAllowedPaths:
    def test_docs_src_pass(self):
        assert check_scope(["docs/guide.md", "src/main.py"]) == []

    def test_empty_list(self):
        assert check_scope([]) == []

    def test_readme_allowed(self):
        assert check_scope(["README.md"]) == []


class TestProtectedPrefixes:
    def test_ledger_blocked(self):
        assert check_scope(["ledger/balances.json"]) == ["ledger/balances.json"]

    def test_scripts_blocked(self):
        assert check_scope(["scripts/tide.py"]) == ["scripts/tide.py"]

    def test_github_blocked(self):
        assert check_scope([".github/workflows/tide.yml"]) == [".github/workflows/tide.yml"]

    def test_agent0_dir_blocked(self):
        assert check_scope(["agent0/operations.md"]) == ["agent0/operations.md"]

    def test_nested_protected_path(self):
        assert check_scope(["ledger/history/2026-03-01.jsonl"]) == ["ledger/history/2026-03-01.jsonl"]


class TestProtectedFiles:
    def test_agent0_md(self):
        assert check_scope(["AGENT0.md"]) == ["AGENT0.md"]

    def test_claude_md(self):
        assert check_scope(["CLAUDE.md"]) == ["CLAUDE.md"]

    def test_contributing_md(self):
        assert check_scope(["CONTRIBUTING.md"]) == ["CONTRIBUTING.md"]

    def test_claude_local_md(self):
        assert check_scope(["CLAUDE.local.md"]) == ["CLAUDE.local.md"]


class TestMixedPaths:
    def test_mixed_allowed_and_blocked(self):
        files = ["contrib/scripts/ok.py", "ledger/balances.json", "docs/readme.md", "AGENT0.md"]
        violations = check_scope(files)
        assert sorted(violations) == ["AGENT0.md", "ledger/balances.json"]

    def test_case_sensitive(self):
        """Uppercase LEDGER/ should NOT match lowercase ledger/ prefix."""
        assert check_scope(["LEDGER/balances.json"]) == []


class TestContribPath:
    def test_contrib_scripts_allowed(self):
        """contrib/scripts/ is never blocked."""
        assert check_scope(["contrib/scripts/my_tool.py"]) == []

    def test_contrib_readme_allowed(self):
        assert check_scope(["contrib/README.md"]) == []

    def test_contrib_nested_allowed(self):
        assert check_scope(["contrib/scripts/reports/economy.py"]) == []


class TestBypassLabel:
    @pytest.fixture(autouse=True)
    def _clean_env(self):
        old = os.environ.pop("PR_LABELS", None)
        yield
        if old is not None:
            os.environ["PR_LABELS"] = old
        else:
            os.environ.pop("PR_LABELS", None)

    def test_no_env_no_bypass(self):
        assert has_bypass_label() is False

    def test_empty_env_no_bypass(self):
        os.environ["PR_LABELS"] = ""
        assert has_bypass_label() is False

    def test_infra_label_present(self):
        os.environ["PR_LABELS"] = "task,infra,open"
        assert has_bypass_label() is True

    def test_infra_label_absent(self):
        os.environ["PR_LABELS"] = "task,open"
        assert has_bypass_label() is False

    def test_infra_only(self):
        os.environ["PR_LABELS"] = "infra"
        assert has_bypass_label() is True

    def test_whitespace_handling(self):
        os.environ["PR_LABELS"] = "  infra  ,  task  "
        assert has_bypass_label() is True


@pytest.mark.parametrize("path", ["agent0/operations.md", "gunnery/agent0/operations.md", "gunnery/agent0/ROLE.md"])
def test_agent0_protection_survives_relocation(path):
    assert check_scope([path]) == [path]
