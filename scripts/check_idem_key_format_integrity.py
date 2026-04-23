#!/usr/bin/env python3
"""Validate structure of all keys in ledger/idem_keys.json.

For each key in the file (top-level and inside the nested "keys" wrapper),
attempts to match it against one of the five known idem-key format patterns.
Keys that trigger a known pattern prefix but fail segment validation are
reported as MALFORMED. Keys that match no known prefix are reported as UNKNOWN.

Known patterns:
  accept|{issue}|{agent}[|{qualifier}]  issue: positive int, agent: contains @
  escrow_create|{issue}                  issue: positive int
  escrow-return-{cycle}-{issue}          cycle/issue: positive ints (digit-only)
  gauntlet-T{N}-S{M}-{agent}            N/M: positive ints, agent: contains @
  register|{agent}                       agent: contains @

Detection rule: a key triggers a pattern validator only when its prefix
unambiguously signals that pattern type. For example, "escrow-return-"
triggers the escrow-return validator only if the very next character is a
digit (distinguishing it from "escrow-return-cycle10-..." which is UNKNOWN).
Unknown patterns are surfaced in the report but do NOT cause exit code 1.

Output: JSON to stdout:
  {
    "status": "pass" | "fail",
    "totals": {"total": N, "valid": N, "malformed": N, "unknown": N},
    "by_category": {
      "accept": N, "escrow_create": N, "escrow_return": N,
      "gauntlet": N, "register": N
    },
    "malformed_keys": [{"key": "...", "reason": "..."}],
    "unknown_sample": ["...", ...]
  }

Exit codes:
  0 — no malformed keys
  1 — one or more malformed keys found
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

_SKIP_TOP_LEVEL: frozenset[str] = frozenset({"version", "keys"})
_GAUNTLET_RE = re.compile(r"^gauntlet-T(\d+)-S(\d+)-(.+)$")
_UNKNOWN_SAMPLE_LIMIT = 20


def _is_positive_int(s: str) -> bool:
    return bool(re.fullmatch(r"[0-9]+", s)) and int(s) > 0


def _has_at(s: str) -> bool:
    return "@" in s


def classify_key(key: str) -> tuple[str, str | None]:
    """Classify a single idem key.

    Returns one of:
      ("valid", category_name)
      ("malformed", reason_string)
      ("unknown", None)
    """
    # Pattern 1: accept|{issue}|{agent}[|{qualifier}]
    if key.startswith("accept|"):
        parts = key.split("|")
        if len(parts) < 3:
            return "malformed", f"needs at least 3 pipe-segments, got {len(parts)}"
        issue, agent = parts[1], parts[2]
        if not issue:
            return "malformed", "empty issue segment"
        if not _is_positive_int(issue):
            return "malformed", f"issue not a positive integer: {issue!r}"
        if not agent:
            return "malformed", "empty agent segment"
        if not _has_at(agent):
            return "malformed", f"agent missing '@': {agent!r}"
        return "valid", "accept"

    # Pattern 2: escrow_create|{issue}[|{slug}]
    if key.startswith("escrow_create|"):
        parts = key.split("|")
        # Expect 2 parts (no slug) or 3 parts (with optional slug)
        if len(parts) < 2 or not parts[1]:
            return "malformed", "missing issue after 'escrow_create|'"
        if len(parts) > 3:
            return "malformed", f"too many pipe-segments in escrow_create key: {len(parts)}"
        if not _is_positive_int(parts[1]):
            return "malformed", f"issue not a positive integer: {parts[1]!r}"
        if len(parts) == 3 and not parts[2]:
            return "malformed", "empty slug segment"
        return "valid", "escrow_create"

    # Pattern 3: escrow-return-{cycle}-{issue} (both pure integers, digit-triggered)
    if key.startswith("escrow-return-"):
        rest = key[len("escrow-return-"):]
        if rest and rest[0].isdigit():
            parts = rest.split("-")
            if len(parts) != 2:
                return "malformed", f"expected 'N-M' after 'escrow-return-', got {rest!r}"
            if not _is_positive_int(parts[0]):
                return "malformed", f"cycle not a positive integer: {parts[0]!r}"
            if not _is_positive_int(parts[1]):
                return "malformed", f"issue not a positive integer: {parts[1]!r}"
            return "valid", "escrow_return"
        # Non-digit start (e.g. "cycle10-...") — not this pattern
        return "unknown", None

    # Pattern 4: gauntlet-T{N}-S{M}-{agent} (digit-triggered after T)
    if key.startswith("gauntlet-T"):
        rest_after_t = key[len("gauntlet-T"):]
        if rest_after_t and rest_after_t[0].isdigit():
            m = _GAUNTLET_RE.match(key)
            if not m:
                return "malformed", "invalid gauntlet key structure"
            n_str, m_str, agent = m.group(1), m.group(2), m.group(3)
            if not _is_positive_int(n_str):
                return "malformed", f"trajectory N not a positive integer: {n_str!r}"
            if not _is_positive_int(m_str):
                return "malformed", f"slot M not a positive integer: {m_str!r}"
            if not _has_at(agent):
                return "malformed", f"agent missing '@': {agent!r}"
            return "valid", "gauntlet"
        return "unknown", None

    # Pattern 5: register|{agent}
    if key.startswith("register|"):
        rest = key[len("register|"):]
        if not rest:
            return "malformed", "missing agent after 'register|'"
        if "|" in rest:
            return "malformed", "unexpected extra '|' in register key"
        if not _has_at(rest):
            return "malformed", f"agent missing '@': {rest!r}"
        return "valid", "register"

    return "unknown", None


def collect_keys(data: dict[str, Any]) -> list[str]:
    """Return all idem key strings from both top-level and nested 'keys' wrapper."""
    keys = [k for k in data if k not in _SKIP_TOP_LEVEL]
    nested = data.get("keys")
    if isinstance(nested, dict):
        keys.extend(nested.keys())
    return keys


def build_report(root: Path) -> dict[str, Any]:
    path = root / "ledger" / "idem_keys.json"

    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {
            "status": "fail",
            "error": "ledger/idem_keys.json not found",
            "totals": {"total": 0, "valid": 0, "malformed": 0, "unknown": 0},
            "by_category": {"accept": 0, "escrow_create": 0, "escrow_return": 0, "gauntlet": 0, "register": 0},
            "malformed_keys": [],
            "unknown_sample": [],
        }

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return {
            "status": "fail",
            "error": f"JSON parse error: {exc}",
            "totals": {"total": 0, "valid": 0, "malformed": 0, "unknown": 0},
            "by_category": {"accept": 0, "escrow_create": 0, "escrow_return": 0, "gauntlet": 0, "register": 0},
            "malformed_keys": [],
            "unknown_sample": [],
        }

    if not isinstance(data, dict):
        return {
            "status": "fail",
            "error": "top-level value must be a JSON object",
            "totals": {"total": 0, "valid": 0, "malformed": 0, "unknown": 0},
            "by_category": {"accept": 0, "escrow_create": 0, "escrow_return": 0, "gauntlet": 0, "register": 0},
            "malformed_keys": [],
            "unknown_sample": [],
        }

    keys = collect_keys(data)
    by_category: dict[str, int] = {
        "accept": 0, "escrow_create": 0, "escrow_return": 0, "gauntlet": 0, "register": 0
    }
    malformed: list[dict[str, str]] = []
    unknown: list[str] = []
    valid_count = 0

    for key in keys:
        kind, detail = classify_key(key)
        if kind == "valid":
            valid_count += 1
            by_category[detail] += 1  # type: ignore[index]
        elif kind == "malformed":
            malformed.append({"key": key, "reason": detail or ""})
        else:
            unknown.append(key)

    return {
        "status": "fail" if malformed else "pass",
        "totals": {
            "total": len(keys),
            "valid": valid_count,
            "malformed": len(malformed),
            "unknown": len(unknown),
        },
        "by_category": by_category,
        "malformed_keys": malformed,
        "unknown_sample": unknown[:_UNKNOWN_SAMPLE_LIMIT],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Repository root (default: auto-detected from script location)",
    )
    args = parser.parse_args(argv)
    root = args.root.resolve() if args.root else Path(__file__).resolve().parent.parent
    report = build_report(root)
    print(json.dumps(report, indent=2))
    return 1 if report["status"] == "fail" else 0


if __name__ == "__main__":
    sys.exit(main())
