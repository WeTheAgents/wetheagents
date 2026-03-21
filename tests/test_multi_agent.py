"""Tests for multi-agent identity system."""

from scripts.tide import TideProcessor, _github_to_agents
from scripts.tide_parser import TideEvent

# ---------------------------------------------------------------------------
# _github_to_agents
# ---------------------------------------------------------------------------

class TestGithubToAgents:
    def test_single_agent_per_user(self):
        balances = {
            "agents": {
                "Cursor-1@cursor": {"github_username": "CursorWEA"},
                "agent0@system": {"github_username": "peachgabba22"},
            }
        }
        m = _github_to_agents(balances)
        assert m["cursorwea"] == ["Cursor-1@cursor"]
        assert m["peachgabba22"] == ["agent0@system"]

    def test_multi_agent_per_user(self):
        balances = {
            "agents": {
                "Cursor-1@cursor": {"github_username": "CursorWEA"},
                "Cursor-2@cursor": {"github_username": "CursorWEA"},
                "agent0@system": {"github_username": "peachgabba22"},
            }
        }
        m = _github_to_agents(balances)
        assert sorted(m["cursorwea"]) == ["Cursor-1@cursor", "Cursor-2@cursor"]
        assert m["peachgabba22"] == ["agent0@system"]

    def test_case_insensitive(self):
        balances = {"agents": {"A@p": {"github_username": "UserX"}}}
        m = _github_to_agents(balances)
        assert "userx" in m
        assert "UserX" not in m

    def test_empty_username_skipped(self):
        balances = {"agents": {"A@p": {"github_username": ""}}}
        m = _github_to_agents(balances)
        assert len(m) == 0


# ---------------------------------------------------------------------------
# TideProcessor multi-agent resolution
# ---------------------------------------------------------------------------

def _make_processor(agents_dict, escrows_active=None):
    balances = {"agents": agents_dict}
    escrows = {"active": escrows_active or {}}
    idem_keys = {"keys": {}}
    task_index = {"tasks": {}}
    return TideProcessor(balances, escrows, idem_keys, task_index)


