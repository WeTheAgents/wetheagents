"""Release session commands for `wea release` — Structured Genome Reasoning (SGR)."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Schema loading & validation
# ---------------------------------------------------------------------------

def _release_schema_dir(root: Path) -> Path:
    return root / "pipeline" / "release"


def _load_schema(root: Path, name: str) -> dict[str, Any]:
    """Load a release JSON schema by filename."""
    path = _release_schema_dir(root) / name
    if not path.exists():
        raise FileNotFoundError(f"Release schema not found: {path}")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def validate_proposal(root: Path, payload: dict[str, Any]) -> None:
    """Validate a proposal payload against proposal.schema.json + extra rules."""
    try:
        from jsonschema import validate
    except ImportError:
        raise ImportError("jsonschema is required. Install with: pip install jsonschema")

    schema = _load_schema(root, "proposal.schema.json")
    validate(instance=payload, schema=schema)

    # Extra: modify/remove requires current_content
    change_type = payload.get("proposal", {}).get("change_type")
    if change_type in ("modify", "remove"):
        current = payload.get("proposal", {}).get("current_content")
        if not current or not current.strip():
            raise ValueError(
                f"proposal.current_content is required for change_type={change_type!r}"
            )


def validate_decision(root: Path, payload: dict[str, Any]) -> None:
    """Validate a decision payload against decision.schema.json."""
    try:
        from jsonschema import validate
    except ImportError:
        raise ImportError("jsonschema is required. Install with: pip install jsonschema")

    schema = _load_schema(root, "decision.schema.json")
    validate(instance=payload, schema=schema)


def validate_summary(root: Path, payload: dict[str, Any]) -> None:
    """Validate a summary payload against summary.schema.json."""
    try:
        from jsonschema import validate
    except ImportError:
        raise ImportError("jsonschema is required. Install with: pip install jsonschema")

    schema = _load_schema(root, "summary.schema.json")
    validate(instance=payload, schema=schema)


# ---------------------------------------------------------------------------
# Proposal hashing
# ---------------------------------------------------------------------------

def compute_proposal_hash(payload: dict[str, Any]) -> str:
    """SHA-256 of canonical JSON, first 16 hex chars."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Comment parsing
# ---------------------------------------------------------------------------

_JSON_BLOCK_RE = re.compile(r"```json\s*\n(.*?)\n```", re.DOTALL)


def parse_release_comments(comments: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Parse issue comments into proposals and decisions.

    Returns {"proposals": [...], "decisions": [...], "summaries": [...]}.
    """
    result: dict[str, list[dict[str, Any]]] = {
        "proposals": [],
        "decisions": [],
        "summaries": [],
    }
    for comment in comments:
        body = comment.get("body", "")
        for match in _JSON_BLOCK_RE.finditer(body):
            try:
                data = json.loads(match.group(1))
            except json.JSONDecodeError:
                continue
            if not isinstance(data, dict) or data.get("station") != "release":
                continue
            dtype = data.get("type")
            if dtype == "decision":
                result["decisions"].append(data)
            elif dtype == "summary":
                result["summaries"].append(data)
            elif "proposal" in data:
                result["proposals"].append(data)
    return result


# ---------------------------------------------------------------------------
# Provenance record builder
# ---------------------------------------------------------------------------

def build_provenance(
    proposals: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a provenance object for genome_meta.json from approved proposals."""
    approved_hashes = {
        d["proposal_hash"] for d in decisions if d.get("verdict") == "approved"
    }
    entries = []
    for p in proposals:
        h = compute_proposal_hash(p)
        if h not in approved_hashes:
            continue
        entries.append({
            "proposal_hash": h,
            "severity": p.get("severity"),
            "experience": {
                "task_id": p.get("experience", {}).get("task_id"),
                "mechanic": p.get("experience", {}).get("mechanic"),
                "outcome": p.get("experience", {}).get("outcome"),
                "key_moment": p.get("experience", {}).get("key_moment"),
            },
            "reflection_summary": p.get("reflection", {}).get("root_cause", ""),
            "verdict": "approved",
            "target_section": p.get("proposal", {}).get("target_section"),
        })
    return {
        "sgr_version": 1,
        "proposals": entries,
    }


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------

def cmd_release_propose(args: argparse.Namespace) -> int:
    """Submit a structured mutation proposal (reads JSON from stdin)."""
    from wea_cli.cli import EXIT_DOMAIN_ERROR, EXIT_OK, EXIT_RUNTIME_ERROR, emit, resolve_repo_root
    from wea_cli.config import resolve_agent
    from wea_cli.gh import post_issue_comment

    try:
        root = resolve_repo_root(args.root)
    except FileNotFoundError as exc:
        print(f"Error: {exc}")
        return EXIT_RUNTIME_ERROR

    agent_id = resolve_agent(args.agent)
    if not agent_id:
        print("Error: agent not set. Use --agent or WEA_AGENT env var.")
        return EXIT_DOMAIN_ERROR

    # Read payload from stdin
    raw = sys.stdin.read().strip()
    if not raw:
        print("Error: no JSON payload on stdin.")
        return EXIT_DOMAIN_ERROR

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"Error: invalid JSON: {exc}")
        return EXIT_DOMAIN_ERROR

    # Inject station and agent_id
    payload["station"] = "release"
    payload["agent_id"] = agent_id
    payload["issue"] = args.issue

    # Validate
    try:
        validate_proposal(root, payload)
    except Exception as exc:
        print(f"Validation error: {exc}")
        return EXIT_DOMAIN_ERROR

    proposal_hash = compute_proposal_hash(payload)

    # Render comment
    body_json = json.dumps(payload, indent=2, ensure_ascii=False)
    comment_body = f"### SGR Proposal by {agent_id}\n\n```json\n{body_json}\n```\n\nHash: `{proposal_hash}`"

    if args.dry_run:
        emit("--- Dry Run ---")
        emit(comment_body)
        emit(f"\nProposal hash: {proposal_hash}")
        emit("Dry run -- no comment posted.")
        return EXIT_OK

    post_issue_comment(args.issue, comment_body, repo=args.repo)
    emit(f"Proposal posted on #{args.issue}. Hash: {proposal_hash}")
    return EXIT_OK


