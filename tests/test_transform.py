"""Tests for the Transform mechanic — two-phase consent identity transformation."""

from __future__ import annotations

import copy
import json
import re
from datetime import datetime, timezone, timedelta

import pytest

from scripts.tide_parser import TideEvent, parse_comment
from scripts.tide import TideProcessor
from scripts.check_ledger_schema import validate_achievements, ERRORS


@pytest.fixture(autouse=True)
def _clear_errors():
    ERRORS.clear()
    yield
    ERRORS.clear()


# ---------------------------------------------------------------------------
# Parser tests
# ---------------------------------------------------------------------------


class TestTransformParsing:
    def _parse(self, body: str) -> TideEvent | None:
        return parse_comment(
            body,
            issue=42,
            created_at="2026-03-10T12:00:00Z",
            author_github="CursorWEA",
            comment_id=999,
        )

    def test_accept_transform(self):
        ev = self._parse("!accept-transform")
        assert ev is not None
        assert ev.type == "accept_transform"
        assert ev.issue == 42

    def test_reject_transform(self):
        ev = self._parse("!reject-transform")
        assert ev is not None
        assert ev.type == "reject_transform"

    def test_accept_transform_case_insensitive(self):
        ev = self._parse("!Accept-Transform")
        assert ev is not None
        assert ev.type == "accept_transform"

    def test_reject_transform_case_insensitive(self):
        ev = self._parse("!REJECT-TRANSFORM")
        assert ev is not None
        assert ev.type == "reject_transform"

    def test_accept_transform_trailing_whitespace(self):
        ev = self._parse("!accept-transform   ")
        assert ev is not None
        assert ev.type == "accept_transform"

    def test_accept_transform_with_extra_text_no_match(self):
        """!accept-transform must be alone on the line."""
        ev = self._parse("!accept-transform please")
        assert ev is None or ev.type != "accept_transform"

    def test_regular_comment_not_matched(self):
        ev = self._parse("I think this is a good idea")
        assert ev is None

    def test_accept_transform_in_multiline(self):
        """!accept-transform on its own line in multiline comment."""
        ev = self._parse("Thanks for the proposal.\n!accept-transform\nLooking forward.")
        assert ev is not None
        assert ev.type == "accept_transform"


# ---------------------------------------------------------------------------
# TideProcessor transform tests
# ---------------------------------------------------------------------------


def _make_processor(
    achievements: dict | None = None,
    balances: dict | None = None,
) -> TideProcessor:
    """Create a TideProcessor with minimal state for transform testing."""
    if balances is None:
        balances = {
            "agents": {
                "agent0@system": {
                    "balance": 7000, "registered_at": "2026-01-01T00:00:00Z",
                    "platform": "system", "github_username": "peachgabba22",
                },
                "Cursor-1@cursor": {
                    "balance": 300, "registered_at": "2026-01-01T00:00:00Z",
                    "platform": "Cursor", "github_username": "CursorWEA",
                },
            }
        }
    escrows = {"version": 1, "active": {}}
    idem_keys = {"keys": {}}
    task_index = {"version": 1, "tasks": {}}
    return TideProcessor(balances, escrows, idem_keys, task_index, achievements)


def _make_achievements_with_pending(
    agent_id: str = "Cursor-1@cursor",
    words: list[str] | None = None,
    new_word: str = "builder",
    issue: int = 42,
) -> dict:
    """Create achievements data with a pending transform."""
    if words is None:
        words = ["planner", "persistent"]
    title = "-".join(reversed(words)) if words else ""
    history = [
        {"action": "award", "word": w, "at": f"2026-03-0{i+1}T00:00:00Z"}
        for i, w in enumerate(words)
    ]
    return {
        "version": 1,
        "agents": {
            agent_id: {
                "title": title,
                "words": list(words),
                "history": history,
                "pending_transform": {
                    "new_word": new_word,
                    "proposed_at": "2026-03-10T12:00:00Z",
                    "issue": issue,
                },
            }
        }
    }


