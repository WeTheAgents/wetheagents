"""Helpers for planner-loop checkpoint/replan behavior."""

from __future__ import annotations

from collections import Counter


def detect_subtree_anchor_prefix(steps: list) -> str:
    """Detect repeated NOT_FOUND exploration under the same path prefix."""
    prefixes: list[str] = []
    for step in steps:
        if step.tool_name not in {"outline", "list", "read"}:
            continue
        if "NOT_FOUND" not in (step.output or ""):
            continue
        path = str(step.tool_input.get("path", "")).strip()
        if not path or path == "/":
            continue
        parts = [part for part in path.split("/") if part and part != "."]
        if not parts:
            continue
        prefixes.append(parts[0])

    if not prefixes:
        return ""

    counts = Counter(prefixes)
    prefix, count = counts.most_common(1)[0]
    return prefix if count >= 2 else ""


def has_scope_expansion_step(steps: list, anchor_prefix: str) -> bool:
    """Return whether the executor has already widened scope beyond the anchor prefix."""
    if not anchor_prefix:
        return False
    anchor_root = anchor_prefix.split("/", 1)[0]
    for step in steps:
        if step.tool_name not in {"outline", "list"}:
            continue
        path = str(step.tool_input.get("path", "")).strip()
        if path == "/":
            return True
        if path and not path.startswith(anchor_root):
            return True
    return False


def build_checkpoint_force_message(anchor_prefix: str, expanded_once: bool) -> str:
    if anchor_prefix and not expanded_once:
        anchor_root = anchor_prefix.split("/", 1)[0]
        return (
            "[PLANNER REPLAN]: EXPAND SCOPE EXACTLY ONCE. The current branch appears mis-anchored under "
            f"'{anchor_prefix}'. Do not guess more subpaths there. Outline '/' once, then inspect sibling folders outside "
            f"'{anchor_root}' that could contain the target artifact. After that single broader discovery step, either act "
            "on the discovered target or report the best supported final outcome now.\n"
            "[REPLAN KIND]: checkpoint_force_expand\n"
            "Previous narrow subtree assumption is obsolete."
        )

    return (
        "[PLANNER REPLAN]: STOP DISCOVERY. Use the current evidence and either act now with the minimal remaining write "
        "set or report the correct final outcome now.\n"
        "[REPLAN KIND]: checkpoint_force_finish\n"
        "Previous exploratory plan is obsolete. Do not reopen broad discovery."
    )
