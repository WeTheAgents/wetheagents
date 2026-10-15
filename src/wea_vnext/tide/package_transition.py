"""Explicit full-package continuation; no activation or financial authority."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from datetime import datetime
from pathlib import Path

from . import hello_world as hw
from .collection import REPOSITORY_ID
from .records import timestamp
from .replay import ReplayError, digest

MARKER = "<!-- wea:hello-world-package-transition -->\n"
SCHEMA = "wea-hello-world-package-transition-1"
FIELDS = {
    "schema",
    "anchor_sha256",
    "previous_package_sha256",
    "package_sha256",
    "previous_transition_sha256",
    "previous_tide_hash",
    "predecessor",
    "code_sha",
}


def manifest_valid(value):
    """Validate full manifests without reading today's files during replay."""
    if not isinstance(value, dict) or not value:
        raise ReplayError("package manifest is empty or invalid")
    for path, sha in value.items():
        if (
            not isinstance(path, str)
            or not path.startswith(("wea_vnext/", "wea_cli/"))
            or not path.endswith((".py", ".json"))
            or not re.fullmatch(r"[A-Za-z0-9_./-]+", path)
            or any(part in {"", ".", "..", "__pycache__"} for part in path.split("/"))
            or not isinstance(sha, str)
            or not re.fullmatch(r"[0-9a-f]{64}", sha)
        ):
            raise ReplayError("package manifest path or digest is invalid")


def git_manifest(root: Path, commit: str):
    """Hash canonical blobs, never checkout newline conversions or candidate code."""
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ReplayError("package requires an exact Git commit")
    tree = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "ls-tree",
            "-rz",
            commit,
            "--",
            "src/wea_vnext",
            "src/wea_cli",
        ],
        capture_output=True,
        check=True,
    ).stdout
    selected = []
    for row in tree.split(b"\0"):
        if not row:
            continue
        metadata, raw_path = row.split(b"\t", 1)
        path = raw_path.decode().removeprefix("src/")
        if not path.endswith((".py", ".json")) or "/__pycache__/" in path:
            continue
        mode, kind, sha = metadata.split()
        if kind != b"blob" or mode not in {b"100644", b"100755"}:
            raise ReplayError("package Git entry is not a regular file")
        selected.append((path, sha))
    result = subprocess.run(
        ["git", "-C", str(root), "cat-file", "--batch"],
        input=b"\n".join(sha for _, sha in selected) + b"\n",
        capture_output=True,
        check=True,
    ).stdout
    hashes, offset = {}, 0
    for path, sha in selected:
        end = result.index(b"\n", offset)
        actual, kind, size = result[offset:end].split()
        if actual != sha or kind != b"blob":
            raise ReplayError("package Git blob differs")
        offset = end + 1
        data = result[offset : offset + int(size)]
        hashes[path] = hashlib.sha256(data).hexdigest()
        offset += int(size) + 1
    manifest_valid(hashes)
    return dict(sorted(hashes.items()))


def current_hash(engine):
    previous = engine.hello_world_package
    return (
        previous["authorization"]["package_sha256"]
        if previous is not None
        else engine.hello_world_anchor["checkpoint"]["installation_sha256"]
    )


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ReplayError("duplicate package authorization field")
        result[key] = value
    return result


def authorization(captured, revision, *, after, body_hash):
    """Strict source boundary independent of active Hello World's isolation path."""
    from .activation import OPERATOR

    rows = [row for row in captured["sources"] if row.get("revision_id") == revision]
    if len(rows) != 1:
        raise ReplayError("package authorization source is missing or ambiguous")
    row = rows[0]
    if (
        row.get("repository_id") != str(REPOSITORY_ID)
        or row.get("issue_id") != "4015417565"
        or type(row.get("issue_number")) is not int
        or row["issue_number"] != 1
        or row.get("object_kind") != "issue_comment"
        or row.get("actor_account_id") != str(OPERATOR)
        or row.get("original_author_account_id") != str(OPERATOR)
        or row.get("revision_status") != "confirmed"
        or row.get("edit_history") != []
        or not isinstance(revision, str)
        or not revision.endswith(":created")
        or not isinstance(row.get("body"), str)
        or not row["body"].startswith(MARKER)
        or hashlib.sha256(row["body"].encode()).hexdigest() != row.get("content_hash")
    ):
        raise ReplayError("package authorization requires an unedited operator source")
    try:
        when = timestamp(row["effective_at"])
        lower = after if isinstance(after, datetime) else timestamp(after)
        if timestamp(row["created_at"]) != when or not lower < when <= timestamp(
            captured["cutoff"]
        ):
            raise ReplayError("package authorization is stale or outside the boundary")
        result = json.loads(row["body"][len(MARKER) :], object_pairs_hook=_unique)
    except (KeyError, TypeError, ValueError) as exc:
        raise ReplayError("package authorization is malformed") from exc
    issues = [
        r
        for r in captured["sources"]
        if r.get("object_kind") == "issue" and r.get("object_id") == "4015417565"
    ]
    if len(issues) != 1 or any(
        (
            issues[0].get("repository_id") != str(REPOSITORY_ID),
            issues[0].get("revision_status") != "confirmed",
            issues[0].get("issue_state") != "open",
            issues[0].get("content_hash") != body_hash,
            hashlib.sha256(issues[0].get("body", "").encode()).hexdigest() != body_hash,
        )
    ):
        raise ReplayError(
            "package transition requires unchanged active permanent Issue1"
        )
    if not isinstance(result, dict) or set(result) != FIELDS:
        raise ReplayError("package authorization fields differ")
    return result


