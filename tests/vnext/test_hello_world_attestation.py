from __future__ import annotations

import base64
import copy
import hashlib
import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (
    ROOT / "oled/changes/wea-vnext-recreation/evidence/check_hello_world_attestation.py"
)
ARTIFACT = (
    ROOT
    / "oled/changes/wea-vnext-recreation/evidence/block2_hello_world_attestation.json"
)


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "check_vnext_hello_world_attestation", SCRIPT
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _loaded(module: ModuleType) -> tuple[dict[str, object], object]:
    raw = ARTIFACT.read_bytes()
    bundle = module._load_json(raw, str(ARTIFACT))
    reader = module._git_reader(ROOT, bundle["source"]["commit"])
    return bundle, reader


def _ledger_hashes() -> dict[str, str]:
    return {
        path.as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted((ROOT / "ledger").rglob("*"))
        if path.is_file()
    }


def test_canonical_attestation_passes_without_ledger_effects() -> None:
    module = _module()
    bundle, reader = _loaded(module)
    before = _ledger_hashes()

    result = module.validate_attestation(bundle, reader)

    assert result["mint_uses"] == 3
    assert result["retired_tombstones"] == 1
    assert result["left_side"] == result["right_side"] == 19025
    assert _ledger_hashes() == before


def test_missing_operator_verdict_is_rejected() -> None:
    module = _module()
    bundle, reader = _loaded(module)
    bundle["authority"]["verdict"] = ""

    with pytest.raises(module.AttestationError, match="operator verdict"):
        module.validate_attestation(bundle, reader)


def test_mismatched_account_or_comment_is_rejected() -> None:
    module = _module()
    bundle, reader = _loaded(module)
    broken = copy.deepcopy(bundle)
    broken["mint_uses"][0]["submission"]["node_id"] = "IC_missing"

    with pytest.raises(module.AttestationError, match="absent from snapshot"):
        module.validate_attestation(broken, reader)

    broken = copy.deepcopy(bundle)
    broken["mint_uses"][0]["account"]["id"] = 1
    with pytest.raises(module.AttestationError, match="mismatch"):
        module.validate_attestation(broken, reader)


def test_invariant_mismatch_is_rejected() -> None:
    module = _module()
    bundle, reader = _loaded(module)
    bundle["invariant"]["balances"] += 1

    with pytest.raises(module.AttestationError, match="invariant does not match"):
        module.validate_attestation(bundle, reader)


def test_retired_tombstone_cannot_authorize_an_agent() -> None:
    module = _module()
    bundle, reader = _loaded(module)
    retired = next(
        row for row in bundle["mint_uses"] if row["disposition"] == "retired_tombstone"
    )
    retired["current_agent_id"] = "khattab-crow@openclaw"

    with pytest.raises(
        module.AttestationError, match="retired mint use fields mismatch"
    ):
        module.validate_attestation(bundle, reader)


def test_rehashed_replacement_verdict_is_rejected() -> None:
    module = _module()
    bundle, reader = _loaded(module)
    bundle["authority"]["verdict"] = "replacement verdict"
    bundle["authority"]["verdict_sha256"] = hashlib.sha256(
        b"replacement verdict"
    ).hexdigest()

    with pytest.raises(module.AttestationError, match="canonical authority"):
        module.validate_attestation(bundle, reader)


@pytest.mark.parametrize("replacement", [True, 1.0])
def test_schema_version_rejects_bool_and_float(replacement: object) -> None:
    module = _module()
    bundle, reader = _loaded(module)
    bundle["schema_version"] = replacement

    with pytest.raises(module.AttestationError, match="unsupported schema_version"):
        module.validate_attestation(bundle, reader)


@pytest.mark.parametrize("target", ["issue_body", "comment_body_hash", "comment_id"])
def test_unpinned_issue_or_comment_snapshot_is_rejected(target: str) -> None:
    module = _module()
    bundle, reader = _loaded(module)
    if target == "issue_body":
        bundle["issue_snapshot"]["body_sha256"] = "0" * 64
    elif target == "comment_body_hash":
        bundle["issue_snapshot"]["comments"][0]["body_sha256"] = "0" * 64
    else:
        bundle["issue_snapshot"]["comments"][0]["id"] += 1

    with pytest.raises(module.AttestationError, match="mismatch"):
        module.validate_attestation(bundle, reader)


@pytest.mark.parametrize("target", ["issue", "unselected_comment"])
def test_rehashed_replacement_body_bytes_are_rejected(target: str) -> None:
    module = _module()
    bundle, reader = _loaded(module)
    replacement = b"replacement REST body"
    encoded = base64.b64encode(replacement).decode("ascii")
    digest = hashlib.sha256(replacement).hexdigest()
    if target == "issue":
        bundle["issue_snapshot"]["body_utf8_base64"] = encoded
        bundle["issue_snapshot"]["body_sha256"] = digest
    else:
        comment = bundle["issue_snapshot"]["comments"][0]
        bundle["issue_snapshot"]["comment_body_utf8_base64"][comment["node_id"]] = (
            encoded
        )
        comment["body_sha256"] = digest

    with pytest.raises(module.AttestationError, match="canonical issue_snapshot"):
        module.validate_attestation(bundle, reader)


@pytest.mark.parametrize("mutation", ["missing", "extra"])
def test_source_hash_manifest_must_be_exact(mutation: str) -> None:
    module = _module()
    bundle, reader = _loaded(module)
    if mutation == "missing":
        del bundle["source"]["file_sha256"]["ledger/history/2026-03-05.jsonl"]
    else:
        bundle["source"]["file_sha256"]["ledger/unrelated.json"] = "0" * 64

    with pytest.raises(module.AttestationError, match="source file manifest mismatch"):
        module.validate_attestation(bundle, reader)


def test_unrelated_active_idempotency_key_is_rejected() -> None:
    module = _module()
    bundle, reader = _loaded(module)
    active = next(
        row for row in bundle["mint_uses"] if row["disposition"] == "active_alias"
    )
    active["idem_keys"] = ["register|cursor-3@cursor"]

    with pytest.raises(module.AttestationError, match="idempotency key set mismatch"):
        module.validate_attestation(bundle, reader)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("base_agent_id", "khattab-crow@openclaw"),
        ("account_binding", {"account_id": 264877938}),
        ("control_group_id", "peachgabba22"),
        ("mint_key", "hello-world:264877938"),
    ],
)
def test_retired_tombstone_rejects_extra_authority_fields(
    field: str, value: object
) -> None:
    module = _module()
    bundle, reader = _loaded(module)
    retired = next(
        row for row in bundle["mint_uses"] if row["disposition"] == "retired_tombstone"
    )
    retired[field] = value

    with pytest.raises(
        module.AttestationError, match="retired mint use fields mismatch"
    ):
        module.validate_attestation(bundle, reader)


@pytest.mark.parametrize(
    "target", ["root", "active", "account", "evidence", "reference"]
)
def test_closed_object_schemas_reject_unknown_fields(target: str) -> None:
    module = _module()
    bundle, reader = _loaded(module)
    active = next(
        row for row in bundle["mint_uses"] if row["disposition"] == "active_alias"
    )
    objects = {
        "root": bundle,
        "active": active,
        "account": active["account"],
        "evidence": active["submission"],
        "reference": active["mint_event"],
    }
    objects[target]["unexpected"] = True

    with pytest.raises(module.AttestationError, match="fields mismatch"):
        module.validate_attestation(bundle, reader)