class TestAcceptTransform:
    def test_happy_path(self):
        """Full accept: all words revoked, new word awarded."""
        ach = _make_achievements_with_pending()
        proc = _make_processor(achievements=ach)

        ev = TideEvent(
            type="accept_transform", issue=42,
            created_at="2026-03-11T00:00:00Z",
            author_github="CursorWEA", source="comment", comment_id=100,
        )
        result = proc.process(ev)
        assert result is True
        assert proc.count == 1

        agent_ach = proc.achievements["agents"]["Cursor-1@cursor"]
        assert agent_ach["words"] == ["builder"]
        assert agent_ach["title"] == "builder"
        assert "pending_transform" not in agent_ach

        # Check history entries
        history = agent_ach["history"]
        revokes = [h for h in history if h["action"] == "transform_revoke"]
        awards = [h for h in history if h["action"] == "transform_award"]
        assert len(revokes) == 2  # persistent + planner
        assert len(awards) == 1
        assert awards[0]["word"] == "builder"

        # Check idem key (includes proposed_at for uniqueness)
        assert proc._has_idem("transform|42|Cursor-1@cursor|2026-03-10T12:00:00Z")

        # Check confirmation comment
        assert any("Transform complete" in a.body for a in proc.actions if a.body)

    def test_single_word_transform(self):
        """Transform agent with only one word."""
        ach = _make_achievements_with_pending(words=["planner"], new_word="builder")
        proc = _make_processor(achievements=ach)

        ev = TideEvent(
            type="accept_transform", issue=42,
            created_at="2026-03-11T00:00:00Z",
            author_github="CursorWEA", source="comment", comment_id=100,
        )
        result = proc.process(ev)
        assert result is True

        agent_ach = proc.achievements["agents"]["Cursor-1@cursor"]
        assert agent_ach["words"] == ["builder"]
        assert agent_ach["title"] == "builder"

    def test_no_pending_returns_false(self):
        """No pending transform → no-op."""
        ach = {
            "version": 1,
            "agents": {
                "Cursor-1@cursor": {
                    "title": "planner", "words": ["planner"],
                    "history": [{"action": "award", "word": "planner", "at": "2026-03-01T00:00:00Z"}],
                }
            }
        }
        proc = _make_processor(achievements=ach)
        ev = TideEvent(
            type="accept_transform", issue=42,
            created_at="2026-03-11T00:00:00Z",
            author_github="CursorWEA", source="comment", comment_id=100,
        )
        result = proc.process(ev)
        assert result is False

    def test_wrong_issue_returns_false(self):
        """Accept on different issue than pending → no-op."""
        ach = _make_achievements_with_pending(issue=42)
        proc = _make_processor(achievements=ach)
        ev = TideEvent(
            type="accept_transform", issue=99,
            created_at="2026-03-11T00:00:00Z",
            author_github="CursorWEA", source="comment", comment_id=100,
        )
        result = proc.process(ev)
        assert result is False

    def test_wrong_agent_returns_false(self):
        """Different GitHub user tries to accept → no-op."""
        ach = _make_achievements_with_pending()
        proc = _make_processor(achievements=ach)
        ev = TideEvent(
            type="accept_transform", issue=42,
            created_at="2026-03-11T00:00:00Z",
            author_github="SomeOtherUser", source="comment", comment_id=100,
        )
        result = proc.process(ev)
        assert result is False

    def test_idem_key_prevents_replay(self):
        """Second accept is blocked by idem key."""
        ach = _make_achievements_with_pending()
        proc = _make_processor(achievements=ach)
        ev = TideEvent(
            type="accept_transform", issue=42,
            created_at="2026-03-11T00:00:00Z",
            author_github="CursorWEA", source="comment", comment_id=100,
        )
        proc.process(ev)
        # Try again
        result = proc.process(ev)
        assert result is False

    def test_expired_accept_returns_false(self):
        """Accept comment posted after 7-day window → no-op."""
        # Proposal on day 0, accept comment on day 8 → expired at event time
        proposal_time = "2026-03-01T00:00:00Z"
        accept_time = "2026-03-09T00:00:00Z"  # 8 days later

        ach = _make_achievements_with_pending()
        ach["agents"]["Cursor-1@cursor"]["pending_transform"]["proposed_at"] = proposal_time

        proc = _make_processor(achievements=ach)
        ev = TideEvent(
            type="accept_transform", issue=42,
            created_at=accept_time,
            author_github="CursorWEA", source="comment", comment_id=100,
        )
        result = proc.process(ev)
        assert result is False
        # Pending transform still there (expire_transforms handles removal)
        assert "pending_transform" in proc.achievements["agents"]["Cursor-1@cursor"]

    def test_in_window_accept_succeeds_even_if_processing_late(self):
        """Accept posted on day 6, processed on day 8 → should succeed."""
        proposal_time = "2026-03-01T00:00:00Z"
        accept_time = "2026-03-07T00:00:00Z"  # 6 days later — within window

        ach = _make_achievements_with_pending()
        ach["agents"]["Cursor-1@cursor"]["pending_transform"]["proposed_at"] = proposal_time

        proc = _make_processor(achievements=ach)
        ev = TideEvent(
            type="accept_transform", issue=42,
            created_at=accept_time,
            author_github="CursorWEA", source="comment", comment_id=100,
        )
        result = proc.process(ev)
        assert result is True
        # Transform was applied
        assert proc.achievements["agents"]["Cursor-1@cursor"]["words"] == ["builder"]

    def test_achievements_dirty_flag(self):
        """achievements_dirty is set after transform."""
        ach = _make_achievements_with_pending()
        proc = _make_processor(achievements=ach)
        ev = TideEvent(
            type="accept_transform", issue=42,
            created_at="2026-03-11T00:00:00Z",
            author_github="CursorWEA", source="comment", comment_id=100,
        )
        assert proc.achievements_dirty is False
        proc.process(ev)
        assert proc.achievements_dirty is True


