from __future__ import annotations

import json
import subprocess
from copy import deepcopy
from pathlib import Path

import pytest

from wea_vnext.block9.common import Block9Error, canonical_bytes, sha256_hex
from wea_vnext.block9.github_native import (
    COMMAND_MARKER,
    _api_getter,
    _candidate_record_path,
    _validate_vnext_tree,
    build_candidate,
    parse_command_comment,
    validate_candidate_commits,
    validate_pull_request_commits,
)


def _git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _commit(root: Path, message: str) -> str:
    _git(root, "add", "-A")
    _git(root, "commit", "-m", message)
    return _git(root, "rev-parse", "HEAD")


def _amend(root: Path) -> str:
    _git(root, "add", "-A")
    _git(root, "commit", "--amend", "--no-edit")
    return _git(root, "rev-parse", "HEAD")


def _event(
    *,
    idempotency_key: str,
    financial_hash: str,
    genesis_hash: str,
) -> bytes:
    payload = {
        "event_type": "epoch_started",
        "financial_postings": [],
        "genesis_sha256": genesis_hash,
        "idempotency_key": idempotency_key,
        "operation": "activate",
        "prior_financial_hash": "0" * 64,
        "resulting_financial_hash": financial_hash,
    }
    core = {
        "payload": payload,
        "previous_event_hash": "0" * 64,
        "sequence": 0,
    }
    return canonical_bytes({**core, "event_hash": sha256_hex(canonical_bytes(core))})


def _activation_files(predecessor: str, idempotency_key: str) -> dict[str, bytes]:
    genesis = canonical_bytes(
        {
            "achievement_history": [],
            "balances": {"agent0@system": 10, "worker@example": 0},
            "gauntlet_history": [],
            "genomes": {"agent0@system": {"sha256": "1" * 64}},
            "hello_world_keys": [],
            "historical": {"achievements": [], "gauntlet": []},
            "history_refs": ["ledger/history/example.jsonl"],
            "identities": {
                "agent0@system": {"github_username": "owner"},
                "worker@example": {"github_username": "worker"},
            },
            "input_hash": "2" * 64,
            "opening_supply": 10,
            "predecessor": predecessor,
            "reconciliation_hash": "3" * 64,
            "schema": "wea-vnext-genesis-1",
            "source_hashes": {"ledger": "4" * 64},
            "conversion_intents": [],
        }
    )
    # Use the accepted genesis validator's exact field set.
    genesis_value = json.loads(genesis)
    genesis_value.pop("achievement_history")
    genesis_value.pop("gauntlet_history")
    genesis = canonical_bytes(genesis_value)
    financial = {
        "active_escrows": {},
        "balances": {"agent0@system": 10, "worker@example": 0},
        "opening_supply": 10,
    }
    financial_hash = sha256_hex(canonical_bytes(financial))
    event = _event(
        idempotency_key=idempotency_key,
        financial_hash=financial_hash,
        genesis_hash=sha256_hex(genesis),
    )
    event_hash = json.loads(event)["event_hash"]
    state = canonical_bytes(
        {
            **financial,
            "epoch_id": "wea-vnext-1",
            "genesis_sha256": sha256_hex(genesis),
            "last_event_hash": event_hash,
            "runtime": {
                "executor_manifest_hash": "5" * 64,
                "ruleset_hash": "6" * 64,
                "tide_interface_version": "0.8",
            },
            "schema": "wea-vnext-github-state-1",
            "sequence": 0,
        }
    )
    return {
        "ledger/vnext/bootstrap.json": canonical_bytes(
            {
                "epoch_id": "wea-vnext-1",
                "predecessor": predecessor,
                "repository_id": "1171421025",
                "schema": "wea-vnext-github-bootstrap-1",
                "target_ref": "refs/heads/main",
                "workflow_path": ".github/workflows/agent0-ledger-candidate.yml",
                "writer_agent_id": "agent0@system",
            }
        ),
        "ledger/vnext/events/0000000000000000.json": event,
        "ledger/vnext/genesis.json": genesis,
        "ledger/vnext/idempotency.json": canonical_bytes(
            {
                "keys": {idempotency_key: event_hash},
                "schema": "wea-vnext-idempotency-1",
            }
        ),
        "ledger/vnext/state.json": state,
    }