def cmd_release_open(args: argparse.Namespace) -> int:
    """Open a release session on an issue (Agent0 only)."""
    from wea_cli.cli import AGENT0_ID, EXIT_DOMAIN_ERROR, EXIT_OK, EXIT_RUNTIME_ERROR, emit, resolve_repo_root
    from wea_cli.config import resolve_agent
    from wea_cli.gh import post_issue_comment

    caller = resolve_agent(args.agent)
    if caller != AGENT0_ID:
        print(f"release open is restricted to {AGENT0_ID}. Current agent: {caller or '(not set)'}.")
        return EXIT_DOMAIN_ERROR

    try:
        resolve_repo_root(args.root)
    except FileNotFoundError as exc:
        print(f"Error: {exc}")
        return EXIT_RUNTIME_ERROR

    participants = ", ".join(args.participants)
    comment_body = (
        f"## Release Session\n\n"
        f"Task #{args.issue} is settled. Participants: {participants}\n\n"
        f"Each participant: submit your **genome reflection** as a structured SGR proposal:\n\n"
        f"```bash\n"
        f"echo '<JSON>' | wea release propose --issue {args.issue}\n"
        f"```\n\n"
        f"Your proposal must include: `experience` (what happened), "
        f"`reflection` (what you learned), `proposal` (what to change), "
        f"and `severity` (memory / example / instruction).\n\n"
        f"Schema: `pipeline/release/proposal.schema.json`\n\n"
        f"Deadline: 48 hours from this comment."
    )

    if args.dry_run:
        emit("--- Dry Run ---")
        emit(comment_body)
        return EXIT_OK

    post_issue_comment(args.issue, comment_body, repo=args.repo)
    emit(f"Release session opened on #{args.issue} for: {participants}")
    return EXIT_OK


def cmd_release_status(args: argparse.Namespace) -> int:
    """Show release session status for an issue."""
    from wea_cli.cli import EXIT_OK, EXIT_RUNTIME_ERROR, emit, resolve_repo_root
    from wea_cli.gh import view_issue_comments

    try:
        resolve_repo_root(args.root)
    except FileNotFoundError as exc:
        print(f"Error: {exc}")
        return EXIT_RUNTIME_ERROR

    data = view_issue_comments(args.issue, repo=args.repo)
    comments = data.get("comments", [])
    if not comments:
        emit(f"No comments on #{args.issue}.")
        return EXIT_OK

    parsed = parse_release_comments(comments)
    proposals = parsed["proposals"]
    decisions = parsed["decisions"]
    summaries = parsed["summaries"]

    emit(f"--- Release Session #{args.issue} ---")
    emit(f"Proposals: {len(proposals)}  |  Decisions: {len(decisions)}  |  Summaries: {len(summaries)}")

    if proposals:
        emit("")
        emit(f"{'Agent':<25} {'Severity':<14} {'Change':<8} {'Section':<20} {'Verdict'}")
        emit("-" * 80)

        # Index decisions by hash
        decision_map = {d["proposal_hash"]: d for d in decisions}

        for p in proposals:
            agent = p.get("agent_id", "?")
            severity = p.get("severity", "?")
            change = p.get("proposal", {}).get("change_type", "?")
            section = p.get("proposal", {}).get("target_section", "?")
            h = compute_proposal_hash(p)
            dec = decision_map.get(h)
            verdict = dec["verdict"] if dec else "pending"
            emit(f"{agent:<25} {severity:<14} {change:<8} {section:<20} {verdict}")

    return EXIT_OK


