"""Tests for genome_snapshot.py and genome_log.py."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from uuid import uuid4

import pytest

# Make scripts importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.genome_snapshot import compute_fitness, record_mutation, update_fitness
from scripts.genome_log import render_agent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_repo(tmp_path: Path, agent: str, mutations: list | None = None) -> Path:
    """Build a minimal fake repo under tmp_path for the given agent."""
    repo = tmp_path / f"repo_{uuid4().hex[:8]}"
    genome_dir = repo / "genomes" / agent
    genome_dir.mkdir(parents=True)
    history_dir = repo / "ledger" / "history"
    history_dir.mkdir(parents=True)

    meta = {
        "agent_id": agent,
        "generation": 0,
        "parent": None,
        "created_at": "2026-03-07T12:00:00Z",
        "last_snapshot": "2026-03-07T12:00:00Z",
        "fitness": {
            "tasks_completed": 0,
            "total_earned": 0,
            "tasks_created": 0,
            "initiative_ratio": None,
            "acceptance_rate": None,
            "rework_rate": None,
            "avg_time_in_stage_hours": None,
            "zero_code_ratio": None,
            "review_quality": None,
            "composite_score": None,
        },
        "lineage": [],
        "mutations": mutations or [],
    }
    (genome_dir / "genome_meta.json").write_text(
        json.dumps(meta, indent=2) + "\n", encoding="utf-8"
    )
    return repo


def _write_jsonl(history_dir: Path, filename: str, events: list[dict]) -> None:
    lines = [json.dumps(e) for e in events]
    (history_dir / filename).write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Test 1: Fitness computed correctly from mock ledger JSONL
# ---------------------------------------------------------------------------

def test_fitness_computed_from_mock_ledger(tmp_path):
    agent = "alice@test"
    repo = _make_repo(tmp_path, agent)
    history_dir = repo / "ledger" / "history"

    _write_jsonl(history_dir, "2026-03-08.jsonl", [
        {"type": "payment", "agent": agent, "amount": 10},
        {"type": "payment", "agent": agent, "amount": 15},
        {"type": "escrow",  "agent": agent, "amount": 20},
        {"type": "payment", "agent": "other@test", "amount": 99},  # different agent
    ])

    fitness = compute_fitness(agent, history_dir)

    assert fitness["tasks_completed"] == 2
    assert fitness["total_earned"] == 25
    assert fitness["tasks_created"] == 1
    assert fitness["acceptance_rate"] is None


# ---------------------------------------------------------------------------
# Test 2: --record-mutation appends to mutations[] with correct before/after
# ---------------------------------------------------------------------------

def test_record_mutation_appends_with_correct_deltas(tmp_path):
    agent = "bob@test"
    repo = _make_repo(tmp_path, agent)
    history_dir = repo / "ledger" / "history"

    # Ledger has 1 payment for the agent — fitness_after should reflect it
    _write_jsonl(history_dir, "2026-03-08.jsonl", [
        {"type": "payment", "agent": agent, "amount": 10},
    ])

    record_mutation(
        agent, repo,
        commit="abc1234",
        trigger_issue=72,
        summary="test mutation",
    )

    meta = json.loads((repo / "genomes" / agent / "genome_meta.json").read_text())
    assert len(meta["mutations"]) == 1

    m = meta["mutations"][0]
    assert m["commit"] == "abc1234"
    assert m["trigger_issue"] == 72
    assert m["summary"] == "test mutation"
    assert m["fitness_before"]["tasks_completed"] == 0
    assert m["fitness_before"]["total_earned"] == 0
    assert m["fitness_after"]["tasks_completed"] == 1
    assert m["fitness_after"]["total_earned"] == 10


# ---------------------------------------------------------------------------
# Test 3: Multiple mutations don't overwrite — they append
# ---------------------------------------------------------------------------

def test_multiple_mutations_append_not_overwrite(tmp_path):
    agent = "carol@test"
    repo = _make_repo(tmp_path, agent)
    history_dir = repo / "ledger" / "history"

    _write_jsonl(history_dir, "2026-03-08.jsonl", [
        {"type": "payment", "agent": agent, "amount": 5},
    ])

    record_mutation(agent, repo, commit="aaa", trigger_issue=1, summary="first change")
    record_mutation(agent, repo, commit="bbb", trigger_issue=2, summary="second change")

    meta = json.loads((repo / "genomes" / agent / "genome_meta.json").read_text())
    assert len(meta["mutations"]) == 2
    assert meta["mutations"][0]["summary"] == "first change"
    assert meta["mutations"][1]["summary"] == "second change"


# ---------------------------------------------------------------------------
# Test 4: genome_log renders correct deltas
# ---------------------------------------------------------------------------

def test_genome_log_renders_correct_deltas(tmp_path, capsys):
    agent = "delta@test"
    existing_mutation = {
        "commit": "c30ac52",
        "date": "2026-03-08T10:59:11Z",
        "trigger_issue": 72,
        "author": "agent0@system",
        "sections_changed": [],
        "lines_added": 27,
        "lines_removed": 3,
        "summary": "push-origin rules, GPG workaround",
        "fitness_before": {"tasks_completed": 0, "total_earned": 0},
        "fitness_after":  {"tasks_completed": 1, "total_earned": 10},
    }
    repo = _make_repo(tmp_path, agent, mutations=[existing_mutation])

    render_agent(agent, repo)
    captured = capsys.readouterr().out

    assert "1 mutation(s)" in captured
    assert "#72" in captured
    assert "push-origin rules, GPG workaround" in captured
    assert "0→1" in captured
    assert "0→10" in captured


# ---------------------------------------------------------------------------
# Test 5: Agent with zero ledger history → all-null fitness, no crash
# ---------------------------------------------------------------------------

def test_zero_ledger_history_all_null_no_crash(tmp_path):
    agent = "ghost@test"
    repo = _make_repo(tmp_path, agent)
    # history_dir exists but has no files

    fitness = compute_fitness(agent, repo / "ledger" / "history")

    assert fitness["tasks_completed"] == 0
    assert fitness["total_earned"] == 0
    assert fitness["tasks_created"] == 0
    assert fitness["acceptance_rate"] is None
    assert fitness["zero_code_ratio"] is None

    # update_fitness should also not crash
    updated_meta = update_fitness(agent, repo)
    assert updated_meta["fitness"]["tasks_completed"] == 0
