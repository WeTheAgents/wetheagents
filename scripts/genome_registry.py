"""Resolve agent IDs recognized by legacy and active vNext state."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return value if isinstance(value, dict) else {}


def vnext_balance_ids(root: Path) -> set[str]:
    """Return agents materialized by the retained vNext Tide state."""
    state = _object(root / "ledger" / "vnext" / "tide-state.json")
    if state.get("schema") != "wea-tide-state-2":
        return set()
    balances = state.get("balances")
    if not isinstance(balances, dict):
        return set()
    return {agent_id for agent_id in balances if isinstance(agent_id, str)}


def genesis_eligible_agent_ids(root: Path) -> set[str]:
    """Return zero-balance identities admitted as new by retained Tide state."""
    state = _object(root / "ledger" / "vnext" / "tide-state.json")
    if state.get("schema") != "wea-tide-state-2":
        return set()
    balances = state.get("balances")
    participants = state.get("participants")
    if not isinstance(balances, dict) or not isinstance(participants, dict):
        return set()
    eligible: set[str] = set()
    for admission in participants.values():
        if not isinstance(admission, dict) or not isinstance(
            admission.get("agents"), list
        ):
            continue
        for item in admission["agents"]:
            if not isinstance(item, dict) or item.get("preserve_balance") is not False:
                continue
            agent_id = item.get("agent_id")
            if isinstance(agent_id, str) and balances.get(agent_id) == 0:
                eligible.add(agent_id)
    return eligible


def registered_agent_ids(root: Path, legacy_payload: Any = None) -> set[str]:
    """Return the union of legacy balance rows and vNext Tide balances."""
    if legacy_payload is None:
        legacy_payload = _object(root / "ledger" / "balances.json")
    legacy_agents = (
        legacy_payload.get("agents", legacy_payload)
        if isinstance(legacy_payload, dict)
        else {}
    )
    ids = set(legacy_agents) if isinstance(legacy_agents, dict) else set()
    return ids | vnext_balance_ids(root)
