"""Tests for tide_parser — command and issue body parsing."""

from __future__ import annotations

from scripts.tide_parser import TideEvent, parse_comment, parse_task_issue

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE = dict(issue=42, created_at="2026-03-05T12:00:00Z", author_github="testuser")
_COMMENT_BASE = {**_BASE, "comment_id": 999}


def _comment(body: str) -> TideEvent | None:
    return parse_comment(body, **_COMMENT_BASE)


# ---------------------------------------------------------------------------
# Comment parsing — happy paths
# ---------------------------------------------------------------------------


class TestClaim:
    def test_simple(self):
        ev = _comment("claim alice@cursor")
        assert ev is not None
        assert ev.type == "claim"
        assert ev.agent == "alice@cursor"

    def test_case_insensitive(self):
        ev = _comment("Claim Bob@gemini")
        assert ev is not None
        assert ev.type == "claim"
        assert ev.agent == "Bob@gemini"

    def test_with_trailing_text(self):
        ev = _comment("claim agent@x\nsome extra context here")
        assert ev is not None
        assert ev.agent == "agent@x"


class TestAccept:
    def test_with_at(self):
        ev = _comment("accept @alice@cursor")
        assert ev is not None
        assert ev.type == "accept"
        assert ev.agent == "alice@cursor"

    def test_without_at(self):
        ev = _comment("accept alice@cursor")
        assert ev is not None
        assert ev.agent == "alice@cursor"


class TestReject:
    def test_with_reason(self):
        ev = _comment("reject @alice@cursor reason: incomplete submission")
        assert ev is not None
        assert ev.type == "reject"
        assert ev.agent == "alice@cursor"
        assert ev.reason == "incomplete submission"

    def test_reason_multiword(self):
        ev = _comment("reject bob@x reason: did not meet acceptance criteria, missing tests")
        assert ev is not None
        assert ev.reason == "did not meet acceptance criteria, missing tests"


class TestRanking:
    def test_two_agents(self):
        ev = _comment("ranking: @alice@x, @bob@y")
        assert ev is not None
        assert ev.type == "ranking"
        assert ev.agents == ["alice@x", "bob@y"]

    def test_three_agents(self):
        ev = _comment("ranking: @a@x, @b@y, @c@z")
        assert ev.agents == ["a@x", "b@y", "c@z"]

    def test_without_at_signs(self):
        ev = _comment("ranking: alice@x, bob@y")
        assert ev.agents == ["alice@x", "bob@y"]


class TestWinner:
    def test_simple(self):
        ev = _comment("winner: @alice@cursor")
        assert ev is not None
        assert ev.type == "ranking"
        assert ev.agents == ["alice@cursor"]

    def test_without_at(self):
        ev = _comment("winner: alice@x")
        assert ev.agents == ["alice@x"]


class TestDuelWinner:
    def test_simple(self):
        ev = _comment("duel-winner: @alice@cursor")
        assert ev is not None
        assert ev.type == "duel_winner"
        assert ev.agent == "alice@cursor"

    def test_not_confused_with_winner(self):
        """duel-winner should match duel_winner, not ranking."""
        ev = _comment("duel-winner: @bob@x")
        assert ev.type == "duel_winner"


class TestDuelSubmission:
    def test_work_header(self):
        ev = _comment("## Work\n\nHere is my argument for round 1...")
        assert ev is not None
        assert ev.type == "duel_submission"

    def test_work_header_case(self):
        ev = _comment("## work\n\nContent")
        assert ev is not None
        assert ev.type == "duel_submission"


# ---------------------------------------------------------------------------
# Comment parsing — non-commands
# ---------------------------------------------------------------------------


class TestNonCommands:
    def test_empty(self):
        assert _comment("") is None

    def test_regular_comment(self):
        assert _comment("Great work on this task!") is None

    def test_partial_command(self):
        assert _comment("I accept that this is good work") is None

    def test_claim_in_middle(self):
        """claim must be at start of a line."""
        assert _comment("I want to claim alice@x") is None


# ---------------------------------------------------------------------------
# Task issue body parsing
# ---------------------------------------------------------------------------

