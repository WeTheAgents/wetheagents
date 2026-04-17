"""Tests for scripts/check_t6_team_enforcement.py.

Covers the 12+ required scenarios using in-memory fixture injection only
(no filesystem access required).
"""

from __future__ import annotations

from pathlib import Path

from scripts import check_t6_team_enforcement as checker

AUTHORIZED = checker.DEFAULT_T6_AGENT  # "gemini-4@google"
WRONG = "Claude-1@claude"
OTHER = "Codex-2@codex"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(
    mints: list[dict] | None = None,
    events: list[dict] | None = None,
    authorized_agent: str = AUTHORIZED,
) -> dict:
    """Run check with synthetic in-memory data."""
    return checker.run_check(
        Path("/fake/root"),
        mints=mints if mints is not None else [],
        events=events if events is not None else [],
        authorized_agent=authorized_agent,
    )


def _mint(trajectory: str, slot: int, agents: list[str], issue: str = "#100") -> dict:
    """Build a trajectory_mints.json-style mint record."""
    return {
        "trajectory": trajectory,
        "slot": slot,
        "amount": 20,
        "agents": agents,
        "issue_or_pr": issue,
    }


def _event(trajectory: str, slot: int, agents: list[str], issue: int = 100) -> dict:
    """Build a history trajectory_mint event (list-agents form)."""
    return {
        "type": "trajectory_mint",
        "trajectory": trajectory,
        "slot": slot,
        "amount": 20,
        "agents": agents,
        "issue": issue,
    }


def _event_singular(trajectory: str, slot: int, agent: str, issue: int = 100) -> dict:
    """Build a history trajectory_mint event using the singular 'agent' field."""
    return {
        "type": "trajectory_mint",
        "trajectory": trajectory,
        "slot": slot,
        "amount": 20,
        "agent": agent,
        "issue": issue,
    }


# ---------------------------------------------------------------------------
# PASS cases
# ---------------------------------------------------------------------------

def test_all_t6_to_authorized_mints_pass() -> None:
    """All T6 mints credited to authorized agent → PASS."""
    mints = [
        _mint("T6", 2, [AUTHORIZED], "#200"),
        _mint("T6", 3, [AUTHORIZED], "#201"),
    ]
    result = _run(mints=mints)
    assert result["status"] == "PASS"
    assert result["violations"] == []


def test_all_t6_to_authorized_history_pass() -> None:
    """All T6 history events credited to authorized agent → PASS."""
    events = [
        _event("T6", 2, [AUTHORIZED], 200),
        _event("T6", 3, [AUTHORIZED], 201),
    ]
    result = _run(events=events)
    assert result["status"] == "PASS"
    assert result["violations"] == []


def test_empty_t6_history_pass() -> None:
    """No T6 records anywhere → PASS (nothing to violate)."""
    result = _run(mints=[], events=[])
    assert result["status"] == "PASS"
    assert result["violations"] == []


def test_non_t6_trajectories_not_checked() -> None:
    """T1–T5 mints to any agent are not checked → PASS."""
    mints = [
        _mint("T1", 1, [WRONG]),
        _mint("T2", 1, [WRONG]),
        _mint("T3", 1, [OTHER]),
        _mint("T4", 1, [OTHER]),
        _mint("T5", 1, [WRONG]),
    ]
    events = [
        _event("T1", 1, [WRONG]),
        _event("T3", 2, [OTHER]),
    ]
    result = _run(mints=mints, events=events)
    assert result["status"] == "PASS"
    assert result["violations"] == []


def test_non_trajectory_mint_events_ignored() -> None:
    """Non-trajectory_mint event types in history are ignored."""
    events = [
        {"type": "payment", "trajectory": "T6", "agents": [WRONG], "issue": 1},
        {"type": "escrow", "trajectory": "T6", "agents": [WRONG], "issue": 2},
        {"type": "escrow_return", "trajectory": "T6", "agents": [WRONG], "issue": 3},
    ]
    result = _run(events=events)
    assert result["status"] == "PASS"
    assert result["violations"] == []


def test_singular_agent_field_authorized_pass() -> None:
    """History event using 'agent' (singular) field with authorized agent → PASS."""
    events = [_event_singular("T6", 9, AUTHORIZED, 431)]
    result = _run(events=events)
    assert result["status"] == "PASS"
    assert result["violations"] == []


# ---------------------------------------------------------------------------
# FAIL cases
# ---------------------------------------------------------------------------

