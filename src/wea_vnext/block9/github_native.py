"""GitHub-native candidate building and trusted pull-request validation.

The trusted guard reads candidate Git objects as data.  It never imports or
executes code from the pull request.  A candidate branch is not authoritative;
only its later merge into canonical ``main`` can make the ledger bytes live.
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import re
import ssl
import subprocess
import sys
from collections.abc import Callable, Mapping
from pathlib import Path

from .common import (
    Block9Error,
    canonical_bytes,
    require_hash,
    require_relative_path,
    require_text,
    sha256_hex,
)
from .migration import replay_genesis

COMMAND_MARKER = "<!-- wea-vnext-command -->\n"
REPOSITORY_ID = "1171421025"
TARGET_REF = "refs/heads/main"
WRITER_AGENT_ID = "agent0@system"
CANDIDATE_WORKFLOW = ".github/workflows/agent0-ledger-candidate.yml"
GUARD_WORKFLOW = ".github/workflows/guard-vnext-ledger.yml"
_CANDIDATE_WORKFLOW_REF = (
    f"WeTheAgents/wetheagents/{CANDIDATE_WORKFLOW}@refs/heads/main"
)
_CANDIDATE_RUN_PATH = CANDIDATE_WORKFLOW

_COMMAND_FIELDS = {
    "schema",
    "repository_id",
    "target_ref",
    "expected_predecessor",
    "writer_agent_id",
    "idempotency_key",
    "operation",
    "package_ref",
    "package_commit",
    "package_manifest_path",
    "package_manifest_sha256",
}
_PACKAGE_FIELDS = {
    "schema",
    "package_id",
    "repository_id",
    "target_ref",
    "expected_predecessor",
    "operation",
    "idempotency_key",
    "epoch_id",
    "sequence",
    "previous_event_hash",
    "files",
    "checks",
}
_PACKAGE_CHECK_FIELDS = {
    "event_hash",
    "genesis_sha256",
    "opening_supply",
    "state_sha256",
}
_PACKAGE_ROW_FIELDS = {"before_sha256", "sha256", "source", "target"}
_SOURCE_FIELDS = {
    "repository",
    "issue_number",
    "comment_id",
    "comment_url",
    "comment_author",
    "author_association",
    "body_sha256",
    "command_sha256",
}
_WORKFLOW_FIELDS = {
    "actor",
    "run_id",
    "run_attempt",
    "workflow_path",
    "workflow_ref",
    "workflow_sha",
}
_RECORD_FIELDS = {
    "schema",
    "repository_id",
    "target_ref",
    "expected_predecessor",
    "writer_agent_id",
    "operation",
    "idempotency_key",
    "package_id",
    "package_ref",
    "package_commit",
    "package_manifest_path",
    "package_manifest_sha256",
    "command_sha256",
    "source",
    "workflow",
    "target_files",
    "expected_paths",
}
_BOOTSTRAP_FIELDS = {
    "schema",
    "epoch_id",
    "predecessor",
    "repository_id",
    "target_ref",
    "workflow_path",
    "writer_agent_id",
}
_STATE_FIELDS = {
    "schema",
    "epoch_id",
    "sequence",
    "last_event_hash",
    "genesis_sha256",
    "runtime",
    "opening_supply",
    "balances",
    "active_escrows",
}
_RUNTIME_FIELDS = {
    "ruleset_hash",
    "tide_interface_version",
    "executor_manifest_hash",
}
_EVENT_FIELDS = {"sequence", "previous_event_hash", "payload", "event_hash"}
_EVENT_REQUIRED_PAYLOAD_FIELDS = {
    "event_type",
    "financial_postings",
    "idempotency_key",
    "operation",
    "prior_financial_hash",
    "resulting_financial_hash",
}
_POSTING_FIELDS = {"account_type", "account_id", "delta"}
_IDEMPOTENCY_FIELDS = {"schema", "keys"}
_SAFE_ID = re.compile(r"[a-z0-9][a-z0-9._-]{2,100}")
_SAFE_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{2,180}")
_EVENT_PATH = re.compile(r"ledger/vnext/events/([0-9]{16})\.json")
_GITHUB_API_PATH = re.compile(
    r"/repos/WeTheAgents/wetheagents/(?:issues/comments|actions/runs)/[1-9][0-9]*"
)


def _mapping(value: object, *, field: str) -> dict[str, object]:
    if type(value) is not dict:
        raise Block9Error(f"{field} must be an exact mapping")
    return value


def _list(value: object, *, field: str) -> list[object]:
    if type(value) is not list:
        raise Block9Error(f"{field} must be an exact list")
    return value


def _positive_int(value: object, *, field: str) -> int:
    if type(value) is not int or value <= 0:
        raise Block9Error(f"{field} must be a positive integer")
    return value


def _nonnegative_int(value: object, *, field: str) -> int:
    if type(value) is not int or value < 0:
        raise Block9Error(f"{field} must be a nonnegative integer")
    return value


def _safe_id(value: object, *, field: str) -> str:
    text = require_text(value, field=field)
    if not _SAFE_ID.fullmatch(text):
        raise Block9Error(f"{field} must be a path-safe lowercase ID")
    return text


def _load_canonical(raw: bytes, *, field: str) -> dict[str, object]:
    if type(raw) is not bytes:
        raise Block9Error(f"{field} must use exact bytes")
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Block9Error(f"{field} is not JSON") from exc
    if type(value) is not dict or canonical_bytes(value) != raw:
        raise Block9Error(f"{field} must use canonical JSON bytes")
    return value


def _git(root: Path, *arguments: str) -> bytes:
    if not isinstance(root, Path) or not root.is_dir():
        raise Block9Error("Git repository root is missing")
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *arguments],
            check=False,
            capture_output=True,
        )
    except OSError as exc:
        raise Block9Error("Git is unavailable") from exc
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise Block9Error(f"Git command failed: {message or arguments[0]}")
    return result.stdout


def _git_text(root: Path, *arguments: str) -> str:
    try:
        return _git(root, *arguments).decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise Block9Error("Git output is not UTF-8") from exc


def _git_file(root: Path, commit: str, path: str) -> bytes | None:
    require_hash(commit, field="Git commit", length=40)
    path = require_relative_path(path, field="Git path")
    try:
        return _git(root, "show", f"{commit}:{path}")
    except Block9Error as exc:
        # Missing paths are normal for before-image checks.  Do not hide other
        # repository failures behind a generic absence result.
        probe = subprocess.run(
            ["git", "-C", str(root), "cat-file", "-e", f"{commit}^{{commit}}"],
            check=False,
            capture_output=True,
        )
        if probe.returncode != 0:
            raise exc
        return None


def _git_paths(root: Path, commit: str, prefix: str) -> tuple[str, ...]:
    require_hash(commit, field="Git commit", length=40)
    prefix = require_relative_path(prefix, field="Git prefix")
    raw = _git(root, "ls-tree", "-r", "--name-only", "-z", commit, "--", prefix)
    try:
        paths = tuple(item.decode("utf-8") for item in raw.split(b"\0") if item)
    except UnicodeDecodeError as exc:
        raise Block9Error("Git path is not UTF-8") from exc
    return paths


def parse_command_comment(body: str) -> bytes:
    """Extract one exact canonical command from a GitHub comment body."""

    if type(body) is not str or not body.startswith(COMMAND_MARKER):
        raise Block9Error("command comment marker is missing or not first")
    raw = body[len(COMMAND_MARKER) :].encode("utf-8")
    _validate_command(raw)
    return raw


def _validate_command(raw: bytes) -> dict[str, object]:
    command = _load_canonical(raw, field="command")
    if set(command) != _COMMAND_FIELDS:
        raise Block9Error("command fields are incomplete")
    if command["schema"] != "wea-vnext-command-1":
        raise Block9Error("command schema is unknown")
    if command["repository_id"] != REPOSITORY_ID:
        raise Block9Error("command repository identity changed")
    if command["target_ref"] != TARGET_REF:
        raise Block9Error("command target ref changed")
    if command["writer_agent_id"] != WRITER_AGENT_ID:
        raise Block9Error("command writer must be agent0@system")
    require_hash(
        command["expected_predecessor"],
        field="command predecessor",
        length=40,
    )
    _safe_id(command["idempotency_key"], field="command idempotency_key")
    if command["operation"] not in {"activate", "transaction", "repair"}:
        raise Block9Error("command operation is unknown")
    package_ref = require_text(command["package_ref"], field="package_ref")
    if not _SAFE_REF.fullmatch(package_ref) or package_ref.startswith("/"):
        raise Block9Error("package_ref is not a safe branch name")
    require_hash(command["package_commit"], field="package_commit", length=40)
    require_relative_path(
        command["package_manifest_path"], field="package_manifest_path"
    )
    require_hash(command["package_manifest_sha256"], field="package manifest hash")
    return command


def _validate_source_evidence(
    value: Mapping[str, object], command: bytes
) -> dict[str, object]:
    source = dict(value)
    if set(source) != _SOURCE_FIELDS:
        raise Block9Error("command source evidence fields are incomplete")
    if source["repository"] != "WeTheAgents/wetheagents":
        raise Block9Error("command source repository changed")
    _positive_int(source["issue_number"], field="source issue_number")
    _positive_int(source["comment_id"], field="source comment_id")
    require_text(source["comment_url"], field="source comment_url")
    require_text(source["comment_author"], field="source comment_author")
    if source["author_association"] != "OWNER":
        raise Block9Error("command source must have GitHub OWNER association")
    require_hash(source["body_sha256"], field="source body hash")
    require_hash(source["command_sha256"], field="source command hash")
    if source["command_sha256"] != sha256_hex(command):
        raise Block9Error("command source does not bind the exact command")
    body = (COMMAND_MARKER + command.decode("utf-8")).encode("utf-8")
    if source["body_sha256"] != sha256_hex(body):
        raise Block9Error("command source body hash changed")
    return source


def _validate_workflow_evidence(
    value: Mapping[str, object], *, predecessor: str, actor: str
) -> dict[str, object]:
    workflow = dict(value)
    if set(workflow) != _WORKFLOW_FIELDS:
        raise Block9Error("workflow evidence fields are incomplete")
    if workflow["workflow_path"] != CANDIDATE_WORKFLOW:
        raise Block9Error("candidate workflow path changed")
    if workflow["workflow_ref"] != _CANDIDATE_WORKFLOW_REF:
        raise Block9Error("candidate workflow ref is not canonical main")
    require_hash(workflow["workflow_sha"], field="workflow_sha", length=40)
    if workflow["workflow_sha"] != predecessor:
        raise Block9Error("candidate workflow does not bind the predecessor")
    if workflow["actor"] != actor:
        raise Block9Error("workflow actor differs from the command author")
    _positive_int(workflow["run_id"], field="workflow run_id")
    _positive_int(workflow["run_attempt"], field="workflow run_attempt")
    return workflow


def _manifest_payloads(
    command: Mapping[str, object],
    manifest_raw: bytes,
    *,
    read_source: Callable[[str], bytes | None],
) -> tuple[dict[str, object], dict[str, bytes]]:
    manifest = _load_canonical(manifest_raw, field="package manifest")
    if set(manifest) != _PACKAGE_FIELDS:
        raise Block9Error("package manifest fields are incomplete")
    if manifest["schema"] != "wea-vnext-package-1":
        raise Block9Error("package manifest schema is unknown")
    package_id = _safe_id(manifest["package_id"], field="package_id")
    del package_id
    for field in (
        "repository_id",
        "target_ref",
        "expected_predecessor",
        "operation",
        "idempotency_key",
    ):
        if manifest[field] != command[field]:
            raise Block9Error(f"package manifest changed command field: {field}")
    require_text(manifest["epoch_id"], field="package epoch_id")
    sequence = _nonnegative_int(manifest["sequence"], field="package sequence")
    require_hash(manifest["previous_event_hash"], field="previous event hash")
    if command["operation"] == "activate":
        if sequence != 0 or manifest["previous_event_hash"] != "0" * 64:
            raise Block9Error("activation package must start at sequence zero")
    checks = _mapping(manifest["checks"], field="package checks")
    if set(checks) != _PACKAGE_CHECK_FIELDS:
        raise Block9Error("package checks are incomplete")
    for field in ("event_hash", "genesis_sha256", "state_sha256"):
        require_hash(checks[field], field=f"package checks.{field}")
    _nonnegative_int(checks["opening_supply"], field="package opening_supply")

    manifest_dir = str(Path(str(command["package_manifest_path"])).parent).replace(
        "\\", "/"
    )
    rows = _list(manifest["files"], field="package files")
    if not rows:
        raise Block9Error("package file set is empty")
    payloads: dict[str, bytes] = {}
    sources: set[str] = set()
    for raw_row in rows:
        row = _mapping(raw_row, field="package file row")
        if set(row) != _PACKAGE_ROW_FIELDS:
            raise Block9Error("package file row fields are incomplete")
        source = require_relative_path(row["source"], field="package source")
        target = require_relative_path(row["target"], field="package target")
        if not target.startswith("ledger/vnext/") or not target.endswith(".json"):
            raise Block9Error("package target is outside canonical vNext JSON")
        if source in sources or target in payloads:
            raise Block9Error("package source or target appears more than once")
        sources.add(source)
        require_hash(row["sha256"], field="package file hash")
        before = row["before_sha256"]
        if before is not None:
            require_hash(before, field="package before hash")
        full_source = f"{manifest_dir}/{source}" if manifest_dir != "." else source
        content = read_source(full_source)
        if content is None or sha256_hex(content) != row["sha256"]:
            raise Block9Error(f"package source bytes changed: {source}")
        _load_canonical(content, field=f"package source {source}")
        payloads[target] = content
    event_path = f"ledger/vnext/events/{sequence:016d}.json"
    expected_targets = {
        "ledger/vnext/idempotency.json",
        "ledger/vnext/state.json",
        event_path,
    }
    if command["operation"] == "activate":
        expected_targets |= {
            "ledger/vnext/bootstrap.json",
            "ledger/vnext/genesis.json",
        }
    if set(payloads) != expected_targets:
        raise Block9Error("package target set is not the exact next transaction")
    return manifest, payloads


def _financial_projection(state: Mapping[str, object]) -> dict[str, object]:
    return {
        "active_escrows": state["active_escrows"],
        "balances": state["balances"],
        "opening_supply": state["opening_supply"],
    }


def _financial_hash(state: Mapping[str, object]) -> str:
    return sha256_hex(canonical_bytes(_financial_projection(state)))


def _opening_financial_projection(genesis: Mapping[str, object]) -> dict[str, object]:
    balances = _mapping(genesis["balances"], field="genesis balances")
    opening = {
        "active_escrows": {},
        "balances": {
            require_text(agent_id, field="genesis balance Agent ID"): _nonnegative_int(
                amount, field=f"genesis balance.{agent_id}"
            )
            for agent_id, amount in balances.items()
        },
        "opening_supply": _nonnegative_int(
            genesis["opening_supply"], field="genesis opening_supply"
        ),
    }
    if sum(opening["balances"].values()) != opening["opening_supply"]:
        raise Block9Error("genesis balances do not equal opening supply")
    return opening


def _apply_financial_postings(
    state: Mapping[str, object], payload: Mapping[str, object]
) -> dict[str, object]:
    """Apply one explicit, balanced financial transition to derived state."""

    balances = dict(_mapping(state["balances"], field="replay balances"))
    escrows = dict(_mapping(state["active_escrows"], field="replay escrows"))
    postings = _list(payload["financial_postings"], field="financial_postings")
    seen: set[tuple[str, str]] = set()
    total_delta = 0
    for raw_posting in postings:
        posting = _mapping(raw_posting, field="financial posting")
        if set(posting) != _POSTING_FIELDS:
            raise Block9Error("financial posting fields are incomplete")
        account_type = posting["account_type"]
        if account_type not in {"balance", "escrow"}:
            raise Block9Error("financial posting account type is unknown")
        account_id = require_text(posting["account_id"], field="posting account_id")
        if account_id != account_id.strip():
            raise Block9Error("financial posting account ID is not canonical")
        key = (str(account_type), account_id)
        if key in seen:
            raise Block9Error("financial posting account appears more than once")
        seen.add(key)
        delta = posting["delta"]
        if type(delta) is not int or delta == 0:
            raise Block9Error("financial posting delta must be a nonzero integer")
        total_delta += delta
        accounts = balances if account_type == "balance" else escrows
        if account_type == "balance" and account_id not in accounts:
            raise Block9Error("financial posting names an unknown Agent balance")
        current = accounts.get(account_id, 0)
        if type(current) is not int or current < 0:
            raise Block9Error("financial replay account is invalid")
        result = current + delta
        if result < 0:
            raise Block9Error("financial posting makes an account negative")
        if account_type == "escrow" and result == 0:
            accounts.pop(account_id, None)
        else:
            accounts[account_id] = result
    if total_delta != 0:
        raise Block9Error("financial postings are not balanced")
    if payload["operation"] == "repair" and payload["event_type"] == "replay_repair":
        if postings:
            raise Block9Error("replay repair must not change financial state")
    return {
        "active_escrows": escrows,
        "balances": balances,
        "opening_supply": state["opening_supply"],
    }


def _validate_vnext_tree(
    *,
    read_file: Callable[[str], bytes | None],
    paths: tuple[str, ...],
) -> dict[str, object]:
    allowed_fixed = {
        "ledger/vnext/bootstrap.json",
        "ledger/vnext/genesis.json",
        "ledger/vnext/idempotency.json",
        "ledger/vnext/state.json",
    }
    path_set = set(paths)
    if not allowed_fixed <= path_set:
        raise Block9Error("canonical vNext tree is incomplete")
    unexpected = sorted(
        path
        for path in path_set
        if path not in allowed_fixed and not _EVENT_PATH.fullmatch(path)
    )
    if unexpected:
        raise Block9Error(f"canonical vNext path is unknown: {unexpected[0]}")

    bootstrap_raw = read_file("ledger/vnext/bootstrap.json")
    genesis_raw = read_file("ledger/vnext/genesis.json")
    state_raw = read_file("ledger/vnext/state.json")
    idempotency_raw = read_file("ledger/vnext/idempotency.json")
    if None in (bootstrap_raw, genesis_raw, state_raw, idempotency_raw):
        raise Block9Error("canonical vNext fixed files are missing")
    assert bootstrap_raw is not None
    assert genesis_raw is not None
    assert state_raw is not None
    assert idempotency_raw is not None

    bootstrap = _load_canonical(bootstrap_raw, field="bootstrap")
    if set(bootstrap) != _BOOTSTRAP_FIELDS:
        raise Block9Error("bootstrap fields are incomplete")
    expected_bootstrap = {
        "schema": "wea-vnext-github-bootstrap-1",
        "repository_id": REPOSITORY_ID,
        "target_ref": TARGET_REF,
        "writer_agent_id": WRITER_AGENT_ID,
        "workflow_path": CANDIDATE_WORKFLOW,
    }
    if any(bootstrap.get(key) != value for key, value in expected_bootstrap.items()):
        raise Block9Error("bootstrap GitHub authority changed")
    require_text(bootstrap["epoch_id"], field="bootstrap epoch_id")
    require_hash(bootstrap["predecessor"], field="bootstrap predecessor", length=40)

    genesis = replay_genesis(genesis_raw)
    if genesis["predecessor"] != bootstrap["predecessor"]:
        raise Block9Error("genesis predecessor differs from bootstrap")
    state = _load_canonical(state_raw, field="state")
    if set(state) != _STATE_FIELDS or state["schema"] != "wea-vnext-github-state-1":
        raise Block9Error("state schema or fields are incomplete")
    if state["epoch_id"] != bootstrap["epoch_id"]:
        raise Block9Error("state epoch differs from bootstrap")
    if state["genesis_sha256"] != sha256_hex(genesis_raw):
        raise Block9Error("state genesis hash changed")
    runtime = _mapping(state["runtime"], field="state runtime")
    if set(runtime) != _RUNTIME_FIELDS:
        raise Block9Error("state runtime is incomplete")
    require_hash(runtime["ruleset_hash"], field="runtime ruleset_hash")
    require_hash(
        runtime["executor_manifest_hash"], field="runtime executor_manifest_hash"
    )
    require_text(runtime["tide_interface_version"], field="runtime interface")

    balances = _mapping(state["balances"], field="state balances")
    escrows = _mapping(state["active_escrows"], field="state active_escrows")
    balance_total = sum(
        _nonnegative_int(amount, field=f"balance.{agent_id}")
        for agent_id, amount in balances.items()
        if require_text(agent_id, field="balance Agent ID")
    )
    escrow_total = sum(
        _nonnegative_int(amount, field=f"escrow.{escrow_id}")
        for escrow_id, amount in escrows.items()
        if require_text(escrow_id, field="escrow ID")
    )
    opening_supply = _nonnegative_int(
        state["opening_supply"], field="state opening_supply"
    )
    if balance_total + escrow_total != opening_supply:
        raise Block9Error("state money does not equal opening supply")
    if balances != genesis["balances"] and state["sequence"] == 0:
        raise Block9Error("activation state balances differ from genesis")
    if opening_supply != genesis["opening_supply"]:
        raise Block9Error("state opening supply differs from genesis")

    event_paths = sorted(path for path in path_set if _EVENT_PATH.fullmatch(path))
    if not event_paths:
        raise Block9Error("canonical event chain is empty")
    previous = "0" * 64
    idempotency_expected: dict[str, str] = {}
    replayed_financial = _opening_financial_projection(genesis)
    for sequence, path in enumerate(event_paths):
        expected_path = f"ledger/vnext/events/{sequence:016d}.json"
        if path != expected_path:
            raise Block9Error("canonical event sequence is not contiguous")
        raw = read_file(path)
        if raw is None:
            raise Block9Error("canonical event is missing")
        event = _load_canonical(raw, field=f"event {sequence}")
        if set(event) != _EVENT_FIELDS:
            raise Block9Error("canonical event fields are incomplete")
        if event["sequence"] != sequence or event["previous_event_hash"] != previous:
            raise Block9Error("canonical event sequence or predecessor changed")
        payload = _mapping(event["payload"], field="event payload")
        if not _EVENT_REQUIRED_PAYLOAD_FIELDS <= set(payload):
            raise Block9Error("canonical event payload is incomplete")
        key = _safe_id(payload["idempotency_key"], field="event idempotency_key")
        if key in idempotency_expected:
            raise Block9Error("canonical idempotency key is repeated")
        event_type = require_text(payload["event_type"], field="event_type")
        operation = payload["operation"]
        if operation not in {"activate", "transaction", "repair"}:
            raise Block9Error("event operation is unknown")
        prior_financial_hash = require_hash(
            payload["prior_financial_hash"], field="prior financial hash"
        )
        resulting_financial_hash = require_hash(
            payload["resulting_financial_hash"], field="resulting financial hash"
        )
        if sequence == 0:
            if (
                operation != "activate"
                or event_type != "epoch_started"
                or prior_financial_hash != "0" * 64
                or payload["financial_postings"] != []
                or payload.get("genesis_sha256") != sha256_hex(genesis_raw)
            ):
                raise Block9Error("sequence zero activation evidence is incomplete")
        else:
            accepted_types = {
                "transaction": {"transaction_applied"},
                "repair": {"financial_correction", "replay_repair"},
            }
            if operation == "activate" or event_type not in accepted_types.get(
                str(operation), set()
            ):
                raise Block9Error("event type does not match its operation")
            if prior_financial_hash != _financial_hash(replayed_financial):
                raise Block9Error("event prior financial state changed during replay")
            replayed_financial = _apply_financial_postings(
                replayed_financial, payload
            )
        if resulting_financial_hash != _financial_hash(replayed_financial):
            raise Block9Error("event result differs from semantic financial replay")
        core = {
            "payload": payload,
            "previous_event_hash": previous,
            "sequence": sequence,
        }
        event_hash = sha256_hex(canonical_bytes(core))
        if event["event_hash"] != event_hash:
            raise Block9Error("canonical event hash changed")
        idempotency_expected[key] = event_hash
        previous = event_hash
    if state["sequence"] != len(event_paths) - 1:
        raise Block9Error("state sequence differs from the event chain")
    if state["last_event_hash"] != previous:
        raise Block9Error("state event hash differs from the event chain")
    if _financial_projection(state) != replayed_financial:
        raise Block9Error("state differs from semantic financial replay")

    idempotency = _load_canonical(idempotency_raw, field="idempotency index")
    if set(idempotency) != _IDEMPOTENCY_FIELDS:
        raise Block9Error("idempotency index fields are incomplete")
    if idempotency["schema"] != "wea-vnext-idempotency-1":
        raise Block9Error("idempotency index schema is unknown")
    keys = _mapping(idempotency["keys"], field="idempotency keys")
    if keys != idempotency_expected:
        raise Block9Error("idempotency index differs from the event chain")
    return state


def _validate_package_checks(
    manifest: Mapping[str, object], payloads: Mapping[str, bytes]
) -> None:
    sequence = _nonnegative_int(manifest["sequence"], field="package sequence")
    event_path = f"ledger/vnext/events/{sequence:016d}.json"
    state = payloads.get("ledger/vnext/state.json")
    event = payloads.get(event_path)
    if state is None or event is None:
        raise Block9Error("package lacks its next event or resulting state")
    checks = _mapping(manifest["checks"], field="package checks")
    event_value = _load_canonical(event, field="package event")
    if checks["event_hash"] != event_value.get("event_hash"):
        raise Block9Error("package event check changed")
    if checks["state_sha256"] != sha256_hex(state):
        raise Block9Error("package state check changed")
    genesis = payloads.get("ledger/vnext/genesis.json")
    if manifest["operation"] == "activate":
        if genesis is None or checks["genesis_sha256"] != sha256_hex(genesis):
            raise Block9Error("package genesis check changed")
    state_value = _load_canonical(state, field="package state")
    if checks["opening_supply"] != state_value.get("opening_supply"):
        raise Block9Error("package supply check changed")


def _package_from_commit(
    root: Path, command: Mapping[str, object]
) -> tuple[bytes, dict[str, object], dict[str, bytes]]:
    commit = str(command["package_commit"])
    manifest_path = str(command["package_manifest_path"])
    manifest_raw = _git_file(root, commit, manifest_path)
    if manifest_raw is None:
        raise Block9Error("package manifest is absent from the package commit")
    if sha256_hex(manifest_raw) != command["package_manifest_sha256"]:
        raise Block9Error("package manifest hash changed")
    manifest, payloads = _manifest_payloads(
        command,
        manifest_raw,
        read_source=lambda path: _git_file(root, commit, path),
    )
    _validate_package_checks(manifest, payloads)
    return manifest_raw, manifest, payloads


def build_candidate(
    root: Path,
    *,
    command: bytes,
    source_evidence: Mapping[str, object],
    workflow_evidence: Mapping[str, object],
) -> dict[str, object]:
    """Materialize one non-authoritative candidate from exact GitHub evidence."""

    command_value = _validate_command(command)
    predecessor = str(command_value["expected_predecessor"])
    head = _git_text(root, "rev-parse", "HEAD")
    if head != predecessor:
        raise Block9Error("candidate predecessor differs from checked-out HEAD")
    tracked = _git_text(root, "status", "--porcelain", "--untracked-files=no")
    if tracked:
        raise Block9Error("candidate checkout has tracked changes before build")
    source = _validate_source_evidence(source_evidence, command)
    workflow = _validate_workflow_evidence(
        workflow_evidence,
        predecessor=predecessor,
        actor=str(source["comment_author"]),
    )
    manifest_raw, manifest, payloads = _package_from_commit(root, command_value)

    for raw_row in _list(manifest["files"], field="package files"):
        row = _mapping(raw_row, field="package file row")
        target = str(row["target"])
        before = _git_file(root, predecessor, target)
        expected_before = row["before_sha256"]
        actual_before = sha256_hex(before) if before is not None else None
        if actual_before != expected_before:
            raise Block9Error(f"package before-image changed: {target}")

    package_id = str(manifest["package_id"])
    evidence_root = f"evidence/vnext/github-transactions/{package_id}"
    source_by_target = {
        str(_mapping(row, field="package row")["target"]): str(
            _mapping(row, field="package row")["source"]
        )
        for row in _list(manifest["files"], field="package files")
    }
    written: dict[str, bytes] = {}
    for target, content in sorted(payloads.items()):
        written[target] = content
        source_path = source_by_target[target]
        written[f"{evidence_root}/package/{source_path}"] = content
    written[f"{evidence_root}/command.json"] = command
    written[f"{evidence_root}/package.json"] = manifest_raw

    record_path = f"{evidence_root}/candidate.json"
    expected_paths = sorted((*written, record_path))
    record: dict[str, object] = {
        "schema": "wea-vnext-github-candidate-1",
        "repository_id": REPOSITORY_ID,
        "target_ref": TARGET_REF,
        "expected_predecessor": predecessor,
        "writer_agent_id": WRITER_AGENT_ID,
        "operation": command_value["operation"],
        "idempotency_key": command_value["idempotency_key"],
        "package_id": package_id,
        "package_ref": command_value["package_ref"],
        "package_commit": command_value["package_commit"],
        "package_manifest_path": command_value["package_manifest_path"],
        "package_manifest_sha256": command_value["package_manifest_sha256"],
        "command_sha256": sha256_hex(command),
        "source": source,
        "workflow": workflow,
        "target_files": {
            path: sha256_hex(content) for path, content in sorted(payloads.items())
        },
        "expected_paths": expected_paths,
    }
    written[record_path] = canonical_bytes(record)
    for relative, content in written.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return record


def _changed_paths(
    root: Path,
    base: str,
    candidate: str,
    *,
    allow_deletions: bool = False,
) -> tuple[str, ...]:
    raw = _git(root, "diff", "--name-status", "--no-renames", "-z", base, candidate)
    parts = raw.split(b"\0")
    paths: list[str] = []
    index = 0
    while index < len(parts) and parts[index]:
        try:
            status = parts[index].decode("ascii")
            path = parts[index + 1].decode("utf-8")
        except (IndexError, UnicodeDecodeError) as exc:
            raise Block9Error("candidate diff is unreadable") from exc
        accepted_statuses = {"A", "M", "D"} if allow_deletions else {"A", "M"}
        if status not in accepted_statuses:
            raise Block9Error("candidate diff contains a deletion or rename")
        paths.append(require_relative_path(path, field="candidate path"))
        index += 2
    return tuple(sorted(paths))


def _source_snapshot(root: Path, commit: str) -> dict[str, bytes]:
    raw = _git(root, "ls-tree", "-r", "--name-only", "-z", commit)
    try:
        paths = tuple(item.decode("utf-8") for item in raw.split(b"\0") if item)
    except UnicodeDecodeError as exc:
        raise Block9Error("source path is not UTF-8") from exc
    suffixes = {
        ".bat",
        ".cjs",
        ".cmd",
        ".cs",
        ".go",
        ".java",
        ".js",
        ".mjs",
        ".php",
        ".ps1",
        ".py",
        ".rb",
        ".rs",
        ".sh",
        ".toml",
        ".ts",
        ".yaml",
        ".yml",
    }
    prefixes = (".github/actions/", ".github/workflows/", "scripts/", "src/")
    selected = {
        path
        for path in paths
        if path == "pyproject.toml"
        or (
            path.startswith(prefixes)
            and (
                Path(path).suffix.lower() in suffixes
                or not Path(path).suffix
            )
        )
    }
    snapshot: dict[str, bytes] = {}
    for path in sorted(selected):
        content = _git_file(root, commit, path)
        if content is None:  # pragma: no cover - ls-tree proved existence
            raise Block9Error(f"source disappeared from Git tree: {path}")
        snapshot[path] = content
    return snapshot


def validate_pull_request_commits(
    root: Path,
    *,
    base_commit: str,
    candidate_commit: str,
    api_get: Callable[[str], object] | None = None,
) -> dict[str, object] | None:
    """Route one pull request through the ledger or writer-boundary proof."""

    changed = _changed_paths(
        root, base_commit, candidate_commit, allow_deletions=True
    )
    has_vnext_ledger = any(path.startswith("ledger/vnext/") for path in changed)
    has_transaction_evidence = any(
        path.startswith("evidence/vnext/github-transactions/") for path in changed
    )
    if has_vnext_ledger or has_transaction_evidence:
        if not has_vnext_ledger or not has_transaction_evidence:
            raise Block9Error(
                "ledger and GitHub transaction evidence must change together"
            )
        return validate_candidate_commits(
            root,
            base_commit=base_commit,
            candidate_commit=candidate_commit,
            api_get=api_get,
        )
    legacy_ledger = [path for path in changed if path.startswith("ledger/")]
    if legacy_ledger:
        raise Block9Error(
            f"legacy direct ledger change is retired: {legacy_ledger[0]}"
        )
    from .writer import validate_writer_boundary_sources

    validate_writer_boundary_sources(
        _source_snapshot(root, base_commit),
        _source_snapshot(root, candidate_commit),
    )
    return None


def _candidate_record_path(root: Path, base: str, candidate: str) -> str:
    records = [
        path
        for path in _changed_paths(root, base, candidate)
        if path.startswith("evidence/vnext/github-transactions/")
        and path.endswith("/candidate.json")
    ]
    if len(records) != 1:
        raise Block9Error("candidate must contain exactly one transaction record")
    return records[0]


def validate_candidate_commits(
    root: Path,
    *,
    base_commit: str,
    candidate_commit: str,
    api_get: Callable[[str], object] | None = None,
) -> dict[str, object]:
    """Validate a candidate using only trusted code and Git object bytes."""

    require_hash(base_commit, field="base commit", length=40)
    require_hash(candidate_commit, field="candidate commit", length=40)
    commit_line = _git_text(
        root, "rev-list", "--parents", "-n", "1", candidate_commit
    ).split()
    if commit_line != [candidate_commit, base_commit]:
        raise Block9Error("candidate must be one direct child of the predecessor")
    record_path = _candidate_record_path(root, base_commit, candidate_commit)
    record_raw = _git_file(root, candidate_commit, record_path)
    if record_raw is None:
        raise Block9Error("candidate transaction record is missing")
    record = _load_canonical(record_raw, field="candidate record")
    if set(record) != _RECORD_FIELDS:
        raise Block9Error("candidate record fields are incomplete")
    if record["schema"] != "wea-vnext-github-candidate-1":
        raise Block9Error("candidate record schema is unknown")
    if record["expected_predecessor"] != base_commit:
        raise Block9Error("candidate predecessor differs from pull-request base")
    fixed = {
        "repository_id": REPOSITORY_ID,
        "target_ref": TARGET_REF,
        "writer_agent_id": WRITER_AGENT_ID,
    }
    if any(record.get(key) != value for key, value in fixed.items()):
        raise Block9Error("candidate GitHub authority changed")
    expected_paths = tuple(
        require_relative_path(path, field="candidate expected path")
        for path in _list(record["expected_paths"], field="candidate expected paths")
    )
    if expected_paths != tuple(sorted(set(expected_paths))):
        raise Block9Error("candidate expected path set is not canonical")
    if _changed_paths(root, base_commit, candidate_commit) != expected_paths:
        raise Block9Error("candidate changed path set differs from its proof")

    evidence_root = record_path.removesuffix("/candidate.json")
    command_path = f"{evidence_root}/command.json"
    manifest_path = f"{evidence_root}/package.json"
    command_raw = _git_file(root, candidate_commit, command_path)
    manifest_raw = _git_file(root, candidate_commit, manifest_path)
    if command_raw is None or manifest_raw is None:
        raise Block9Error("candidate command or package evidence is missing")
    command = _validate_command(command_raw)
    if record["command_sha256"] != sha256_hex(command_raw):
        raise Block9Error("candidate command hash changed")
    for field in (
        "repository_id",
        "target_ref",
        "expected_predecessor",
        "writer_agent_id",
        "operation",
        "idempotency_key",
        "package_ref",
        "package_commit",
        "package_manifest_path",
        "package_manifest_sha256",
    ):
        if record[field] != command[field]:
            raise Block9Error(f"candidate command field changed: {field}")
    if sha256_hex(manifest_raw) != command["package_manifest_sha256"]:
        raise Block9Error("candidate package manifest hash changed")
    source = _validate_source_evidence(
        _mapping(record["source"], field="candidate source"), command_raw
    )
    workflow = _validate_workflow_evidence(
        _mapping(record["workflow"], field="candidate workflow"),
        predecessor=base_commit,
        actor=str(source["comment_author"]),
    )

    package_manifest_dir = str(
        Path(str(command["package_manifest_path"])).parent
    ).replace("\\", "/")

    def read_evidence_source(source_path: str) -> bytes | None:
        relative = source_path
        if package_manifest_dir != ".":
            prefix = f"{package_manifest_dir}/"
            if not source_path.startswith(prefix):
                raise Block9Error("package source escaped its manifest directory")
            relative = source_path.removeprefix(prefix)
        return _git_file(
            root,
            candidate_commit,
            f"{evidence_root}/package/{relative}",
        )

    manifest, payloads = _manifest_payloads(
        command,
        manifest_raw,
        read_source=read_evidence_source,
    )
    _validate_package_checks(manifest, payloads)
    sequence = _nonnegative_int(manifest["sequence"], field="package sequence")
    base_tree_paths = _git_paths(root, base_commit, "ledger/vnext")
    if command["operation"] == "activate":
        if base_tree_paths:
            raise Block9Error("activation predecessor already contains vNext")
    else:
        base_state = _validate_vnext_tree(
            read_file=lambda path: _git_file(root, base_commit, path),
            paths=base_tree_paths,
        )
        if sequence != _nonnegative_int(
            base_state["sequence"], field="base state sequence"
        ) + 1:
            raise Block9Error("package sequence is not the next transaction")
        if manifest["previous_event_hash"] != base_state["last_event_hash"]:
            raise Block9Error("package does not extend the canonical event chain")
    if record["package_id"] != manifest["package_id"]:
        raise Block9Error("candidate package ID changed")
    target_files = _mapping(record["target_files"], field="candidate target files")
    expected_target_files = {
        path: sha256_hex(content) for path, content in sorted(payloads.items())
    }
    if target_files != expected_target_files:
        raise Block9Error("candidate target-file proof changed")
    for raw_row in _list(manifest["files"], field="package files"):
        row = _mapping(raw_row, field="package file row")
        target = str(row["target"])
        before = _git_file(root, base_commit, target)
        actual_before = sha256_hex(before) if before is not None else None
        if actual_before != row["before_sha256"]:
            raise Block9Error(f"candidate before-image changed: {target}")
        candidate_bytes = _git_file(root, candidate_commit, target)
        if candidate_bytes != payloads[target]:
            raise Block9Error(f"candidate target differs from package: {target}")

    tree_paths = _git_paths(root, candidate_commit, "ledger/vnext")
    state = _validate_vnext_tree(
        read_file=lambda path: _git_file(root, candidate_commit, path),
        paths=tree_paths,
    )
    if state["sequence"] != sequence:
        raise Block9Error("package sequence differs from canonical state")
    event_path = f"ledger/vnext/events/{sequence:016d}.json"
    event_raw = _git_file(root, candidate_commit, event_path)
    assert event_raw is not None
    event = _load_canonical(event_raw, field="candidate next event")
    if event["previous_event_hash"] != manifest["previous_event_hash"]:
        raise Block9Error("package predecessor event hash changed")
    payload = _mapping(event["payload"], field="candidate next event payload")
    if (
        payload["idempotency_key"] != command["idempotency_key"]
        or payload["operation"] != command["operation"]
    ):
        raise Block9Error("candidate event differs from command")
    base_idempotency_raw = _git_file(
        root, base_commit, "ledger/vnext/idempotency.json"
    )
    if base_idempotency_raw is not None:
        base_idempotency = _load_canonical(
            base_idempotency_raw, field="base idempotency index"
        )
        base_keys = _mapping(
            base_idempotency.get("keys"), field="base idempotency keys"
        )
        if command["idempotency_key"] in base_keys:
            raise Block9Error("candidate idempotency key was already accepted")
    if api_get is not None:
        _verify_remote_evidence(
            command_raw=command_raw,
            source=source,
            workflow=workflow,
            predecessor=base_commit,
            api_get=api_get,
        )
    return record


def _verify_remote_evidence(
    *,
    command_raw: bytes,
    source: Mapping[str, object],
    workflow: Mapping[str, object],
    predecessor: str,
    api_get: Callable[[str], object],
) -> None:
    repository = str(source["repository"])
    comment = _mapping(
        api_get(f"/repos/{repository}/issues/comments/{source['comment_id']}"),
        field="GitHub comment",
    )
    user = _mapping(comment.get("user"), field="GitHub comment user")
    body = comment.get("body")
    if type(body) is not str or parse_command_comment(body) != command_raw:
        raise Block9Error("live GitHub comment differs from the command")
    if (
        comment.get("html_url") != source["comment_url"]
        or comment.get("author_association") != "OWNER"
        or user.get("login") != source["comment_author"]
        or sha256_hex(body.encode("utf-8")) != source["body_sha256"]
    ):
        raise Block9Error("live GitHub command source evidence changed")
    issue_url = comment.get("issue_url")
    if type(issue_url) is not str or not issue_url.endswith(
        f"/issues/{source['issue_number']}"
    ):
        raise Block9Error("live GitHub command Issue changed")

    run = _mapping(
        api_get(f"/repos/{repository}/actions/runs/{workflow['run_id']}"),
        field="GitHub workflow run",
    )
    actor = _mapping(run.get("actor"), field="GitHub workflow actor")
    if (
        run.get("event") != "workflow_dispatch"
        or run.get("head_sha") != predecessor
        or run.get("run_attempt") != workflow["run_attempt"]
        or run.get("path") != _CANDIDATE_RUN_PATH
        or run.get("status") != "completed"
        or run.get("conclusion") != "success"
        or actor.get("login") != workflow["actor"]
    ):
        raise Block9Error("live GitHub Agent0 workflow evidence changed")


def _api_getter(token: str, api_url: str) -> Callable[[str], object]:
    require_text(token, field="GitHub token")
    api_url = require_text(api_url, field="GitHub API URL").rstrip("/")
    if api_url != "https://api.github.com":
        raise Block9Error("GitHub API origin is not canonical")

    def get(path: str) -> object:
        if type(path) is not str or not _GITHUB_API_PATH.fullmatch(path):
            raise Block9Error("GitHub API path is outside the canonical evidence set")
        tls_context = ssl.create_default_context()
        connection = http.client.HTTPSConnection(  # nosemgrep
            "api.github.com", timeout=30, context=tls_context
        )
        try:
            connection.request(
                "GET",
                path,
                headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": "2022-11-28",
                },
            )
            response = connection.getresponse()
            raw = response.read()
            if response.status != 200:
                raise Block9Error(f"GitHub API read failed: {path}")
        except (OSError, http.client.HTTPException) as exc:
            raise Block9Error(f"GitHub API read failed: {path}") from exc
        finally:
            connection.close()
        try:
            return json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise Block9Error("GitHub API response is not JSON") from exc

    return get


def fetch_command(
    *,
    repository: str,
    issue_number: int,
    comment_id: int,
    expected_sha256: str,
    api_get: Callable[[str], object],
) -> tuple[bytes, dict[str, object]]:
    if repository != "WeTheAgents/wetheagents":
        raise Block9Error("command repository is not canonical")
    _positive_int(issue_number, field="issue_number")
    _positive_int(comment_id, field="comment_id")
    require_hash(expected_sha256, field="expected command hash")
    comment = _mapping(
        api_get(f"/repos/{repository}/issues/comments/{comment_id}"),
        field="GitHub comment",
    )
    user = _mapping(comment.get("user"), field="GitHub comment user")
    body = comment.get("body")
    if type(body) is not str:
        raise Block9Error("GitHub command comment body is missing")
    command = parse_command_comment(body)
    if sha256_hex(command) != expected_sha256:
        raise Block9Error("GitHub command hash differs from workflow input")
    issue_url = comment.get("issue_url")
    if type(issue_url) is not str or not issue_url.endswith(f"/issues/{issue_number}"):
        raise Block9Error("GitHub comment belongs to a different Issue")
    source = _validate_source_evidence(
        {
            "repository": repository,
            "issue_number": issue_number,
            "comment_id": comment_id,
            "comment_url": comment.get("html_url"),
            "comment_author": user.get("login"),
            "author_association": comment.get("author_association"),
            "body_sha256": sha256_hex(body.encode("utf-8")),
            "command_sha256": sha256_hex(command),
        },
        command,
    )
    return command, source


def _write_github_outputs(path: Path, command: Mapping[str, object]) -> None:
    lines = []
    for field in ("package_ref", "package_commit", "package_manifest_path"):
        value = str(command[field])
        if "\n" in value or "\r" in value:
            raise Block9Error("GitHub output contains a newline")
        lines.append(f"{field}={value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command_name", required=True)

    fetch = subparsers.add_parser("fetch-command")
    fetch.add_argument("--repository", required=True)
    fetch.add_argument("--issue-number", required=True, type=int)
    fetch.add_argument("--comment-id", required=True, type=int)
    fetch.add_argument("--expected-sha256", required=True)
    fetch.add_argument("--output", required=True, type=Path)
    fetch.add_argument("--source-output", required=True, type=Path)
    fetch.add_argument("--github-output", type=Path)

    build = subparsers.add_parser("build")
    build.add_argument("--root", default=".", type=Path)
    build.add_argument("--command", required=True, type=Path)
    build.add_argument("--source", required=True, type=Path)
    build.add_argument("--actor", required=True)
    build.add_argument("--run-id", required=True, type=int)
    build.add_argument("--run-attempt", required=True, type=int)
    build.add_argument("--workflow-ref", required=True)
    build.add_argument("--workflow-sha", required=True)

    validate = subparsers.add_parser("validate-pr")
    validate.add_argument("--root", default=".", type=Path)
    validate.add_argument("--base", required=True)
    validate.add_argument("--candidate", required=True)
    validate.add_argument("--verify-github", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command_name == "fetch-command":
            token = os.environ.get("GITHUB_TOKEN", "")
            getter = _api_getter(token, os.environ.get("GITHUB_API_URL", "https://api.github.com"))
            command, source = fetch_command(
                repository=args.repository,
                issue_number=args.issue_number,
                comment_id=args.comment_id,
                expected_sha256=args.expected_sha256,
                api_get=getter,
            )
            args.output.write_bytes(command)
            args.source_output.write_bytes(canonical_bytes(source))
            if args.github_output is not None:
                _write_github_outputs(args.github_output, _validate_command(command))
        elif args.command_name == "build":
            command = args.command.read_bytes()
            source = _load_canonical(args.source.read_bytes(), field="source evidence")
            build_candidate(
                args.root,
                command=command,
                source_evidence=source,
                workflow_evidence={
                    "actor": args.actor,
                    "run_id": args.run_id,
                    "run_attempt": args.run_attempt,
                    "workflow_path": CANDIDATE_WORKFLOW,
                    "workflow_ref": args.workflow_ref,
                    "workflow_sha": args.workflow_sha,
                },
            )
        else:
            getter = None
            if args.verify_github:
                getter = _api_getter(
                    os.environ.get("GITHUB_TOKEN", ""),
                    os.environ.get("GITHUB_API_URL", "https://api.github.com"),
                )
            validate_pull_request_commits(
                args.root,
                base_commit=args.base,
                candidate_commit=args.candidate,
                api_get=getter,
            )
    except (Block9Error, OSError) as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
