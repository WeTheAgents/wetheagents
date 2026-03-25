"""Helpers for traversing GitHub GraphQL issue payloads."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def parse_iso(ts: str) -> datetime | None:
    """Parse ISO 8601 timestamp, normalize Z suffix, return UTC-aware datetime."""
    raw = (ts or "").strip()
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def issue_comments(issue: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract comments.nodes from a GraphQL issue response."""
    comments = ((issue.get("comments") or {}).get("nodes") or []) if isinstance(issue, dict) else []
    return [item for item in comments if isinstance(item, dict)]


def issue_labels(issue: dict[str, Any]) -> list[str]:
    """Extract label names from a GraphQL issue response."""
    labels = ((issue.get("labels") or {}).get("nodes") or []) if isinstance(issue, dict) else []
    return [str(item.get("name", "")).strip() for item in labels if isinstance(item, dict) and item.get("name")]


def comment_author(comment: dict[str, Any]) -> str:
    """Extract author.login from a comment node."""
    author = comment.get("author")
    if not isinstance(author, dict):
        return ""
    return str(author.get("login") or "").strip()


def comment_body(comment: dict[str, Any]) -> str:
    """Extract body text from a comment node."""
    return str(comment.get("body") or "")


def comment_created(comment: dict[str, Any]) -> datetime | None:
    """Extract createdAt as a datetime from a comment node."""
    return parse_iso(str(comment.get("createdAt") or ""))
