#!/usr/bin/env python3
"""Validate genome mutation provenance against real task history.

Rules checked for every mutation entry in ``genomes/*/genome_meta.json``:
1. ``trigger_issue`` (or legacy ``issue``) must map to one or more issue IDs
   that appear in ``ledger/history/*.jsonl`` as ``payment`` or
   ``trajectory_mint`` events.
2. ``commit`` must be a non-empty string.
3. Within a single genome file, no two mutations may share the same
   ``(issue_reference, target_section)`` provenance pair.

The script prints JSON to stdout and exits ``0`` on PASS / ``1`` on FAIL.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

RELEVANT_HISTORY_EVENT_TYPES = {"payment", "trajectory_mint"}
_INVALID_ESCAPE_RE = re.compile(r"\\(?![\"\\/bfnrtu])")
BASE_CHECKS = (
    "repository",
    "history_linkage",
    "commit_non_empty",
    "unique_issue_target_section",
    "genome_meta_readable",
    "mutations_list",
    "mutation_object",
)


def load_json(path: Path) -> Any:
    """Load a JSON file or raise ValueError with a stable message."""
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise ValueError(f"{path.name} not found") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path.name} contains invalid JSON: {exc}") from exc
    except OSError as exc:
        raise ValueError(f"Could not read {path.name}: {exc}") from exc


def _event_type(event: dict[str, Any]) -> str:
    """Return the best available event type name for a history event."""
    for key in ("type", "event", "op"):
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _coerce_history_issue(value: Any, *, location: str) -> int:
    """Normalize a history issue value to ``int`` or raise ValueError."""
    if isinstance(value, bool):
        raise ValueError(f"{location} has non-integer issue value {value!r}")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip():
        raw = value.strip()
        if raw.isdigit():
            return int(raw)
    raise ValueError(f"{location} has non-integer issue value {value!r}")


def load_jsonl_line(raw_line: str) -> dict[str, Any]:
    """Load one JSONL line, repairing legacy stray backslash escapes."""
    try:
        payload = json.loads(raw_line)
    except json.JSONDecodeError:
        payload = json.loads(_INVALID_ESCAPE_RE.sub(r"\\\\", raw_line))

    if not isinstance(payload, dict):
        raise ValueError("event must be a JSON object")
    return payload


def load_history_issue_ids(root: Path) -> tuple[set[int], int]:
    """Return all issue IDs referenced by payment/trajectory_mint history events."""
    history_dir = root / "ledger" / "history"
    if not history_dir.is_dir():
        raise ValueError("ledger/history directory not found")

    issue_ids: set[int] = set()
    relevant_events = 0

    for path in sorted(history_dir.glob("*.jsonl")):
        try:
            raw_text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ValueError(f"Could not read {path.name}: {exc}") from exc

        for line_no, raw_line in enumerate(raw_text.splitlines(), start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                event = load_jsonl_line(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"{path.name}:{line_no} contains invalid JSON: {exc}"
                ) from exc
            except ValueError as exc:
                raise ValueError(f"{path.name}:{line_no} event must be a JSON object")

            if _event_type(event) not in RELEVANT_HISTORY_EVENT_TYPES:
                continue

            location = f"{path.name}:{line_no}"
            issue_ids.add(_coerce_history_issue(event.get("issue"), location=location))
            relevant_events += 1

    return issue_ids, relevant_events


def normalize_issue_reference(value: Any) -> tuple[str, list[int]]:
    """Normalize a mutation issue reference into a canonical key and issue list."""
    if isinstance(value, bool):
        raise ValueError("issue reference must be an integer or '+'-delimited integers")
    if isinstance(value, int):
        return str(value), [value]
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            raise ValueError("issue reference is empty")

        parts = [part.strip() for part in raw.split("+")]
        if any(not part for part in parts):
            raise ValueError(f"issue reference {value!r} contains an empty segment")

        issue_ids: list[int] = []
        for part in parts:
            if not part.isdigit():
                raise ValueError(
                    f"issue reference segment {part!r} is not an integer"
                )
            issue_ids.append(int(part))

        canonical_ids = sorted(set(issue_ids))
        return "+".join(str(issue_id) for issue_id in canonical_ids), canonical_ids

    raise ValueError("issue reference must be an integer or '+'-delimited integers")


def resolve_mutation_issue_reference(
    mutation: dict[str, Any],
) -> tuple[str, Any, str, list[int]]:
    """Return the mutation issue field name, raw value, canonical key, and IDs."""
    if "trigger_issue" in mutation:
        field_name = "trigger_issue"
        raw_value = mutation.get("trigger_issue")
    elif "issue" in mutation:
        field_name = "issue"
        raw_value = mutation.get("issue")
    else:
        raise ValueError("mutation is missing both 'trigger_issue' and 'issue'")

    issue_key, issue_ids = normalize_issue_reference(raw_value)
    return field_name, raw_value, issue_key, issue_ids


def extract_target_sections(mutation: dict[str, Any]) -> list[str]:
    """Extract target section names from known mutation provenance shapes."""
    sections: list[str] = []

    top_level = mutation.get("target_section")
    if isinstance(top_level, str) and top_level.strip():
        sections.append(top_level.strip())

    provenance = mutation.get("provenance")
    if isinstance(provenance, dict):
        proposals = provenance.get("proposals")
        if isinstance(proposals, list):
            for proposal in proposals:
                if not isinstance(proposal, dict):
                    continue
                section = proposal.get("target_section")
                if isinstance(section, str) and section.strip():
                    sections.append(section.strip())

    unique_sections: list[str] = []
    seen: set[str] = set()
    for section in sections:
        if section not in seen:
            seen.add(section)
            unique_sections.append(section)
    return unique_sections


def _relative_path(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _violation(
    *,
    root: Path,
    path: Path | None,
    agent: str | None,
    mutation_index: int | None,
    check: str,
    detail: str,
    **extra: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"check": check, "detail": detail}
    if path is not None:
        payload["file"] = _relative_path(path, root)
    if agent is not None:
        payload["agent"] = agent
    if mutation_index is not None:
        payload["mutation_index"] = mutation_index
    payload.update(extra)
    return payload


def validate_genome_meta(
    path: Path,
    root: Path,
    history_issue_ids: set[int],
) -> tuple[int, list[dict[str, Any]]]:
    """Validate one genome_meta.json file."""
    agent = path.parent.name
    violations: list[dict[str, Any]] = []

    try:
        payload = load_json(path)
    except ValueError as exc:
        return 0, [
            _violation(
                root=root,
                path=path,
                agent=agent,
                mutation_index=None,
                check="genome_meta_readable",
                detail=str(exc),
            )
        ]

    if not isinstance(payload, dict):
        return 0, [
            _violation(
                root=root,
                path=path,
                agent=agent,
                mutation_index=None,
                check="genome_meta_readable",
                detail="genome_meta.json must contain a top-level JSON object",
            )
        ]

    mutations = payload.get("mutations")
    if not isinstance(mutations, list):
        return 0, [
            _violation(
                root=root,
                path=path,
                agent=agent,
                mutation_index=None,
                check="mutations_list",
                detail="genome_meta.json must contain a list at key 'mutations'",
            )
        ]

    total_mutations = 0
    seen_pairs: dict[tuple[str, str], int] = {}

    for mutation_index, mutation in enumerate(mutations):
        total_mutations += 1

        if not isinstance(mutation, dict):
            violations.append(
                _violation(
                    root=root,
                    path=path,
                    agent=agent,
                    mutation_index=mutation_index,
                    check="mutation_object",
                    detail="mutation entry must be a JSON object",
                )
            )
            continue

        issue_key: str | None = None
        issue_field: str | None = None
        raw_issue_value: Any = None

        try:
            issue_field, raw_issue_value, issue_key, issue_ids = (
                resolve_mutation_issue_reference(mutation)
            )
        except ValueError as exc:
            violations.append(
                _violation(
                    root=root,
                    path=path,
                    agent=agent,
                    mutation_index=mutation_index,
                    check="history_linkage",
                    detail=str(exc),
                )
            )
        else:
            missing_issue_ids = [
                issue_id
                for issue_id in issue_ids
                if issue_id not in history_issue_ids
            ]
            if missing_issue_ids:
                violations.append(
                    _violation(
                        root=root,
                        path=path,
                        agent=agent,
                        mutation_index=mutation_index,
                        check="history_linkage",
                        detail=(
                            "issue reference(s) not found in ledger/history as "
                            "payment or trajectory_mint events"
                        ),
                        issue_field=issue_field,
                        issue_value=raw_issue_value,
                        missing_issue_ids=missing_issue_ids,
                    )
                )

        commit = mutation.get("commit")
        if not isinstance(commit, str) or not commit.strip():
            violations.append(
                _violation(
                    root=root,
                    path=path,
                    agent=agent,
                    mutation_index=mutation_index,
                    check="commit_non_empty",
                    detail="commit must be a non-empty string",
                    commit=commit,
                )
            )

        if issue_key is None:
            continue

        for target_section in extract_target_sections(mutation):
            pair = (issue_key, target_section)
            if pair in seen_pairs:
                violations.append(
                    _violation(
                        root=root,
                        path=path,
                        agent=agent,
                        mutation_index=mutation_index,
                        check="unique_issue_target_section",
                        detail=(
                            "duplicate provenance pair found within genome_meta.json; "
                            f"first seen at mutation index {seen_pairs[pair]}"
                        ),
                        issue_field=issue_field,
                        issue_value=raw_issue_value,
                        issue_key=issue_key,
                        target_section=target_section,
                        first_mutation_index=seen_pairs[pair],
                    )
                )
            else:
                seen_pairs[pair] = mutation_index

    return total_mutations, violations


def build_report(
    *,
    files_checked: int,
    mutations_checked: int,
    history_issue_ids: set[int],
    history_events_indexed: int,
    violations: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build the JSON report emitted by the CLI."""
    violation_counts = {
        check_name: sum(1 for violation in violations if violation["check"] == check_name)
        for check_name in BASE_CHECKS
    }

    checks = [
        {
            "name": check_name,
            "status": "FAIL" if violation_counts[check_name] else "PASS",
            "violations": violation_counts[check_name],
        }
        for check_name in BASE_CHECKS
    ]

    return {
        "status": "FAIL" if violations else "PASS",
        "summary": {
            "files_checked": files_checked,
            "mutations_checked": mutations_checked,
            "history_events_indexed": history_events_indexed,
            "history_issue_ids": len(history_issue_ids),
            "violations": len(violations),
        },
        "checks": checks,
        "violations": violations,
    }


