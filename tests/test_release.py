"""Tests for the SGR release session system (wea release)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from wea_cli.release import (
    build_provenance,
    compute_proposal_hash,
    parse_release_comments,
    validate_proposal,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def repo_root(tmp_path: Path) -> Path:
    """Create a minimal repo with release schema files."""
    root = tmp_path / "repo"
    release_dir = root / "pipeline" / "release"
    release_dir.mkdir(parents=True)

    # Copy schemas from the real repo
    real_root = Path(__file__).resolve().parent.parent
    for name in ("proposal.schema.json", "decision.schema.json", "summary.schema.json"):
        src = real_root / "pipeline" / "release" / name
        dst = release_dir / name
        dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

    return root


def _make_proposal(
    *,
    severity: str = "memory",
    change_type: str = "add",
    pattern_count: int | None = None,
    current_content: str | None = None,
) -> dict:
    """Build a minimal valid proposal payload."""
    p: dict = {
        "station": "release",
        "agent_id": "Claude-1@claude",
        "issue": 151,
        "severity": severity,
        "experience": {
            "task_id": 151,
            "mechanic": "duel",
            "outcome": "lose",
            "agent_role": "spec_writer",
            "key_moment": "Expanded scope beyond acceptance criteria",
        },
        "reflection": {
            "what_worked": "Thorough analysis of requirements",
            "what_failed": "Added unrequested features",
            "root_cause": "Eagerness to impress > discipline",
        },
        "proposal": {
            "target_file": "genomes/Claude-1@claude/AGENTS.local.md",
            "target_section": "Instructions",
            "change_type": change_type,
            "proposed_content": "Ground before you design",
        },
    }
    if pattern_count is not None:
        p["reflection"]["pattern_count"] = pattern_count
    if current_content is not None:
        p["proposal"]["current_content"] = current_content
    return p


# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------

class TestProposalValidation:
    def test_valid_memory_proposal(self, repo_root: Path) -> None:
        payload = _make_proposal(severity="memory")
        validate_proposal(repo_root, payload)  # should not raise

    def test_valid_example_proposal(self, repo_root: Path) -> None:
        payload = _make_proposal(severity="example")
        validate_proposal(repo_root, payload)

    def test_valid_instruction_with_pattern_count(self, repo_root: Path) -> None:
        payload = _make_proposal(severity="instruction", pattern_count=3)
        validate_proposal(repo_root, payload)

    def test_instruction_requires_pattern_count_ge_3(self, repo_root: Path) -> None:
        payload = _make_proposal(severity="instruction", pattern_count=2)
        with pytest.raises(Exception):
            validate_proposal(repo_root, payload)

    def test_instruction_without_pattern_count_fails(self, repo_root: Path) -> None:
        payload = _make_proposal(severity="instruction")
        with pytest.raises(Exception):
            validate_proposal(repo_root, payload)

    def test_modify_requires_current_content(self, repo_root: Path) -> None:
        payload = _make_proposal(change_type="modify")
        with pytest.raises(ValueError, match="current_content"):
            validate_proposal(repo_root, payload)

    def test_modify_with_current_content_passes(self, repo_root: Path) -> None:
        payload = _make_proposal(
            change_type="modify",
            current_content="Old principle text",
        )
        validate_proposal(repo_root, payload)

    def test_remove_requires_current_content(self, repo_root: Path) -> None:
        payload = _make_proposal(change_type="remove")
        with pytest.raises(ValueError, match="current_content"):
            validate_proposal(repo_root, payload)

    def test_missing_experience_fails(self, repo_root: Path) -> None:
        payload = _make_proposal()
        del payload["experience"]
        with pytest.raises(Exception):
            validate_proposal(repo_root, payload)

    def test_missing_reflection_fails(self, repo_root: Path) -> None:
        payload = _make_proposal()
        del payload["reflection"]
        with pytest.raises(Exception):
            validate_proposal(repo_root, payload)

    def test_invalid_mechanic_fails(self, repo_root: Path) -> None:
        payload = _make_proposal()
        payload["experience"]["mechanic"] = "coinflip"
        with pytest.raises(Exception):
            validate_proposal(repo_root, payload)

    def test_invalid_severity_fails(self, repo_root: Path) -> None:
        payload = _make_proposal()
        payload["severity"] = "critical"
        with pytest.raises(Exception):
            validate_proposal(repo_root, payload)


# ---------------------------------------------------------------------------
# Proposal hashing
# ---------------------------------------------------------------------------

class TestProposalHash:
    def test_deterministic(self) -> None:
        p = _make_proposal()
        h1 = compute_proposal_hash(p)
        h2 = compute_proposal_hash(p)
        assert h1 == h2

    def test_16_hex_chars(self) -> None:
        p = _make_proposal()
        h = compute_proposal_hash(p)
        assert len(h) == 16
        assert all(c in "0123456789abcdef" for c in h)

    def test_different_payloads_different_hashes(self) -> None:
        p1 = _make_proposal(severity="memory")
        p2 = _make_proposal(severity="example")
        assert compute_proposal_hash(p1) != compute_proposal_hash(p2)

    def test_key_order_irrelevant(self) -> None:
        """Hash uses sorted keys, so insertion order doesn't matter."""
        p1 = {"b": 2, "a": 1}
        p2 = {"a": 1, "b": 2}
        assert compute_proposal_hash(p1) == compute_proposal_hash(p2)


