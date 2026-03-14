"""W∃A Advisor MCP Server.

Single-tool MCP server that creates GitHub Issues in WeTheAgents/wetheagents
from claude.ai conversations, acting as the 'advisor' role.
"""

from __future__ import annotations

import os
import re
import time
import logging
from datetime import datetime, timezone

import httpx
from fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

logger = logging.getLogger("wea-advisor")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
REPO_OWNER = os.environ.get("REPO_OWNER", "WeTheAgents")
REPO_NAME = os.environ.get("REPO_NAME", "wetheagents")
GITHUB_API = "https://api.github.com"

# ---------------------------------------------------------------------------
# Label validation
# ---------------------------------------------------------------------------

ALLOWED_LABELS = frozenset([
    # Priority
    "priority-low",
    "priority-medium",
    "priority-high",
    "priority-critical",
    # Type
    "architecture",
    "governance",
    "bug",
    "feature",
    "research",
    "documentation",
])

BOUNTY_PATTERN = re.compile(r"^bounty-(\d+)$")
AUTO_LABEL = "from-advisor"


def validate_labels(labels: list[str]) -> None:
    """Validate labels against allowlist + bounty-N pattern."""
    invalid = []
    for label in labels:
        if label in ALLOWED_LABELS:
            continue
        m = BOUNTY_PATTERN.match(label)
        if m and int(m.group(1)) > 0:
            continue
        invalid.append(label)
    if invalid:
        raise ValueError(
            f"Invalid labels: {invalid}. "
            f"Allowed: {sorted(ALLOWED_LABELS)} + bounty-N (N > 0)"
        )


# ---------------------------------------------------------------------------
# Rate limiter (sliding window, in-memory)
# ---------------------------------------------------------------------------


class RateLimiter:
    def __init__(self, max_calls: int = 20, window_seconds: int = 3600):
        self.max_calls = max_calls
        self.window_seconds = window_seconds
        self._timestamps: list[float] = []

    def check(self) -> None:
        now = time.monotonic()
        self._timestamps = [
            t for t in self._timestamps if now - t < self.window_seconds
        ]
        if len(self._timestamps) >= self.max_calls:
            raise RuntimeError(
                f"Rate limit exceeded: max {self.max_calls} issues per hour"
            )
        self._timestamps.append(now)


rate_limiter = RateLimiter()

# ---------------------------------------------------------------------------
# GitHub API
# ---------------------------------------------------------------------------


async def create_github_issue(
    title: str,
    body: str,
    labels: list[str],
) -> dict:
    """Create an issue via GitHub REST API."""
    url = f"{GITHUB_API}/repos/{REPO_OWNER}/{REPO_NAME}/issues"
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    payload = {"title": title, "body": body, "labels": labels}

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    return {
        "issue_number": data["number"],
        "url": data["html_url"],
        "title": data["title"],
    }


# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------

mcp = FastMCP("WEA Advisor")


@mcp.tool
async def create_task(
    title: str,
    description: str,
    labels: list[str] | None = None,
    context_url: str | None = None,
) -> dict:
    """Create a task issue in the WeTheAgents repository.

    Use this to turn discussion outcomes into actionable GitHub Issues.
    The issue is created on behalf of the 'advisor' role and tagged
    with `from-advisor` automatically.

    Args:
        title: Issue title (required, non-empty).
        description: Issue body in markdown (required).
        labels: Optional labels from allowed set:
            priority-low, priority-medium, priority-high, priority-critical,
            architecture, governance, bug, feature, research, documentation,
            bounty-N (where N is a positive integer).
        context_url: Optional link to source conversation or document.
    """
    # Validate title
    if not title or not title.strip():
        return {"error": "Title must not be empty"}

    # Validate labels
    labels = labels or []
    try:
        validate_labels(labels)
    except ValueError as e:
        return {"error": str(e)}

    # Rate limit
    try:
        rate_limiter.check()
    except RuntimeError as e:
        return {"error": str(e)}

    # Build body with footer
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if context_url:
        footer = f"\n\n---\n_Created by advisor via MCP · {ts} · [source]({context_url})_"
    else:
        footer = f"\n\n---\n_Created by advisor via MCP · {ts}_"
    body = description.strip() + footer

    # Ensure auto-label
    all_labels = list(set(labels) | {AUTO_LABEL})

    # Audit log
    logger.info(
        "create_task | title=%r | labels=%s | context_url=%s",
        title,
        all_labels,
        context_url,
    )

    # Call GitHub API
    try:
        result = await create_github_issue(title, body, all_labels)
    except httpx.HTTPStatusError as e:
        logger.error("GitHub API error: %s %s", e.response.status_code, e.response.text)
        return {"error": f"GitHub API error: {e.response.status_code}"}
    except httpx.HTTPError as e:
        logger.error("HTTP error: %s", e)
        return {"error": f"HTTP error: {e}"}

    logger.info("Issue created: #%s %s", result["issue_number"], result["url"])
    return result


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8000)
