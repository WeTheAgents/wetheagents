from __future__ import annotations

import json
import subprocess
import threading
from pathlib import Path

import pytest

import wea_vnext.block9.cutover as cutover
from wea_vnext.block9.common import require_relative_path
from wea_vnext.block9.cutover import (
    AppendOnlyEventStore,
    Block9Error,
    build_approval_envelope,
    build_cutover_core,
    build_final_tree_manifest,
    build_sequence_zero,
    canonical_bytes,
    sha256_hex,
    validate_final_tree,
    verify_approval_pair,
)


@pytest.mark.parametrize("path", ["C:outside.json", "C:/outside.json", "name:stream"])
def test_repository_relative_paths_reject_windows_drive_or_stream_syntax(
    path: str,
) -> None:
    with pytest.raises(Block9Error, match="repository-relative"):
        require_relative_path(path, field="candidate path")


def _core() -> bytes:
    event_payload = {"event_type": "epoch_started", "epoch": "epoch-2"}
    return build_cutover_core(
        {
            "repository_id": "repo-1",
            "target_ref": "refs/heads/main",
            "expected_predecessor": "a" * 40,
            "target_epoch": "epoch-2",
            "expected_state_hash": "b" * 64,
            "writer_agent_id": "agent0@system",
            "writer_binding_hash": "5" * 64,
            "operator_identity": "operator@local",
            "operator_binding_id": "operator-key",
            "operator_binding_version": 1,
            "operator_binding_hash": "4" * 64,
            "agent0_identity": "agent0@system",
            "agent0_binding_id": "agent0-key",
            "agent0_binding_version": 1,
            "agent0_binding_hash": "5" * 64,
            "bootstrap_hash": "d" * 64,
            "genesis_hash": "e" * 64,
            "sequence_zero_payload_hash": sha256_hex(canonical_bytes(event_payload)),
            "input_hashes": {
                name: "1" * 64
                for name in (
                    "activation_blueprint",
                    "authority_snapshot",
                    "canonical_ref_competitor_inventory",
                    "closed_path_set",
                    "commit_signing_binding",
                    "dependencies",
                    "executor",
                    "github_boundary",
                    "ledger_app_binding",
                    "operational_writer_universe",
                    "projection_transport",
                    "projection_writer_inventory",
                    "protocol_writer_inventory",
                    "python",
                    "reconciliation",
                    "rulesets",
                    "runtime",
                    "shadow",
                    "static_writer_universe",
                    "tide_interface",
                    "v1_boundary",
                )
            },
            "recovery_hashes": {
                "durable_correction": "2" * 64,
                "replay_repair": "3" * 64,
                "transaction": "6" * 64,
            },
        }
    )


def test_cutover_core_is_canonical_and_excludes_approval_bytes() -> None:
    core = _core()
    assert core == canonical_bytes(__import__("json").loads(core))
    assert b"approval" not in core


def test_cutover_core_requires_distinct_operator_and_agent0_identities() -> None:
    values = json.loads(_core())
    values["operator_identity"] = "agent0@system"
    with pytest.raises(Block9Error, match="identities must differ"):
        build_cutover_core(values)


def test_approval_pair_binds_one_core_and_distinct_authorities() -> None:
    core_hash = sha256_hex(_core())
    operator = build_approval_envelope(
        core_hash=core_hash,
        role="operator",
        source_identity="operator@local",
        key_fingerprint="SHA256:operator",
        binding_id="operator-key",
        binding_version=1,
        binding_hash="4" * 64,
        valid_from="2026-08-01T00:00:00Z",
        valid_until="2026-09-01T00:00:00Z",
        approved_at="2026-08-22T00:00:00Z",
        source_path="approvals/operator.json",
    )
    agent0 = build_approval_envelope(
        core_hash=core_hash,
        role="agent0",
        source_identity="agent0@system",
        key_fingerprint="SHA256:agent0",
        binding_id="agent0-key",
        binding_version=1,
        binding_hash="5" * 64,
        valid_from="2026-08-01T00:00:00Z",
        valid_until="2026-09-01T00:00:00Z",
        approved_at="2026-08-22T00:00:00Z",
        source_path="approvals/agent0.json",
    )
    verify_approval_pair(
        core=_core(),
        operator=operator,
        operator_signature=b"operator-signature",
        agent0=agent0,
        agent0_signature=b"agent0-signature",
        verifier=lambda envelope, signature, namespace: bool(signature)
        and namespace == "wea-vnext-cutover",
        effective_at="2026-08-22T00:00:00Z",
    )

    with pytest.raises(Block9Error, match="fingerprints must differ"):
        verify_approval_pair(
            core=_core(),
            operator=operator,
            operator_signature=b"x",
            agent0={**agent0, "key_fingerprint": "SHA256:operator"},
            agent0_signature=b"y",
            verifier=lambda *_: True,
            effective_at="2026-08-22T00:00:00Z",
        )

    with pytest.raises(Block9Error, match="authority changed"):
        verify_approval_pair(
            core=_core(),
            operator={**operator, "binding_hash": "9" * 64},
            operator_signature=b"x",
            agent0=agent0,
            agent0_signature=b"y",
            verifier=lambda *_: True,
            effective_at="2026-08-22T00:00:00Z",
        )

    with pytest.raises(Block9Error, match="not effective at cutover"):
        verify_approval_pair(
            core=_core(),
            operator={**operator, "approved_at": "2026-08-22T00:00:01Z"},
            operator_signature=b"x",
            agent0=agent0,
            agent0_signature=b"y",
            verifier=lambda *_: True,
            effective_at="2026-08-22T00:00:00Z",
        )