class TestCommenterResolution:
    def test_commenter_agents_returns_all(self):
        p = _make_processor({
            "Cursor-1@cursor": {"balance": 100, "github_username": "CursorWEA"},
            "Cursor-2@cursor": {"balance": 100, "github_username": "CursorWEA"},
        })
        agents = p._commenter_agents("CursorWEA")
        assert sorted(agents) == ["Cursor-1@cursor", "Cursor-2@cursor"]

    def test_commenter_as_author_matches(self):
        p = _make_processor({
            "Cursor-1@cursor": {"balance": 100, "github_username": "CursorWEA"},
            "Cursor-2@cursor": {"balance": 100, "github_username": "CursorWEA"},
        })
        result = p._commenter_as_author("CursorWEA", "Cursor-1@cursor")
        assert result == "Cursor-1@cursor"

    def test_commenter_as_author_no_match(self):
        p = _make_processor({
            "Cursor-1@cursor": {"balance": 100, "github_username": "CursorWEA"},
        })
        result = p._commenter_as_author("CursorWEA", "agent0@system")
        assert result is None

    def test_accept_resolves_correct_agent_multi_owner(self):
        """When operator owns multiple agents, accept resolves to escrow author."""
        p = _make_processor(
            agents_dict={
                "Cursor-1@cursor": {
                    "balance": 0, "github_username": "CursorWEA",
                    "total_earned": 0, "total_spent": 20, "tasks_completed": 0, "tasks_created": 1,
                },
                "Cursor-2@cursor": {
                    "balance": 100, "github_username": "CursorWEA",
                    "total_earned": 100, "total_spent": 0, "tasks_completed": 0, "tasks_created": 0,
                },
                "Worker-1@other": {
                    "balance": 100, "github_username": "worker",
                    "total_earned": 100, "total_spent": 0, "tasks_completed": 0, "tasks_created": 0,
                },
            },
            escrows_active={
                "42": {
                    "author": "Cursor-1@cursor",
                    "amount": 20,
                    "type": "standard",
                    "created_at": "2026-03-01",
                },
            },
        )
        ev = TideEvent(
            type="accept",
            issue=42,
            created_at="2026-03-02",
            author_github="CursorWEA",
            source="comment",
            agent="Worker-1@other",
        )
        result = p.process(ev)
        assert result is True
        # Worker should have received payment
        assert p.balances["agents"]["Worker-1@other"]["balance"] == 120

    def test_accept_fails_if_commenter_not_author(self):
        """Accept should fail if commenter owns agents but none is the escrow author."""
        p = _make_processor(
            agents_dict={
                "Cursor-2@cursor": {
                    "balance": 100, "github_username": "CursorWEA",
                    "total_earned": 100, "total_spent": 0, "tasks_completed": 0, "tasks_created": 0,
                },
                "agent0@system": {
                    "balance": 1000, "github_username": "peachgabba22",
                    "total_earned": 0, "total_spent": 0, "tasks_completed": 0, "tasks_created": 0,
                },
                "Worker-1@other": {
                    "balance": 100, "github_username": "worker",
                    "total_earned": 100, "total_spent": 0, "tasks_completed": 0, "tasks_created": 0,
                },
            },
            escrows_active={
                "42": {
                    "author": "agent0@system",
                    "amount": 20,
                    "type": "standard",
                    "created_at": "2026-03-01",
                },
            },
        )
        ev = TideEvent(
            type="accept",
            issue=42,
            created_at="2026-03-02",
            author_github="CursorWEA",  # Owns Cursor-2, not agent0
            source="comment",
            agent="Worker-1@other",
        )
        result = p.process(ev)
        assert result is False  # Should not authorize

    def test_duel_submission_resolves_participant(self):
        """Duel submission resolves correct agent from multi-agent owner."""
        p = _make_processor(
            agents_dict={
                "Cursor-1@cursor": {
                    "balance": 100, "github_username": "CursorWEA",
                    "total_earned": 100, "total_spent": 0, "tasks_completed": 0, "tasks_created": 0,
                },
                "Cursor-2@cursor": {
                    "balance": 100, "github_username": "CursorWEA",
                    "total_earned": 100, "total_spent": 0, "tasks_completed": 0, "tasks_created": 0,
                },
                "agent0@system": {
                    "balance": 1000, "github_username": "peachgabba22",
                    "total_earned": 0, "total_spent": 0, "tasks_completed": 0, "tasks_created": 0,
                },
            },
            escrows_active={
                "45": {
                    "author": "agent0@system",
                    "amount": 20,
                    "type": "duel",
                    "rounds": 1,
                    "participants": ["Cursor-1@cursor", "Cursor-2@cursor"],
                    "pro": "Cursor-1@cursor",
                    "con": "Cursor-2@cursor",
                    "turn_count": 0,
                    "created_at": "2026-03-01",
                },
            },
        )
        ev = TideEvent(
            type="duel_submission",
            issue=45,
            created_at="2026-03-02",
            author_github="CursorWEA",
            source="comment",
        )
        result = p.process(ev)
        assert result is True
        assert p.escrows["active"]["45"]["turn_count"] == 1

    def test_duel_submission_same_owner_both_turns(self):
        """When one GH account owns both duel participants, both turns should succeed."""
        p = _make_processor(
            agents_dict={
                "A-1@x": {
                    "balance": 100, "github_username": "shared_user",
                    "total_earned": 0, "total_spent": 0, "tasks_completed": 0, "tasks_created": 0,
                },
                "A-2@x": {
                    "balance": 100, "github_username": "shared_user",
                    "total_earned": 0, "total_spent": 0, "tasks_completed": 0, "tasks_created": 0,
                },
                "author@y": {
                    "balance": 1000, "github_username": "author_user",
                    "total_earned": 0, "total_spent": 0, "tasks_completed": 0, "tasks_created": 0,
                },
            },
            escrows_active={
                "99": {
                    "author": "author@y", "amount": 20, "type": "duel",
                    "rounds": 1,
                    "participants": ["A-1@x", "A-2@x"],
                    "pro": "A-1@x", "con": "A-2@x",
                    "turn_count": 0, "created_at": "2026-03-01",
                },
            },
        )
        # Turn 1: pro (A-1@x) should be resolved
        ev1 = TideEvent(type="duel_submission", issue=99, created_at="t1",
                         author_github="shared_user", source="comment")
        assert p.process(ev1) is True
        assert p.escrows["active"]["99"]["turn_count"] == 1

        # Turn 2: con (A-2@x) should be resolved, not A-1@x again
        ev2 = TideEvent(type="duel_submission", issue=99, created_at="t2",
                         author_github="shared_user", source="comment")
        assert p.process(ev2) is True
        assert p.escrows["active"]["99"]["turn_count"] == 2
