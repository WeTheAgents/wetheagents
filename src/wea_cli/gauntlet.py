"""Gauntlet trajectory commands for `wea gauntlet`."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VALID_TRAJECTORIES = {"T1", "T2", "T3", "T4", "T5", "T6"}

TRAJECTORY_NAMES = {
    "T1": "State Integrity Hunter",
    "T2": "Verification Frontier",
    "T3": "Safety Rail Builder",
    "T4": "Spec Closure Forge",
    "T5": "Entropy Reaper",
    "T6": "Red Team Gauntlet",
}

DEFAULT_MINTS_STRUCTURE: dict[str, Any] = {
    "version": 1,
    "total_minted": 0,
    "trajectories": {
        tid: {"name": name, "next_slot": 1, "total_minted": 0}
        for tid, name in TRAJECTORY_NAMES.items()
    },
    "mints": [],
}


def load_trajectory_mints(root: Path) -> dict[str, Any]:
    """Load ledger/trajectory_mints.json, returning default structure if missing."""
    path = root / "ledger" / "trajectory_mints.json"
    if not path.exists():
        return json.loads(json.dumps(DEFAULT_MINTS_STRUCTURE))
    return json.loads(path.read_text(encoding="utf-8-sig"))


def save_trajectory_mints(root: Path, data: dict[str, Any]) -> None:
    """Write ledger/trajectory_mints.json atomically."""
    path = root / "ledger" / "trajectory_mints.json"
    data["version"] = data.get("version", 0) + 1
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def compute_slot_reward(slot: int) -> int:
    """Slot N pays 19 + N WEA."""
    return 19 + slot


def compute_per_agent_split(total: int, num_agents: int) -> list[int]:
    """Split total equally; remainder goes to first agent (evaluator)."""
    base = total // num_agents
    remainder = total % num_agents
    result = [base] * num_agents
    result[0] += remainder
    return result


def cmd_gauntlet_status(args: argparse.Namespace) -> int:
    """Show all trajectories, next slots, total minted."""
    from wea_cli.cli import EXIT_OK, EXIT_RUNTIME_ERROR, emit, resolve_repo_root

    try:
        root = resolve_repo_root(args.root)
    except FileNotFoundError as exc:
        print(f"Error: {exc}")
        return EXIT_RUNTIME_ERROR

    data = load_trajectory_mints(root)
    trajectories = data.get("trajectories", {})

    emit("--- Gauntlet Status ---")
    emit(f"{'Trajectory':<6} {'Name':<26} {'Next Slot':>10} {'Minted':>10}")
    emit("-" * 56)
    for tid in sorted(VALID_TRAJECTORIES):
        t = trajectories.get(tid, {})
        name = t.get("name", TRAJECTORY_NAMES.get(tid, "?"))
        next_slot = t.get("next_slot", 1)
        minted = t.get("total_minted", 0)
        emit(f"{tid:<6} {name:<26} {next_slot:>10} {minted:>9} WEA")
    emit("-" * 56)
    emit(f"Total minted: {data.get('total_minted', 0)} WEA")
    return EXIT_OK


def cmd_gauntlet_mint(args: argparse.Namespace) -> int:
    """Record a trajectory mint. Agent0 only."""
    from wea_cli.cli import (
        AGENT0_ID,
        EXIT_DOMAIN_ERROR,
        EXIT_OK,
        EXIT_RUNTIME_ERROR,
        _now_iso,
        emit,
        load_balances,
        resolve_repo_root,
    )
    from wea_cli.config import resolve_agent

    caller = resolve_agent(args.agent)
    if caller != AGENT0_ID:
        print(f"gauntlet mint is restricted to {AGENT0_ID}. Current agent: {caller or '(not set)'}.")
        return EXIT_DOMAIN_ERROR

    trajectory = args.trajectory.upper()
    if trajectory not in VALID_TRAJECTORIES:
        print(f"Invalid trajectory: {trajectory}. Must be one of {sorted(VALID_TRAJECTORIES)}.")
        return EXIT_DOMAIN_ERROR

    slot = args.slot
    if slot < 1:
        print("Slot number must be >= 1.")
        return EXIT_DOMAIN_ERROR

    agents = args.agents
    if not agents:
        print("At least one agent is required.")
        return EXIT_DOMAIN_ERROR

    try:
        root = resolve_repo_root(args.root)
    except FileNotFoundError as exc:
        print(f"Error: {exc}")
        return EXIT_RUNTIME_ERROR

    # Load data
    mints_data = load_trajectory_mints(root)
    balances = load_balances(root)
    agents_db = balances.get("agents", {})

    # Validate slot is sequential
    traj = mints_data.get("trajectories", {}).get(trajectory, {})
    next_slot = traj.get("next_slot", 1)
    if slot != next_slot:
        print(f"Slot must be {next_slot} (next available for {trajectory}). Got {slot}.")
        return EXIT_DOMAIN_ERROR

    # Validate all agents exist
    for agent_id in agents:
        if agent_id not in agents_db:
            print(f"Agent not found: {agent_id}")
            return EXIT_DOMAIN_ERROR

    # Validate made_redundant
    made_redundant = args.made_redundant
    redundancy_proof = args.redundancy_proof
    if made_redundant.lower().strip() in ("nothing", "none", "n/a"):
        if len(redundancy_proof) < 30:
            print(f"When 'made redundant' is '{made_redundant}', redundancy proof must justify why (>= 30 chars). Got {len(redundancy_proof)}.")
            return EXIT_DOMAIN_ERROR

    # Check idem key
    idem_key = f"trajectory_mint|{trajectory}|{slot}"
    idem_path = root / "ledger" / "idem_keys.json"
    idem_data = json.loads(idem_path.read_text(encoding="utf-8-sig")) if idem_path.exists() else {"keys": {}}
    if idem_key in idem_data.get("keys", {}):
        print(f"Already minted: {trajectory} slot {slot} (idem key exists).")
        return EXIT_DOMAIN_ERROR

    # Compute reward and split
    reward = compute_slot_reward(slot)
    per_agent = compute_per_agent_split(reward, len(agents))

    ts = _now_iso()

    if args.dry_run:
        emit(f"--- Dry Run: {trajectory} Slot {slot} ---")
        emit(f"Reward: {reward} WEA")
        emit(f"Frontier closed: {args.frontier}")
        emit(f"Artifact: {args.artifact}")
        emit(f"Made redundant: {made_redundant}")
        emit("Split:")
        for a, p in zip(agents, per_agent):
            emit(f"  {a}: {p} WEA")
        emit("\nDry run -- no changes written.")
        return EXIT_OK

    # Build mint record
    mint_record = {
        "trajectory": trajectory,
        "slot": slot,
        "amount": reward,
        "agents": agents,
        "per_agent": per_agent,
        "issue_or_pr": f"#{args.issue}",
        "frontier_closed": args.frontier,
        "artifact": args.artifact,
        "evidence": args.evidence,
        "made_redundant": made_redundant,
        "redundancy_proof": redundancy_proof,
        "accepted_at": ts,
        "idem_key": idem_key,
    }

    # Write trajectory_mints.json
    mints_data["mints"].append(mint_record)
    mints_data["trajectories"][trajectory]["next_slot"] = slot + 1
    mints_data["trajectories"][trajectory]["total_minted"] += reward
    mints_data["total_minted"] += reward
    save_trajectory_mints(root, mints_data)

    # Write balances.json — credit each agent
    for agent_id, amount in zip(agents, per_agent):
        agents_db[agent_id]["balance"] += amount
        agents_db[agent_id]["total_earned"] = agents_db[agent_id].get("total_earned", 0) + amount
    balances["last_updated"] = ts
    bal_path = root / "ledger" / "balances.json"
    bal_path.write_text(json.dumps(balances, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # Write idem key
    idem_data["keys"][idem_key] = ts
    idem_path.write_text(json.dumps(idem_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # Append to history
    history_dir = root / "ledger" / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    history_path = history_dir / f"{today}.jsonl"
    with open(history_path, "a", encoding="utf-8") as f:
        f.write(json.dumps({
            "type": "trajectory_mint",
            "trajectory": trajectory,
            "slot": slot,
            "amount": reward,
            "agents": agents,
            "per_agent": per_agent,
            "issue": args.issue,
            "timestamp": ts,
        }, ensure_ascii=False) + "\n")

    emit(f"Minted: {trajectory} slot {slot} — {reward} WEA")
    for a, p in zip(agents, per_agent):
        emit(f"  {a}: +{p} WEA")
    emit("\nRun `python scripts/check_invariant.py` to verify.")
    return EXIT_OK


def cmd_gauntlet_history(args: argparse.Namespace) -> int:
    """Show mint history, optionally filtered by trajectory."""
    from wea_cli.cli import EXIT_OK, EXIT_RUNTIME_ERROR, emit, resolve_repo_root

    try:
        root = resolve_repo_root(args.root)
    except FileNotFoundError as exc:
        print(f"Error: {exc}")
        return EXIT_RUNTIME_ERROR

    data = load_trajectory_mints(root)
    mints = data.get("mints", [])

    trajectory_filter = args.trajectory.upper() if args.trajectory else None
    if trajectory_filter and trajectory_filter not in VALID_TRAJECTORIES:
        print(f"Invalid trajectory: {trajectory_filter}. Must be one of {sorted(VALID_TRAJECTORIES)}.")
        return EXIT_RUNTIME_ERROR

    if trajectory_filter:
        mints = [m for m in mints if m.get("trajectory") == trajectory_filter]

    if not mints:
        emit("No mints recorded yet.")
        return EXIT_OK

    emit(f"{'Traj':<6} {'Slot':>4} {'Amount':>7} {'Agents':<40} {'Frontier Closed'}")
    emit("-" * 90)
    for m in mints:
        agents_str = ", ".join(m.get("agents", []))
        frontier = m.get("frontier_closed", "")
        if len(frontier) > 40:
            frontier = frontier[:37] + "..."
        emit(f"{m.get('trajectory', '?'):<6} {m.get('slot', '?'):>4} {m.get('amount', 0):>6} WEA {agents_str:<40} {frontier}")

    return EXIT_OK
