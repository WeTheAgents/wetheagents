"""Bounded external repository observations, separate from canonical writes."""

from __future__ import annotations

import argparse
import http.client
import json
import os
import re
import urllib.error
import urllib.request

from .domain_access import make_domain_record
from .tide.github import GitHubError, _NoRedirect

MAX_BYTES = 1024 * 1024
TIMEOUT = 30
COMMIT_QUERY = (
    "query($id:ID!,$revision:String!){node(id:$id){"
    "... on Repository{id nameWithOwner object(expression:$revision){"
    "... on Commit{oid}}}}}"
)


class RepositoryReader:
    """Read identities and exact commits with an already available token only."""

    def __init__(self, token: str):
        if not token:
            raise GitHubError("GITHUB_TOKEN is required")
        self._token = token
        self.opener = urllib.request.build_opener(_NoRedirect())

    def _read(self, path: str, payload: dict | None = None) -> dict:
        # Do not turn this transport into a second generic GitHub client.
        if payload is None:
            if not path.startswith("repos/"):
                raise GitHubError("repository reader endpoint is not permitted")
            make_domain_record(
                domain_id="observation",
                repository_id="observation",
                repository_locator="https://github.com/" + path[len("repos/") :],
                revision="0" * 40,
            )
        elif (
            path != "graphql"
            or set(payload) != {"query", "variables"}
            or payload["query"] != COMMIT_QUERY
        ):
            raise GitHubError("repository reader query is not permitted")
        request = urllib.request.Request(
            "https://api.github.com/" + path,
            data=None if payload is None else json.dumps(payload).encode(),
            method="GET" if payload is None else "POST",
            headers={
                "Authorization": "Bearer " + self._token,
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
                "User-Agent": "wea-repository-reader",
            },
        )
        try:
            with self.opener.open(request, timeout=TIMEOUT) as response:
                raw = response.read(MAX_BYTES + 1)
        except urllib.error.HTTPError as exc:
            raise GitHubError(
                f"required repository read failed with HTTP {exc.code}; "
                "the existing token may not have repository visibility"
            ) from None
        except (OSError, urllib.error.URLError, ValueError, http.client.HTTPException):
            raise GitHubError("required repository read transport failed") from None
        if len(raw) > MAX_BYTES:
            raise GitHubError("repository response exceeds the evidence bound")
        try:
            value = json.loads(raw)
        except (ValueError, UnicodeError):
            raise GitHubError("repository response is not valid JSON") from None
        if type(value) is not dict:
            raise GitHubError("repository response is not an object")
        return value

    def identity(self, locator: str) -> dict:
        make_domain_record(
            domain_id="observation",
            repository_id="observation",
            repository_locator=locator,
            revision="0" * 40,
        )
        value = self._read("repos/" + locator.removeprefix("https://github.com/"))
        if type(value.get("id")) is not int or value["id"] <= 0:
            raise GitHubError("required repository numeric identity read failed")
        node, name = value.get("node_id"), value.get("full_name")
        if type(node) is not str or node.isdigit():
            raise GitHubError("required repository node identity read failed")
        if type(name) is not str:
            raise GitHubError("required repository locator read failed")
        try:
            make_domain_record(
                domain_id="observation",
                repository_id=node,
                repository_locator="https://github.com/" + name,
                revision="0" * 40,
            )
        except ValueError:
            raise GitHubError("required repository identity read failed") from None
        return {"id": value["id"], "node_id": node, "full_name": name}

    def commit(self, node_id: str, revision: str) -> dict:
        make_domain_record(
            domain_id="observation",
            repository_id=node_id,
            repository_locator="https://github.com/WeTheAgents/wetheagents",
            revision=revision,
        )
        value = self._read(
            "graphql",
            {
                "query": COMMIT_QUERY,
                "variables": {"id": node_id, "revision": revision},
            },
        )
        data = value.get("data")
        node = data.get("node") if type(data) is dict else None
        if value.get("errors") or type(node) is not dict or node.get("id") != node_id:
            raise GitHubError("required permanent repository context read failed")
        obj = node.get("object")
        if type(obj) is not dict or obj.get("oid") != revision:
            raise GitHubError(
                "context revision is not a commit in the permanent repository"
            )
        name = node.get("nameWithOwner")
        try:
            if type(name) is not str:
                raise ValueError
            make_domain_record(
                domain_id="observation",
                repository_id=node_id,
                repository_locator="https://github.com/" + name,
                revision=revision,
            )
        except ValueError:
            raise GitHubError(
                "required repository context locator read failed"
            ) from None
        return {"id": node_id, "nameWithOwner": name, "object": {"oid": revision}}


def preflight(
    locator: str,
    repository_id: str,
    revision: str,
    execution_sha: str,
    token: str,
    credential_source: str,
) -> dict:
    """Observe only: no source intake, journal, receipt or policy operation."""
    make_domain_record(
        domain_id="observation",
        repository_id=repository_id,
        repository_locator=locator,
        revision=revision,
    )
    if not re.fullmatch(r"[0-9a-f]{40}", execution_sha):
        raise ValueError("preflight requires an exact execution SHA")
    reader = RepositoryReader(token)
    identity = reader.identity(locator)
    aliases = sorted({str(identity["id"]), identity["node_id"]})
    if repository_id not in aliases:
        raise GitHubError("resolved repository ID differs")
    context = reader.commit(identity["node_id"], revision)
    return {
        "status": "read-only-verified",
        "execution_code_sha": execution_sha,
        "credential_source": credential_source,
        "requested_locator": locator,
        "requested_repository_id": repository_id,
        "repository_aliases": aliases,
        "repository_locator": "https://github.com/" + context["nameWithOwner"],
        "context_revision": revision,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only repository preflight")
    parser.add_argument("--locator", required=True)
    parser.add_argument("--repository-id", required=True)
    parser.add_argument("--revision", required=True)
    args = parser.parse_args()
    try:
        domain_token = os.environ.get("WEA_DOMAIN_READ_TOKEN", "")
        result = preflight(
            args.locator,
            args.repository_id,
            args.revision,
            os.environ.get("GITHUB_SHA", ""),
            domain_token or os.environ.get("GITHUB_TOKEN", ""),
            "WEA_DOMAIN_READ_TOKEN" if domain_token else "GITHUB_TOKEN",
        )
        print(json.dumps(result))
        return 0
    except (ValueError, GitHubError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
