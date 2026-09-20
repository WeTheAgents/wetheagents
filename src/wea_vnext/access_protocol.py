"""Operator-authorized Access package updates; grant history stays immutable."""

from __future__ import annotations

import re
from typing import Any

from . import access_control as control
from .tide.collection import REPOSITORY_ID

SCHEMA = "wea-access-protocol-1"
MARKER = "<!-- wea-access-protocol -->\n"
REF = "refs/heads/wea/access-journal"


def package(genesis: dict, entries: list[dict]) -> dict:
    """Select a package only after the caller has validated mixed replay."""
    latest = next((e for e in reversed(entries) if e["schema"] == SCHEMA), genesis)
    return {key: latest[key] for key in ("code_sha", "protocol_files")}


def decision(previous: dict, code_sha: str, files: dict) -> dict:
    return {
        "status": "protocol-updated",
        "request": None,
        "request_key": None,
        "previous_protocol_hash": control.digest(previous["protocol_files"]),
        "code_sha": code_sha,
        "protocol_hash": control.digest(files),
    }


def validate(genesis: dict, previous: dict, entry: dict[str, Any]) -> None:
    if (
        set(entry)
        != {
            "schema",
            "source",
            "accepted_at",
            "code_sha",
            "protocol_files",
            "provenance",
            "decision",
        }
        or entry["schema"] != SCHEMA
    ):
        raise ValueError("protocol update fields differ")
    source = entry["source"]
    if (
        source["repository_id"] != str(REPOSITORY_ID)
        or source["issue_number"] != genesis["issue_number"]
        or source["object_kind"] != "issue_comment"
        or source["actor_account_id"] != str(control.OPERATOR)
        or source["original_author_account_id"] != str(control.OPERATOR)
        or source["edit_history"]
        or source["revision_status"] != "confirmed"
        or not source["revision_id"].endswith(":created")
        or control.sha256(source["body"]) != source["content_hash"]
    ):
        raise ValueError("protocol update requires an exact unedited operator source")
    if not (
        control.timestamp(genesis["cutoff"])
        < control.timestamp(source["created_at"])
        <= control.timestamp(entry["accepted_at"])
    ):
        raise ValueError("protocol update source is outside acceptance interval")
    if not re.fullmatch(r"[0-9a-f]{40}", entry["code_sha"]):
        raise ValueError("protocol update requires an exact code SHA")
    files = entry["protocol_files"]
    if (
        type(files) is not dict
        or not files
        or any(
            type(path) is not str
            or not (
                re.fullmatch(r"src/wea_vnext/[a-zA-Z0-9_./-]+", path)
                or path in {"src/wea_cli/access.py", ".github/workflows/access.yml"}
            )
            or ".." in path
            or type(value) is not str
            or not re.fullmatch(r"[0-9a-f]{64}", value)
            for path, value in files.items()
        )
    ):
        raise ValueError("protocol update manifest differs")
    expected = decision(previous, entry["code_sha"], files)
    if expected["previous_protocol_hash"] == expected["protocol_hash"]:
        raise ValueError("protocol update must change the package")
    body = source["body"]
    if not body.startswith(MARKER) or len(body.encode()) > 16384:
        raise ValueError("protocol update marker or source size differs")
    command = control.strict_json(body[len(MARKER) :])
    if command != {
        "schema": SCHEMA,
        "previous_protocol_hash": expected["previous_protocol_hash"],
        "code_sha": entry["code_sha"],
        "protocol_hash": expected["protocol_hash"],
        "journal_ref": REF,
    }:
        raise ValueError("protocol update source or predecessor differs")
    if entry["decision"] != expected:
        raise ValueError("protocol update receipt differs")
