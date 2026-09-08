"""Bounded canonical-repository API access and immutable artifact capture."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .collection import API_ROOT, REPOSITORY, CollectionError

MAX_BYTES = 8 * 1024 * 1024


class GitHubError(RuntimeError):
    """Authenticated GitHub request failed without exposing credentials."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise GitHubError("GitHub API redirect is not permitted")


class GitHub:
    def __init__(self, token: str):
        if not token:
            raise GitHubError("GITHUB_TOKEN is required")
        self.token = token
        self.opener = urllib.request.build_opener(_NoRedirect())

    def request(self, method: str, path: str, data: Any = None) -> Any:
        if not (
            path == "graphql" or path.startswith(API_ROOT + "/") or path == API_ROOT
        ):
            raise GitHubError("API request is outside the canonical repository")
        if any(value in path for value in ("..", "\\", "#", "\r", "\n")):
            raise GitHubError("API path is malformed")
        request = urllib.request.Request(
            "https://api.github.com/" + path,
            data=None if data is None else json.dumps(data).encode(),
            method=method,
            headers={
                "Authorization": "Bearer " + self.token,
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
                "User-Agent": "wea-tide",
            },
        )
        try:
            with self.opener.open(request, timeout=45) as response:
                raw = response.read(MAX_BYTES + 1)
        except urllib.error.HTTPError as exc:
            raise GitHubError(f"GitHub {method} failed with HTTP {exc.code}") from None
        except (OSError, urllib.error.URLError) as exc:
            raise GitHubError(
                f"GitHub {method} transport failed: {type(exc).__name__}"
            ) from None
        if len(raw) > MAX_BYTES:
            raise GitHubError("GitHub response exceeds the retained evidence bound")
        return None if not raw else json.loads(raw)

    def get(self, path: str) -> Any:
        return self.request("GET", path)

    def graphql(self, query: str, variables: dict[str, Any]) -> Any:
        return self.request("POST", "graphql", {"query": query, "variables": variables})


def retain_artifacts(
    collection: dict[str, Any], api_get: Any, declaration: Any
) -> dict[str, Any]:
    """Only an immutable file in the canonical repository supplies Work bytes."""
    result = json.loads(json.dumps(collection))
    pattern = re.compile(
        r"https://github\.com/"
        + re.escape(REPOSITORY)
        + r"/blob/([0-9a-f]{40})/([^?#]+)\Z"
    )
    for source in result["sources"]:
        try:
            data = declaration(source["body"])
        except (ValueError, KeyError, TypeError):
            continue
        if data is None or data.get("kind") != "work":
            continue
        match = pattern.fullmatch(str(data.get("source", "")))
        if match is None:
            source["artifact_error"] = (
                "Work source must pin a canonical GitHub file to a full commit SHA"
            )
            continue
        sha, encoded_path = match.groups()
        path = urllib.parse.unquote(encoded_path)
        if (
            not path
            or any(part in {"", ".", ".."} for part in path.split("/"))
            or "\\" in path
        ):
            source["artifact_error"] = "Work artifact path is malformed"
            continue
        try:
            item = api_get(
                f"{API_ROOT}/contents/{urllib.parse.quote(path, safe='/')}?ref={sha}"
            )
            if (
                type(item) is not dict
                or item.get("type") != "file"
                or item.get("path") != path
                or item.get("encoding") != "base64"
                or type(item.get("size")) is not int
                or not 0 <= item["size"] <= 1024 * 1024
            ):
                raise CollectionError("artifact is not one bounded immutable file")
            raw = base64.b64decode("".join(item["content"].split()), validate=True)
            if len(raw) != item["size"]:
                raise CollectionError("artifact length differs")
            # Git's object format requires SHA-1, not a new security signature.
            # Retained artifact and batch integrity use SHA-256 below.
            blob_hash = hashlib.sha1(  # nosemgrep
                b"blob " + str(len(raw)).encode() + b"\0" + raw,
                usedforsecurity=False,
            ).hexdigest()
            if item["sha"] != blob_hash:
                raise CollectionError("artifact Git blob hash differs")
            text = raw.decode("utf-8")
        except (CollectionError, ValueError, KeyError, TypeError) as exc:
            source["artifact_error"] = str(exc)
            continue
        source["artifact"] = {
            "source": data["source"],
            "text": text,
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
    # The collector hash identifies the original source window. Artifact evidence
    # has its own hashes and is covered by the containing Tide batch hash.
    return result
