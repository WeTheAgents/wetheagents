from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from wea_cli import cli, genome


def _root(tmp_path: Path) -> Path:
    (tmp_path / "ledger").mkdir()
    (tmp_path / "ledger" / "balances.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / "genomes").mkdir()
    return tmp_path


def _target(agent_id: str, second: int = 0) -> genome.GenesisTarget:
    return genome.GenesisTarget(
        agent_id,
        datetime(2026, 9, 14, 10, 0, second, tzinfo=timezone.utc),
    )


def _context(*targets: genome.GenesisTarget) -> genome.CanonicalGenomeContext:
    return genome.CanonicalGenomeContext(
        commit="a" * 40,
        template="# canonical genome\n",
        targets={target.agent_id: target for target in targets},
        agent0_active=True,
    )


def _args(root: Path, targets: list[str], *, dry_run: bool = False) -> SimpleNamespace:
    return SimpleNamespace(root=str(root), targets=targets, dry_run=dry_run)


def _install_context(
    monkeypatch: pytest.MonkeyPatch,
    context: genome.CanonicalGenomeContext,
    *,
    canonical_paths: set[str] | None = None,
) -> None:
    monkeypatch.setattr(genome, "_canonical_context", lambda root: context)
    present = canonical_paths or set()
    monkeypatch.setattr(
        genome,
        "_canonical_has_path",
        lambda root, commit, path: path in present,
    )


def test_agent0_initializes_a_cohort_from_canonical_template(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _root(tmp_path)
    first = _target("New-1@claude")
    second = _target("New-2@codex", 1)
    context = _context(first, second)
    _install_context(monkeypatch, context)
    monkeypatch.setenv("WEA_AGENT", genome.AGENT0_ID)

    result = genome.init(_args(root, [first.agent_id, second.agent_id]))

    assert result == cli.EXIT_OK
    for target in (first, second):
        path = root / "genomes" / target.agent_id
        assert (
            path / "AGENTS.local.md"
        ).read_text(encoding="utf-8") == context.template
        metadata = json.loads((path / "genome_meta.json").read_text(encoding="utf-8"))
        assert metadata["agent_id"] == target.agent_id
        assert metadata["generation"] == 0
        assert metadata["parent"] is None
        assert metadata["lineage"] == []
        assert metadata["mutations"] == []
        assert metadata["fitness"]["total_earned"] == 0


def test_agent_can_dry_run_only_its_own_genome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _root(tmp_path)
    target = _target("New-1@claude")
    _install_context(monkeypatch, _context(target))
    monkeypatch.setenv("WEA_AGENT", target.agent_id)

    result = genome.init(_args(root, [], dry_run=True))

    assert result == cli.EXIT_OK
    assert target.agent_id in capsys.readouterr().out
    assert not (root / "genomes" / target.agent_id).exists()


def test_agent_cannot_initialize_another_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _root(tmp_path)
    first = _target("New-1@claude")
    second = _target("New-2@claude")
    _install_context(monkeypatch, _context(first, second))
    monkeypatch.setenv("WEA_AGENT", first.agent_id)

    result = genome.init(_args(root, [second.agent_id]))

    assert result == cli.EXIT_DOMAIN_ERROR
    assert not (root / "genomes" / second.agent_id).exists()


@pytest.mark.parametrize("location", ["canonical", "worktree"])
def test_existing_genome_rejects_the_whole_cohort(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, location: str
) -> None:
    root = _root(tmp_path)
    first = _target("New-1@claude")
    second = _target("New-2@claude")
    canonical = {f"genomes/{first.agent_id}"} if location == "canonical" else set()
    _install_context(monkeypatch, _context(first, second), canonical_paths=canonical)
    if location == "worktree":
        (root / "genomes" / first.agent_id).mkdir()
    monkeypatch.setenv("WEA_AGENT", genome.AGENT0_ID)

    result = genome.init(_args(root, [first.agent_id, second.agent_id]))

    assert result == cli.EXIT_DOMAIN_ERROR
    assert not (root / "genomes" / second.agent_id).exists()


@pytest.mark.parametrize(
    "targets",
    [["Unknown@claude"], ["New-1@claude", "New-1@claude"], ["../escape@claude"]],
)
def test_invalid_or_ineligible_target_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, targets: list[str]
) -> None:
    root = _root(tmp_path)
    eligible = _target("New-1@claude")
    _install_context(monkeypatch, _context(eligible))
    monkeypatch.setenv("WEA_AGENT", genome.AGENT0_ID)

    result = genome.init(_args(root, targets))

    assert result == cli.EXIT_DOMAIN_ERROR
    assert list((root / "genomes").iterdir()) == []


def test_canonical_context_allows_only_new_active_zero_balance_identities(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _root(tmp_path)
    admitted_at = datetime(2026, 9, 14, tzinfo=timezone.utc)
    binding = lambda agent, active=True, kind="agent": SimpleNamespace(  # noqa: E731
        subject_id=agent,
        actor_kind=kind,
        effective_from=admitted_at,
        effective_until=None if active else admitted_at,
    )
    state = {
        "participants": {
            "request": {
                "agents": [
                    {"agent_id": "New@claude", "preserve_balance": False},
                    {"agent_id": "Preserved@claude", "preserve_balance": True},
                    {"agent_id": "Paid@claude", "preserve_balance": False},
                    {"agent_id": "Inactive@claude", "preserve_balance": False},
                ]
            }
        },
        "balances": {
            "New@claude": 0,
            "Preserved@claude": 0,
            "Paid@claude": 1,
            "Inactive@claude": 0,
        },
    }
    engine = SimpleNamespace(
        state=lambda: state,
        registry=SimpleNamespace(
            bindings=[
                binding("New@claude"),
                binding("Preserved@claude"),
                binding("Paid@claude"),
                binding("Inactive@claude", active=False),
                binding(genome.AGENT0_ID, kind="agent0"),
            ]
        ),
    )
    monkeypatch.setattr(genome, "git", lambda *args: "b" * 40)
    monkeypatch.setattr(genome, "load", lambda *args: (engine, []))
    monkeypatch.setattr(genome, "_git_text", lambda *args: "# template\n")

    context = genome._canonical_context(root)

    assert set(context.targets) == {"New@claude"}
    assert context.agent0_active is True


def test_parser_exposes_genome_init_without_reset_option() -> None:
    parser = cli.build_parser()

    args = parser.parse_args(["genome", "init", "New@claude", "--dry-run"])

    assert args.targets == ["New@claude"]
    assert args.dry_run is True
    with pytest.raises(SystemExit):
        parser.parse_args(["genome", "init", "New@claude", "--force"])
