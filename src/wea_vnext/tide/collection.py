"""Capture a stable, bounded view without treating edited bodies as revisions.

The production caller supplies the authenticated GitHub API reader. This module
does not advance a cursor or write ledger state. A returned snapshot is input to
runtime validation, not proof of a task decision or permission to pay.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from typing import Any

from ..block9.common import canonical_bytes, sha256_hex

REPOSITORY = "WeTheAgents/wetheagents"
REPOSITORY_ID = 1171421025
API_ROOT = f"repos/{REPOSITORY}"
PAGE_SIZE = 100
_REVISION_FIELDS = """
  id databaseId body createdAt lastEditedAt
  userContentEdits(first:100, after:$after) {
    pageInfo { hasNextPage endCursor }
    nodes { id editedAt deletedAt editor {
      login ... on User { databaseId } ... on Bot { databaseId }
    } }
  }
"""
REVISION_QUERY = (
    "query($id:ID!,$after:String){node(id:$id){"
    "... on Issue {" + _REVISION_FIELDS + "}"
    "... on IssueComment {" + _REVISION_FIELDS + "}}}"
)


class CollectionError(ValueError):
    """The requested source boundary cannot be established."""


def cutoff_evidence(collection: dict[str, Any]) -> dict[str, Any]:
    """Compare authority evidence without mutable audit observations.

    GitHub login and repository association can change without a content edit.
    They remain writer observations in the retained batch; numeric account IDs
    and every content/revision field remain part of authenticated comparison.
    """
    return {
        **{
            key: value
            for key, value in collection.items()
            if key not in {"sources", "capture_hash"}
        },
        "sources": [
            {
                key: value
                for key, value in source.items()
                if key not in {"actor_login", "author_association"}
            }
            for source in collection["sources"]
        ],
    }


def _time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise CollectionError("source timestamp is missing")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CollectionError("source timestamp is malformed") from exc
    if result.tzinfo is None:
        raise CollectionError("source timestamp has no timezone")
    return result.astimezone(timezone.utc)


def _positive_id(value: Any) -> int:
    if type(value) is not int or value <= 0:
        raise CollectionError("GitHub object identity is malformed")
    return value


def _pages(
    api_get: Callable[[str], object], endpoint: str, max_pages: int
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[int] = set()
    for page in range(1, max_pages + 1):
        data = api_get(f"{endpoint}&per_page={PAGE_SIZE}&page={page}")
        if type(data) is not list or len(data) > PAGE_SIZE:
            raise CollectionError("GitHub pagination response is malformed")
        for item in data:
            if type(item) is not dict:
                raise CollectionError("GitHub pagination item is malformed")
            identifier = _positive_id(item.get("id"))
            if identifier in seen:
                raise CollectionError("GitHub pagination repeats an object")
            seen.add(identifier)
            rows.append(item)
        if len(data) < PAGE_SIZE:
            return rows
    raise CollectionError("GitHub pagination did not reach its end")


def _revision(
    api_graphql: Callable[[str, dict[str, Any]], object],
    row: dict[str, Any],
    max_pages: int,
) -> dict[str, Any]:
    node_id = row.get("node_id")
    if type(node_id) is not str or not node_id:
        raise CollectionError("source GraphQL identity is missing")
    after = None
    cursors: set[str] = set()
    matches: list[dict[str, Any]] = []
    history: list[dict[str, Any]] = []
    original: dict[str, Any] | None = None
    for _ in range(max_pages):
        result = api_graphql(REVISION_QUERY, {"id": node_id, "after": after})
        if type(result) is not dict or result.get("errors"):
            raise CollectionError("GitHub edit-history query failed")
        data = result.get("data")
        node = data.get("node") if type(data) is dict else None
        if (
            type(node) is not dict
            or not {
                "id",
                "databaseId",
                "body",
                "createdAt",
                "lastEditedAt",
                "userContentEdits",
            }
            <= node.keys()
        ):
            raise CollectionError("GitHub edit-history evidence is missing")
        if (
            node["id"] != node_id
            or node["databaseId"] != row["id"]
            or node["body"] != (row.get("body") or "")
            or _time(node["createdAt"]) != _time(row["created_at"])
        ):
            raise CollectionError("REST and GraphQL source snapshots disagree")
        snapshot = {key: node[key] for key in node if key != "userContentEdits"}
        if original is not None and original != snapshot:
            raise CollectionError("source changed while reading edit history")
        original = snapshot
        if node["lastEditedAt"] is None:
            return {
                "revision_id": f"github:{node_id}:created",
                "edit_history": [],
                "effective_at": row["created_at"],
            }
        edits = node["userContentEdits"]
        if type(edits) is not dict or type(edits.get("nodes")) is not list:
            raise CollectionError("GitHub edit-history pagination is missing")
        for edit in edits["nodes"]:
            if type(edit) is not dict:
                raise CollectionError("GitHub edit-history entry is missing")
            if type(edit.get("id")) is not str or not edit["id"]:
                raise CollectionError("edit history has no immutable identity")
            _time(edit.get("editedAt"))
            if any(item["revision_id"] == edit["id"] for item in history):
                raise CollectionError("edit history repeats a revision")
            history.append(
                {"revision_id": edit["id"], "effective_at": edit["editedAt"]}
            )
            if (
                edit.get("editedAt") == node["lastEditedAt"]
                and edit.get("deletedAt") is None
            ):
                matches.append(edit)
        info = edits.get("pageInfo")
        if type(info) is not dict or type(info.get("hasNextPage")) is not bool:
            raise CollectionError("GitHub edit-history pagination is incomplete")
        if not info["hasNextPage"]:
            break
        after = info.get("endCursor")
        if type(after) is not str or not after or after in cursors:
            raise CollectionError("GitHub edit-history cursor is invalid")
        cursors.add(after)
    else:
        raise CollectionError("GitHub edit-history pagination did not finish")
    if len(matches) != 1:
        return {
            "revision_id": None,
            "effective_at": original["lastEditedAt"],
            "edit_history": history,
        }
    edit = matches[0]
    if type(edit.get("id")) is not str or not edit["id"]:
        raise CollectionError("immutable edit identity is missing")
    editor = edit.get("editor")
    if type(editor) is not dict or type(editor.get("databaseId")) is not int:
        return {
            "revision_id": None,
            "effective_at": original["lastEditedAt"],
            "edit_history": history,
        }
    return {
        "revision_id": edit["id"],
        "edit_history": history,
        "effective_at": edit["editedAt"],
        "editor_id": _positive_id(editor["databaseId"]),
        "editor_login": editor.get("login"),
    }


def _source(
    row: dict[str, Any],
    *,
    number: int,
    kind: str,
    cutoff: datetime,
    api_graphql: Callable[[str, dict[str, Any]], object],
    max_pages: int,
) -> dict[str, Any] | None:
    created = _time(row.get("created_at"))
    updated = _time(row.get("updated_at"))
    if updated < created:
        raise CollectionError("source update predates creation")
    if created > cutoff:
        return None
    identifier = _positive_id(row.get("id"))
    user = row.get("user")
    if type(user) is not dict:
        raise CollectionError("source author is missing")
    account_id = _positive_id(user.get("id"))
    body = row.get("body")
    if body is None:
        body = ""
    if type(body) is not str:
        raise CollectionError("source body is malformed")
    expected_url = f"https://github.com/{REPOSITORY}/issues/{number}"
    if kind == "issue_comment":
        expected_url += f"#issuecomment-{identifier}"
        if row.get("issue_url") != f"https://api.github.com/{API_ROOT}/issues/{number}":
            raise CollectionError("comment belongs to another Issue")
    if row.get("html_url") != expected_url:
        raise CollectionError("source URL does not match its canonical identity")
    revision = _revision(api_graphql, row, max_pages)
    if _time(revision["effective_at"]) > cutoff:
        raise CollectionError("source body changed after cutoff; retry a fresh capture")
    # General updated_at also changes for non-body activity. Only a matching
    # content-edit node can establish an edited declaration's revision.
    return {
        "actor_account_id": str(revision.get("editor_id", account_id)),
        "actor_login": revision.get("editor_login", user.get("login")),
        "original_author_account_id": str(account_id),
        "author_association": row.get("author_association"),
        "body": body,
        "content_hash": sha256_hex(body.encode("utf-8")),
        "created_at": row["created_at"],
        "effective_at": revision["effective_at"],
        "object_id": str(identifier),
        "object_kind": kind,
        "issue_number": number,
        "repository_id": str(REPOSITORY_ID),
        "url": expected_url,
        "revision_id": revision["revision_id"],
        "edit_history": revision["edit_history"],
        "revision_status": "confirmed"
        if revision["revision_id"]
        else "requires-edit-evidence",
    }


def _capture_once(
    api_get: Callable[[str], object],
    api_graphql: Callable[[str, dict[str, Any]], object],
    *,
    cutoff: datetime,
    tracked: tuple[int, ...],
    max_pages: int,
) -> list[dict[str, Any]]:
    repo = api_get(API_ROOT)
    if (
        type(repo) is not dict
        or type(repo.get("id")) is not int
        or repo["id"] != REPOSITORY_ID
        or repo.get("full_name") != REPOSITORY
    ):
        raise CollectionError("authenticated repository identity does not match")
    discovered = _pages(
        api_get,
        f"{API_ROOT}/issues?state=all&labels=vnext&sort=created&direction=asc",
        max_pages,
    )
    numbers = set(tracked)
    for row in discovered:
        if "pull_request" not in row and _time(row.get("created_at")) <= cutoff:
            numbers.add(_positive_id(row.get("number")))
    sources: list[dict[str, Any]] = []
    for number in sorted(numbers):
        issue = api_get(f"{API_ROOT}/issues/{number}")
        if (
            type(issue) is not dict
            or issue.get("number") != number
            or "pull_request" in issue
        ):
            raise CollectionError("tracked Issue is missing or substituted")
        source = _source(
            issue,
            number=number,
            kind="issue",
            cutoff=cutoff,
            api_graphql=api_graphql,
            max_pages=max_pages,
        )
        if source is None:
            continue
        source["issue_id"] = str(issue["id"])
        sources.append(source)
        comments = _pages(api_get, f"{API_ROOT}/issues/{number}/comments?", max_pages)
        for comment in comments:
            source = _source(
                comment,
                number=number,
                kind="issue_comment",
                cutoff=cutoff,
                api_graphql=api_graphql,
                max_pages=max_pages,
            )
            if source is not None:
                source["issue_id"] = str(issue["id"])
                sources.append(source)
    return sorted(
        sources,
        key=lambda row: (
            _time(row["effective_at"]),
            row["object_id"],
            row["object_kind"],
        ),
    )


def collect_sources(
    api_get: Callable[[str], object],
    api_graphql: Callable[[str, dict[str, Any]], object],
    *,
    cutoff: datetime,
    tracked_issues: Iterable[int] = (),
    max_pages: int = 100,
) -> dict[str, Any]:
    """Collect twice at one caller-fixed cutoff; never infer a successful read.

    vnext-labelled Issues discover new tasks. Canonically tracked Issues stay in
    scope even after label removal or closure. Runtime ordering and edit-history
    validation remain separate from this transport capture.
    """
    if not isinstance(cutoff, datetime) or cutoff.tzinfo is None:
        raise CollectionError("cutoff must be timezone-aware")
    cutoff = cutoff.astimezone(timezone.utc)
    if type(max_pages) is not int or max_pages < 1:
        raise CollectionError("max_pages must be positive")
    tracked = tuple(sorted({_positive_id(value) for value in tracked_issues}))
    first = _capture_once(
        api_get, api_graphql, cutoff=cutoff, tracked=tracked, max_pages=max_pages
    )
    second = _capture_once(
        api_get, api_graphql, cutoff=cutoff, tracked=tracked, max_pages=max_pages
    )
    if cutoff_evidence({"sources": first}) != cutoff_evidence({"sources": second}):
        raise CollectionError("source snapshots changed during collection")
    body = {
        "schema": "wea-tide-collection-1",
        "repository_id": str(REPOSITORY_ID),
        "cutoff": cutoff.isoformat().replace("+00:00", "Z"),
        "tracked_issues": list(tracked),
        "sources": first,
    }
    return {**body, "capture_hash": sha256_hex(canonical_bytes(cutoff_evidence(body)))}
