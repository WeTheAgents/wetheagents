#!/usr/bin/env python3
"""Validate the read-only Block 2 historical Hello World attestation."""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, NoReturn

ARTIFACT = Path(__file__).with_name("block2_hello_world_attestation.json")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
EXPECTED_ACCOUNTS = {264877938, 265255605, 265329370}
EXPECTED_LOGINS = {
    264877938: "khattab-crow",
    265255605: "CursorWEA",
    265329370: "AntigravityWea",
}
EXPECTED_SECTION_SHA256 = {
    "authority": "68bd4ed5bc654c576c1bd0932c9b6c871de5b58f0427be0a7c706897da31ef85",
    "effects": "1fe21feffc339808078c3b8b8a91f1be82c46503e1e3f47838955e7ce4d8ff43",
    "invariant": "3abc331f95bc52825af8900d64babfd0672d42353aee4a5ea619e65461e06ec9",
    "issue_snapshot": (
        "affa14a98e3e998bdb1fb0b2fa30ee481c81f267f7762328909ca83e99a21639"
    ),
    "mint_uses": "93e1b3bfcffd48f3f5e7d4b18a1c4ec75ad040f748f723f673afb5e26ba6d631",
    "source": "b9806bfe88259513fc5f6ec76601182c0c1e2803a3c781499fc1de22a5a2c397",
}
EXPECTED_ROOT_KEYS = {
    "authority",
    "effects",
    "invariant",
    "issue_snapshot",
    "mint_uses",
    "purpose",
    "schema_version",
    "source",
}
EXPECTED_FILE_PATHS = {
    "ledger/agent_aliases.json",
    "ledger/balances.json",
    "ledger/escrows.json",
    "ledger/history/2026-03-03.jsonl",
    "ledger/history/2026-03-05.jsonl",
    "ledger/history/2026-03-07.jsonl",
    "ledger/idem_keys.json",
    "ledger/trajectory_mints.json",
}
EXPECTED_IDEM_KEYS = {
    265255605: {"hello_world|cursor-3@cursor"},
    265329370: {
        "hello_world|Antigravity-1@Google",
        "hello_world|gemini-4@google",
    },
}
SOURCE_KEYS = {"repository", "commit", "captured_on", "file_sha256"}
AUTHORITY_KEYS = {
    "kind",
    "operator_login",
    "operator_account_id",
    "accepted_on",
    "verdict",
    "verdict_sha256",
}
ISSUE_KEYS = {
    "repository_id_scope",
    "issue_number",
    "issue_id",
    "issue_node_id",
    "author_login",
    "author_account_id",
    "created_at",
    "updated_at",
    "body_sha256",
    "body_utf8_base64",
    "comment_body_utf8_base64",
    "comments",
}
COMMENT_KEYS = {
    "id",
    "node_id",
    "author_login",
    "author_account_id",
    "created_at",
    "updated_at",
    "body_sha256",
}
ACTIVE_MINT_KEYS = {
    "disposition",
    "account",
    "submission",
    "decision",
    "legacy_agent_id",
    "current_agent_id",
    "mint_event",
    "burn_event",
    "alias",
    "idem_keys",
}
RETIRED_MINT_KEYS = {
    "disposition",
    "account",
    "submission",
    "decision",
    "legacy_agent_id",
    "mint_event",
    "retirement_event",
    "mint_key_state",
    "active_authority",
}
ACCOUNT_KEYS = {"id", "login"}
COMMENT_EVIDENCE_KEYS = {"node_id", "body_sha256"}
EVENT_REFERENCE_KEYS = {"path", "line", "sha256"}
ALIAS_KEYS = {"from", "to"}
INVARIANT_KEYS = {
    "base_supply",
    "balances",
    "active_escrow",
    "trajectory_minted",
    "left_side",
    "right_side",
}
EFFECT_KEYS = {
    "ledger_writes",
    "github_writes",
    "new_mints",
    "balance_delta",
    "live_vnext_authority",
}


class AttestationError(ValueError):
    """Raised when historical evidence is incomplete or inconsistent."""


def _fail(message: str) -> NoReturn:
    raise AttestationError(message)