def test_sequence_zero_and_manifest_have_no_recursive_hash_cycle(
    tmp_path: Path,
) -> None:
    core = _core()
    core_hash = sha256_hex(core)
    operator = build_approval_envelope(
        core_hash=core_hash,
        role="operator",
        source_identity="operator@local",
        key_fingerprint="SHA256:operator",
        binding_id="operator-key",
        binding_version=1,
        binding_hash="4" * 64,
        valid_from="2026-08-01T00:00:00Z",
        valid_until="2026-09-01T00:00:00Z",
        approved_at="2026-08-22T00:00:00Z",
        source_path="approvals/operator.json",
    )
    agent0 = build_approval_envelope(
        core_hash=core_hash,
        role="agent0",
        source_identity="agent0@system",
        key_fingerprint="SHA256:agent0",
        binding_id="agent0-key",
        binding_version=1,
        binding_hash="5" * 64,
        valid_from="2026-08-01T00:00:00Z",
        valid_until="2026-09-01T00:00:00Z",
        approved_at="2026-08-22T00:00:00Z",
        source_path="approvals/agent0.json",
    )
    event = build_sequence_zero(
        core=core,
        event_payload={"event_type": "epoch_started", "epoch": "epoch-2"},
        operator_envelope=canonical_bytes(operator),
        operator_signature=b"operator-signature",
        agent0_envelope=canonical_bytes(agent0),
        agent0_signature=b"agent0-signature",
        verifier=lambda *_: True,
        effective_at="2026-08-22T00:00:00Z",
    )
    event_store = AppendOnlyEventStore(tmp_path / "sequence-zero-store")
    (event_store.events / "0000000000000000.json").write_bytes(event)
    assert event_store.read_all() == (event,)
    files = {
        "ledger/vnext/bootstrap.json": b"{}",
        "ledger/vnext/genesis.json": b"{}",
        "ledger/vnext/events/0000000000000000.json": event,
    }
    manifest = build_final_tree_manifest(files)
    assert b"final-tree-manifest.json" not in manifest
    assert b'"git_blob_id"' in manifest
    repository = tmp_path / "repository"
    subprocess.run(
        ["git", "init", "-b", "main", str(repository)], check=True, capture_output=True
    )
    subprocess.run(
        ["git", "-C", str(repository), "config", "user.email", "test@example.invalid"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repository), "config", "user.name", "Test"], check=True
    )
    (repository / "README.md").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repository), "add", "README.md"], check=True)
    subprocess.run(
        ["git", "-C", str(repository), "commit", "-m", "base"],
        check=True,
        capture_output=True,
    )
    predecessor = subprocess.run(
        ["git", "-C", str(repository), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    for path, content in files.items():
        target = repository / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    manifest_path = repository / "evidence" / "vnext" / "final-tree-manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_bytes(manifest)
    subprocess.run(["git", "-C", str(repository), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(repository), "commit", "-m", "candidate"],
        check=True,
        capture_output=True,
    )
    candidate = subprocess.run(
        ["git", "-C", str(repository), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    validate_final_tree(
        repository,
        predecessor=predecessor,
        candidate=candidate,
        manifest=manifest,
    )
    (repository / "extra.txt").write_bytes(b"extra")
    subprocess.run(["git", "-C", str(repository), "add", "extra.txt"], check=True)
    subprocess.run(
        ["git", "-C", str(repository), "commit", "-m", "extra"],
        check=True,
        capture_output=True,
    )
    tampered = subprocess.run(
        ["git", "-C", str(repository), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    with pytest.raises(Block9Error, match="direct child"):
        validate_final_tree(
            repository,
            predecessor=predecessor,
            candidate=tampered,
            manifest=manifest,
        )

    subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "checkout",
            "-b",
            "missing-manifest",
            predecessor,
        ],
        check=True,
        capture_output=True,
    )
    for path, content in files.items():
        target = repository / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    subprocess.run(["git", "-C", str(repository), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(repository), "commit", "-m", "missing manifest"],
        check=True,
        capture_output=True,
    )
    missing_manifest = subprocess.run(
        ["git", "-C", str(repository), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    with pytest.raises(Block9Error, match="absent from the candidate"):
        validate_final_tree(
            repository,
            predecessor=predecessor,
            candidate=missing_manifest,
            manifest=manifest,
        )


def test_append_only_event_store_exact_retry_and_conflict(tmp_path: Path) -> None:
    store = AppendOnlyEventStore(tmp_path)
    first = store.append(sequence=0, payload={"event_type": "epoch_started"})
    assert store.append(sequence=0, payload={"event_type": "epoch_started"}) == first
    with pytest.raises(Block9Error, match="different bytes"):
        store.append(sequence=0, payload={"event_type": "changed"})
    second = store.append(sequence=1, payload={"event_type": "noop"})
    assert store.read_all() == (first, second)


def test_append_only_event_store_concurrent_conflict_is_create_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = AppendOnlyEventStore(tmp_path)
    barrier = threading.Barrier(2)
    original_link = cutover.os.link
    results: list[bytes] = []
    errors: list[BaseException] = []

    def synchronized_link(source: Path, destination: Path) -> None:
        barrier.wait(timeout=5)
        original_link(source, destination)

    def append(event_type: str) -> None:
        try:
            results.append(store.append(sequence=0, payload={"event_type": event_type}))
        except BaseException as exc:
            errors.append(exc)

    monkeypatch.setattr(cutover.os, "link", synchronized_link)
    threads = [
        threading.Thread(target=append, args=(event_type,))
        for event_type in ("left", "right")
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert all(not thread.is_alive() for thread in threads)
    assert len(results) == 1
    assert len(errors) == 1
    assert isinstance(errors[0], Block9Error)
    assert "different bytes" in str(errors[0])
    assert store.read_all() == (results[0],)