_WTA_BODY = """### Your Agent ID

agent0@system

### Task Description

Do something useful.

### Reward Type

Winner Take All (single winner, full budget)

### Reward (WEA)

30

### Slots (Progressive Every Good only)

_No response_

### Winners X ([X] Best only)

_No response_

### Rounds (Duel only)

_No response_

### Skills Needed

Coding (Python)

### Deadline (optional)

_No response_"""

_PROGRESSIVE_BODY = """### Your Agent ID

alice@cursor

### Task Description

Progressive task.

### Reward Type

Progressive Every Good (Fibonacci rewards per slot)

### Reward (WEA)

12

### Slots (Progressive Every Good only)

5

### Winners X ([X] Best only)

_No response_

### Rounds (Duel only)

_No response_

### Skills Needed

Research

### Deadline (optional)

2026-03-10"""

_EVERY_GOOD_BODY = """### Your Agent ID

alice@cursor

### Task Description

Every accepted submission gets paid the same amount.

### Reward Type

Every Good (each accepted submission gets paid)

### Reward (WEA)

15

### Per Acceptance (Every Good only)

5

### Slots (Progressive Every Good only)

_No response_

### Winners X ([X] Best only)

_No response_

### Rounds (Duel only)

_No response_

### Skills Needed

Coding (Python)

### Deadline (optional)

_No response_"""

_DUEL_BODY = """### Your Agent ID

bob@gemini

### Task Description

A duel about something.

### Reward Type

Duel (two agents debate, 90/10 split)

### Reward (WEA)

20

### Slots (Progressive Every Good only)

_No response_

### Winners X ([X] Best only)

_No response_

### Rounds (Duel only)

3

### Skills Needed

Creative

### Deadline (optional)

_No response_"""

_BEST_X_BODY = """### Your Agent ID

agent0@system

### Task Description

Best of 3.

### Reward Type

[X] Best (ranked winners share budget, X > 1)

### Reward (WEA)

30

### Slots (Progressive Every Good only)

_No response_

### Winners X ([X] Best only)

3

### Rounds (Duel only)

_No response_

### Skills Needed

Other

### Deadline (optional)

_No response_"""


class TestTaskIssueParsing:
    def test_winner_take_all(self):
        ev = parse_task_issue(_WTA_BODY, **_BASE)
        assert ev is not None
        assert ev.type == "task_create"
        assert ev.task_author_agent == "agent0@system"
        assert ev.reward == 30
        assert ev.reward_type == "best_x"
        assert ev.winners == 1
        assert ev.deadline is None

    def test_progressive(self):
        ev = parse_task_issue(_PROGRESSIVE_BODY, **_BASE)
        assert ev is not None
        assert ev.reward_type == "progressive"
        assert ev.reward == 12
        assert ev.slots == 5
        assert ev.deadline == "2026-03-10"

    def test_every_good_per_acceptance(self):
        ev = parse_task_issue(_EVERY_GOOD_BODY, **_BASE)
        assert ev is not None
        assert ev.reward_type == "every_good"
        assert ev.reward == 15
        assert ev.per_acceptance == 5

    def test_duel(self):
        ev = parse_task_issue(_DUEL_BODY, **_BASE)
        assert ev is not None
        assert ev.reward_type == "duel"
        assert ev.reward == 20
        assert ev.rounds == 3
        assert ev.task_author_agent == "bob@gemini"

    def test_best_x(self):
        ev = parse_task_issue(_BEST_X_BODY, **_BASE)
        assert ev is not None
        assert ev.reward_type == "best_x"
        assert ev.winners == 3

    def test_empty_body(self):
        assert parse_task_issue("", **_BASE) is None

    def test_missing_fields(self):
        assert parse_task_issue("### Your Agent ID\n\nfoo@x", **_BASE) is None

    def test_zero_reward(self):
        body = _WTA_BODY.replace("30", "0")
        assert parse_task_issue(body, **_BASE) is None


# ---------------------------------------------------------------------------
# Malformed input edge cases (#63)
# ---------------------------------------------------------------------------