def _repo(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.name", "test")
    _git(root, "config", "user.email", "test@example.com")
    (root / "README.md").write_text("base\n", encoding="utf-8")
    predecessor = _commit(root, "base")
    return root, predecessor


def _install_pinned_boundary(root: Path) -> None:
    pinned = {
        ".github/workflows/access.yml": b"permissions:\n  contents: write\n",
        ".github/workflows/tide.yml": (b"permissions:\n  contents: write\n"),
        ".github/workflows/guard-vnext-ledger.yml": (
            b"permissions:\n  contents: read\n"
        ),
        "pyproject.toml": b"[project]\nname='fixture'\n",
        "src/wea_vnext/block9/common.py": b"# common\n",
        "src/wea_vnext/block9/github_native.py": b"# guard\n",
        "src/wea_vnext/block9/migration.py": b"# migration\n",
        "src/wea_vnext/block9/writer.py": b"# writer boundary\n",
        "src/wea_vnext/executors/v0_8_0/canonical.py": b"# canonical\n",
    }
    for relative in (
        "src/wea_vnext/__init__.py",
        "src/wea_vnext/block9/__init__.py",
        "src/wea_vnext/engine.py",
        "src/wea_vnext/domain_access.py",
        "src/wea_vnext/access_control.py",
        "src/wea_vnext/access_protocol.py",
        "src/wea_vnext/initiatives.py",
        "src/wea_vnext/access_github.py",
        "src/wea_cli/access.py",
        *(
            f"src/wea_vnext/tide/{name}.py"
            for name in (
                "__main__",
                "__init__",
                "activation",
                "collection",
                "github",
                "ledger",
                "records",
                "replay",
            )
        ),
    ):
        pinned[relative] = b"# trusted boundary fixture\n"
    for relative, content in pinned.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)


def _package(
    root: Path,
    predecessor: str,
    *,
    idempotency_key: str = "activate-private-pilot",
) -> tuple[str, bytes, bytes]:
    files = _activation_files(predecessor, idempotency_key)
    package_dir = root / "evidence" / "vnext" / "packages" / "activation-1"
    payload_dir = package_dir / "payload"
    payload_dir.mkdir(parents=True)
    rows = []
    for index, (target, content) in enumerate(sorted(files.items())):
        source = f"payload/{index:02d}.json"
        (package_dir / source).write_bytes(content)
        rows.append(
            {
                "before_sha256": None,
                "sha256": sha256_hex(content),
                "source": source,
                "target": target,
            }
        )
    state = files["ledger/vnext/state.json"]
    event = files["ledger/vnext/events/0000000000000000.json"]
    manifest = canonical_bytes(
        {
            "checks": {
                "event_hash": json.loads(event)["event_hash"],
                "genesis_sha256": sha256_hex(files["ledger/vnext/genesis.json"]),
                "opening_supply": 10,
                "state_sha256": sha256_hex(state),
            },
            "epoch_id": "wea-vnext-1",
            "expected_predecessor": predecessor,
            "files": rows,
            "idempotency_key": idempotency_key,
            "operation": "activate",
            "package_id": "activation-1",
            "previous_event_hash": "0" * 64,
            "repository_id": "1171421025",
            "schema": "wea-vnext-package-1",
            "sequence": 0,
            "target_ref": "refs/heads/main",
        }
    )
    manifest_path = package_dir / "package.json"
    manifest_path.write_bytes(manifest)
    package_commit = _commit(root, "package")
    command = canonical_bytes(
        {
            "expected_predecessor": predecessor,
            "idempotency_key": idempotency_key,
            "operation": "activate",
            "package_commit": package_commit,
            "package_manifest_path": manifest_path.relative_to(root).as_posix(),
            "package_manifest_sha256": sha256_hex(manifest),
            "package_ref": "package/activation-1",
            "repository_id": "1171421025",
            "schema": "wea-vnext-command-1",
            "target_ref": "refs/heads/main",
            "writer_agent_id": "agent0@system",
        }
    )
    return package_commit, manifest, command


def _source(command: bytes) -> dict[str, object]:
    body = COMMAND_MARKER + command.decode("utf-8")
    return {
        "author_association": "MEMBER",
        "body_sha256": sha256_hex(body.encode()),
        "command_sha256": sha256_hex(command),
        "comment_author": "peachgabba22",
        "comment_id": 41,
        "comment_url": "https://github.com/WeTheAgents/wetheagents/issues/9#issuecomment-41",
        "issue_number": 9,
        "repository": "WeTheAgents/wetheagents",
    }


