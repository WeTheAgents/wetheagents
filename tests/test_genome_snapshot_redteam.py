"""Adversarial tests for scripts/genome_snapshot.py.

These cases stress malformed inputs, missing files, and hostile paths while
keeping the suite hermetic via tmp_path-based fake repos.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from uuid import uuid4

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import genome_snapshot as snapshot


@pytest.fixture
def tmp_path() -> Path:
    root = Path(".test_runs") / f"genome_snapshot_redteam_{uuid4().hex}"
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)
    yield root
    shutil.rmtree(root, ignore_errors=True)


def _make_repo(
    tmp_path: Path,
    agent_id: str = "Red-1@test",
    *,
    with_meta: bool = True,
    meta_override: dict | None = None,
) -> Path:
    root = tmp_path / "repo"
    (root / "ledger" / "history").mkdir(parents=True)
    genome_dir = root / "genomes" / agent_id
    genome_dir.mkdir(parents=True)
    if with_meta:
        meta = {
            "agent_id": agent_id,
            "generation": 0,
            "parent": None,
            "created_at": "2026-03-07T12:00:00Z",
            "last_snapshot": "2026-03-07T12:00:00Z",
            "fitness": {
                "tasks_completed": 0,
                "tasks_created": 0,
                "total_earned": 0,
                "total_minted": 0,
                "gauntlet_slots": 0,
                "total_income": 0,
            },
            "mutations": [],
        }
        if meta_override is not None:
            meta.update(meta_override)
        (genome_dir / "genome_meta.json").write_text(
            json.dumps(meta, indent=2) + "\n",
            encoding="utf-8",
        )
    return root


def _write_history(root: Path, filename: str, events: list[dict]) -> None:
    path = root / "ledger" / "history" / filename
    path.write_text(
        "\n".join(json.dumps(event) for event in events) + "\n",
        encoding="utf-8",
    )


def _load_meta(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_adv01_missing_balances_json_does_not_block_snapshot(tmp_path: Path) -> None:
    """PASS: balances.json is not required by the current snapshot script."""
    agent = "Red-1@test"
    root = _make_repo(tmp_path, agent)
    _write_history(
        root,
        "2026-04-12.jsonl",
        [{"type": "payment", "agent": agent, "amount": 7, "issue": 1}],
    )

    meta = snapshot.update_genome_fitness(agent, root, now="2026-04-12T00:00:00Z")

    assert meta["fitness"]["tasks_completed"] == 1
    assert meta["fitness"]["total_earned"] == 7


def test_adv02_agent_absent_from_balances_still_uses_history(tmp_path: Path) -> None:
    """PASS: unknown balances identity does not affect ledger-history fitness."""
    agent = "Ghost-7@test"
    root = _make_repo(tmp_path, agent)
    (root / "ledger" / "balances.json").write_text(
        json.dumps({"agents": {"Other-1@test": {"balance": 99}}}),
        encoding="utf-8",
    )
    _write_history(
        root,
        "2026-04-12.jsonl",
        [{"type": "payment", "agent": agent, "amount": 11, "issue": 2}],
    )

    meta = snapshot.update_genome_fitness(agent, root, now="2026-04-12T00:00:00Z")

    assert meta["fitness"]["tasks_completed"] == 1
    assert meta["fitness"]["total_earned"] == 11


def test_adv03_invalid_genome_meta_json_raises_decode_error(tmp_path: Path) -> None:
    """FAIL: malformed genome_meta.json should surface a parse error."""
    agent = "Broken-1@test"
    root = _make_repo(tmp_path, agent, with_meta=False)
    genome_path = root / "genomes" / agent / "genome_meta.json"
    genome_path.write_text("{not valid json", encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
        snapshot.update_genome_fitness(agent, root)


def test_adv04_missing_genome_meta_json_raises(tmp_path: Path) -> None:
    """FAIL: missing genome metadata must not be silently created."""
    agent = "Missing-1@test"
    root = _make_repo(tmp_path, agent, with_meta=False)

    with pytest.raises(FileNotFoundError, match="genome_meta.json not found"):
        snapshot.update_genome_fitness(agent, root)


def test_adv05_missing_root_path_exits_nonzero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """FAIL: CLI returns exit 1 when --root points at a missing repo."""
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "genome_snapshot.py",
            "--agent",
            "Nope-1@test",
            "--root",
            str(tmp_path / "does-not-exist"),
        ],
    )

    with pytest.raises(SystemExit) as excinfo:
        snapshot.main()

    captured = capsys.readouterr()
    assert excinfo.value.code == 1
    assert "genome_meta.json not found" in captured.err


def test_adv06_negative_payment_produces_negative_total_earned(tmp_path: Path) -> None:
    """PASS: hostile negative payment amounts currently flow into fitness as-is."""
    agent = "Debt-1@test"
    root = _make_repo(tmp_path, agent)
    _write_history(
        root,
        "2026-04-12.jsonl",
        [{"type": "payment", "agent": agent, "amount": -9, "issue": 3}],
    )

    meta = snapshot.update_genome_fitness(agent, root, now="2026-04-12T00:00:00Z")

    assert meta["fitness"]["tasks_completed"] == 1
    assert meta["fitness"]["total_earned"] == -9
    assert meta["fitness"]["total_income"] == -9


def test_adv07_gap_non_dict_fitness_block_crashes(tmp_path: Path) -> None:
    """GAP: a list-valued fitness block crashes before the script can repair it."""
    agent = "Weird-1@test"
    root = _make_repo(tmp_path, agent, meta_override={"fitness": ["bad", "shape"]})
    _write_history(
        root,
        "2026-04-12.jsonl",
        [{"type": "escrow", "author": agent, "amount": 4, "issue": 4}],
    )

    with pytest.raises(AttributeError, match="'list' object has no attribute 'get'"):
        snapshot.update_genome_fitness(agent, root, now="2026-04-12T00:00:00Z")


def test_adv08_invalid_trajectory_mints_json_is_ignored(tmp_path: Path) -> None:
    """PASS: malformed trajectory_mints.json falls back to zero minted income."""
    agent = "Mint-1@test"
    root = _make_repo(tmp_path, agent)
    (root / "ledger" / "trajectory_mints.json").write_text(
        "{invalid json",
        encoding="utf-8",
    )

    meta = snapshot.update_genome_fitness(agent, root, now="2026-04-12T00:00:00Z")

    assert meta["fitness"]["total_minted"] == 0
    assert meta["fitness"]["gauntlet_slots"] == 0


def test_adv09_non_writable_genome_meta_bubbles_permission_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAIL: simulate a non-writable destination during the atomic rename."""
    agent = "Locked-1@test"
    root = _make_repo(tmp_path, agent)
    genome_path = root / "genomes" / agent / "genome_meta.json"
    original = genome_path.read_text(encoding="utf-8")

    def deny_replace(src: str, dst: Path) -> None:
        raise PermissionError("destination is not writable")

    monkeypatch.setattr(snapshot.os, "replace", deny_replace)

    with pytest.raises(PermissionError, match="not writable"):
        snapshot.update_genome_fitness(agent, root, now="2026-04-12T00:00:00Z")

    assert genome_path.read_text(encoding="utf-8") == original