class TestMalformedCommands:
    def test_claim_no_agent(self):
        """'claim ' with trailing space but no agent should return None."""
        assert _comment("claim ") is None

    def test_claim_whitespace_only_after(self):
        assert _comment("claim   ") is None

    def test_ranking_duplicate_agents(self):
        """Parser does not deduplicate — documents current behavior."""
        ev = _comment("ranking: @alice@x, @alice@x")
        assert ev is not None
        assert ev.agents == ["alice@x", "alice@x"]

    def test_ranking_single_agent(self):
        ev = _comment("ranking: @alice@x")
        assert ev is not None
        assert ev.agents == ["alice@x"]

    def test_negative_reward_task(self):
        body = _WTA_BODY.replace("30", "-5")
        assert parse_task_issue(body, **_BASE) is None

    def test_non_integer_reward_task(self):
        body = _WTA_BODY.replace("30", "abc")
        assert parse_task_issue(body, **_BASE) is None

    def test_reward_type_case_insensitive(self):
        body = _WTA_BODY.replace(
            "Winner Take All (single winner, full budget)",
            "WINNER TAKE ALL (single winner, full budget)",
        )
        ev = parse_task_issue(body, **_BASE)
        assert ev is not None
        assert ev.reward_type == "best_x"

    def test_missing_reward_type_field(self):
        body = "### Your Agent ID\n\nagent0@system\n\n### Reward (WEA)\n\n30"
        assert parse_task_issue(body, **_BASE) is None


# ---------------------------------------------------------------------------
# Verify command parsing
# ---------------------------------------------------------------------------


class TestVerifyCommand:
    def test_simple(self):
        ev = _comment("verify @bob@y evidence: tests pass and endpoint works")
        assert ev is not None
        assert ev.type == "verify"
        assert ev.agent == "bob@y"
        assert ev.reason == "tests pass and endpoint works"

    def test_without_at(self):
        ev = _comment("verify bob@y evidence: all checks pass")
        assert ev is not None
        assert ev.agent == "bob@y"

    def test_case_insensitive(self):
        ev = _comment("Verify @alice@x evidence: confirmed behavior")
        assert ev is not None
        assert ev.type == "verify"

    def test_multiline_evidence(self):
        ev = _comment("verify @bob@y evidence: line1\nline2\nline3")
        assert ev is not None
        assert "line1" in ev.reason
        assert "line3" in ev.reason

    def test_not_confused_with_accept(self):
        """verify should not match as accept."""
        ev = _comment("verify @bob@y evidence: ok")
        assert ev.type == "verify"

    def test_verify_without_evidence_fails(self):
        """verify without 'evidence:' keyword is not a command."""
        assert _comment("verify @bob@y looks good") is None


# ---------------------------------------------------------------------------
# Verification criteria extraction from issue body
# ---------------------------------------------------------------------------

_BODY_WITH_CRITERIA = """### Your Agent ID

agent0@system

### Reward Type

Winner Take All (single winner, full budget)

### Reward (WEA)

30

### Verification Criteria

- [ ] `pytest tests/ -q` exits 0
- [ ] New endpoint returns expected JSON
- [ ] Manual: Agent0 confirms behavior

### Slots (Progressive Every Good only)

_No response_

### Winners X ([X] Best only)

_No response_

### Rounds (Duel only)

_No response_

### Skills Needed

Coding (Python)

### Deadline (optional)

_No response_"""


class TestVerificationCriteriaParsing:
    def test_criteria_extracted(self):
        ev = parse_task_issue(_BODY_WITH_CRITERIA, **_BASE)
        assert ev is not None
        assert ev.verification_criteria is not None
        assert len(ev.verification_criteria) == 3
        assert "`pytest tests/ -q` exits 0" in ev.verification_criteria[0]
        assert "Manual: Agent0 confirms behavior" in ev.verification_criteria[2]

    def test_no_criteria_field(self):
        ev = parse_task_issue(_WTA_BODY, **_BASE)
        assert ev is not None
        assert ev.verification_criteria is None

    def test_empty_criteria(self):
        body = _WTA_BODY + "\n\n### Verification Criteria\n\n_No response_"
        ev = parse_task_issue(body, **_BASE)
        assert ev is not None
        assert ev.verification_criteria is None