class TestRejectTransform:
    def test_happy_path(self):
        """Reject removes pending, posts comment, no word changes."""
        ach = _make_achievements_with_pending()
        proc = _make_processor(achievements=ach)
        ev = TideEvent(
            type="reject_transform", issue=42,
            created_at="2026-03-11T00:00:00Z",
            author_github="CursorWEA", source="comment", comment_id=100,
        )
        result = proc.process(ev)
        assert result is True

        agent_ach = proc.achievements["agents"]["Cursor-1@cursor"]
        assert "pending_transform" not in agent_ach
        # Words unchanged
        assert agent_ach["words"] == ["planner", "persistent"]
        assert agent_ach["title"] == "persistent-planner"

        # Confirmation comment posted
        assert any("declined" in a.body for a in proc.actions if a.body)

    def test_no_pending_returns_false(self):
        ach = {
            "version": 1,
            "agents": {
                "Cursor-1@cursor": {
                    "title": "planner", "words": ["planner"],
                    "history": [{"action": "award", "word": "planner", "at": "2026-03-01T00:00:00Z"}],
                }
            }
        }
        proc = _make_processor(achievements=ach)
        ev = TideEvent(
            type="reject_transform", issue=42,
            created_at="2026-03-11T00:00:00Z",
            author_github="CursorWEA", source="comment", comment_id=100,
        )
        result = proc.process(ev)
        assert result is False

    def test_wrong_agent_returns_false(self):
        ach = _make_achievements_with_pending()
        proc = _make_processor(achievements=ach)
        ev = TideEvent(
            type="reject_transform", issue=42,
            created_at="2026-03-11T00:00:00Z",
            author_github="SomeOtherUser", source="comment", comment_id=100,
        )
        result = proc.process(ev)
        assert result is False


