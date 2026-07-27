"""Tests for genome_snapshot.py and genome_log.py.

Minimum 5 tests as specified in task #109.
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_repo(tmp_path: Path, agent_id: str) -> Path:
    """Create a minimal fake repo structure under tmp_path."""
    root = tmp_path / f"repo_{uuid4().hex[:8]}"
    history = root / "ledger" / "history"
    history.mkdir(parents=True)
    genome_dir = root / "genomes" / agent_id
    genome_dir.mkdir(parents=True)

    _write_genome_meta(genome_dir / "genome_meta.json", agent_id)
    return root


def _write_genome_meta(path: Path, agent_id: str) -> None:
    meta = {
        "agent_id": agent_id,
        "generation": 0,
        "parent": None,
        "created_at": "2026-03-07T12:00:00Z",
        "last_snapshot": "2026-03-07T12:00:00Z",
        "fitness": {
            "tasks_completed": 0,
            "tasks_created": 0,
            "initiative_ratio": None,
            "acceptance_rate": None,
            "rework_rate": None,
            "avg_time_in_stage_hours": None,
            "zero_code_ratio": None,
            "review_quality": None,
            "composite_score": None,
            "total_earned": 0,
        },
        "lineage": [],
        "mutations": [],
    }
    path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, events: list[dict]) -> None:
    lines = [json.dumps(e) for e in events]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _load_meta(root: Path, agent_id: str) -> dict:
    return json.loads(
        (root / "genomes" / agent_id / "genome_meta.json").read_text(encoding="utf-8")
    )


# ---------------------------------------------------------------------------
# Import the modules under test
# ---------------------------------------------------------------------------

import sys
from pathlib import Path as _P

_SCRIPTS = _P(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from genome_log import log_all, render_agent_log
from genome_snapshot import compute_fitness, update_genome_fitness

# ---------------------------------------------------------------------------
# Test 1: Fitness computed correctly from mock ledger JSONL
# ---------------------------------------------------------------------------

def test_compute_fitness_from_mock_ledger(tmp_path: Path) -> None:
    """Fitness fields correctly tallied from JSONL payment and escrow events."""
    agent = "Alice-1@test"
    root = _make_repo(tmp_path, agent)
    history = root / "ledger" / "history"

    _write_jsonl(
        history / "2026-03-08.jsonl",
        [
            # Two payments for Alice
            {"type": "payment", "agent": agent, "amount": 10, "issue": 1},
            {"type": "payment", "agent": agent, "amount": 15, "issue": 2},
            # Payment for another agent — should NOT be counted
            {"type": "payment", "agent": "Bob-2@test", "amount": 5, "issue": 3},
            # Escrow authored by Alice — tasks_created
            {"type": "escrow", "author": agent, "amount": 20, "issue": 4},
            # Escrow authored by someone else — NOT counted
            {"type": "escrow", "author": "Bob-2@test", "amount": 20, "issue": 5},
        ],
    )

    fitness = compute_fitness(agent, history)

    assert fitness["tasks_completed"] == 2
    assert fitness["total_earned"] == 25  # 10 + 15
    assert fitness["tasks_created"] == 1


# ---------------------------------------------------------------------------
# Test 2: --record-mutation appends to mutations[] with correct before/after
# ---------------------------------------------------------------------------

def test_record_mutation_appends_with_before_after(tmp_path: Path) -> None:
    """record-mutation captures fitness_before (old) and fitness_after (new)."""
    agent = "Alice-1@test"
    root = _make_repo(tmp_path, agent)
    history = root / "ledger" / "history"

    # Give Alice 1 task worth 10 WEA in the ledger
    _write_jsonl(
        history / "2026-03-08.jsonl",
        [{"type": "payment", "agent": agent, "amount": 10, "issue": 1}],
    )

    meta = update_genome_fitness(
        agent,
        root,
        record_mutation=True,
        commit="abc1234",
        trigger_issue=72,
        summary="First mutation",
        now="2026-03-08T10:59:11Z",
    )

    mutations = meta["mutations"]
    assert len(mutations) == 1

    m = mutations[0]
    assert m["commit"] == "abc1234"
    assert m["trigger_issue"] == 72
    assert m["summary"] == "First mutation"
    assert m["date"] == "2026-03-08T10:59:11Z"

    # fitness_before should reflect the state BEFORE this ledger scan
    # (genome_meta.json started with tasks_completed=0, total_earned=0)
    assert m["fitness_before"] == {
        "tasks_completed": 0,
        "total_earned": 0,
        "total_minted": 0,
        "total_income": 0,
    }

    # fitness_after should reflect the newly computed fitness
    assert m["fitness_after"] == {
        "tasks_completed": 1,
        "total_earned": 10,
        "total_minted": 0,
        "total_income": 10,
    }


# ---------------------------------------------------------------------------
# Test 3: Multiple mutations append — do NOT overwrite
# ---------------------------------------------------------------------------

def test_multiple_mutations_append(tmp_path: Path) -> None:
    """Calling record-mutation twice results in two entries, not one."""
    agent = "Alice-1@test"
    root = _make_repo(tmp_path, agent)
    history = root / "ledger" / "history"

    _write_jsonl(
        history / "2026-03-08.jsonl",
        [{"type": "payment", "agent": agent, "amount": 10, "issue": 1}],
    )

    # First mutation
    update_genome_fitness(
        agent,
        root,
        record_mutation=True,
        commit="aaa1111",
        trigger_issue=72,
        summary="Mutation one",
        now="2026-03-08T10:00:00Z",
    )

    # Second mutation (ledger unchanged but we record again)
    update_genome_fitness(
        agent,
        root,
        record_mutation=True,
        commit="bbb2222",
        trigger_issue=99,
        summary="Mutation two",
        now="2026-03-08T11:00:00Z",
    )

    meta = _load_meta(root, agent)
    assert len(meta["mutations"]) == 2
    assert meta["mutations"][0]["commit"] == "aaa1111"
    assert meta["mutations"][1]["commit"] == "bbb2222"


# ---------------------------------------------------------------------------
# Test 4: genome_log renders correct deltas (0→1 tasks, 0→10 earned)
# ---------------------------------------------------------------------------

def test_genome_log_renders_correct_deltas() -> None:
    """render_agent_log shows correct before/after delta strings."""
    agent = "Claude-1@claude"
    meta = {
        "agent_id": agent,
        "mutations": [
            {
                "commit": "c30ac52",
                "date": "2026-03-08T10:59:11Z",
                "trigger_issue": 72,
                "author": "agent0@system",
                "sections_changed": ["Instructions"],
                "lines_added": 27,
                "lines_removed": 3,
                "summary": "push-origin rules, GPG workaround",
                "fitness_before": {"tasks_completed": 0, "total_earned": 0},
                "fitness_after": {"tasks_completed": 1, "total_earned": 10},
            }
        ],
    }

    output = render_agent_log(agent, meta)

    assert "Claude-1@claude" in output
    assert "1 mutation(s)" in output
    assert "#72" in output
    # Unicode arrow in deltas
    assert "0\u21921" in output   # tasks delta
    assert "0\u219210" in output  # earned delta


# ---------------------------------------------------------------------------
# Test 5: Agent with zero ledger history → all-null fitness, no crash
# ---------------------------------------------------------------------------

def test_zero_ledger_history_no_crash(tmp_path: Path) -> None:
    """Agent with no ledger events gets zero fitness without raising."""
    agent = "Ghost-0@void"
    root = _make_repo(tmp_path, agent)
    # history dir exists but is empty

    # Should not raise
    meta = update_genome_fitness(agent, root, now="2026-03-08T00:00:00Z")

    fitness = meta["fitness"]
    assert fitness["tasks_completed"] == 0
    assert fitness["total_earned"] == 0
    assert fitness["tasks_created"] == 0
    assert len(meta.get("mutations", [])) == 0


# ---------------------------------------------------------------------------
# Test 6: Malformed JSONL lines are skipped, valid lines still counted
# ---------------------------------------------------------------------------

def test_malformed_jsonl_lines_skipped(tmp_path: Path) -> None:
    """Bad JSON lines in history are ignored; valid lines count normally."""
    agent = "Alice-1@test"
    root = _make_repo(tmp_path, agent)
    history = root / "ledger" / "history"

    bad_line = r'{"type": "payment", "agent": "Alice-1@test", "amount": 5, "note": "bad \escape"}'
    good_line = json.dumps({"type": "payment", "agent": agent, "amount": 20, "issue": 9})

    (history / "2026-03-08.jsonl").write_text(
        bad_line + "\n" + good_line + "\n", encoding="utf-8"
    )

    fitness = compute_fitness(agent, history)

    # bad_line is skipped, good_line is counted
    assert fitness["tasks_completed"] == 1
    assert fitness["total_earned"] == 20


# ---------------------------------------------------------------------------
# Test 7: log_all runs without error when multiple genome dirs exist
# ---------------------------------------------------------------------------

def test_log_all_multiple_agents(tmp_path: Path) -> None:
    """log_all iterates all agents and returns 0."""
    for agent in ("Alice-1@test", "Bob-2@test"):
        d = tmp_path / "genomes" / agent
        d.mkdir(parents=True)
        _write_genome_meta(d / "genome_meta.json", agent)

    # No history dir needed — compute_fitness handles missing dir gracefully
    rc = log_all(tmp_path)
    assert rc == 0


# ---------------------------------------------------------------------------
# Test 8: update_genome_fitness raises ValueError on bad args
# ---------------------------------------------------------------------------

def test_record_mutation_requires_commit_and_issue(tmp_path: Path) -> None:
    """record_mutation=True without required args raises ValueError."""
    agent = "Alice-1@test"
    root = _make_repo(tmp_path, agent)

    with pytest.raises(ValueError, match="--commit"):
        update_genome_fitness(
            agent,
            root,
            record_mutation=True,
            commit=None,
            trigger_issue=1,
            summary="oops",
        )

    with pytest.raises(ValueError, match="--trigger-issue"):
        update_genome_fitness(
            agent,
            root,
            record_mutation=True,
            commit="abc123",
            trigger_issue=None,
            summary="oops",
        )
