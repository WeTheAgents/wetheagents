"""Safe issue label editing primitives.

This module is intentionally importable and testable without GitHub access.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from wea_cli.errors import WeaCliError


class IssueEditError(WeaCliError):
    """Raised when a safe edit operation fails or requires rollback."""


def _normalize_state(value: str) -> str:
    normalized = value.strip().upper()
    if normalized in {"OPEN", "CLOSED"}:
        return normalized
    raise IssueEditError(f"Unsupported issue state: {value!r}")


def _extract_label_names(issue_payload: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    raw_labels = issue_payload.get("labels", [])
    if not isinstance(raw_labels, list):
        return names
    for raw in raw_labels:
        if isinstance(raw, dict):
            name = str(raw.get("name", "")).strip()
        else:
            name = str(raw).strip()
        if name:
            names.add(name)
    return names


def compute_target_labels(
    current_labels: set[str],
    add_labels: list[str] | None,
    remove_labels: list[str] | None,
    swaps: list[tuple[str, str]] | None,
) -> set[str]:
    target = set(current_labels)
    for old_label, new_label in swaps or []:
        old_clean = old_label.strip()
        new_clean = new_label.strip()
        if not old_clean or not new_clean:
            raise IssueEditError("Swap labels must be non-empty")
        target.discard(old_clean)
        target.add(new_clean)

    for label in remove_labels or []:
        clean = label.strip()
        if clean:
            target.discard(clean)

    for label in add_labels or []:
        clean = label.strip()
        if clean:
            target.add(clean)

    return target


def safe_edit_issue_labels(
    issue_number: int,
    *,
    add_labels: list[str] | None,
    remove_labels: list[str] | None,
    swaps: list[tuple[str, str]] | None,
    get_issue: Callable[[int], dict[str, Any]],
    set_labels: Callable[[int, list[str]], None],
    set_state: Callable[[int, str], None],
) -> dict[str, Any]:
    """Safely apply label operations and rollback if issue state flips."""
    issue_before = get_issue(issue_number)
    if not issue_before:
        raise IssueEditError(f"Issue not found: #{issue_number}")

    state_before = _normalize_state(str(issue_before.get("state", "")))
    labels_before = _extract_label_names(issue_before)
    labels_target = compute_target_labels(labels_before, add_labels, remove_labels, swaps)

    changed = labels_target != labels_before
    if changed:
        set_labels(issue_number, sorted(labels_target))

    issue_after = get_issue(issue_number)
    if not issue_after:
        raise IssueEditError(f"Issue not found after edit: #{issue_number}")

    state_after = _normalize_state(str(issue_after.get("state", "")))
    labels_after = _extract_label_names(issue_after)

    if state_after != state_before:
        rollback_errors: list[str] = []
        try:
            set_labels(issue_number, sorted(labels_before))
        except Exception as exc:
            rollback_errors.append(f"label rollback failed: {exc}")
        try:
            set_state(issue_number, state_before)
        except Exception as exc:
            rollback_errors.append(f"state rollback failed: {exc}")

        details = "; ".join(rollback_errors)
        if details:
            raise IssueEditError(
                f"Issue state changed unexpectedly ({state_before} -> {state_after}). "
                f"Rollback attempted with errors: {details}"
            )
        raise IssueEditError(
            f"Issue state changed unexpectedly ({state_before} -> {state_after}). "
            "Rollback was applied."
        )

    return {
        "issue": issue_number,
        "state_before": state_before,
        "state_after": state_after,
        "labels_before": sorted(labels_before),
        "labels_after": sorted(labels_after),
        "labels_target": sorted(labels_target),
        "changed": changed,
    }