class TestExpireTransforms:
    def test_expired_transform_removed(self):
        """Transform older than 7 days is auto-expired."""
        old_time = (datetime.now(timezone.utc) - timedelta(days=8)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        ach = _make_achievements_with_pending()
        ach["agents"]["Cursor-1@cursor"]["pending_transform"]["proposed_at"] = old_time

        proc = _make_processor(achievements=ach)
        proc.expire_transforms()

        agent_ach = proc.achievements["agents"]["Cursor-1@cursor"]
        assert "pending_transform" not in agent_ach
        assert proc.achievements_dirty is True
        # Expiration comment posted
        assert any("expired" in a.body for a in proc.actions if a.body)

    def test_fresh_transform_not_expired(self):
        """Transform within 7 days is NOT expired."""
        ach = _make_achievements_with_pending()
        # proposed_at is "2026-03-10T12:00:00Z" — assume that's recent enough
        # Override with a fresh timestamp
        fresh_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        ach["agents"]["Cursor-1@cursor"]["pending_transform"]["proposed_at"] = fresh_time

        proc = _make_processor(achievements=ach)
        proc.expire_transforms()

        agent_ach = proc.achievements["agents"]["Cursor-1@cursor"]
        assert "pending_transform" in agent_ach
        assert proc.achievements_dirty is False

    def test_no_achievements_no_crash(self):
        """Expire with no achievements data doesn't crash."""
        proc = _make_processor(achievements=None)
        proc.expire_transforms()  # Should not raise


# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------


class TestSchemaWithPendingTransform:
    def test_valid_pending_transform(self):
        data = {
            "version": 1,
            "agents": {
                "A@p": {
                    "title": "planner",
                    "words": ["planner"],
                    "history": [{"action": "award", "word": "planner", "at": "2026-03-01T00:00:00Z"}],
                    "pending_transform": {
                        "new_word": "builder",
                        "proposed_at": "2026-03-10T12:00:00Z",
                        "issue": 42,
                    },
                }
            }
        }
        validate_achievements(data)
        assert len(ERRORS) == 0

    def test_pending_transform_missing_new_word(self):
        data = {
            "version": 1,
            "agents": {
                "A@p": {
                    "title": "planner",
                    "words": ["planner"],
                    "history": [{"action": "award", "word": "planner", "at": "2026-03-01T00:00:00Z"}],
                    "pending_transform": {
                        "proposed_at": "2026-03-10T12:00:00Z",
                        "issue": 42,
                    },
                }
            }
        }
        validate_achievements(data)
        assert any("new_word" in e for e in ERRORS)

    def test_pending_transform_missing_issue(self):
        data = {
            "version": 1,
            "agents": {
                "A@p": {
                    "title": "planner",
                    "words": ["planner"],
                    "history": [{"action": "award", "word": "planner", "at": "2026-03-01T00:00:00Z"}],
                    "pending_transform": {
                        "new_word": "builder",
                        "proposed_at": "2026-03-10T12:00:00Z",
                    },
                }
            }
        }
        validate_achievements(data)
        assert any("issue" in e for e in ERRORS)

    def test_pending_transform_not_dict(self):
        data = {
            "version": 1,
            "agents": {
                "A@p": {
                    "title": "planner",
                    "words": ["planner"],
                    "history": [{"action": "award", "word": "planner", "at": "2026-03-01T00:00:00Z"}],
                    "pending_transform": "invalid",
                }
            }
        }
        validate_achievements(data)
        assert any("pending_transform must be a dict" in e for e in ERRORS)

    def test_no_pending_transform_still_valid(self):
        """Agent without pending_transform is perfectly valid."""
        data = {
            "version": 1,
            "agents": {
                "A@p": {
                    "title": "planner",
                    "words": ["planner"],
                    "history": [{"action": "award", "word": "planner", "at": "2026-03-01T00:00:00Z"}],
                }
            }
        }
        validate_achievements(data)
        assert len(ERRORS) == 0

    def test_pending_transform_with_reason(self):
        """Optional reason field is accepted."""
        data = {
            "version": 1,
            "agents": {
                "A@p": {
                    "title": "planner",
                    "words": ["planner"],
                    "history": [{"action": "award", "word": "planner", "at": "2026-03-01T00:00:00Z"}],
                    "pending_transform": {
                        "new_word": "builder",
                        "proposed_at": "2026-03-10T12:00:00Z",
                        "issue": 42,
                        "reason": "Acting more as a builder",
                    },
                }
            }
        }
        validate_achievements(data)
        assert len(ERRORS) == 0


# ---------------------------------------------------------------------------
# Full cycle consistency: transform then validate
# ---------------------------------------------------------------------------


class TestTransformConsistency:
    def test_post_transform_passes_schema(self):
        """After transform, achievements pass schema validation."""
        ach = _make_achievements_with_pending()
        proc = _make_processor(achievements=ach)
        ev = TideEvent(
            type="accept_transform", issue=42,
            created_at="2026-03-11T00:00:00Z",
            author_github="CursorWEA", source="comment", comment_id=100,
        )
        proc.process(ev)

        validate_achievements(proc.achievements)
        assert len(ERRORS) == 0, f"Schema errors after transform: {ERRORS}"

    def test_post_reject_passes_schema(self):
        """After reject, achievements pass schema validation."""
        ach = _make_achievements_with_pending()
        proc = _make_processor(achievements=ach)
        ev = TideEvent(
            type="reject_transform", issue=42,
            created_at="2026-03-11T00:00:00Z",
            author_github="CursorWEA", source="comment", comment_id=100,
        )
        proc.process(ev)

        validate_achievements(proc.achievements)
        assert len(ERRORS) == 0, f"Schema errors after reject: {ERRORS}"


class TestExpireNaiveDatetime:
    """P1 fix: expire_transforms must handle naive datetimes (no timezone)."""

    def test_naive_proposed_at_does_not_crash(self):
        """Naive datetime (no Z or offset) must not raise TypeError."""
        old_time = (datetime.now(timezone.utc) - timedelta(days=8)).strftime(
            "%Y-%m-%dT%H:%M:%S"  # no Z — produces naive datetime
        )
        ach = _make_achievements_with_pending()
        ach["agents"]["Cursor-1@cursor"]["pending_transform"]["proposed_at"] = old_time

        proc = _make_processor(achievements=ach)
        proc.expire_transforms()  # Must not raise TypeError

        # Should still expire (treated as UTC)
        agent_ach = proc.achievements["agents"]["Cursor-1@cursor"]
        assert "pending_transform" not in agent_ach
        assert proc.achievements_dirty is True


class TestMultiAgentAmbiguity:
    """P2 fix: two agents same owner, same issue → ambiguous, no-op."""

    def test_ambiguous_accept_returns_false(self):
        """Two pending transforms on same issue for same owner → no-op."""
        ach = {
            "version": 1,
            "agents": {
                "Cursor-1@cursor": {
                    "title": "planner", "words": ["planner"],
                    "history": [{"action": "award", "word": "planner", "at": "2026-03-01T00:00:00Z"}],
                    "pending_transform": {
                        "new_word": "builder", "proposed_at": "2026-03-10T12:00:00Z", "issue": 42,
                    },
                },
                "Cursor-2@cursor": {
                    "title": "tester", "words": ["tester"],
                    "history": [{"action": "award", "word": "tester", "at": "2026-03-01T00:00:00Z"}],
                    "pending_transform": {
                        "new_word": "reviewer", "proposed_at": "2026-03-10T12:00:00Z", "issue": 42,
                    },
                },
            },
        }
        balances = {
            "agents": {
                "Cursor-1@cursor": {"github_username": "CursorWEA", "balance": 100},
                "Cursor-2@cursor": {"github_username": "CursorWEA", "balance": 100},
            }
        }
        proc = TideProcessor(balances, {"active": {}}, {"keys": {}}, {"tasks": {}}, ach)
        ev = TideEvent(
            type="accept_transform", issue=42,
            created_at="2026-03-11T00:00:00Z",
            author_github="CursorWEA", source="comment", comment_id=100,
        )
        result = proc.process(ev)
        assert result is False
        # Both pending transforms should remain untouched
        assert "pending_transform" in proc.achievements["agents"]["Cursor-1@cursor"]
        assert "pending_transform" in proc.achievements["agents"]["Cursor-2@cursor"]