def _workflow(predecessor: str) -> dict[str, object]:
    return {
        "actor": "peachgabba22",
        "run_attempt": 1,
        "run_id": 9001,
        "workflow_path": ".github/workflows/agent0-ledger-candidate.yml",
        "workflow_ref": (
            "WeTheAgents/wetheagents/.github/workflows/"
            "agent0-ledger-candidate.yml@refs/heads/main"
        ),
        "workflow_sha": predecessor,
    }


def _build(tmp_path: Path) -> tuple[Path, str, str, bytes]:
    root, predecessor = _repo(tmp_path)
    _package_commit, _manifest, command = _package(root, predecessor)
    _git(root, "checkout", "--detach", predecessor)
    build_candidate(
        root,
        command=command,
        source_evidence=_source(command),
        workflow_evidence=_workflow(predecessor),
    )
    candidate = _commit(root, "candidate")
    return root, predecessor, candidate, command


def test_command_comment_is_exact_and_canonical(tmp_path: Path) -> None:
    root, predecessor = _repo(tmp_path)
    _package_commit, _manifest, command = _package(root, predecessor)
    body = COMMAND_MARKER + command.decode("utf-8")
    assert parse_command_comment(body) == command
    with pytest.raises(Block9Error, match="marker"):
        parse_command_comment("intro\n" + body)
    with pytest.raises(Block9Error, match="canonical"):
        parse_command_comment(COMMAND_MARKER + json.dumps(json.loads(command)))


def test_github_api_reader_rejects_noncanonical_network_targets() -> None:
    with pytest.raises(Block9Error, match="origin"):
        _api_getter("token", "https://example.com")
    getter = _api_getter("token", "https://api.github.com")
    with pytest.raises(Block9Error, match="path"):
        getter("/user")


