"""Strict shared helpers for the dormant Block 9 implementation."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from ..executors.v0_8_0.canonical import CanonicalJSONError, canonical_dumps


class Block9Error(ValueError):
    """Reject incomplete, ambiguous, stale, or non-canonical Block 9 input."""


def canonical_bytes(value: Any) -> bytes:
    """Return canonical JSON bytes and expose one Block 9 error boundary."""

    try:
        return canonical_dumps(value)
    except CanonicalJSONError as exc:
        raise Block9Error(f"non-canonical JSON: {exc}") from exc


def sha256_hex(value: bytes) -> str:
    if type(value) is not bytes:
        raise Block9Error("hash input must be exact bytes")
    return hashlib.sha256(value).hexdigest()


def require_text(value: object, *, field: str) -> str:
    if type(value) is not str or not value or value.strip() != value:
        raise Block9Error(f"{field} must be non-empty exact text")
    return value


def require_hash(value: object, *, field: str, length: int = 64) -> str:
    text = require_text(value, field=field)
    if len(text) != length or any(ch not in "0123456789abcdef" for ch in text):
        raise Block9Error(f"{field} must be a lowercase hexadecimal hash")
    return text


def require_positive_int(value: object, *, field: str) -> int:
    if type(value) is not int or value <= 0:
        raise Block9Error(f"{field} must be a positive integer")
    return value


def parse_utc(value: object, *, field: str) -> datetime:
    text = require_text(value, field=field)
    if not text.endswith("Z"):
        raise Block9Error(f"{field} must use canonical UTC Z form")
    try:
        parsed = datetime.fromisoformat(f"{text[:-1]}+00:00")
    except ValueError as exc:
        raise Block9Error(f"{field} is not a valid timestamp") from exc
    if (
        parsed.tzinfo != timezone.utc
        or parsed.isoformat().replace("+00:00", "Z") != text
    ):
        raise Block9Error(f"{field} must use canonical UTC Z form")
    return parsed


def require_relative_path(value: object, *, field: str) -> str:
    text = require_text(value, field=field)
    if "\\" in text or ":" in text or text.startswith("/") or text.endswith("/"):
        raise Block9Error(f"{field} must be a canonical repository-relative path")
    parts = text.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise Block9Error(f"{field} must be a canonical repository-relative path")
    return text
