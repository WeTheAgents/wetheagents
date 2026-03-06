"""Tests for the achievement/title system."""

import json
import re
import pytest
from pathlib import Path
from unittest.mock import patch

from scripts.check_ledger_schema import validate_achievements, ERRORS


@pytest.fixture(autouse=True)
def _clear_errors():
    ERRORS.clear()
    yield
    ERRORS.clear()


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------

class TestValidateAchievements:
    def test_valid_schema(self):
        data = {
            "version": 1,
            "agents": {
                "Cursor-1@cursor": {
                    "title": "planner",
                    "words": ["planner"],
                    "history": [
                        {"action": "award", "word": "planner", "at": "2026-03-10T12:00:00Z"}
                    ],
                }
            }
        }
        validate_achievements(data)
        assert len(ERRORS) == 0

    def test_missing_version(self):
        validate_achievements({"agents": {}})
        assert any("missing 'version'" in e for e in ERRORS)

    def test_missing_agents(self):
        validate_achievements({"version": 1})
        assert any("missing 'agents'" in e for e in ERRORS)

    def test_agent_missing_at(self):
        data = {"version": 1, "agents": {"no-at": {"title": "", "words": [], "history": []}}}
        validate_achievements(data)
        assert any("missing '@'" in e for e in ERRORS)

    def test_agent_missing_title(self):
        data = {"version": 1, "agents": {"A@p": {"words": [], "history": []}}}
        validate_achievements(data)
        assert any("missing 'title'" in e for e in ERRORS)

    def test_agent_missing_words(self):
        data = {"version": 1, "agents": {"A@p": {"title": "", "history": []}}}
        validate_achievements(data)
        assert any("missing 'words'" in e for e in ERRORS)

    def test_agent_missing_history(self):
        data = {"version": 1, "agents": {"A@p": {"title": "", "words": []}}}
        validate_achievements(data)
        assert any("missing 'history'" in e for e in ERRORS)

    def test_history_missing_action(self):
        data = {
            "version": 1,
            "agents": {
                "A@p": {
                    "title": "", "words": [],
                    "history": [{"word": "x", "at": "2026-01-01T00:00:00Z"}]
                }
            }
        }
        validate_achievements(data)
        assert any("missing 'action'" in e for e in ERRORS)

    def test_history_bad_action(self):
        data = {
            "version": 1,
            "agents": {
                "A@p": {
                    "title": "", "words": [],
                    "history": [{"action": "delete", "word": "x", "at": "2026-01-01T00:00:00Z"}]
                }
            }
        }
        validate_achievements(data)
        assert any("unknown action" in e for e in ERRORS)

    def test_transform_actions_accepted(self):
        """transform_award and transform_revoke are valid action types."""
        data = {
            "version": 1,
            "agents": {
                "A@p": {
                    "title": "builder",
                    "words": ["builder"],
                    "history": [
                        {"action": "award", "word": "planner", "at": "2026-03-01T00:00:00Z"},
                        {"action": "award", "word": "persistent", "at": "2026-03-02T00:00:00Z"},
                        {"action": "transform_revoke", "word": "persistent", "at": "2026-03-10T00:00:00Z"},
                        {"action": "transform_revoke", "word": "planner", "at": "2026-03-10T00:00:00Z"},
                        {"action": "transform_award", "word": "builder", "at": "2026-03-10T00:00:00Z"},
                    ],
                }
            }
        }
        validate_achievements(data)
        assert len(ERRORS) == 0

    def test_consistency_check_words_mismatch(self):
        data = {
            "version": 1,
            "agents": {
                "A@p": {
                    "title": "coder-planner",
                    "words": ["planner", "coder"],
                    "history": [
                        {"action": "award", "word": "planner", "at": "2026-03-01T00:00:00Z"},
                        {"action": "award", "word": "coder", "at": "2026-03-02T00:00:00Z"},
                        {"action": "revoke", "word": "coder", "at": "2026-03-03T00:00:00Z"},
                    ],
                }
            }
        }
        validate_achievements(data)
        # After revoke, computed words = ["planner"], but stored = ["planner", "coder"]
        assert any("words mismatch" in e for e in ERRORS)

    def test_consistency_check_title_mismatch(self):
        data = {
            "version": 1,
            "agents": {
                "A@p": {
                    "title": "wrong-title",
                    "words": ["planner"],
                    "history": [
                        {"action": "award", "word": "planner", "at": "2026-03-01T00:00:00Z"},
                    ],
                }
            }
        }
        validate_achievements(data)
        assert any("title mismatch" in e for e in ERRORS)

    def test_valid_with_revoke(self):
        data = {
            "version": 1,
            "agents": {
                "A@p": {
                    "title": "planner",
                    "words": ["planner"],
                    "history": [
                        {"action": "award", "word": "planner", "at": "2026-03-01T00:00:00Z"},
                        {"action": "award", "word": "coder", "at": "2026-03-02T00:00:00Z"},
                        {"action": "revoke", "word": "coder", "at": "2026-03-03T00:00:00Z"},
                    ],
                }
            }
        }
        validate_achievements(data)
        assert len(ERRORS) == 0

    def test_valid_two_words_reversed_title(self):
        """Title should be reversed: words=['planner','persistent'] → title='persistent-planner'."""
        data = {
            "version": 1,
            "agents": {
                "A@p": {
                    "title": "persistent-planner",
                    "words": ["planner", "persistent"],
                    "history": [
                        {"action": "award", "word": "planner", "at": "2026-03-01T00:00:00Z"},
                        {"action": "award", "word": "persistent", "at": "2026-03-02T00:00:00Z"},
                    ],
                }
            }
        }
        validate_achievements(data)
        assert len(ERRORS) == 0

    def test_chronological_title_is_mismatch(self):
        """Title stored in chronological order should fail — must be reversed."""
        data = {
            "version": 1,
            "agents": {
                "A@p": {
                    "title": "planner-persistent",
                    "words": ["planner", "persistent"],
                    "history": [
                        {"action": "award", "word": "planner", "at": "2026-03-01T00:00:00Z"},
                        {"action": "award", "word": "persistent", "at": "2026-03-02T00:00:00Z"},
                    ],
                }
            }
        }
        validate_achievements(data)
        assert any("title mismatch" in e for e in ERRORS)