def _require(condition: bool, message: str) -> None:
    if not condition:
        _fail(message)


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail(f"{label} must be an object")
    return value


def _array(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        _fail(f"{label} must be an array")
    return value


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        _fail(f"{label} must be a non-empty string")
    return value


def _positive_int(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        _fail(f"{label} must be a positive integer")
    return value


def _exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    _require(set(value) == expected, f"{label} fields mismatch")


def _body_bytes(value: Any, label: str) -> bytes:
    encoded = _text(value, label)
    try:
        return base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise AttestationError(f"{label} is not canonical base64") from exc


def _load_json(raw: bytes, label: str) -> dict[str, Any]:
    def reject_duplicate(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                _fail(f"{label}: duplicate key {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=reject_duplicate)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AttestationError(f"{label}: invalid UTF-8 JSON") from exc
    return _object(value, f"{label}: root")


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_sha256(value: Any) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _sha256(raw)


def _git_reader(root: Path, commit: str) -> Callable[[str], bytes]:
    _require(
        bool(re.fullmatch(r"[0-9a-f]{40}", commit)), "source.commit must be a full SHA"
    )

    def read(path: str) -> bytes:
        _require(
            not Path(path).is_absolute() and ".." not in Path(path).parts,
            f"unsafe path: {path}",
        )
        result = subprocess.run(
            ["git", "-C", str(root), "show", f"{commit}:{path}"],
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            detail = result.stderr.decode("utf-8", errors="replace").strip()
            _fail(f"cannot read {path} at {commit}: {detail}")
        return result.stdout

    return read


def _json_source(read_source: Callable[[str], bytes], path: str) -> dict[str, Any]:
    return _load_json(read_source(path), path)


def _event(
    read_source: Callable[[str], bytes],
    reference: dict[str, Any],
    allowed_paths: set[str],
    label: str,
) -> dict[str, Any]:
    _exact_keys(reference, EVENT_REFERENCE_KEYS, label)
    path = _text(reference.get("path"), f"{label}.path")
    _require(path in allowed_paths, f"{label}.path is absent from source manifest")
    line_number = _positive_int(reference.get("line"), f"{label}.line")
    expected_sha = _text(reference.get("sha256"), f"{label}.sha256")
    _require(
        SHA256_RE.fullmatch(expected_sha) is not None,
        f"{label}.sha256 invalid",
    )
    lines = read_source(path).splitlines()
    _require(line_number <= len(lines), f"{label}: line {line_number} missing")
    raw = lines[line_number - 1]
    _require(_sha256(raw) == expected_sha, f"{label}: row hash mismatch")
    return _load_json(raw, label)


def _plain_nonnegative_int(value: Any, label: str) -> int:
    _require(
        isinstance(value, int) and not isinstance(value, bool) and value >= 0,
        f"{label} must be a non-negative integer",
    )
    return value


def validate_attestation(
    bundle: dict[str, Any], read_source: Callable[[str], bytes]
) -> dict[str, int]:
    _require(set(bundle) == EXPECTED_ROOT_KEYS, "attestation root fields mismatch")
    schema_version = bundle.get("schema_version")
    _require(
        type(schema_version) is int and schema_version == 1,
        "unsupported schema_version",
    )
    _require(
        bundle.get("purpose") == "block2_historical_hello_world_attestation",
        "unexpected purpose",
    )

    source = _object(bundle.get("source"), "source")
    authority = _object(bundle.get("authority"), "authority")
    issue = _object(bundle.get("issue_snapshot"), "issue_snapshot")
    uses = _array(bundle.get("mint_uses"), "mint_uses")
    invariant = _object(bundle.get("invariant"), "invariant")
    effects = _object(bundle.get("effects"), "effects")
    _exact_keys(source, SOURCE_KEYS, "source")
    _exact_keys(authority, AUTHORITY_KEYS, "authority")
    _exact_keys(issue, ISSUE_KEYS, "issue_snapshot")
    _exact_keys(invariant, INVARIANT_KEYS, "invariant")
    _exact_keys(effects, EFFECT_KEYS, "effects")

    _require(
        source.get("repository") == "WeTheAgents/wetheagents",
        "wrong source repository",
    )
    _require(source.get("captured_on") == "2026-07-28", "wrong capture date")
    verdict = _text(authority.get("verdict"), "operator verdict")
    _require(
        authority.get("kind") == "operator_verdict",
        "authority kind must be operator_verdict",
    )
    _require(
        authority.get("operator_login") == "peachgabba22", "unexpected operator login"
    )
    _require(
        authority.get("operator_account_id") == 129645949, "unexpected operator account"
    )
    _require(authority.get("accepted_on") == "2026-07-28", "wrong verdict date")
    _require(bool(verdict.strip()), "operator verdict missing")
    _require(
        _sha256(verdict.encode("utf-8")) == authority.get("verdict_sha256"),
        "operator verdict hash mismatch",
    )

    file_hashes = _object(source.get("file_sha256"), "source file hashes")
    _require(set(file_hashes) == EXPECTED_FILE_PATHS, "source file manifest mismatch")
    for path, expected_sha in file_hashes.items():
        expected_sha = _text(expected_sha, f"source file hash for {path}")
        _require(
            SHA256_RE.fullmatch(expected_sha) is not None, f"invalid SHA-256 for {path}"
        )
        _require(
            _sha256(read_source(path)) == expected_sha,
            f"source file hash mismatch: {path}",
        )

    _require(
        issue.get("repository_id_scope") == "WeTheAgents/wetheagents",
        "wrong issue repository",
    )
    _require(issue.get("issue_number") == 1, "wrong issue number")
    _require(issue.get("issue_id") == 4015417565, "wrong permanent issue id")
    _require(issue.get("issue_node_id") == "I_kwDORdJ3Yc7vVmjd", "wrong issue node id")
    _require(issue.get("author_account_id") == 129645949, "wrong issue author")
    _require(issue.get("author_login") == "peachgabba22", "wrong issue author login")
    _require(
        SHA256_RE.fullmatch(str(issue.get("body_sha256", ""))) is not None,
        "issue body hash missing",
    )
    issue_body = _body_bytes(issue.get("body_utf8_base64"), "issue body")
    _require(
        _sha256(issue_body) == issue.get("body_sha256"), "issue body bytes mismatch"
    )
    comment_bodies = _object(
        issue.get("comment_body_utf8_base64"), "comment body snapshot"
    )
    comments = _array(issue.get("comments"), "issue comments")
    _require(len(comments) == 11, "expected exactly 11 comment snapshots")
    by_node: dict[str, dict[str, Any]] = {}
    numeric_ids: set[int] = set()
    for raw_comment in comments:
        comment = _object(raw_comment, "comment snapshot")
        _exact_keys(comment, COMMENT_KEYS, "comment snapshot")
        node_id = _text(comment.get("node_id"), "comment node id")
        numeric_id = _positive_int(comment.get("id"), "comment id")
        _require(
            node_id not in by_node,
            "duplicate or missing comment node id",
        )
        _require(
            numeric_id not in numeric_ids,
            "duplicate or missing comment id",
        )
        _require(
            comment.get("created_at") == comment.get("updated_at"),
            f"edited comment is not attested: {node_id}",
        )
        _require(
            SHA256_RE.fullmatch(str(comment.get("body_sha256", ""))) is not None,
            f"comment body hash missing: {node_id}",
        )
        comment_body = _body_bytes(
            comment_bodies.get(node_id), f"comment body {node_id}"
        )
        _require(
            _sha256(comment_body) == comment.get("body_sha256"),
            f"comment body bytes mismatch: {node_id}",
        )
        by_node[node_id] = comment
        numeric_ids.add(numeric_id)
    _require(set(comment_bodies) == set(by_node), "comment body snapshot set mismatch")

    _require(len(uses) == 3, "expected exactly three historical mint uses")
    aliases = _json_source(read_source, "ledger/agent_aliases.json")
    balances = _json_source(read_source, "ledger/balances.json")
    idem_root = _json_source(read_source, "ledger/idem_keys.json")
    idem_keys = _object(idem_root.get("keys"), "ledger/idem_keys.json keys")
    agents = _object(balances.get("agents"), "ledger/balances.json agents")

    retired_count = 0
    account_ids: set[int] = set()
    for raw_row in uses:
        row = _object(raw_row, "mint use")
        disposition = row.get("disposition")
        if disposition == "active_alias":
            _exact_keys(row, ACTIVE_MINT_KEYS, "active mint use")
        elif disposition == "retired_tombstone":
            _exact_keys(row, RETIRED_MINT_KEYS, "retired mint use")
        else:
            _fail(f"unknown mint disposition: {disposition!r}")
        account = _object(row.get("account"), "mint account")
        submission = _object(row.get("submission"), "submission evidence")
        decision = _object(row.get("decision"), "decision evidence")
        _exact_keys(account, ACCOUNT_KEYS, "mint account")
        _exact_keys(submission, COMMENT_EVIDENCE_KEYS, "submission evidence")
        _exact_keys(decision, COMMENT_EVIDENCE_KEYS, "decision evidence")
        account_id = _positive_int(account.get("id"), "account id")
        account_login = _text(account.get("login"), "account login")
        _require(
            EXPECTED_LOGINS.get(account_id) == account_login,
            "historical account login mismatch",
        )
        account_ids.add(account_id)
        for evidence, role, expected_author, expected_login in (
            (submission, "submission", account_id, account_login),
            (decision, "decision", 129645949, "peachgabba22"),
        ):
            evidence_node_id = _text(evidence.get("node_id"), f"{role} node id")
            snapshot = by_node.get(evidence_node_id)
            if snapshot is None:
                _fail(f"{role} comment is absent from snapshot")
            _require(
                snapshot.get("body_sha256") == evidence.get("body_sha256"),
                f"{role} body hash mismatch",
            )
            _require(
                snapshot.get("author_account_id") == expected_author,
                f"{role} author mismatch",
            )
            _require(
                snapshot.get("author_login") == expected_login,
                f"{role} author login mismatch",
            )

        legacy_agent_id = _text(row.get("legacy_agent_id"), "legacy_agent_id")
        mint_reference = _object(row.get("mint_event"), "mint_event")
        mint = _event(read_source, mint_reference, EXPECTED_FILE_PATHS, "mint_event")
        _require(
            mint.get("issue") == 1
            and mint.get("agent") == legacy_agent_id
            and mint.get("amount") == 100,
            "mint event mismatch",
        )
        _require(
            mint.get("type") == "hello_world_mint"
            or (mint.get("type") == "mint" and mint.get("reason") == "hello_world"),
            "not a Hello World mint",
        )

        if disposition == "active_alias":
            current_agent_id = _text(row.get("current_agent_id"), "current_agent_id")
            alias = _object(row.get("alias"), "alias")
            keys = _array(row.get("idem_keys"), "idem_keys")
            _exact_keys(alias, ALIAS_KEYS, "alias")
            _require(
                current_agent_id in agents,
                "active mint has no current agent",
            )
            _require(
                alias.get("from") == legacy_agent_id
                and alias.get("to") == current_agent_id,
                "alias evidence mismatch",
            )
            _require(
                aliases.get(legacy_agent_id) == current_agent_id,
                "ledger alias mismatch",
            )
            _require(
                bool(keys)
                and all(isinstance(key, str) and key in idem_keys for key in keys),
                "idempotency evidence missing",
            )
            _require(
                set(keys) == EXPECTED_IDEM_KEYS[account_id]
                and len(keys) == len(EXPECTED_IDEM_KEYS[account_id]),
                "Hello World idempotency key set mismatch",
            )
            burn_reference = _object(row.get("burn_event"), "burn_event")
            burn = _event(
                read_source, burn_reference, EXPECTED_FILE_PATHS, "burn_event"
            )
            _require(
                burn.get("type") == "economy_reset" and burn.get("mint_burned") == 200,
                "active-account burn event mismatch",
            )
            agents_zeroed = _array(burn.get("agents_zeroed"), "agents_zeroed")
            _require(
                legacy_agent_id in agents_zeroed,
                "active account absent from reset event",
            )
        elif disposition == "retired_tombstone":
            retired_count += 1
            _require(
                row.get("active_authority") is False,
                "retired tombstone cannot grant authority",
            )
            _require(
                "current_agent_id" not in row
                and "alias" not in row
                and "idem_keys" not in row,
                "retired tombstone cannot carry active identity fields",
            )
            retirement_reference = _object(
                row.get("retirement_event"), "retirement_event"
            )
            retirement = _event(
                read_source,
                retirement_reference,
                EXPECTED_FILE_PATHS,
                "retirement_event",
            )
            _require(
                retirement.get("type") == "agent_removal"
                and retirement.get("agent") == legacy_agent_id,
                "retirement event mismatch",
            )
            _require(
                retirement.get("mint_burned") == 100, "retired mint was not burned"
            )
            _require(
                legacy_agent_id not in agents, "retired agent is active in balances"
            )
            _require(
                legacy_agent_id not in aliases
                and legacy_agent_id not in aliases.values(),
                "retired agent has an active alias",
            )
            _require(
                not any(legacy_agent_id in key for key in idem_keys),
                "retired agent has an active idempotency binding",
            )
            _require(
                row.get("mint_key_state") == "used_retired",
                "retired mint key must remain used",
            )
    _require(account_ids == EXPECTED_ACCOUNTS, "historical account set mismatch")
    _require(retired_count == 1, "expected exactly one retired tombstone")

    escrows = _json_source(read_source, "ledger/escrows.json")
    trajectory = _json_source(read_source, "ledger/trajectory_mints.json")
    balance_total = 0
    for agent, raw_value in agents.items():
        value = _object(raw_value, f"balance entry {agent}")
        balance_total += _plain_nonnegative_int(
            value.get("balance", 0), f"balance {agent}"
        )
    active = _object(escrows.get("active"), "ledger/escrows.json active")
    escrow_total = 0
    for issue_id, raw_value in active.items():
        value = _object(raw_value, f"escrow entry {issue_id}")
        escrow_total += _plain_nonnegative_int(
            value.get("amount", 0), f"escrow {issue_id}"
        )
    minted_total = _plain_nonnegative_int(
        trajectory.get("total_minted"), "trajectory total_minted"
    )
    mints = _array(trajectory.get("mints"), "trajectory mints")
    mint_sum = 0
    for raw_value in mints:
        value = _object(raw_value, "trajectory mint")
        mint_sum += _plain_nonnegative_int(
            value.get("amount", 0), "trajectory mint amount"
        )
    _require(mint_sum == minted_total, "trajectory mint total mismatch")
    expected = {
        "base_supply": 10000,
        "balances": balance_total,
        "active_escrow": escrow_total,
        "trajectory_minted": minted_total,
        "left_side": balance_total + escrow_total,
        "right_side": 10000 + minted_total,
    }
    _require(
        invariant == expected, "attested WEA invariant does not match pinned ledger"
    )
    _require(expected["left_side"] == expected["right_side"], "WEA invariant fails")

    _require(
        effects
        == {
            "ledger_writes": 0,
            "github_writes": 0,
            "new_mints": 0,
            "balance_delta": 0,
            "live_vnext_authority": False,
        },
        "effects must remain read-only and fail-closed",
    )
    for section_name, expected_sha in EXPECTED_SECTION_SHA256.items():
        _require(
            _canonical_sha256(bundle[section_name]) == expected_sha,
            f"canonical {section_name} snapshot mismatch",
        )
    return {"mint_uses": len(uses), "retired_tombstones": retired_count, **expected}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[4]
    )
    parser.add_argument("--artifact", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    artifact_path = (args.artifact or ARTIFACT).resolve()
    try:
        raw = artifact_path.read_bytes()
        bundle = _load_json(raw, str(artifact_path))
        source = _object(bundle.get("source"), "source")
        commit = _text(source.get("commit"), "source.commit")
        result = validate_attestation(bundle, _git_reader(root, commit))
    except (OSError, AttestationError) as exc:
        print(f"FAIL: {exc}")
        return 1
    print("PASS: Block 2 historical Hello World attestation is complete and read-only")
    print(f"Canonical artifact SHA-256: {_canonical_sha256(bundle)}")
    mint_uses = result["mint_uses"]
    retired_tombstones = result["retired_tombstones"]
    print(f"Mint uses: {mint_uses} (retired tombstones: {retired_tombstones})")
    print(f"WEA invariant: {result['left_side']} = {result['right_side']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