def test_t6_mint_wrong_agent_fails() -> None:
    """T6 mint credited to unauthorized agent → FAIL."""
    mints = [_mint("T6", 1, [WRONG], "#301")]
    result = _run(mints=mints)
    assert result["status"] == "FAIL"
    assert len(result["violations"]) == 1
    v = result["violations"][0]
    assert v["source"] == "trajectory_mints"
    assert v["slot"] == 1
    assert WRONG in v["actual_agents"]
    assert WRONG in v["unauthorized_agents"]


def test_history_t6_wrong_agent_fails() -> None:
    """T6 history event credited to unauthorized agent → FAIL."""
    events = [_event("T6", 1, [WRONG], 301)]
    result = _run(events=events)
    assert result["status"] == "FAIL"
    assert len(result["violations"]) == 1
    v = result["violations"][0]
    assert v["source"] == "history"
    assert v["slot"] == 1
    assert WRONG in v["actual_agents"]


def test_mixed_agents_in_t6_mint_fails() -> None:
    """T6 mint with mixed agents (authorized + unauthorized) → FAIL."""
    mints = [_mint("T6", 5, [AUTHORIZED, WRONG], "#500")]
    result = _run(mints=mints)
    assert result["status"] == "FAIL"
    assert len(result["violations"]) == 1
    v = result["violations"][0]
    assert AUTHORIZED in v["actual_agents"]
    assert WRONG in v["unauthorized_agents"]


def test_multiple_t6_violations_fail() -> None:
    """Multiple T6 mints with wrong agents → FAIL with multiple violations."""
    mints = [
        _mint("T6", 1, [WRONG], "#301"),
        _mint("T6", 2, [AUTHORIZED], "#335"),   # ok
        _mint("T6", 3, [OTHER], "#400"),
    ]
    result = _run(mints=mints)
    assert result["status"] == "FAIL"
    assert len(result["violations"]) == 2
    slots = {v["slot"] for v in result["violations"]}
    assert slots == {1, 3}


def test_t6_violation_in_both_sources_reported_separately() -> None:
    """The same T6 slot violation in both mints and history is reported twice."""
    mints = [_mint("T6", 1, [WRONG], "#301")]
    events = [_event("T6", 1, [WRONG], 301)]
    result = _run(mints=mints, events=events)
    assert result["status"] == "FAIL"
    # One from trajectory_mints, one from history
    assert len(result["violations"]) == 2
    sources = {v["source"] for v in result["violations"]}
    assert sources == {"trajectory_mints", "history"}


def test_singular_agent_field_wrong_agent_fails() -> None:
    """History event using 'agent' (singular) field with wrong agent → FAIL."""
    events = [_event_singular("T6", 9, WRONG, 431)]
    result = _run(events=events)
    assert result["status"] == "FAIL"
    assert len(result["violations"]) == 1
    assert result["violations"][0]["source"] == "history"
    assert WRONG in result["violations"][0]["actual_agents"]


def test_custom_authorized_agent_configurable() -> None:
    """Custom authorized_agent parameter is respected."""
    custom = "custom-agent@platform"
    # With default authorized_agent, custom is wrong:
    mints = [_mint("T6", 1, [custom], "#100")]
    result_default = _run(mints=mints, authorized_agent=AUTHORIZED)
    assert result_default["status"] == "FAIL"

    # With custom as authorized_agent, it should PASS:
    result_custom = _run(mints=mints, authorized_agent=custom)
    assert result_custom["status"] == "PASS"
    assert result_custom["violations"] == []


# ---------------------------------------------------------------------------
# Output contract
# ---------------------------------------------------------------------------

def test_output_has_required_fields() -> None:
    """Result dict always contains status, violations, summary, authorized_agent."""
    result = _run()
    for key in ("status", "violations", "summary", "authorized_agent"):
        assert key in result, f"missing key: {key}"


def test_authorized_agent_reflected_in_output() -> None:
    """authorized_agent in the result matches the configured value."""
    custom = "another-agent@platform"
    result = _run(authorized_agent=custom)
    assert result["authorized_agent"] == custom


def test_summary_reflects_violation_count() -> None:
    """Summary string correctly reflects zero vs nonzero violations."""
    clean = _run(mints=[], events=[])
    assert "0 violation" in clean["summary"]

    dirty = _run(mints=[_mint("T6", 1, [WRONG])])
    assert "1 violation" in dirty["summary"]


def test_empty_agents_list_in_mint_fails() -> None:
    """T6 mint with agents=[] (no credit) is a violation — not silently ignored."""
    mints = [{"trajectory": "T6", "slot": 99, "amount": 20, "agents": [], "issue_or_pr": "#999"}]
    result = _run(mints=mints)
    assert result["status"] == "FAIL"
    assert len(result["violations"]) == 1
    assert result["violations"][0]["actual_agents"] == []
    assert "no agents credited" in result["violations"][0].get("detail", "")