def run_check(root: Path) -> tuple[dict[str, Any], int]:
    """Run the mutation provenance validation for a repository root."""
    genomes_dir = root / "genomes"
    if not genomes_dir.is_dir():
        report = build_report(
            files_checked=0,
            mutations_checked=0,
            history_issue_ids=set(),
            history_events_indexed=0,
            violations=[
                _violation(
                    root=root,
                    path=None,
                    agent=None,
                    mutation_index=None,
                    check="repository",
                    detail="genomes directory not found",
                )
            ],
        )
        return report, 1

    try:
        history_issue_ids, history_events_indexed = load_history_issue_ids(root)
    except ValueError as exc:
        report = build_report(
            files_checked=0,
            mutations_checked=0,
            history_issue_ids=set(),
            history_events_indexed=0,
            violations=[
                _violation(
                    root=root,
                    path=None,
                    agent=None,
                    mutation_index=None,
                    check="repository",
                    detail=str(exc),
                )
            ],
        )
        return report, 1

    genome_paths = sorted(genomes_dir.glob("*/genome_meta.json"))
    if not genome_paths:
        report = build_report(
            files_checked=0,
            mutations_checked=0,
            history_issue_ids=history_issue_ids,
            history_events_indexed=history_events_indexed,
            violations=[
                _violation(
                    root=root,
                    path=None,
                    agent=None,
                    mutation_index=None,
                    check="repository",
                    detail="no genome_meta.json files found under genomes/",
                )
            ],
        )
        return report, 1

    total_mutations = 0
    violations: list[dict[str, Any]] = []

    for path in genome_paths:
        mutation_count, file_violations = validate_genome_meta(
            path,
            root,
            history_issue_ids,
        )
        total_mutations += mutation_count
        violations.extend(file_violations)

    report = build_report(
        files_checked=len(genome_paths),
        mutations_checked=total_mutations,
        history_issue_ids=history_issue_ids,
        history_events_indexed=history_events_indexed,
        violations=violations,
    )
    return report, 1 if violations else 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate genome mutation provenance against task history.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Repository root directory (default: auto-detected from this script)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = args.root or Path(__file__).resolve().parent.parent
    report, exit_code = run_check(root)
    print(json.dumps(report, indent=2))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