def validate(engine, batch, record):
    """Validate retained evidence only; old prefixes never read installed bytes."""
    if engine.hello_world_anchor is None or engine.hello_world is None:
        raise ReplayError("package transition requires canonically active Hello World")
    if batch.get("hello_world") != engine.hello_world_anchor:
        raise ReplayError("package transition cannot change the original anchor")
    if (
        not isinstance(record, dict)
        or set(record)
        != {
            "schema",
            "source_revision_id",
            "previous_code_sha",
            "previous_manifest",
            "manifest",
            "authorization",
        }
        or record["schema"] != SCHEMA
    ):
        raise ReplayError("package transition fields differ")
    old, new = record["previous_manifest"], record["manifest"]
    manifest_valid(old)
    manifest_valid(new)
    previous = engine.hello_world_package
    if previous is not None and old != previous["manifest"]:
        raise ReplayError("package predecessor manifest differs")
    previous_code = (
        previous["authorization"]["code_sha"]
        if previous
        else engine.hello_world_anchor["checkpoint"]["predecessor"]
    )
    if record["previous_code_sha"] != previous_code:
        raise ReplayError("package predecessor code provenance differs")

    def preserved(values):
        return {
            k: v
            for k, v in values.items()
            if k.startswith(("wea_vnext/executors/", "wea_vnext/rulesets/"))
        }

    if preserved(old) != preserved(new):
        raise ReplayError("package transition cannot change released native closures")
    auth = authorization(
        batch["collection"],
        record["source_revision_id"],
        after=engine.last_cutoff,
        body_hash=engine.hello_world["contract"]["body_hash"],
    )
    expected = {
        "schema": SCHEMA,
        "anchor_sha256": digest(engine.hello_world_anchor),
        "previous_package_sha256": current_hash(engine),
        "package_sha256": digest(new),
        "previous_transition_sha256": digest(previous) if previous else None,
        "previous_tide_hash": engine.last_hash,
        "predecessor": batch["predecessor"],
        "code_sha": batch["predecessor"],
    }
    if (
        auth != expected
        or record["authorization"] != auth
        or digest(old) != current_hash(engine)
        or old == new
        or not re.fullmatch(r"[0-9a-f]{40}", batch["predecessor"])
        or (previous and record["source_revision_id"] == previous["source_revision_id"])
    ):
        raise ReplayError("package authorization does not bind the exact transition")


def prepare(root, base, engine, captured, revision):
    """Select new authority explicitly; a canonical same-source retry is a no-op."""
    if engine.hello_world_anchor is None or engine.hello_world is None:
        raise ReplayError("package transition requires canonically active Hello World")
    previous = engine.hello_world_package
    if previous and revision == previous["source_revision_id"]:
        return None
    old_code = (
        previous["authorization"]["code_sha"]
        if previous
        else engine.hello_world_anchor["checkpoint"]["predecessor"]
    )
    record = {
        "schema": SCHEMA,
        "source_revision_id": revision,
        "previous_code_sha": old_code,
        "previous_manifest": git_manifest(root, old_code),
        "manifest": git_manifest(root, base),
        "authorization": authorization(
            captured,
            revision,
            after=engine.last_cutoff,
            body_hash=engine.hello_world["contract"]["body_hash"],
        ),
    }
    validate(
        engine,
        {
            "predecessor": base,
            "collection": captured,
            "hello_world": engine.hello_world_anchor,
        },
        record,
    )
    return record


def verify_installed(root, base, engine, record):
    """Live producer/independent guard must run the exact authorized full package."""
    if record is not None:
        if record["previous_manifest"] != git_manifest(
            root, record["previous_code_sha"]
        ):
            raise ReplayError("package old manifest differs from historical Git")
        expected = record["manifest"]
    elif engine.hello_world_package is not None:
        expected = engine.hello_world_package["manifest"]
    else:
        if hw.package_hash() != current_hash(engine):
            raise ReplayError("Hello World installed package differs")
        return
    if expected != git_manifest(root, base) or expected != hw.package_files():
        raise ReplayError("authorized package differs from Git or installed bytes")