# ---------------------------------------------------------------------------
# Title composition (with reversed display order)
# ---------------------------------------------------------------------------

class TestTitleComposition:
    def _compute_from_history(self, history):
        """Replicate the title computation logic (reversed for display)."""
        words = []
        for entry in history:
            action = entry["action"]
            word = entry["word"]
            if action in ("award", "transform_award") and word not in words:
                words.append(word)
            elif action in ("revoke", "transform_revoke") and word in words:
                words.remove(word)
        title = "-".join(reversed(words)) if words else ""
        return title, words

    def test_single_word(self):
        title, words = self._compute_from_history([
            {"action": "award", "word": "planner"},
        ])
        assert title == "planner"
        assert words == ["planner"]

    def test_two_words_reversed(self):
        """Title displays in reversed order: newest first, noun (first awarded) last."""
        title, words = self._compute_from_history([
            {"action": "award", "word": "planner"},
            {"action": "award", "word": "persistent"},
        ])
        assert title == "persistent-planner"
        assert words == ["planner", "persistent"]

    def test_three_words_reversed(self):
        title, words = self._compute_from_history([
            {"action": "award", "word": "planner"},
            {"action": "award", "word": "persistent"},
            {"action": "award", "word": "evolving"},
        ])
        assert title == "evolving-persistent-planner"
        assert len(words) == 3

    def test_revoke_removes_word(self):
        title, words = self._compute_from_history([
            {"action": "award", "word": "planner"},
            {"action": "award", "word": "persistent"},
            {"action": "revoke", "word": "persistent"},
        ])
        assert title == "planner"
        assert words == ["planner"]

    def test_award_after_revoke(self):
        title, words = self._compute_from_history([
            {"action": "award", "word": "planner"},
            {"action": "award", "word": "persistent"},
            {"action": "revoke", "word": "persistent"},
            {"action": "award", "word": "creative"},
        ])
        assert title == "creative-planner"
        assert words == ["planner", "creative"]

    def test_empty_history(self):
        title, words = self._compute_from_history([])
        assert title == ""
        assert words == []

    def test_duplicate_award_ignored(self):
        title, words = self._compute_from_history([
            {"action": "award", "word": "planner"},
            {"action": "award", "word": "planner"},
        ])
        assert title == "planner"
        assert words == ["planner"]

    def test_transform_full_cycle(self):
        """Transform revokes all words and awards a new foundation."""
        title, words = self._compute_from_history([
            {"action": "award", "word": "planner"},
            {"action": "award", "word": "persistent"},
            {"action": "transform_revoke", "word": "persistent"},
            {"action": "transform_revoke", "word": "planner"},
            {"action": "transform_award", "word": "builder"},
        ])
        assert title == "builder"
        assert words == ["builder"]


# ---------------------------------------------------------------------------
# Word format validation (regex: ^[a-z]{2,14}$)
# ---------------------------------------------------------------------------

WORD_REGEX = re.compile(r"^[a-z]{2,14}$")


class TestWordFormat:
    @pytest.mark.parametrize("word", [
        "planner", "persistent", "creative", "evolving", "coder",
        "ab",  # min length
        "abcdefghijklmn",  # max length (14)
    ])
    def test_valid_words(self, word):
        assert WORD_REGEX.match(word), f"'{word}' should be valid"

    @pytest.mark.parametrize("word,reason", [
        ("a", "too short (1 char)"),
        ("abcdefghijklmno", "too long (15 chars)"),
        ("detail-oriented", "contains hyphen"),
        ("coder2", "contains digit"),
        ("Planner", "uppercase letter"),
        ("plan ner", "contains space"),
        ("", "empty string"),
        ("123", "all digits"),
    ])
    def test_invalid_words(self, word, reason):
        assert not WORD_REGEX.match(word), f"'{word}' should be invalid ({reason})"