def cmd_release_review(args: argparse.Namespace) -> int:
    """Review and apply mutation proposals (Agent0 only, reads decision JSON from stdin)."""
    from wea_cli.cli import AGENT0_ID, EXIT_DOMAIN_ERROR, EXIT_OK, EXIT_RUNTIME_ERROR, _now_iso, emit, resolve_repo_root
    from wea_cli.config import resolve_agent
    from wea_cli.gh import post_issue_comment, view_issue_comments

    caller = resolve_agent(args.agent)
    if caller != AGENT0_ID:
        print(f"release review is restricted to {AGENT0_ID}. Current agent: {caller or '(not set)'}.")
        return EXIT_DOMAIN_ERROR

    try:
        root = resolve_repo_root(args.root)
    except FileNotFoundError as exc:
        print(f"Error: {exc}")
        return EXIT_RUNTIME_ERROR

    # Read decision(s) from stdin
    raw = sys.stdin.read().strip()
    if not raw:
        print("Error: no JSON payload on stdin.")
        return EXIT_DOMAIN_ERROR

    try:
        raw_payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"Error: invalid JSON: {exc}")
        return EXIT_DOMAIN_ERROR

    # Accept single decision or array of decisions
    if isinstance(raw_payload, list):
        decision_list = raw_payload
    else:
        decision_list = [raw_payload]

    # Validate each decision
    for dec in decision_list:
        dec["station"] = "release"
        dec["type"] = "decision"
        dec["issue"] = args.issue
        dec.setdefault("reviewer_id", AGENT0_ID)
        dec.setdefault("decided_at", _now_iso())
        try:
            validate_decision(root, dec)
        except Exception as exc:
            print(f"Decision validation error: {exc}")
            return EXIT_DOMAIN_ERROR

    # Fetch proposals from issue comments for provenance
    issue_data = view_issue_comments(args.issue, repo=args.repo)
    comments = issue_data.get("comments", [])
    parsed = parse_release_comments(comments)
    all_proposals = parsed["proposals"]

    approved_count = sum(1 for d in decision_list if d["verdict"] == "approved")
    rejected_count = sum(1 for d in decision_list if d["verdict"] == "rejected")

    if args.dry_run:
        emit("--- Dry Run ---")
        emit(f"Decisions: {approved_count} approved, {rejected_count} rejected")
        for dec in decision_list:
            emit(f"  {dec['agent_id']}: {dec['verdict']} ({dec['proposal_hash'][:8]}...)")
            if dec["verdict"] == "approved":
                emit(f"    Diff: {dec.get('applied_diff', '(none)')}")
            else:
                emit(f"    Reason: {dec.get('rejection_reason', '?')}")

        provenance = build_provenance(all_proposals, decision_list)
        emit(f"\nProvenance record ({len(provenance['proposals'])} entries):")
        emit(json.dumps(provenance, indent=2, ensure_ascii=False))
        emit("\nDry run -- no changes written.")
        return EXIT_OK

    # Post each decision as a comment
    for dec in decision_list:
        body_json = json.dumps(dec, indent=2, ensure_ascii=False)
        comment_body = f"### SGR Decision by {AGENT0_ID}\n\n```json\n{body_json}\n```"
        post_issue_comment(args.issue, comment_body, repo=args.repo)

    # Build and write provenance to a temp file for genome_snapshot.py
    provenance = build_provenance(all_proposals, decision_list)
    provenance_path = root / "pipeline" / "release" / ".provenance_tmp.json"
    provenance_path.write_text(
        json.dumps(provenance, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    # Collect per-agent stats for commit message
    agent_counts: dict[str, int] = {}
    for dec in decision_list:
        if dec["verdict"] == "approved":
            aid = dec["agent_id"]
            agent_counts[aid] = agent_counts.get(aid, 0) + 1

    emit(f"Decisions posted: {approved_count} approved, {rejected_count} rejected")
    emit(f"Provenance written to: {provenance_path}")

    if agent_counts:
        parts = [f"{a} +{n}" for a, n in agent_counts.items()]
        agents_summary = ", ".join(parts)
        emit(f"\nSuggested commit message:")
        emit(f"  chore(genome): release #{args.issue} — {agents_summary} mutations [skip genome-tracker]")

    emit(f"\nNext steps:")
    emit(f"  1. Apply approved mutations to genome files")
    emit(f"  2. python scripts/genome_snapshot.py --agent <AGENT> --record-mutation \\")
    emit(f"       --commit <HASH> --trigger-issue {args.issue} --provenance-json {provenance_path}")
    emit(f"  3. Post closing summary: wea release close --issue {args.issue}")

    return EXIT_OK
