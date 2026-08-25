"""Canonical cutover evidence graph and append-only candidate event store."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import uuid
from collections.abc import Callable, Mapping
from pathlib import Path

from .common import (
    Block9Error,
    canonical_bytes,
    parse_utc,
    require_hash,
    require_positive_int,
    require_relative_path,
    require_text,
    sha256_hex,
)

FINAL_TREE_MANIFEST_PATH = "evidence/vnext/final-tree-manifest.json"

_CORE_FIELDS = {
    "repository_id",
    "target_ref",
    "expected_predecessor",
    "target_epoch",
    "expected_state_hash",
    "writer_agent_id",
    "writer_binding_hash",
    "operator_identity",
    "operator_binding_id",
    "operator_binding_version",
    "operator_binding_hash",
    "agent0_identity",
    "agent0_binding_id",
    "agent0_binding_version",
    "agent0_binding_hash",
    "bootstrap_hash",
    "genesis_hash",
    "sequence_zero_payload_hash",
    "input_hashes",
    "recovery_hashes",
}
_INPUT_HASH_FIELDS = {
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
}
_RECOVERY_HASH_FIELDS = {
    "durable_correction",
    "replay_repair",
    "transaction",
}


def _canonical_mapping_bytes(value: Mapping[str, object], *, field: str) -> bytes:
    if type(value) is not dict:
        value = dict(value)
    try:
        data = canonical_bytes(value)
        if type(json.loads(data)) is not dict:
            raise Block9Error(f"{field} must be a mapping")
        return data
    except (TypeError, ValueError) as exc:
        raise Block9Error(f"{field} is incomplete") from exc


def build_cutover_core(values: Mapping[str, object]) -> bytes:
    if not isinstance(values, Mapping):
        raise Block9Error("cutover core must be a mapping")
    if set(values) != _CORE_FIELDS:
        missing = sorted(_CORE_FIELDS - set(values))
        extra = sorted(set(values) - _CORE_FIELDS)
        raise Block9Error(
            f"cutover core fields mismatch: missing={missing}, extra={extra}"
        )
    require_text(values["repository_id"], field="repository_id")
    if values["target_ref"] != "refs/heads/main":
        raise Block9Error("cutover target ref must be refs/heads/main")
    require_hash(
        values["expected_predecessor"], field="expected_predecessor", length=40
    )
    require_text(values["target_epoch"], field="target_epoch")
    require_hash(values["expected_state_hash"], field="expected_state_hash")
    if values["writer_agent_id"] != "agent0@system":
        raise Block9Error("cutover writer must be agent0@system")
    operator_identity = require_text(
        values["operator_identity"], field="operator_identity"
    )
    require_text(values["operator_binding_id"], field="operator_binding_id")
    require_positive_int(
        values["operator_binding_version"], field="operator_binding_version"
    )
    require_hash(values["operator_binding_hash"], field="operator_binding_hash")
    if values["agent0_identity"] != "agent0@system":
        raise Block9Error("cutover Agent0 approval identity must be agent0@system")
    if operator_identity == values["agent0_identity"]:
        raise Block9Error("operator and Agent0 identities must differ")
    require_text(values["agent0_binding_id"], field="agent0_binding_id")
    require_positive_int(
        values["agent0_binding_version"], field="agent0_binding_version"
    )
    require_hash(values["agent0_binding_hash"], field="agent0_binding_hash")
    for field in (
        "writer_binding_hash",
        "bootstrap_hash",
        "genesis_hash",
        "sequence_zero_payload_hash",
    ):
        require_hash(values[field], field=field)
    if values["writer_binding_hash"] != values["agent0_binding_hash"]:
        raise Block9Error("writer binding is not the approved Agent0 binding")
    for field, expected_fields in (
        ("input_hashes", _INPUT_HASH_FIELDS),
        ("recovery_hashes", _RECOVERY_HASH_FIELDS),
    ):
        child = values[field]
        if type(child) is not dict or set(child) != expected_fields:
            raise Block9Error(f"{field} does not cover the accepted cutover evidence")
        for key, digest in child.items():
            require_text(key, field=f"{field} key")
            require_hash(digest, field=f"{field}.{key}")
    return _canonical_mapping_bytes(dict(values), field="cutover core")


def build_approval_envelope(
    *,
    core_hash: str,
    role: str,
    source_identity: str,
    key_fingerprint: str,
    binding_id: str,
    binding_version: int,
    binding_hash: str,
    valid_from: str,
    valid_until: str,
    approved_at: str,
    source_path: str,
) -> dict[str, object]:
    require_hash(core_hash, field="core_hash")
    if role not in {"operator", "agent0"}:
        raise Block9Error("approval role is not accepted")
    require_text(source_identity, field="source_identity")
    require_text(key_fingerprint, field="key_fingerprint")
    require_text(binding_id, field="binding_id")
    require_positive_int(binding_version, field="binding_version")
    require_hash(binding_hash, field="binding_hash")
    start = parse_utc(valid_from, field="valid_from")
    end = parse_utc(valid_until, field="valid_until")
    approved = parse_utc(approved_at, field="approved_at")
    if not start <= approved < end:
        raise Block9Error("approval time is outside the binding interval")
    require_relative_path(source_path, field="source_path")
    envelope: dict[str, object] = {
        "core_hash": core_hash,
        "role": role,
        "source_identity": source_identity,
        "key_fingerprint": key_fingerprint,
        "binding_id": binding_id,
        "binding_version": binding_version,
        "binding_hash": binding_hash,
        "valid_from": valid_from,
        "valid_until": valid_until,
        "approved_at": approved_at,
        "source_path": source_path,
    }
    canonical_bytes(envelope)
    return envelope


def _rebuild_envelope(value: Mapping[str, object], *, role: str) -> dict[str, object]:
    try:
        return build_approval_envelope(
            core_hash=require_hash(value["core_hash"], field=f"{role}.core_hash"),
            role=require_text(value["role"], field=f"{role}.role"),
            source_identity=require_text(
                value["source_identity"], field=f"{role}.source_identity"
            ),
            key_fingerprint=require_text(
                value["key_fingerprint"], field=f"{role}.key_fingerprint"
            ),
            binding_id=require_text(value["binding_id"], field=f"{role}.binding_id"),
            binding_version=require_positive_int(
                value["binding_version"], field=f"{role}.binding_version"
            ),
            binding_hash=require_hash(
                value["binding_hash"], field=f"{role}.binding_hash"
            ),
            valid_from=require_text(value["valid_from"], field=f"{role}.valid_from"),
            valid_until=require_text(value["valid_until"], field=f"{role}.valid_until"),
            approved_at=require_text(value["approved_at"], field=f"{role}.approved_at"),
            source_path=require_text(value["source_path"], field=f"{role}.source_path"),
        )
    except (KeyError, TypeError) as exc:
        raise Block9Error(f"{role} approval envelope is incomplete") from exc


def verify_approval_pair(
    *,
    core: bytes,
    operator: Mapping[str, object],
    operator_signature: bytes,
    agent0: Mapping[str, object],
    agent0_signature: bytes,
    verifier: Callable[[bytes, bytes, str], bool],
    effective_at: str,
) -> None:
    if type(core) is not bytes:
        raise Block9Error("cutover core must be exact bytes")
    try:
        core_value = json.loads(core)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Block9Error("cutover core is not JSON") from exc
    if build_cutover_core(core_value) != core:
        raise Block9Error("cutover core bytes are not canonical")
    core_hash = sha256_hex(core)
    at = parse_utc(effective_at, field="effective_at")
    op = _rebuild_envelope(operator, role="operator")
    a0 = _rebuild_envelope(agent0, role="agent0")
    if op["role"] != "operator" or a0["role"] != "agent0":
        raise Block9Error("approval roles must be operator and agent0")
    if op["core_hash"] != core_hash or a0["core_hash"] != core_hash:
        raise Block9Error("approvals do not bind the same cutover core")
    if a0["source_identity"] != "agent0@system":
        raise Block9Error("Agent0 approval identity is not agent0@system")
    if op["source_identity"] == a0["source_identity"]:
        raise Block9Error("operator and Agent0 identities must differ")
    for role, envelope in (("operator", op), ("agent0", a0)):
        expected = {
            "source_identity": core_value[f"{role}_identity"],
            "binding_id": core_value[f"{role}_binding_id"],
            "binding_version": core_value[f"{role}_binding_version"],
            "binding_hash": core_value[f"{role}_binding_hash"],
        }
        if any(envelope[field] != value for field, value in expected.items()):
            raise Block9Error(
                f"{role} approval authority changed from the cutover core"
            )
    if op["key_fingerprint"] == a0["key_fingerprint"]:
        raise Block9Error("operator and Agent0 fingerprints must differ")
    for name, envelope, signature in (
        ("operator", op, operator_signature),
        ("agent0", a0, agent0_signature),
    ):
        if type(signature) is not bytes or not signature:
            raise Block9Error(f"{name} signature is missing")
        start = parse_utc(envelope["valid_from"], field=f"{name}.valid_from")
        end = parse_utc(envelope["valid_until"], field=f"{name}.valid_until")
        approved = parse_utc(envelope["approved_at"], field=f"{name}.approved_at")
        if not start <= at < end:
            raise Block9Error(f"{name} authority is not active")
        if not start <= approved < end or approved > at:
            raise Block9Error(f"{name} approval is not effective at cutover")
        envelope_bytes = canonical_bytes(envelope)
        if not verifier(envelope_bytes, signature, "wea-vnext-cutover"):
            raise Block9Error(f"{name} signature did not verify")


def build_sequence_zero(
    *,
    core: bytes,
    event_payload: Mapping[str, object],
    operator_envelope: bytes,
    operator_signature: bytes,
    agent0_envelope: bytes,
    agent0_signature: bytes,
    verifier: Callable[[bytes, bytes, str], bool],
    effective_at: str,
) -> bytes:
    if type(core) is not bytes or build_cutover_core(json.loads(core)) != core:
        raise Block9Error("cutover core bytes are not canonical")
    core_value = json.loads(core)
    core_hash = sha256_hex(core)
    if type(event_payload) is not dict:
        raise Block9Error("sequence-zero payload must be an exact mapping")
    payload_bytes = canonical_bytes(event_payload)
    if sha256_hex(payload_bytes) != core_value["sequence_zero_payload_hash"]:
        raise Block9Error("sequence-zero payload does not match the cutover core")
    envelopes: dict[str, dict[str, object]] = {}
    for role, raw in (("operator", operator_envelope), ("agent0", agent0_envelope)):
        if type(raw) is not bytes:
            raise Block9Error(f"{role} envelope must be exact bytes")
        try:
            parsed = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise Block9Error(f"{role} envelope is not JSON") from exc
        if canonical_bytes(parsed) != raw or type(parsed) is not dict:
            raise Block9Error(f"{role} envelope bytes are not canonical")
        rebuilt = _rebuild_envelope(parsed, role=role)
        if (
            rebuilt != parsed
            or rebuilt["role"] != role
            or rebuilt["core_hash"] != core_hash
        ):
            raise Block9Error(f"{role} envelope does not bind the cutover core")
        envelopes[role] = rebuilt
    verify_approval_pair(
        core=core,
        operator=envelopes["operator"],
        operator_signature=operator_signature,
        agent0=envelopes["agent0"],
        agent0_signature=agent0_signature,
        verifier=verifier,
        effective_at=effective_at,
    )
    payload_value = json.loads(payload_bytes)
    if payload_value.get("event_type") != "epoch_started":
        raise Block9Error("sequence zero must be the epoch_started event")
    if "cutover" in payload_value:
        raise Block9Error("sequence-zero payload uses the reserved cutover field")
    chain_payload = {
        **payload_value,
        "cutover": {
            "core_hash": core_hash,
            "approvals": {
                "operator": {
                    "envelope_sha256": sha256_hex(operator_envelope),
                    "signature_sha256": sha256_hex(operator_signature),
                },
                "agent0": {
                    "envelope_sha256": sha256_hex(agent0_envelope),
                    "signature_sha256": sha256_hex(agent0_signature),
                },
            },
        },
    }
    chain_core = {
        "sequence": 0,
        "previous_event_hash": "0" * 64,
        "payload": chain_payload,
    }
    return canonical_bytes(
        {**chain_core, "event_hash": sha256_hex(canonical_bytes(chain_core))}
    )


def build_final_tree_manifest(files: Mapping[str, bytes]) -> bytes:
    if not isinstance(files, Mapping) or not files:
        raise Block9Error("activation file set is empty")
    rows: list[dict[str, object]] = []
    for path, content in sorted(files.items()):
        path = require_relative_path(path, field="activation path")
        if path.endswith("final-tree-manifest.json"):
            raise Block9Error("final tree manifest cannot include itself")
        if type(content) is not bytes:
            raise Block9Error("activation file content must be exact bytes")
        rows.append(
            {
                "path": path,
                "byte_length": len(content),
                "sha256": sha256_hex(content),
                # Git object identity is SHA-1 by repository format, not a new
                # cryptographic signature choice.
                "git_blob_id": hashlib.sha1(  # nosemgrep
                    f"blob {len(content)}\0".encode() + content,
                    usedforsecurity=False,
                ).hexdigest(),
            }
        )
    return canonical_bytes({"files": rows})


def _git_bytes(root: Path, *arguments: str) -> bytes:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *arguments],
            check=False,
            capture_output=True,
        )
    except OSError as exc:
        raise Block9Error("activation Git tree is unavailable") from exc
    if result.returncode != 0:
        raise Block9Error("activation Git tree cannot be read")
    return result.stdout


def _actual_activation_files(
    repository_root: Path,
    *,
    predecessor: str,
    candidate: str,
) -> dict[str, bytes]:
    if not isinstance(repository_root, Path) or not repository_root.is_dir():
        raise Block9Error("activation repository root is missing")
    require_hash(predecessor, field="activation predecessor", length=40)
    require_hash(candidate, field="activation candidate", length=40)
    deleted = _git_bytes(
        repository_root,
        "diff",
        "--no-renames",
        "--name-only",
        "-z",
        "--diff-filter=D",
        predecessor,
        candidate,
        "--",
    )
    if deleted:
        raise Block9Error("activation tree contains an unmanifested deletion")
    raw_paths = _git_bytes(
        repository_root,
        "diff",
        "--no-renames",
        "--name-only",
        "-z",
        predecessor,
        candidate,
        "--",
    )
    files: dict[str, bytes] = {}
    for raw_path in raw_paths.split(b"\0"):
        if not raw_path:
            continue
        try:
            path = raw_path.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise Block9Error("activation path is not UTF-8") from exc
        path = require_relative_path(path, field="activation path")
        if path == FINAL_TREE_MANIFEST_PATH:
            continue
        files[path] = _git_bytes(repository_root, "show", f"{candidate}:{path}")
    if not files:
        raise Block9Error("actual activation tree is empty")
    return files


def validate_final_tree(
    repository_root: Path,
    *,
    predecessor: str,
    candidate: str,
    manifest: bytes,
) -> None:
    """Match the manifest to the actual candidate diff from its predecessor."""

    if type(manifest) is not bytes:
        raise Block9Error("final tree manifest must be exact bytes")
    require_hash(predecessor, field="cutover predecessor", length=40)
    require_hash(candidate, field="cutover candidate", length=40)
    commit_line = _git_bytes(
        repository_root, "rev-list", "--parents", "-n", "1", candidate
    ).decode("ascii").split()
    if commit_line != [candidate, predecessor]:
        raise Block9Error("cutover candidate must be one direct child")
    try:
        parsed = json.loads(manifest)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Block9Error("final tree manifest is not JSON") from exc
    if canonical_bytes(parsed) != manifest or type(parsed) is not dict:
        raise Block9Error("final tree manifest is not canonical")
    changed_manifest = _git_bytes(
        repository_root,
        "diff",
        "--name-only",
        predecessor,
        candidate,
        "--",
        FINAL_TREE_MANIFEST_PATH,
    )
    if not changed_manifest.strip():
        raise Block9Error("final tree manifest is absent from the candidate")
    actual_manifest = _git_bytes(
        repository_root,
        "show",
        f"{candidate}:{FINAL_TREE_MANIFEST_PATH}",
    )
    if actual_manifest != manifest:
        raise Block9Error("final tree manifest is absent or changed in the candidate")
    expected = build_final_tree_manifest(
        _actual_activation_files(
            repository_root,
            predecessor=predecessor,
            candidate=candidate,
        )
    )
    if expected != manifest:
        raise Block9Error("final tree manifest path set or content changed")


class AppendOnlyEventStore:
    """Append candidate event bytes without exposing a live adapter."""

    def __init__(self, root: Path) -> None:
        if not isinstance(root, Path):
            raise Block9Error("event root must be a Path")
        self.events = root.resolve() / "events"
        self.events.mkdir(parents=True, exist_ok=True)

    def _path(self, sequence: int) -> Path:
        if type(sequence) is not int or sequence < 0:
            raise Block9Error("event sequence must be a nonnegative integer")
        return self.events / f"{sequence:016d}.json"

    def prepare(self, *, sequence: int, payload: Mapping[str, object]) -> bytes:
        path = self._path(sequence)
        existing = self.read_all()
        if path.exists():
            current = path.read_bytes()
            parsed = json.loads(current)
            if parsed.get("payload") == dict(payload):
                return current
            raise Block9Error("event sequence already contains different bytes")
        previous_event_hash = sha256_hex(existing[-1]) if existing else "0" * 64
        core = {
            "sequence": sequence,
            "previous_event_hash": previous_event_hash,
            "payload": dict(payload),
        }
        event = canonical_bytes(
            {**core, "event_hash": sha256_hex(canonical_bytes(core))}
        )
        if sequence != len(existing):
            raise Block9Error("event sequence is not contiguous")
        return event

    def append(self, *, sequence: int, payload: Mapping[str, object]) -> bytes:
        path = self._path(sequence)
        event = self.prepare(sequence=sequence, payload=payload)
        if path.exists():
            return event
        temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("xb") as stream:
                stream.write(event)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError:
                if path.read_bytes() != event:
                    raise Block9Error(
                        "event sequence already contains different bytes"
                    ) from None
        finally:
            temporary.unlink(missing_ok=True)
        return event

    def read_all(self) -> tuple[bytes, ...]:
        result: list[bytes] = []
        previous_event_hash = "0" * 64
        for expected, path in enumerate(sorted(self.events.glob("*.json"))):
            if path.name != f"{expected:016d}.json":
                raise Block9Error("event store contains a sequence gap")
            raw = path.read_bytes()
            try:
                parsed = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise Block9Error("event store contains invalid JSON") from exc
            if canonical_bytes(parsed) != raw or parsed.get("sequence") != expected:
                raise Block9Error("event store contains non-canonical bytes")
            if type(parsed) is not dict or set(parsed) != {
                "event_hash",
                "payload",
                "previous_event_hash",
                "sequence",
            }:
                raise Block9Error("event store contains an incomplete event")
            if parsed["previous_event_hash"] != previous_event_hash:
                raise Block9Error("event store predecessor chain changed")
            core = {
                "sequence": parsed["sequence"],
                "previous_event_hash": parsed["previous_event_hash"],
                "payload": parsed["payload"],
            }
            if parsed["event_hash"] != sha256_hex(canonical_bytes(core)):
                raise Block9Error("event store event hash changed")
            result.append(raw)
            previous_event_hash = sha256_hex(raw)
        return tuple(result)


__all__ = [
    "AppendOnlyEventStore",
    "Block9Error",
    "build_approval_envelope",
    "build_cutover_core",
    "build_final_tree_manifest",
    "build_sequence_zero",
    "canonical_bytes",
    "sha256_hex",
    "validate_final_tree",
    "verify_approval_pair",
]