# ---------------------------------------------------------------------------
# Comment parsing
# ---------------------------------------------------------------------------

class TestCommentParsing:
    def test_parse_proposal_comment(self) -> None:
        payload = _make_proposal()
        body = f"### SGR Proposal by Claude-1\n\n```json\n{json.dumps(payload)}\n```"
        comments = [{"body": body}]
        result = parse_release_comments(comments)
        assert len(result["proposals"]) == 1
        assert result["proposals"][0]["agent_id"] == "Claude-1@claude"

    def test_parse_decision_comment(self) -> None:
        dec = {
            "station": "release",
            "type": "decision",
            "issue": 151,
            "agent_id": "Claude-1@claude",
            "proposal_hash": "a1b2c3d4e5f67890",
            "verdict": "approved",
            "rationale": "Pattern confirmed.",
            "applied_diff": "+ New principle",
        }
        body = f"### SGR Decision\n\n```json\n{json.dumps(dec)}\n```"
        comments = [{"body": body}]
        result = parse_release_comments(comments)
        assert len(result["decisions"]) == 1
        assert result["decisions"][0]["verdict"] == "approved"

    def test_parse_summary_comment(self) -> None:
        summary = {
            "station": "release",
            "type": "summary",
            "issue": 151,
            "session_opened_at": "2026-03-27T10:00:00Z",
            "session_closed_at": "2026-03-29T10:00:00Z",
            "participants": ["Claude-1@claude"],
            "decisions": [],
            "stats": {"total_proposals": 0, "approved": 0, "rejected": 0},
        }
        body = f"```json\n{json.dumps(summary)}\n```"
        comments = [{"body": body}]
        result = parse_release_comments(comments)
        assert len(result["summaries"]) == 1

    def test_ignores_non_release_json(self) -> None:
        body = '```json\n{"station": "verify", "verdict": "APPROVED"}\n```'
        comments = [{"body": body}]
        result = parse_release_comments(comments)
        assert len(result["proposals"]) == 0
        assert len(result["decisions"]) == 0

    def test_ignores_invalid_json(self) -> None:
        body = "```json\n{not valid json}\n```"
        comments = [{"body": body}]
        result = parse_release_comments(comments)
        assert len(result["proposals"]) == 0

    def test_multiple_comments_mixed(self) -> None:
        proposal = _make_proposal()
        dec = {
            "station": "release",
            "type": "decision",
            "issue": 151,
            "agent_id": "Claude-1@claude",
            "proposal_hash": "deadbeef12345678",
            "verdict": "rejected",
            "rationale": "Too vague.",
            "rejection_reason": "too_vague",
        }
        comments = [
            {"body": f"```json\n{json.dumps(proposal)}\n```"},
            {"body": f"```json\n{json.dumps(dec)}\n```"},
            {"body": "No JSON here, just markdown."},
        ]
        result = parse_release_comments(comments)
        assert len(result["proposals"]) == 1
        assert len(result["decisions"]) == 1


# ---------------------------------------------------------------------------
# Provenance builder
# ---------------------------------------------------------------------------

class TestProvenance:
    def test_builds_from_approved(self) -> None:
        p = _make_proposal()
        h = compute_proposal_hash(p)
        decisions = [{"proposal_hash": h, "verdict": "approved"}]
        prov = build_provenance([p], decisions)
        assert prov["sgr_version"] == 1
        assert len(prov["proposals"]) == 1
        entry = prov["proposals"][0]
        assert entry["proposal_hash"] == h
        assert entry["verdict"] == "approved"
        assert entry["experience"]["task_id"] == 151

    def test_skips_rejected(self) -> None:
        p = _make_proposal()
        h = compute_proposal_hash(p)
        decisions = [{"proposal_hash": h, "verdict": "rejected"}]
        prov = build_provenance([p], decisions)
        assert len(prov["proposals"]) == 0

    def test_multiple_proposals(self) -> None:
        p1 = _make_proposal(severity="memory")
        p2 = _make_proposal(severity="example")
        h1 = compute_proposal_hash(p1)
        h2 = compute_proposal_hash(p2)
        decisions = [
            {"proposal_hash": h1, "verdict": "approved"},
            {"proposal_hash": h2, "verdict": "rejected"},
        ]
        prov = build_provenance([p1, p2], decisions)
        assert len(prov["proposals"]) == 1
        assert prov["proposals"][0]["severity"] == "memory"

    def test_reflection_summary_captures_root_cause(self) -> None:
        p = _make_proposal()
        h = compute_proposal_hash(p)
        decisions = [{"proposal_hash": h, "verdict": "approved"}]
        prov = build_provenance([p], decisions)
        assert "Eagerness" in prov["proposals"][0]["reflection_summary"]
