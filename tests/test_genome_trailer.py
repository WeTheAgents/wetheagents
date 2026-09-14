"""Tests for genome drift guard (check_genome_trailer.py)."""

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from wea_cli.genome import CanonicalGenomeContext, GenesisTarget, _metadata

# Import the module under test
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import check_genome_trailer as cgt


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

    def test_valid_self_genesis_passes_without_release_session(self, msg_file):
        f = msg_file("initialize\n\nGenome-Genesis: New@agent\n")
        with _mock_staged(agent_genomes=["genomes/New@agent/AGENTS.local.md"]):
            with _mock_agent0(False), patch.object(
                cgt, "_is_valid_self_genesis", return_value=True
            ):
                sys.argv = ["check_genome_trailer.py", f]
                assert cgt.main() == 0

    def test_invalid_genesis_still_requires_release_session(self, msg_file):
        f = msg_file("initialize\n\nGenome-Genesis: Other@agent\n")
        with _mock_staged(agent_genomes=["genomes/New@agent/AGENTS.local.md"]):
            with _mock_agent0(False), patch.object(
                cgt, "_is_valid_self_genesis", return_value=False
            ):
                sys.argv = ["check_genome_trailer.py", f]
                assert cgt.main() == 1

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

    def test_genesis_format(self):
        assert cgt.GENESIS_TRAILER.search("Genome-Genesis: New@agent")
        assert not cgt.GENESIS_TRAILER.search("genome-genesis: New@agent")


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


def test_self_genesis_checks_identity_shape_template_and_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent_id = "New@agent"
    prefix = f"genomes/{agent_id}/"
    files = prefix + "AGENTS.local.md\n" + prefix + "genome_meta.json\n"
    target = GenesisTarget(
        agent_id,
        datetime.fromisoformat("2026-09-14T12:00:00+00:00"),
    )
    context = CanonicalGenomeContext(
        "canonical-commit", "# template\n", {agent_id: target}, True
    )
    meta = json.dumps(_metadata(target))

    def fake_git(*args: str) -> str:
        if args == ("rev-parse", "--show-toplevel"):
            return str(tmp_path)
        if args[:3] == ("diff", "--cached", "--name-only"):
            return files
        if args[:4] == ("diff", "--cached", "--diff-filter=A", "--name-only"):
            return files
        if args == ("show", f":{prefix}genome_meta.json"):
            return meta
        if args == ("show", f":{prefix}AGENTS.local.md"):
            return "# template\n"
        raise AssertionError(args)

    monkeypatch.setenv("WEA_AGENT", agent_id)
    monkeypatch.setattr(cgt, "_git", fake_git)
    monkeypatch.setattr(cgt, "_canonical_context", lambda root: context)
    monkeypatch.setattr(cgt, "_canonical_path_ever_existed", lambda *args: False)

    assert cgt._is_valid_self_genesis(f"Genome-Genesis: {agent_id}\n") is True

    spoofed = _metadata(target)
    fitness = spoofed["fitness"]
    assert isinstance(fitness, dict)
    fitness["total_earned"] = 99
    meta = json.dumps(spoofed)
    assert cgt._is_valid_self_genesis(f"Genome-Genesis: {agent_id}\n") is False

    monkeypatch.setattr(cgt, "_canonical_path_ever_existed", lambda *args: True)
    assert cgt._is_valid_self_genesis(f"Genome-Genesis: {agent_id}\n") is False
