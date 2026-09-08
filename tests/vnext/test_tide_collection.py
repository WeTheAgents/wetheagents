from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

import pytest

from wea_vnext.tide.collection import (
    API_ROOT,
    CollectionError,
    collect_sources,
    cutoff_evidence,
)

NOW = "2026-09-08T12:00:00Z"
CUTOFF = datetime(2026, 9, 8, 12, tzinfo=timezone.utc)


def source(identifier=10, *, comment=False):
    return {
        "id": identifier,
        "node_id": f"node-{identifier}",
        "number": 1,
        "body": "Exact source\r\nwith Unicode: агент",
        "created_at": "2026-09-08T11:00:00Z",
        "updated_at": "2026-09-08T11:00:00Z",
        "user": {"id": 42, "login": "participant"},
        "author_association": "COLLABORATOR",
        "html_url": "https://github.com/WeTheAgents/wetheagents/issues/1"
        + (f"#issuecomment-{identifier}" if comment else ""),
        "issue_url": f"https://api.github.com/{API_ROOT}/issues/1",
    }


class API:
    def __init__(self):
        self.issue = source()
        self.comments = [source(20, comment=True)]
        self.discovered = True
        self.edits = {}
        self.comment_reads = 0

    def get(self, path):
        if path == API_ROOT:
            return {"id": 1171421025, "full_name": "WeTheAgents/wetheagents"}
        if "/issues?" in path:
            return [deepcopy(self.issue)] if self.discovered else []
        if "/comments?" in path:
            self.comment_reads += 1
            return deepcopy(self.comments)
        assert path == f"{API_ROOT}/issues/1"
        return deepcopy(self.issue)

    def graphql(self, query, variables):
        row = next(
            r for r in [self.issue, *self.comments] if r["node_id"] == variables["id"]
        )
        edits = self.edits.get(row["id"], [])
        return {
            "data": {
                "node": {
                    "id": row["node_id"],
                    "databaseId": row["id"],
                    "body": row["body"],
                    "createdAt": row["created_at"],
                    "lastEditedAt": edits[0]["editedAt"] if edits else None,
                    "userContentEdits": {
                        "nodes": edits,
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                    },
                }
            }
        }


def test_exact_source_and_original_identity_are_retained():
    api = API()
    result = collect_sources(api.get, api.graphql, cutoff=CUTOFF)
    assert result["sources"][1]["body"] == api.comments[0]["body"]
    assert result["sources"][1]["actor_account_id"] == "42"
    assert result["sources"][1]["revision_id"] == "github:node-20:created"
    assert result["sources"][1]["author_association"] == "COLLABORATOR"
    assert len(result["capture_hash"]) == 64


def test_arrival_after_cutoff_is_left_for_next_tide():
    api = API()
    original = api.get

    def get(path):
        if "/comments?" in path and api.comment_reads == 1:
            extra = source(21, comment=True)
            extra["created_at"] = extra["updated_at"] = "2026-09-08T12:00:01Z"
            api.comments.append(extra)
        return original(path)

    result = collect_sources(get, api.graphql, cutoff=CUTOFF)
    assert [row["object_id"] for row in result["sources"]] == ["10", "20"]


def test_known_issue_is_still_read_without_discovery_label():
    api = API()
    api.discovered = False
    result = collect_sources(api.get, api.graphql, cutoff=CUTOFF, tracked_issues=[1])
    assert len(result["sources"]) == 2


def test_general_updated_at_is_not_treated_as_a_body_edit():
    api = API()
    original = collect_sources(api.get, api.graphql, cutoff=CUTOFF)
    api.issue["updated_at"] = "2026-09-08T12:01:00Z"
    result = collect_sources(api.get, api.graphql, cutoff=CUTOFF)
    assert result["sources"][0]["effective_at"] == api.issue["created_at"]
    assert result == original


def test_body_edit_uses_immutable_identity_and_editor_authority():
    api = API()
    api.edits[20] = [
        {
            "id": "immutable-edit-1",
            "editedAt": "2026-09-08T11:30:00Z",
            "deletedAt": None,
            "editor": {"databaseId": 43, "login": "editor"},
        }
    ]
    result = collect_sources(api.get, api.graphql, cutoff=CUTOFF)
    edited = result["sources"][1]
    assert edited["revision_id"] == "immutable-edit-1"
    assert edited["actor_account_id"] == "43"
    assert edited["original_author_account_id"] == "42"


def test_login_or_association_changes_do_not_change_numeric_authority():
    api = API()
    before = collect_sources(api.get, api.graphql, cutoff=CUTOFF)
    api.issue["user"]["login"] = "renamed-participant"
    api.issue["author_association"] = "MEMBER"
    after = collect_sources(api.get, api.graphql, cutoff=CUTOFF)
    assert after != before  # Preserve the actual writer observations.
    assert cutoff_evidence(after) == cutoff_evidence(before)
    assert after["capture_hash"] == before["capture_hash"]
    api.issue["user"]["id"] = 43
    substituted = collect_sources(api.get, api.graphql, cutoff=CUTOFF)
    assert cutoff_evidence(substituted) != cutoff_evidence(before)


def test_deleted_edit_history_is_retained_as_unresolved():
    api = API()
    api.edits[20] = [{"id": "edit-1", "editedAt": NOW, "deletedAt": NOW}]
    result = collect_sources(api.get, api.graphql, cutoff=CUTOFF)
    assert result["sources"][1]["revision_id"] is None
    assert result["sources"][1]["revision_status"] == "requires-edit-evidence"


def test_body_edit_after_cutoff_prevents_capture():
    api = API()
    api.edits[20] = [
        {"id": "edit-1", "editedAt": "2026-09-08T12:01:00Z", "deletedAt": None}
    ]
    with pytest.raises(CollectionError, match="after cutoff"):
        collect_sources(api.get, api.graphql, cutoff=CUTOFF)


@pytest.mark.parametrize(
    "failure", ["read", "duplicate", "unfinished", "wrong-repository", "wrong-issue"]
)
def test_incomplete_or_substituted_sources_never_produce_a_batch(failure):
    api = API()
    original = api.get
    if failure == "wrong-issue":
        api.comments[0]["issue_url"] += "2"

    def get(path):
        if failure == "wrong-repository" and path == API_ROOT:
            return {"id": 7, "full_name": "WeTheAgents/wetheagents"}
        if "/comments?" in path:
            if failure == "read":
                raise CollectionError("read failed")
            if failure == "duplicate":
                return [api.comments[0], api.comments[0]]
            if failure == "unfinished":
                return [source(i, comment=True) for i in range(100, 200)]
        return original(path)

    with pytest.raises(CollectionError):
        collect_sources(get, api.graphql, cutoff=CUTOFF, max_pages=1)


def test_rest_graphql_content_mismatch_is_rejected():
    api = API()

    def graph(query, variables):
        result = api.graphql(query, variables)
        result["data"]["node"]["body"] = "substituted"
        return result

    with pytest.raises(CollectionError, match="disagree"):
        collect_sources(api.get, graph, cutoff=CUTOFF)


def test_required_artifact_api_failure_aborts_instead_of_reclassifying_work():
    from wea_vnext.tide.github import GitHubError, retain_artifacts

    url = "https://github.com/WeTheAgents/wetheagents/blob/" + "a" * 40 + "/audit.md"

    def unavailable(path):
        raise GitHubError("GitHub GET failed with HTTP 403")

    with pytest.raises(GitHubError, match="403"):
        retain_artifacts(
            {"sources": [{"body": "declaration"}]},
            unavailable,
            lambda body: {"kind": "work", "source": url},
        )
