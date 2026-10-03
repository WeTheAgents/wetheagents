"""Explicit pending Hello World installation, native replay and financial adapter."""

from __future__ import annotations

import hashlib
import importlib.util
from importlib import resources
from pathlib import Path
from typing import Any

from ..engine import RuntimeReference, installed_executor, load_executor
from . import collection, records
from .replay import ReplayError, digest

EXECUTOR = "0.11.0"
SCHEMA = "wea-hello-world-evidence-1"


def package_files() -> dict[str, str]:
    """Fingerprint all installed WEA Python/JSON bytes, including old runtimes."""
    hashes = {}
    for package in ("wea_vnext", "wea_cli"):
        pending = [(resources.files(package), package)]
        while pending:
            directory, prefix = pending.pop()
            for entry in directory.iterdir():
                path = f"{prefix}/{entry.name}"
                if entry.is_dir() and entry.name != "__pycache__":
                    pending.append((entry, path))
                elif entry.is_file() and entry.name.endswith((".py", ".json")):
                    hashes[path] = hashlib.sha256(entry.read_bytes()).hexdigest()
    return dict(sorted(hashes.items()))


def package_hash() -> str:
    """Hash the complete source-package identity, excluding review documents."""
    return digest(package_files())


def validate_historical(root: Path) -> dict[str, Any]:
    """Reuse the accepted read-only validator and its pinned Git inputs."""
    path = (
        root
        / "oled/changes/wea-vnext-recreation/evidence/check_hello_world_attestation.py"
    )
    spec = importlib.util.spec_from_file_location("hello_world_attestation", path)
    if spec is None or spec.loader is None:
        raise ReplayError("accepted historical validator is missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    artifact = path.with_name("block2_hello_world_attestation.json")
    bundle = module._load_json(artifact.read_bytes(), str(artifact))
    result = module.validate_attestation(
        bundle, module._git_reader(root, bundle["source"]["commit"])
    )
    # This inventory detects uncovered ledger records; it does not reinterpret
    # historical comments or infer eligibility from an absent current key.
    import json

    known = {row["mint_event"]["sha256"] for row in bundle["mint_uses"]}
    for path in sorted((root / "ledger/history").glob("*.jsonl")):
        for number, raw in enumerate(path.read_bytes().splitlines(), 1):
            if not raw.strip():
                continue
            row = json.loads(raw)
            if row.get("type") == "hello_world_mint" or (
                row.get("type") == "mint" and row.get("reason") == "hello_world"
            ):
                if hashlib.sha256(raw).hexdigest() not in known:
                    raise ReplayError(
                        "uncovered historical Hello World mint "
                        "requires explicit mapping: "
                        f"{path.name}:{number}"
                    )
    keys = json.loads((root / "ledger/idem_keys.json").read_bytes())
    observed = {
        key
        for section in (keys, keys.get("keys", {}))
        for key in section
        if key.startswith("hello_world|")
    }
    attested = {key for row in bundle["mint_uses"] for key in row.get("idem_keys", [])}
    if observed - attested:
        raise ReplayError(
            "uncovered historical Hello World keys require explicit mapping"
        )
    return result


def checkpoint(engine: Any, predecessor: str) -> dict[str, str]:
    """Bind canonical admission and balances at the separately installed base."""
    state = engine.state()
    if state["cutoff"] is None:
        raise ReplayError("Hello World requires a canonical Tide cutoff")
    return {
        "predecessor": predecessor,
        "state_hash": digest(state),
        "installation_sha256": package_hash(),
        "identities_hash": digest(engine.registry.to_data()),
        "cutoff": state["cutoff"],
    }


def _source_window_hash(captured: dict[str, Any]) -> str:
    """Hash original collector bytes before Work artifact enrichment.

    Artifact bytes keep their own hashes and remain in the full Tide batch.
    The trusted guard still compares the complete enriched collection with
    independent authenticated source and artifact reads.
    """
    window = {
        **captured,
        "sources": [
            {
                key: value
                for key, value in row.items()
                if key not in {"artifact", "artifact_error"}
            }
            for row in captured["sources"]
        ],
    }
    return digest(collection.cutoff_evidence(window))


def collect_hello_world_sources(api_get, api_graphql, *, cutoff, tracked_issues=(1,)):
    """Capture the permanent Issue explicitly without changing task discovery."""
    endpoint = f"{collection.API_ROOT}/issues/1"
    before = api_get(endpoint)
    captured = collection.collect_sources(
        api_get,
        api_graphql,
        cutoff=cutoff,
        tracked_issues=sorted(set(tracked_issues) | {1}),
    )
    after = api_get(endpoint)
    keys = ("id", "node_id", "body", "state", "updated_at")
    if (
        any(before.get(key) != after.get(key) for key in keys)
        or after.get("id") != 4015417565
    ):
        raise collection.CollectionError(
            "permanent Hello World Issue changed during capture"
        )
    sources = captured["sources"]
    issues = [
        row
        for row in sources
        if row["object_kind"] == "issue" and row["issue_number"] == 1
    ]
    if len(issues) != 1 or issues[0]["body"] != after["body"]:
        raise collection.CollectionError(
            "Hello World Issue snapshot is missing or inconsistent"
        )
    issues[0]["issue_state"] = after["state"]
    return {
        **captured,
        "sources": sources,
        "capture_hash": digest(
            collection.cutoff_evidence({**captured, "sources": sources})
        ),
    }


def preview(
    engine: Any, predecessor: str, packet: dict[str, Any], *, root: Path
) -> dict[str, Any]:
    """Calculate candidate effects from evidence; publish and mutate nothing."""
    if (
        set(packet) != {"schema", "runtime", "checkpoint", "collection"}
        or packet["schema"] != SCHEMA
    ):
        raise ReplayError("Hello World evidence packet fields do not match")
    expected = installed_executor(EXECUTOR).reference
    if packet["runtime"] != list(expected):
        raise ReplayError("Hello World preview requires the explicit candidate runtime")
    opening = engine
    activation_base = packet["checkpoint"]["predecessor"]
    if activation_base != predecessor:
        from .ledger import git, load

        # A later canonical admission extends identities without replacing the
        # original activation checkpoint or reauthorizing the operator event.
        git(root, "merge-base", "--is-ancestor", activation_base, predecessor)
        opening, _ = load(root, activation_base)
    point = checkpoint(opening, activation_base)
    if packet["checkpoint"] != point:
        raise ReplayError("Hello World activation checkpoint is stale")
    validate_historical(root)
    captured = packet["collection"]
    if captured.get("schema") != "wea-tide-collection-1":
        raise ReplayError("Hello World collection schema differs")
    if captured["repository_id"] != str(collection.REPOSITORY_ID) or captured[
        "tracked_issues"
    ] != [1]:
        raise ReplayError("Hello World collection requires permanent Issue #1")
    if captured["capture_hash"] != _source_window_hash(captured):
        raise ReplayError("Hello World collection hash differs")
    modules, evidence = native_evidence(packet, captured)
    source = modules["sources"]
    result = source.call_verified(
        "replay_hello_world",
        github_state=evidence,
        registry=records.registry(modules, engine.registry.to_data()),
        opening_registry=records.registry(modules, opening.registry.to_data()),
        checkpoint=point,
        previous=getattr(engine, "hello_world", None),
    )
    balances = dict(engine.balances)
    for mint in result["mint_intents"]:
        balances[mint["agent_id"]] = (
            balances.get(mint["agent_id"], 0) + mint["amount_wea"]
        )
    delta = sum(mint["amount_wea"] for mint in result["mint_intents"])
    if sum(balances.values()) + engine.state()["escrow_wea"] != engine.supply + delta:
        raise ReplayError("Hello World candidate financial invariant differs")
    return {
        "status": "candidate-only; installation and activation pending",
        "hello_world": result,
        "balances": balances,
        "supply_wea": engine.supply + delta,
        "task_state_hash": digest(engine.state()),
        "writes": 0,
    }


def native_evidence(anchor, captured):
    expected = RuntimeReference(*anchor["runtime"])
    modules = load_executor(RuntimeReference(*anchor["runtime"])).import_modules(
        ("sources", "identity")
    )
    source = modules["sources"]
    # Native types are resolved together from the same verified closure.
    events = []
    for raw in captured["sources"]:
        if raw["issue_number"] != 1:
            continue
        if raw["revision_status"] != "confirmed" or raw["repository_id"] != str(
            collection.REPOSITORY_ID
        ):
            raise ReplayError("Hello World source boundary is unresolved or foreign")
        payload = {
            key: raw[key]
            for key in (
                "issue_id",
                "issue_number",
                "revision_status",
                "original_author_account_id",
                "created_at",
                "edit_history",
            )
        }
        if raw["object_kind"] == "issue":
            payload["issue_state"] = raw["issue_state"]
        event = source.GitHubEvent(
            repository_id=raw["repository_id"],
            object_kind=raw["object_kind"],
            object_id=raw["object_id"],
            revision_id=raw["revision_id"],
            effective_at=records.timestamp(raw["effective_at"]),
            body=raw["body"],
            content_hash=raw["content_hash"],
            actor_account_id=raw["actor_account_id"],
            payload=payload,
        )
        events.append(event)
    boundary = source.GitHubReadBoundary(
        repository=collection.REPOSITORY,
        repository_id=str(collection.REPOSITORY_ID),
        captured_at=records.timestamp(captured["cutoff"]),
        read_sequence=1,
        end_cursor=f"hello-world:{captured['capture_hash']}",
        complete=True,
    )
    initial = source.ProtocolState(
        schema_version=1,
        ruleset_hash=expected.ruleset_hash,
        tide_interface_version=expected.tide_interface_version,
        executor_manifest_hash=expected.executor_manifest_hash,
    )
    evidence = source.accept_github_batch(
        initial, source.GitHubEventBatch(boundary=boundary, events=events)
    ).state
    return modules, evidence


BATCH_SCHEMA = "wea-tide-batch-5"
INSTALLATION_MARKER = "<!-- wea:hello-world-installation -->\n"


def installation_source(anchor, captured):
    """Select the exact independent operator installation from captured sources."""
    import json

    rows = [
        r
        for r in captured["sources"]
        if r["revision_id"] == anchor["installation_revision_id"]
    ]
    if len(rows) != 1:
        raise ReplayError("Hello World installation source is missing")
    row = rows[0]
    if (
        row["issue_id"] != "4015417565"
        or row["issue_number"] != 1
        or row["object_kind"] != "issue_comment"
        or row["actor_account_id"] != "129645949"
        or row["original_author_account_id"] != "129645949"
        or row["revision_status"] != "confirmed"
        or row["edit_history"] != []
        or records.timestamp(row["created_at"])
        != records.timestamp(row["effective_at"])
        or not row["revision_id"].endswith(":created")
        or not row["body"].startswith(INSTALLATION_MARKER)
        or hashlib.sha256(row["body"].encode()).hexdigest() != row["content_hash"]
    ):
        raise ReplayError(
            "Hello World installation requires an unedited "
            "authenticated operator source"
        )

    def unique_fields(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ReplayError("duplicate Hello World installation field")
            result[key] = value
        return result

    decision = json.loads(
        row["body"][len(INSTALLATION_MARKER) :], object_pairs_hook=unique_fields
    )
    if decision != {
        "schema": "wea-hello-world-installation-1",
        "runtime": anchor["runtime"],
        "checkpoint": anchor["checkpoint"],
    }:
        raise ReplayError(
            "Hello World installation does not bind the exact package and predecessor"
        )
    if records.timestamp(row["effective_at"]) <= records.timestamp(
        anchor["checkpoint"]["cutoff"]
    ):
        raise ReplayError("Hello World installation is stale")
    return row


def advance(engine, batch):
    """Apply only newly derived intents inside Tide's existing transaction."""
    import copy

    anchor = batch["hello_world"]
    if (
        set(anchor)
        != {
            "schema",
            "runtime",
            "checkpoint",
            "opening_identities",
            "installation_revision_id",
        }
        or anchor["schema"] != "wea-hello-world-anchor-1"
    ):
        raise ReplayError("Hello World anchor fields differ")
    if anchor["runtime"] != list(installed_executor(EXECUTOR).reference):
        raise ReplayError("Hello World runtime differs from the verified closure")
    if engine.hello_world_anchor is not None and anchor != engine.hello_world_anchor:
        raise ReplayError("Hello World activation anchor is immutable")
    if engine.hello_world_anchor is None:
        point = anchor["checkpoint"]
        if (
            point["predecessor"] != batch["predecessor"]
            or point["state_hash"] != digest(engine._hello_world_before)
            or point["identities_hash"] != digest(anchor["opening_identities"])
            or anchor["opening_identities"] != engine._hello_world_registry
        ):
            raise ReplayError("Hello World initial canonical checkpoint differs")
    captured = batch["collection"]
    if (
        captured.get("schema") != "wea-tide-collection-1"
        or captured.get("repository_id") != str(collection.REPOSITORY_ID)
        or 1 not in captured.get("tracked_issues", [])
        or captured.get("capture_hash") != _source_window_hash(captured)
    ):
        raise ReplayError("Hello World requires a complete authenticated collection")
    try:
        installed = installation_source(anchor, captured)
        modules, evidence = native_evidence(anchor, captured)
        source = modules["sources"]
        result = source.call_verified(
            "replay_hello_world",
            github_state=evidence,
            registry=records.registry(modules, engine.registry.to_data()),
            opening_registry=records.registry(modules, anchor["opening_identities"]),
            checkpoint=anchor["checkpoint"],
            previous=engine.hello_world,
            retain_failures=True,
        )
        activation = next(
            r
            for r in captured["sources"]
            if r["revision_id"] == result["activation_revision_id"]
        )
        if records.timestamp(activation["effective_at"]) <= records.timestamp(
            installed["effective_at"]
        ):
            raise ReplayError(
                "Hello World activation must follow separate installation"
            )
    except (ValueError, KeyError, TypeError, RecursionError) as exc:
        if engine.hello_world is None:
            raise
        engine.dispositions["hello-world:source-boundary"] = {
            "status": "unresolved",
            "reason": str(exc),
        }
        return
    if "hello-world:source-boundary" in engine.dispositions:
        engine.dispositions["hello-world:source-boundary"] = {
            "status": "resolved",
            "reason": "exact Hello World source boundary restored",
        }
    paid = (
        set()
        if engine.hello_world is None
        else {r["mint_key"] for r in engine.hello_world["records"]}
    )
    intents = result["mint_intents"]
    if len({m["idempotency_key"] for m in intents}) != len(intents):
        raise ReplayError("duplicate Hello World MintIntent")
    for mint in intents:
        if mint["idempotency_key"] in paid or mint["amount_wea"] != 42:
            raise ReplayError("Hello World repeated or invalid MintIntent")
        engine.balances[mint["agent_id"]] = (
            engine.balances.get(mint["agent_id"], 0) + 42
        )
        engine.supply += 42
    # Pending projections retain all immutable witnesses; batch intents are audit only.
    result["mint_intents"] = []
    engine.hello_world = result
    engine.hello_world_anchor = copy.deepcopy(anchor)
    for revision, outcome in result["dispositions"].items():
        engine.dispositions[revision] = {
            "status": "unresolved" if outcome.startswith("unresolved:") else "accepted",
            "reason": "Hello World: " + outcome,
        }


def prepare_anchor(engine, predecessor, installation_revision_id):
    """An explicit proposed selection is evidence input, never operator approval."""
    return {
        "schema": "wea-hello-world-anchor-1",
        "runtime": list(installed_executor(EXECUTOR).reference),
        "checkpoint": checkpoint(engine, predecessor),
        "opening_identities": engine.registry.to_data(),
        "installation_revision_id": installation_revision_id,
    }
