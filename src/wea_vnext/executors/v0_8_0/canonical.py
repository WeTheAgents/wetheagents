"""Canonical JSON encoding for WEA protocol bytes and hashes."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from types import MappingProxyType
from typing import Any


class CanonicalJSONError(ValueError):
    """Raised when a value cannot have one unambiguous protocol encoding."""


MAX_INTEGER_DECIMAL_DIGITS = 640
_MAX_INTEGER_ABS_EXCLUSIVE = 10**MAX_INTEGER_DECIMAL_DIGITS


def _reject_float(value: str) -> None:
    raise CanonicalJSONError(f"non-integer JSON number is forbidden: {value}")


def _reject_constant(value: str) -> None:
    raise CanonicalJSONError(f"non-JSON numeric constant is forbidden: {value}")


def _parse_integer(value: str) -> int:
    digits = value.removeprefix("-")
    if len(digits) > MAX_INTEGER_DECIMAL_DIGITS:
        raise CanonicalJSONError(
            "JSON integer exceeds the protocol limit of "
            f"{MAX_INTEGER_DECIMAL_DIGITS} decimal digits"
        )
    try:
        return int(value)
    except ValueError as exc:
        raise CanonicalJSONError(f"invalid JSON integer: {value}") from exc


def _object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CanonicalJSONError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _validate_string(value: str, *, path: str) -> None:
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise CanonicalJSONError(
            f"string at {path} contains a lone Unicode surrogate"
        ) from exc


def _validate(value: Any, *, path: str = "$") -> None:
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, str):
        _validate_string(value, path=path)
        return
    if isinstance(value, int):
        if not -_MAX_INTEGER_ABS_EXCLUSIVE < value < _MAX_INTEGER_ABS_EXCLUSIVE:
            raise CanonicalJSONError(
                f"integer at {path} exceeds the protocol limit of "
                f"{MAX_INTEGER_DECIMAL_DIGITS} decimal digits"
            )
        return
    if isinstance(value, float):
        raise CanonicalJSONError(f"float is forbidden at {path}")
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate(item, path=f"{path}[{index}]")
        return
    if isinstance(value, tuple):
        for index, item in enumerate(value):
            _validate(item, path=f"{path}[{index}]")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise CanonicalJSONError(f"JSON object key at {path} is not a string")
            _validate_string(key, path=f"{path} key")
            _validate(item, path=f"{path}.{key}")
        return
    raise CanonicalJSONError(
        f"unsupported JSON value at {path}: {type(value).__name__}"
    )


def _plain_json(value: Any) -> Any:
    """Return a mutable stdlib-JSON tree without changing scalar values."""
    if is_dataclass(value) and not isinstance(value, type):
        value = asdict(value)
    try:
        _validate(value)

        def convert(item: Any) -> Any:
            if isinstance(item, Mapping):
                return {key: convert(child) for key, child in item.items()}
            if isinstance(item, (list, tuple)):
                return [convert(child) for child in item]
            return item

        return convert(value)
    except RecursionError as exc:
        raise CanonicalJSONError("JSON nesting exceeds the protocol limit") from exc


def freeze_json(value: Any) -> Any:
    """Copy a JSON value into recursive immutable containers."""
    plain = canonical_loads(canonical_dumps(value))

    def freeze(item: Any) -> Any:
        if isinstance(item, dict):
            return MappingProxyType({key: freeze(child) for key, child in item.items()})
        if isinstance(item, list):
            return tuple(freeze(child) for child in item)
        return item

    return freeze(plain)


def thaw_json(value: Any) -> Any:
    """Copy an immutable JSON view into ordinary dict/list containers."""
    return _plain_json(value)


def canonical_loads(raw: bytes | str) -> Any:
    """Decode strict UTF-8 JSON while rejecting ambiguous numeric/key forms."""
    if isinstance(raw, bytes):
        if raw.startswith(b"\xef\xbb\xbf"):
            raise CanonicalJSONError("UTF-8 BOM is forbidden")
        try:
            text = raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise CanonicalJSONError("input is not strict UTF-8") from exc
    else:
        text = raw
        if text.startswith("\ufeff"):
            raise CanonicalJSONError("UTF-8 BOM is forbidden")
    try:
        value = json.loads(
            text,
            object_pairs_hook=_object_without_duplicates,
            parse_int=_parse_integer,
            parse_float=_reject_float,
            parse_constant=_reject_constant,
        )
    except CanonicalJSONError:
        raise
    except (json.JSONDecodeError, ValueError, RecursionError) as exc:
        raise CanonicalJSONError(str(exc)) from exc
    try:
        _validate(value)
    except RecursionError as exc:
        raise CanonicalJSONError("JSON nesting exceeds the protocol limit") from exc
    return value


def canonical_dumps(value: Any) -> bytes:
    """Encode a JSON value as sorted compact UTF-8 without a trailing newline."""
    value = _plain_json(value)
    try:
        text = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError, RecursionError) as exc:
        raise CanonicalJSONError(str(exc)) from exc
    try:
        return text.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise CanonicalJSONError("JSON contains a lone Unicode surrogate") from exc


def sha256_hex(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical_hash(value: Any) -> str:
    return sha256_hex(canonical_dumps(value))
