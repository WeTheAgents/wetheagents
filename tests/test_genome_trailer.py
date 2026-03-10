"""Tests for genome drift guard (check_genome_trailer.py)."""

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Import the module under test
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import check_genome_trailer as cgt  # noqa: E402


@pytest.fixture
def msg_file(tmp_path):
    """Create a temp commit message file."""

    def _make(content: str) -> str:
        p = tmp_path / "COMMIT_EDITMSG"
        p.write_text(content, encoding="utf-8")
        return str(p)

    return _make


def _mock_staged(agent_genomes=None, templates=None):
    """Patch _get_staged_genome_files to return specified files."""
    return patch.object(
        cgt,
        "_get_staged_genome_files",
        return_value=(agent_genomes or [], templates or []),
    )


def _mock_agent0(is_agent0: bool):
    """Patch _is_agent0."""
    return patch.object(cgt, "_is_agent0", return_value=is_agent0)


class TestGenomeDriftGuard:
    """Genome drift guard blocks unauthorized genome commits."""

    def test_no_genome_files_passes(self, msg_file):
        """Commits without genome files always pass."""
        f = msg_file("some random commit")
        with _mock_staged(), _mock_agent0(False):
            sys.argv = ["check_genome_trailer.py", f]
            assert cgt.main() == 0

    def test_agent_genome_without_trailer_blocked(self, msg_file):
        """Agent genome change without Release-Session trailer is blocked."""
        f = msg_file("update genome\n\nSigned-off-by: someone")
        with _mock_staged(agent_genomes=["genomes/Codex-2@codex/AGENTS.local.md"]):
            with _mock_agent0(False):
                sys.argv = ["check_genome_trailer.py", f]
                assert cgt.main() == 1

    def test_agent_genome_with_trailer_passes(self, msg_file):
        """Agent genome change with valid Release-Session trailer passes."""
        f = msg_file("update genome\n\nRelease-Session: #150\n")
        with _mock_staged(agent_genomes=["genomes/Codex-2@codex/AGENTS.local.md"]):
            with _mock_agent0(False):
                sys.argv = ["check_genome_trailer.py", f]
                assert cgt.main() == 0

    def test_template_without_trailer_blocked(self, msg_file):
        """Base template change without Constitution-Amendment trailer is blocked."""
        f = msg_file("update constitution\n\nRelease-Session: #150\n")
        with _mock_staged(templates=["genomes/base/AGENTS.local.template.md"]):
            with _mock_agent0(False):
                sys.argv = ["check_genome_trailer.py", f]
                assert cgt.main() == 1

    def test_template_with_trailer_passes(self, msg_file):
        """Base template change with Constitution-Amendment trailer passes."""
        f = msg_file("update constitution\n\nConstitution-Amendment: #148\n")
        with _mock_staged(templates=["genomes/base/AGENTS.local.template.md"]):
            with _mock_agent0(False):
                sys.argv = ["check_genome_trailer.py", f]
                assert cgt.main() == 0

    def test_agent0_bypasses(self, msg_file):
        """Agent0 commits bypass all trailer checks."""
        f = msg_file("direct genome edit by agent0")
        with _mock_staged(
            agent_genomes=["genomes/Codex-2@codex/AGENTS.local.md"],
            templates=["genomes/base/AGENTS.local.template.md"],
        ):
            with _mock_agent0(True):
                sys.argv = ["check_genome_trailer.py", f]
                assert cgt.main() == 0

    def test_both_genome_and_template_need_both_trailers(self, msg_file):
        """Commit touching both genome + template needs both trailers."""
        # Only Release-Session → template blocked
        f = msg_file("both changes\n\nRelease-Session: #150\n")
        with _mock_staged(
            agent_genomes=["genomes/Codex-2@codex/AGENTS.local.md"],
            templates=["genomes/base/AGENTS.local.template.md"],
        ):
            with _mock_agent0(False):
                sys.argv = ["check_genome_trailer.py", f]
                assert cgt.main() == 1

        # Both trailers → passes
        f = msg_file(
            "both changes\n\nRelease-Session: #150\nConstitution-Amendment: #148\n"
        )
        with _mock_staged(
            agent_genomes=["genomes/Codex-2@codex/AGENTS.local.md"],
            templates=["genomes/base/AGENTS.local.template.md"],
        ):
            with _mock_agent0(False):
                sys.argv = ["check_genome_trailer.py", f]
                assert cgt.main() == 0


class TestTrailerRegex:
    """Trailer regex matches expected formats."""

    def test_release_session_formats(self):
        assert cgt.RELEASE_TRAILER.search("Release-Session: #123")
        assert cgt.RELEASE_TRAILER.search("Release-Session: #1")
        assert cgt.RELEASE_TRAILER.search("some text\n\nRelease-Session: #99\n")
        assert not cgt.RELEASE_TRAILER.search("Release-Session: 123")  # missing #
        assert not cgt.RELEASE_TRAILER.search("release-session: #123")  # wrong case

    def test_amendment_formats(self):
        assert cgt.AMENDMENT_TRAILER.search("Constitution-Amendment: #148")
        assert cgt.AMENDMENT_TRAILER.search("text\n\nConstitution-Amendment: #1\n")
        assert not cgt.AMENDMENT_TRAILER.search("Constitution-Amendment: 148")


class TestAgent0Detection:
    """Agent0 identity detection from env and git config."""

    def test_wea_agent_env(self):
        with patch.dict(os.environ, {"WEA_AGENT": "agent0@system"}):
            assert cgt._is_agent0() is True

    def test_non_agent0_env(self):
        with patch.dict(os.environ, {"WEA_AGENT": "Codex-2@codex"}, clear=False):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = subprocess.CompletedProcess(
                    args=[], returncode=0, stdout="codex-2@codex\n"
                )
                assert cgt._is_agent0() is False