def test_github_api_reader_identifies_itself(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        status = 200

        @staticmethod
        def read() -> bytes:
            return b"{}"

    class FakeConnection:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def request(
            self,
            method: str,
            path: str,
            *,
            headers: dict[str, str],
        ) -> None:
            captured.update(method=method, path=path, headers=headers)

        @staticmethod
        def getresponse() -> FakeResponse:
            return FakeResponse()

        @staticmethod
        def close() -> None:
            pass

    monkeypatch.setattr(
        "wea_vnext.block9.github_native.http.client.HTTPSConnection",
        FakeConnection,
    )

    getter = _api_getter("token", "https://api.github.com")
    getter("/repos/WeTheAgents/wetheagents/issues/comments/5437221699")

    headers = captured["headers"]
    assert isinstance(headers, dict)
    assert headers["User-Agent"] == "WeTheAgents-Agent0-vNext/1.0"


def test_guard_selects_only_the_new_candidate_record(tmp_path: Path) -> None:
    root, _predecessor = _repo(tmp_path)
    old = root / "evidence/vnext/github-transactions/old/candidate.json"
    old.parent.mkdir(parents=True)
    old.write_text("{}\n", encoding="utf-8")
    base = _commit(root, "old candidate evidence")
    new = root / "evidence/vnext/github-transactions/new/candidate.json"
    new.parent.mkdir(parents=True)
    new.write_text("{}\n", encoding="utf-8")
    candidate = _commit(root, "new candidate evidence")

    assert (
        _candidate_record_path(root, base, candidate)
        == new.relative_to(root).as_posix()
    )


def test_candidate_rebuilds_exact_package_and_passes_guard(tmp_path: Path) -> None:
    root, predecessor, candidate, _command = _build(tmp_path)
    record = validate_candidate_commits(
        root,
        base_commit=predecessor,
        candidate_commit=candidate,
    )
    assert record["writer_agent_id"] == "agent0@system"
    assert record["expected_predecessor"] == predecessor
    assert record["operation"] == "activate"


def test_guard_rejects_stale_predecessor(tmp_path: Path) -> None:
    root, predecessor, candidate, _command = _build(tmp_path)
    (root / "README.md").write_text("advanced\n", encoding="utf-8")
    advanced = _commit(root, "advanced")
    with pytest.raises(Block9Error, match="predecessor"):
        validate_candidate_commits(
            root,
            base_commit=advanced,
            candidate_commit=candidate,
        )
    assert advanced != predecessor


def test_guard_rejects_an_extra_commit_after_the_candidate(tmp_path: Path) -> None:
    root, predecessor, _candidate, _command = _build(tmp_path)
    _git(root, "commit", "--allow-empty", "-m", "extra")
    extra = _git(root, "rev-parse", "HEAD")

    with pytest.raises(Block9Error, match="direct child"):
        validate_candidate_commits(
            root,
            base_commit=predecessor,
            candidate_commit=extra,
        )


def test_guard_rejects_changed_command_evidence(tmp_path: Path) -> None:
    root, predecessor, candidate, _command = _build(tmp_path)
    record_path = next(
        path
        for path in _git(root, "ls-tree", "-r", "--name-only", candidate).splitlines()
        if path.endswith("/candidate.json")
    )
    command_path = record_path.removesuffix("candidate.json") + "command.json"
    _git(root, "checkout", "--detach", candidate)
    value = json.loads((root / command_path).read_bytes())
    value["idempotency_key"] = "different-key"
    (root / command_path).write_bytes(canonical_bytes(value))
    changed = _amend(root)
    with pytest.raises(Block9Error, match="command"):
        validate_candidate_commits(
            root,
            base_commit=predecessor,
            candidate_commit=changed,
        )


def test_guard_rejects_non_next_sequence(tmp_path: Path) -> None:
    root, predecessor, candidate, _command = _build(tmp_path)
    _git(root, "checkout", "--detach", candidate)
    event = root / "ledger" / "vnext" / "events" / "0000000000000000.json"
    value = json.loads(event.read_bytes())
    value["sequence"] = 2
    event.write_bytes(canonical_bytes(value))
    changed = _amend(root)
    with pytest.raises(Block9Error, match=r"sequence|package"):
        validate_candidate_commits(
            root,
            base_commit=predecessor,
            candidate_commit=changed,
        )


def test_guard_rejects_supply_drift(tmp_path: Path) -> None:
    root, predecessor, candidate, _command = _build(tmp_path)
    _git(root, "checkout", "--detach", candidate)
    state = root / "ledger" / "vnext" / "state.json"
    value = json.loads(state.read_bytes())
    value["balances"]["agent0@system"] = 11
    state.write_bytes(canonical_bytes(value))
    changed = _amend(root)
    with pytest.raises(Block9Error, match=r"package|supply|state"):
        validate_candidate_commits(
            root,
            base_commit=predecessor,
            candidate_commit=changed,
        )


def test_guard_rejects_code_change_mixed_with_ledger(tmp_path: Path) -> None:
    root, predecessor, candidate, _command = _build(tmp_path)
    _git(root, "checkout", "--detach", candidate)
    source = root / "scripts" / "evil.py"
    source.parent.mkdir()
    source.write_text("raise RuntimeError('must never run')\n", encoding="utf-8")
    changed = _amend(root)
    with pytest.raises(Block9Error, match="path set"):
        validate_candidate_commits(
            root,
            base_commit=predecessor,
            candidate_commit=changed,
        )


def test_guard_reads_candidate_code_as_data_and_never_executes_it(
    tmp_path: Path,
) -> None:
    root, predecessor, candidate, _command = _build(tmp_path)
    _git(root, "checkout", "--detach", candidate)
    sentinel = tmp_path / "executed"
    source = root / "scripts" / "candidate.py"
    source.parent.mkdir()
    source.write_text(
        f"from pathlib import Path\nPath({str(sentinel)!r}).write_text('bad')\n",
        encoding="utf-8",
    )
    changed = _amend(root)
    with pytest.raises(Block9Error):
        validate_candidate_commits(
            root,
            base_commit=predecessor,
            candidate_commit=changed,
        )
    assert not sentinel.exists()


def test_ordinary_pr_rejects_a_new_javascript_ledger_writer(
    tmp_path: Path,
) -> None:
    root, _initial = _repo(tmp_path)
    _install_pinned_boundary(root)
    base = _commit(root, "trusted boundary")
    writer = root / "src" / "hidden_writer.js"
    writer.write_text(
        'fs.writeFileSync("ledger/state.json", payload);\n',
        encoding="utf-8",
    )
    candidate = _commit(root, "hidden JavaScript writer")

    with pytest.raises(Block9Error, match="writer universe"):
        validate_pull_request_commits(
            root,
            base_commit=base,
            candidate_commit=candidate,
        )


@pytest.mark.parametrize(
    "path",
    [
        "src/wea_vnext/executors/v0_9_0/lifecycle.py",
        "src/wea_vnext/executors/v0_9_0/manifest.json",
        "src/wea_vnext/rulesets/0.9.json",
        "src/wea_vnext/tide/__init__.py",
        "src/wea_vnext/initiatives.py",
        "src/wea_vnext/__init__.py",
    ],
)
def test_ordinary_pr_cannot_rewrite_existing_runtime_authority(
    tmp_path: Path, path: str
) -> None:
    root, _initial = _repo(tmp_path)
    _install_pinned_boundary(root)
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("{}\n" if path.endswith(".json") else "VALUE = 1\n")
    base = _commit(root, "trusted runtime")
    target.write_text('{"changed":true}\n' if path.endswith(".json") else "VALUE = 2\n")
    candidate = _commit(root, "changed runtime authority")
    with pytest.raises(Block9Error, match="writer boundary changed"):
        validate_pull_request_commits(
            root, base_commit=base, candidate_commit=candidate
        )


def test_ordinary_pr_allows_an_unrelated_source_change(tmp_path: Path) -> None:
    root, _initial = _repo(tmp_path)
    _install_pinned_boundary(root)
    utility = root / "src" / "unrelated.py"
    utility.write_text("VALUE = 1\n", encoding="utf-8")
    base = _commit(root, "trusted boundary")
    utility.write_text("VALUE = 2\n", encoding="utf-8")
    candidate = _commit(root, "ordinary source change")

    assert (
        validate_pull_request_commits(
            root,
            base_commit=base,
            candidate_commit=candidate,
        )
        is None
    )


def test_ordinary_pr_allows_a_harmless_file_deletion(tmp_path: Path) -> None:
    root, _initial = _repo(tmp_path)
    _install_pinned_boundary(root)
    note = root / "docs" / "obsolete.md"
    note.parent.mkdir()
    note.write_text("obsolete\n", encoding="utf-8")
    base = _commit(root, "trusted boundary with note")
    note.unlink()
    candidate = _commit(root, "remove obsolete note")

    assert (
        validate_pull_request_commits(
            root,
            base_commit=base,
            candidate_commit=candidate,
        )
        is None
    )


def test_ordinary_pr_allows_legacy_writer_retirement(tmp_path: Path) -> None:
    root, _initial = _repo(tmp_path)
    _install_pinned_boundary(root)
    writer = root / "scripts" / "legacy_writer.py"
    writer.parent.mkdir()
    writer.write_text(
        "from pathlib import Path\nPath('ledger/state.json').write_text('old')\n",
        encoding="utf-8",
    )
    base = _commit(root, "trusted boundary with legacy writer")
    writer.unlink()
    candidate = _commit(root, "retire legacy writer")

    assert (
        validate_pull_request_commits(
            root,
            base_commit=base,
            candidate_commit=candidate,
        )
        is None
    )


@pytest.mark.parametrize("name", ["publish", ".publish"])
def test_ordinary_pr_rejects_an_extensionless_ledger_writer(
    tmp_path: Path, name: str
) -> None:
    root, _initial = _repo(tmp_path)
    _install_pinned_boundary(root)
    base = _commit(root, "trusted boundary")
    writer = root / "scripts" / name
    writer.parent.mkdir()
    writer.write_text(
        "#!/bin/sh\ngit push origin main # ledger/vnext/\n",
        encoding="utf-8",
    )
    candidate = _commit(root, "hidden extensionless writer")

    with pytest.raises(Block9Error, match="writer universe"):
        validate_pull_request_commits(
            root,
            base_commit=base,
            candidate_commit=candidate,
        )


def test_ordinary_pr_pins_a_workflow_with_an_external_secret(
    tmp_path: Path,
) -> None:
    root, _initial = _repo(tmp_path)
    _install_pinned_boundary(root)
    workflow = root / ".github" / "workflows" / "external.yml"
    workflow.write_text(
        "permissions:\n  contents: read\n"
        "env:\n  TOKEN: ${{ secrets.EXTERNAL_TOKEN }}\n",
        encoding="utf-8",
    )
    base = _commit(root, "trusted boundary")
    workflow.write_text(
        "permissions:\n  contents: read\n"
        "env:\n  TOKEN: ${{ secrets.EXTERNAL_TOKEN }}\n"
        "# changed\n",
        encoding="utf-8",
    )
    candidate = _commit(root, "change credential workflow")

    with pytest.raises(Block9Error, match="writer boundary"):
        validate_pull_request_commits(
            root,
            base_commit=base,
            candidate_commit=candidate,
        )


def test_ordinary_pr_allows_an_issue_only_workflow_change(tmp_path: Path) -> None:
    root, _initial = _repo(tmp_path)
    _install_pinned_boundary(root)
    workflow = root / ".github" / "workflows" / "issue-label.yml"
    workflow.write_text(
        "permissions:\n  contents: read\n  issues: write\n",
        encoding="utf-8",
    )
    base = _commit(root, "trusted boundary")
    workflow.write_text(
        "permissions:\n  contents: read\n  issues: write\n# changed\n",
        encoding="utf-8",
    )
    candidate = _commit(root, "change issue-only workflow")

    assert (
        validate_pull_request_commits(
            root,
            base_commit=base,
            candidate_commit=candidate,
        )
        is None
    )


def test_ordinary_pr_rejects_workflow_with_inherited_write_permission(
    tmp_path: Path,
) -> None:
    root, _initial = _repo(tmp_path)
    _install_pinned_boundary(root)
    base = _commit(root, "trusted boundary")
    workflow = root / ".github" / "workflows" / "hidden-ledger-writer.yml"
    workflow.write_text(
        "on: workflow_dispatch\njobs:\n  write:\n    runs-on: ubuntu-latest\n"
        "    steps:\n      - run: git push origin main # ledger/vnext/\n",
        encoding="utf-8",
    )
    candidate = _commit(root, "workflow inherits token permissions")

    with pytest.raises(Block9Error, match="writer universe"):
        validate_pull_request_commits(
            root,
            base_commit=base,
            candidate_commit=candidate,
        )


def test_guard_rejects_reused_idempotency_key() -> None:
    predecessor = "a" * 40
    files = _activation_files(predecessor, "reused-key")
    first = json.loads(files["ledger/vnext/events/0000000000000000.json"])
    first_financial_hash = first["payload"]["resulting_financial_hash"]
    payload = {
        "event_type": "transaction_applied",
        "financial_postings": [],
        "idempotency_key": "reused-key",
        "operation": "transaction",
        "prior_financial_hash": first_financial_hash,
        "resulting_financial_hash": first_financial_hash,
    }
    core = {
        "payload": payload,
        "previous_event_hash": first["event_hash"],
        "sequence": 1,
    }
    second = {**core, "event_hash": sha256_hex(canonical_bytes(core))}
    files["ledger/vnext/events/0000000000000001.json"] = canonical_bytes(second)
    state = json.loads(files["ledger/vnext/state.json"])
    state["last_event_hash"] = second["event_hash"]
    state["sequence"] = 1
    files["ledger/vnext/state.json"] = canonical_bytes(state)

    with pytest.raises(Block9Error, match="idempotency key is repeated"):
        _validate_vnext_tree(
            read_file=files.get,
            paths=tuple(sorted(files)),
        )


def _append_transaction(
    files: dict[str, bytes],
    *,
    idempotency_key: str,
    postings: list[dict[str, object]],
    resulting_balances: dict[str, int],
    resulting_escrows: dict[str, int] | None = None,
    operation: str = "transaction",
    event_type: str = "transaction_applied",
) -> None:
    state = json.loads(files["ledger/vnext/state.json"])
    sequence = state["sequence"] + 1
    prior_financial = {
        "active_escrows": state["active_escrows"],
        "balances": state["balances"],
        "opening_supply": state["opening_supply"],
    }
    resulting_financial = {
        **prior_financial,
        "active_escrows": resulting_escrows or {},
        "balances": resulting_balances,
    }
    payload = {
        "event_type": event_type,
        "financial_postings": postings,
        "idempotency_key": idempotency_key,
        "operation": operation,
        "prior_financial_hash": sha256_hex(canonical_bytes(prior_financial)),
        "resulting_financial_hash": sha256_hex(canonical_bytes(resulting_financial)),
    }
    core = {
        "payload": payload,
        "previous_event_hash": state["last_event_hash"],
        "sequence": sequence,
    }
    event = {**core, "event_hash": sha256_hex(canonical_bytes(core))}
    files[f"ledger/vnext/events/{sequence:016d}.json"] = canonical_bytes(event)
    state.update(resulting_financial)
    state["last_event_hash"] = event["event_hash"]
    state["sequence"] = sequence
    files["ledger/vnext/state.json"] = canonical_bytes(state)
    idempotency = json.loads(files["ledger/vnext/idempotency.json"])
    idempotency["keys"][idempotency_key] = event["event_hash"]
    files["ledger/vnext/idempotency.json"] = canonical_bytes(idempotency)


def test_guard_replays_escrow_and_payment_as_balanced_postings() -> None:
    files = _activation_files("a" * 40, "activate-private-pilot")
    _append_transaction(
        files,
        idempotency_key="escrow-task-1",
        postings=[
            {"account_id": "agent0@system", "account_type": "balance", "delta": -4},
            {"account_id": "task-1", "account_type": "escrow", "delta": 4},
        ],
        resulting_balances={"agent0@system": 6, "worker@example": 0},
        resulting_escrows={"task-1": 4},
    )
    _append_transaction(
        files,
        idempotency_key="pay-task-1",
        postings=[
            {"account_id": "task-1", "account_type": "escrow", "delta": -4},
            {"account_id": "worker@example", "account_type": "balance", "delta": 4},
        ],
        resulting_balances={"agent0@system": 6, "worker@example": 4},
    )

    state = _validate_vnext_tree(read_file=files.get, paths=tuple(sorted(files)))

    assert state["balances"] == {"agent0@system": 6, "worker@example": 4}
    assert state["active_escrows"] == {}


def test_guard_rejects_self_consistent_state_without_matching_postings() -> None:
    files = _activation_files("a" * 40, "activate-private-pilot")
    _append_transaction(
        files,
        idempotency_key="forged-payment-1",
        postings=[],
        resulting_balances={"agent0@system": 6, "worker@example": 4},
    )

    with pytest.raises(Block9Error, match="semantic financial replay"):
        _validate_vnext_tree(read_file=files.get, paths=tuple(sorted(files)))


def test_replay_repair_cannot_move_money() -> None:
    files = _activation_files("a" * 40, "activate-private-pilot")
    _append_transaction(
        files,
        idempotency_key="bad-replay-repair-1",
        operation="repair",
        event_type="replay_repair",
        postings=[
            {"account_id": "agent0@system", "account_type": "balance", "delta": -4},
            {"account_id": "worker@example", "account_type": "balance", "delta": 4},
        ],
        resulting_balances={"agent0@system": 6, "worker@example": 4},
    )

    with pytest.raises(Block9Error, match="must not change financial"):
        _validate_vnext_tree(read_file=files.get, paths=tuple(sorted(files)))


def test_existing_writer_source_is_immutable_until_retired(tmp_path: Path) -> None:
    root, _initial = _repo(tmp_path)
    _install_pinned_boundary(root)
    writer = root / "src" / "legacy_writer.py"
    writer.write_text(
        "from pathlib import Path\nPath('ledger/state.json').write_text('old')\n",
        encoding="utf-8",
    )
    base = _commit(root, "legacy writer")
    writer.write_text(
        "from pathlib import Path\nPath('ledger/vnext/state.json').write_text('new')\n",
        encoding="utf-8",
    )
    candidate = _commit(root, "redirect legacy writer")

    with pytest.raises(Block9Error, match="existing writer boundary source changed"):
        validate_pull_request_commits(
            root,
            base_commit=base,
            candidate_commit=candidate,
        )


def test_existing_composite_writer_action_is_immutable(tmp_path: Path) -> None:
    root, _initial = _repo(tmp_path)
    _install_pinned_boundary(root)
    action = root / ".github" / "actions" / "legacy-writer" / "action.yml"
    action.parent.mkdir(parents=True)
    action.write_text(
        "runs:\n  using: composite\n  steps:\n"
        "    - shell: bash\n      run: git push origin main # ledger/\n",
        encoding="utf-8",
    )
    base = _commit(root, "legacy composite writer")
    action.write_text(
        "runs:\n  using: composite\n  steps:\n"
        "    - shell: bash\n      run: git push origin main # ledger/vnext/\n",
        encoding="utf-8",
    )
    candidate = _commit(root, "redirect composite writer")

    with pytest.raises(Block9Error, match="existing writer boundary source changed"):
        validate_pull_request_commits(
            root,
            base_commit=base,
            candidate_commit=candidate,
        )


def test_candidate_record_rejects_source_evidence_substitution(tmp_path: Path) -> None:
    root, predecessor = _repo(tmp_path)
    _package_commit, _manifest, command = _package(root, predecessor)
    _git(root, "checkout", "--detach", predecessor)
    source = deepcopy(_source(command))
    source["command_sha256"] = "0" * 64
    with pytest.raises(Block9Error, match="command"):
        build_candidate(
            root,
            command=command,
            source_evidence=source,
            workflow_evidence=_workflow(predecessor),
        )


def test_candidate_requires_the_canonical_operator_source(tmp_path: Path) -> None:
    root, predecessor = _repo(tmp_path)
    _package_commit, _manifest, command = _package(root, predecessor)
    _git(root, "checkout", "--detach", predecessor)

    wrong_author = deepcopy(_source(command))
    wrong_author["comment_author"] = "another-member"
    with pytest.raises(Block9Error, match="canonical operator"):
        build_candidate(
            root,
            command=command,
            source_evidence=wrong_author,
            workflow_evidence=_workflow(predecessor),
        )

    wrong_workflow = deepcopy(_workflow(predecessor))
    wrong_workflow["actor"] = "another-member"
    with pytest.raises(Block9Error, match="actor"):
        build_candidate(
            root,
            command=command,
            source_evidence=_source(command),
            workflow_evidence=wrong_workflow,
        )


@pytest.mark.parametrize(
    "association", ["MEMBER", "OWNER", "COLLABORATOR", "CONTRIBUTOR", "NONE"]
)
def test_candidate_retains_operator_association_as_metadata(
    tmp_path: Path, association: str
) -> None:
    root, predecessor = _repo(tmp_path)
    _package_commit, _manifest, command = _package(root, predecessor)
    _git(root, "checkout", "--detach", predecessor)
    source = deepcopy(_source(command))
    source["author_association"] = association
    record = build_candidate(
        root,
        command=command,
        source_evidence=source,
        workflow_evidence=_workflow(predecessor),
    )
    assert record["source"]["author_association"] == association


@pytest.mark.parametrize("association", ["MEMBER", "COLLABORATOR", "NONE"])
def test_guard_confirms_the_exact_completed_github_workflow_run(
    tmp_path: Path, association: str
) -> None:
    root, predecessor, candidate, command = _build(tmp_path)
    body = COMMAND_MARKER + command.decode("utf-8")

    def api_get(path: str) -> object:
        if path.endswith("/issues/comments/41"):
            return {
                "author_association": association,
                "body": body,
                "html_url": (
                    "https://github.com/WeTheAgents/wetheagents/"
                    "issues/9#issuecomment-41"
                ),
                "issue_url": (
                    "https://api.github.com/repos/WeTheAgents/wetheagents/issues/9"
                ),
                "user": {"login": "peachgabba22"},
            }
        if path.endswith("/actions/runs/9001"):
            return {
                "actor": {"login": "peachgabba22"},
                "conclusion": "success",
                "event": "workflow_dispatch",
                "head_sha": predecessor,
                "path": ".github/workflows/agent0-ledger-candidate.yml",
                "run_attempt": 1,
                "status": "completed",
            }
        raise AssertionError(path)

    validate_candidate_commits(
        root,
        base_commit=predecessor,
        candidate_commit=candidate,
        api_get=api_get,
    )


def test_workflows_use_github_hosted_runner_and_no_app_or_admin_token() -> None:
    root = Path(__file__).resolve().parents[2]
    candidate = (root / ".github/workflows/tide.yml").read_text(encoding="utf-8")
    guard = (root / ".github/workflows/guard-vnext-ledger.yml").read_text(
        encoding="utf-8"
    )
    assert "workflow_dispatch:" in candidate
    assert "contents: write" in candidate
    assert "runs-on: ubuntu-latest" in candidate
    assert "ref: ${{ github.sha }}" in candidate
    assert "schedule:" in candidate
    assert "python -m wea_vnext.tide run" in candidate
    assert "ADMIN_TOKEN" not in candidate
    assert "self-hosted" not in candidate
    assert "github-app" not in candidate.lower()

    assert "pull_request_target:" in guard
    assert "ref: ${{ github.event.pull_request.base.sha || 'main' }}" in guard
    assert "Fetch candidate Git objects without checking them out" in guard
    assert "fetch --no-tags origin" in guard
    assert "http.https://github.com/.extraheader" in guard
    assert "::add-mask::" in guard
    assert "persist-credentials: false" in guard
    assert "actions/checkout@v4" in guard
    assert guard.count("actions/checkout@v4") == 2
    assert "invalidate-pending" in guard
    assert "ADMIN_TOKEN" not in guard
    assert "self-hosted" not in guard


def test_legacy_direct_write_workflows_are_absent_or_read_only() -> None:
    root = Path(__file__).resolve().parents[2]
    workflows = root / ".github/workflows"
    assert not (workflows / "label-paid.yml").exists()
    assert not (workflows / "agent0-ledger-candidate.yml").exists()
    assert not (workflows / "genome-mutation-tracker.yml").exists()
    assert not (workflows / "guard-ledger.yml").exists()
    btc = (workflows / "btc-snapshot.yml").read_text(encoding="utf-8")
    assert "schedule:" not in btc
    assert "contents: write" not in btc
    assert "git push" not in btc
    assert "actions/upload-artifact@v4" in btc
