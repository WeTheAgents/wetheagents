from __future__ import annotations

import io
import json
import shutil
import sys
import uuid
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import audit_entropy  # noqa: E402


@pytest.fixture
def repo_tmp_path() -> Path:
    base_root = Path(r"C:\Users\peach\AppData\Local\Temp\audit-entropy-fixed")
    base_root.mkdir(parents=True, exist_ok=True)
    base = base_root / f"case-{uuid.uuid4().hex}"
    path = base / "wetheagents"
    (path / "ledger").mkdir(parents=True, exist_ok=True)
    (path / "genomes" / "base").mkdir(parents=True, exist_ok=True)
    try:
        yield path
    finally:
        shutil.rmtree(base, ignore_errors=True)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _setup_repo(tmp_path: Path, agents: dict[str, object], genome_dirs: dict[str, dict[str, str]]) -> Path:
    root = tmp_path
    _write_json(root / "ledger" / "balances.json", {"agents": agents})

    genomes = root / "genomes"
    (genomes / "base").mkdir(parents=True, exist_ok=True)
    for dirname, files in genome_dirs.items():
        genome_dir = genomes / dirname
        genome_dir.mkdir(parents=True, exist_ok=True)
        for name, content in files.items():
            (genome_dir / name).write_text(content, encoding="utf-8")

    return root


def _finding_kinds(findings: list[dict[str, str]]) -> set[str]:
    return {finding["kind"] for finding in findings}


def test_audit_genomes_reports_stale_dirs_and_missing_registered_agents(repo_tmp_path: Path) -> None:
    root = _setup_repo(
        repo_tmp_path,
        agents={
            "agent0@system": {},
            "Codex-2@codex": {},
            "Claude-18@claude": {},
        },
        genome_dirs={
            "Codex-2@codex": {
                "genome_meta.json": json.dumps({"agent_id": "Codex-2@codex"}),
            },
            "code-stylist": {
                "AGENTS.local.md": "stale alias\n",
            },
        },
    )

    findings = audit_entropy.audit_genomes(root)

    assert _finding_kinds(findings) == {"stale_genome_dir", "missing_genome_dir"}
    assert any(f["subject"] == "genomes/code-stylist" for f in findings)
    assert any(f["subject"] == "Claude-18@claude" for f in findings)


def test_audit_genomes_reports_mismatches_duplicates_and_unregistered_agents(repo_tmp_path: Path) -> None:
    root = _setup_repo(
        repo_tmp_path,
        agents={
            "Codex-2@codex": {},
        },
        genome_dirs={
            "Codex-2@codex": {
                "genome_meta.json": json.dumps({"agent_id": "Codex-2@codex"}),
            },
            "codex-2": {
                "genome_meta.json": json.dumps({"agent_id": "Codex-2@codex"}),
            },
            "ghost@void": {
                "genome_meta.json": json.dumps({"agent_id": "ghost@void"}),
            },
        },
    )

    findings = audit_entropy.audit_genomes(root)
    kinds = _finding_kinds(findings)

    assert "genome_dir_agent_id_mismatch" in kinds
    assert "duplicate_genome_agent" in kinds
    assert "unregistered_genome_agent" in kinds
    assert not any(f["kind"] == "missing_genome_dir" for f in findings)


def test_audit_worktrees_reports_detached_missing_and_unregistered_dirs(repo_tmp_path: Path) -> None:
    root = _setup_repo(
        repo_tmp_path,
        agents={"Codex-2@codex": {}},
        genome_dirs={"Codex-2@codex": {"genome_meta.json": json.dumps({"agent_id": "Codex-2@codex"})}},
    )

    sibling_root = root.parent

    registered = sibling_root / "wetheagents-codex-2"
    registered.mkdir()
    (registered / ".git").write_text("gitdir: ...\n", encoding="utf-8")

    detached = root / ".codex_tmp" / "pr155-review"
    detached.mkdir(parents=True)

    unregistered = sibling_root / "wetheagents-codex-1"
    unregistered.mkdir()
    (unregistered / ".git").write_text("gitdir: ...\n", encoding="utf-8")

    missing = sibling_root / "wetheagents-pr178-review"

    porcelain = "\n".join(
        [
            f"worktree {root}",
            "HEAD deadbeef",
            "branch refs/heads/main",
            "",
            f"worktree {registered}",
            "HEAD cafebabe",
            "branch refs/heads/agent/codex-2/323-entropy-audit",
            "",
            f"worktree {detached}",
            "HEAD 12345678",
            "",
            f"worktree {missing}",
            "HEAD abcdef12",
            "branch refs/heads/pr-178-latest",
            "",
        ]
    )

    findings = audit_entropy.audit_worktrees(root, porcelain=porcelain)
    kinds = _finding_kinds(findings)

    assert "detached_worktree" in kinds
    assert "missing_registered_worktree" in kinds
    assert "unregistered_worktree_dir" in kinds
    assert any(f["subject"].endswith("wetheagents-codex-1") for f in findings)


def test_main_json_output_returns_nonzero_when_findings_exist(repo_tmp_path: Path, monkeypatch) -> None:
    root = _setup_repo(
        repo_tmp_path,
        agents={
            "Codex-2@codex": {},
            "Claude-18@claude": {},
        },
        genome_dirs={
            "Codex-2@codex": {
                "genome_meta.json": json.dumps({"agent_id": "Codex-2@codex"}),
            },
        },
    )

    monkeypatch.setattr(sys, "argv", ["audit_entropy.py", "--root", str(root), "--json"])
    monkeypatch.setattr(
        audit_entropy,
        "audit_worktrees",
        lambda repo_root, porcelain=None: [
            {
                "kind": "detached_worktree",
                "subject": "D:/GitHub/wetheagents/.codex_tmp/pr155-review",
                "detail": "worktree is registered with detached HEAD",
            }
        ],
    )

    stdout = io.StringIO()
    monkeypatch.setattr(sys, "stdout", stdout)

    code = audit_entropy.main()

    payload = json.loads(stdout.getvalue())
    assert code == 1
    assert payload["counts"]["total_findings"] == 2
    assert payload["counts"]["genome_findings"] == 1
    assert payload["counts"]["worktree_findings"] == 1
