"""Tests for check_pr_scope — protected path enforcement."""

from scripts.check_pr_scope import check_scope


class TestAllowedPaths:
    def test_sandbox_docs_src_pass(self):
        assert check_scope(["sandbox/hello.py", "docs/guide.md", "src/main.py"]) == []

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
        files = ["sandbox/ok.py", "ledger/balances.json", "docs/readme.md", "AGENT0.md"]
        violations = check_scope(files)
        assert sorted(violations) == ["AGENT0.md", "ledger/balances.json"]

    def test_case_sensitive(self):
        """Uppercase LEDGER/ should NOT match lowercase ledger/ prefix."""
        assert check_scope(["LEDGER/balances.json"]) == []