def test_adv10_missing_balances_json_with_record_mutation_still_records(
    tmp_path: Path,
) -> None:
    """PASS: mutation recording does not depend on balances.json either."""
    agent = "Mut-1@test"
    root = _make_repo(tmp_path, agent)

    meta = snapshot.update_genome_fitness(
        agent,
        root,
        record_mutation=True,
        commit="deadbeef",
        trigger_issue=435,
        summary="adversarial snapshot",
        now="2026-04-12T00:00:00Z",
    )

    assert len(meta["mutations"]) == 1
    assert meta["mutations"][0]["commit"] == "deadbeef"


def test_adv11_missing_provenance_file_exits_nonzero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """FAIL: CLI should stop before mutation update when provenance file is absent."""
    agent = "Prov-1@test"
    root = _make_repo(tmp_path, agent)
    missing_prov = tmp_path / "missing-provenance.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "genome_snapshot.py",
            "--agent",
            agent,
            "--root",
            str(root),
            "--provenance-json",
            str(missing_prov),
        ],
    )

    with pytest.raises(SystemExit) as excinfo:
        snapshot.main()

    captured = capsys.readouterr()
    assert excinfo.value.code == 1
    assert "provenance file not found" in captured.err


def test_adv12_gap_agent_id_path_traversal_escapes_genomes_dir(tmp_path: Path) -> None:
    """GAP: '../outside' resolves to root/outside/genome_meta.json."""
    root = tmp_path / "repo"
    (root / "ledger" / "history").mkdir(parents=True)
    outside = root / "outside"
    outside.mkdir(parents=True)
    (outside / "genome_meta.json").write_text(
        json.dumps(
            {
                "agent_id": "Victim-1@test",
                "fitness": {"tasks_completed": 0, "total_earned": 0},
                "mutations": [],
            }
        ),
        encoding="utf-8",
    )
    _write_history(
        root,
        "2026-04-12.jsonl",
        [{"type": "payment", "agent": "Victim-1@test", "amount": 13, "issue": 5}],
    )

    meta = snapshot.update_genome_fitness("../outside", root, now="2026-04-12T00:00:00Z")

    assert meta["fitness"]["total_earned"] == 13
    assert _load_meta(outside / "genome_meta.json")["fitness"]["total_earned"] == 13
