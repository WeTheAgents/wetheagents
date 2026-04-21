#!/usr/bin/env python3
"""Validate genome_meta.json files against the repo's observed schema versions.

The current repository contains two top-level genome metadata variants:
1. ``meta_v1``: canonical genome fields
2. ``meta_v2``: ``meta_v1`` plus ``donor_lineage``

And three mutation entry variants:
1. ``mutation_release_v1``: fitness snapshot mutation written by genome tooling
2. ``mutation_memory_v1``: compact memory-note mutation
3. ``mutation_release_session_v1``: release-session instruction delta

``mutation_release_v1`` may also include a ``provenance`` block using
``provenance_v1``.

The script prints JSON and exits ``0`` when every ``genomes/*/genome_meta.json``
matches one of the supported shapes.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

REQUIRED_META_KEYS = {
    "agent_id",
    "generation",
    "parent",
    "created_at",
    "last_snapshot",
    "role",
    "fitness",
    "lineage",
    "mutations",
}
OPTIONAL_META_KEYS = {"donor_lineage"}
INTEGER_FITNESS_KEYS = {
    "tasks_completed",
    "tasks_created",
    "total_earned",
    "total_minted",
    "gauntlet_slots",
    "total_income",
}
OPTIONAL_NUMBER_FITNESS_KEYS = {
    "initiative_ratio",
    "acceptance_rate",
    "rework_rate",
    "avg_time_in_stage_hours",
    "zero_code_ratio",
    "review_quality",
    "composite_score",
}
EXPECTED_FITNESS_KEYS = INTEGER_FITNESS_KEYS | OPTIONAL_NUMBER_FITNESS_KEYS
RELEASE_MUTATION_KEYS = {
    "commit",
    "date",
    "trigger_issue",
    "author",
    "sections_changed",
    "lines_added",
    "lines_removed",
    "summary",
    "fitness_before",
    "fitness_after",
}
MEMORY_MUTATION_KEYS = {
    "trigger_issue",
    "commit",
    "severity",
    "target_section",
    "key_moment",
    "applied_at",
}
RELEASE_SESSION_MUTATION_KEYS = {"release_session", "date", "changes"}
PROVENANCE_KEYS = {"sgr_version", "proposals"}
PROPOSAL_KEYS = {
    "proposal_hash",
    "severity",
    "experience",
    "reflection_summary",
    "verdict",
    "target_section",
}
EXPERIENCE_KEYS = {"task_id", "mechanic", "outcome", "agent_role", "key_moment"}
LEGACY_EXPERIENCE_KEYS = EXPERIENCE_KEYS - {"agent_role"}
BASE_CHECKS = (
    "repository",
    "meta_shape",
    "fitness_shape",
    "mutation_shape",
    "provenance_shape",
    "timestamp_format",
    "agent_identity",
)


def load_json(path: Path) -> Any:
    """Load JSON with a stable error message."""
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise ValueError(f"{path.name} not found") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path.name} contains invalid JSON: {exc}") from exc
    except OSError as exc:
        raise ValueError(f"Could not read {path.name}: {exc}") from exc


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


def _is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number_or_none(value: Any) -> bool:
    if value is None:
        return True
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _parse_iso_timestamp(value: Any) -> bool:
    if not _is_non_empty_string(value):
        return False
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        datetime.fromisoformat(text)
    except ValueError:
        return False
    return "T" in value


def _parse_iso_date(value: Any) -> bool:
    if not _is_non_empty_string(value):
        return False
    try:
        datetime.strptime(value.strip(), "%Y-%m-%d")
    except ValueError:
        return False
    return True


def _valid_issue_reference(value: Any) -> bool:
    if _is_int(value):
        return value >= 0
    if not _is_non_empty_string(value):
        return False
    parts = [part.strip() for part in value.split("+")]
    return bool(parts) and all(part.isdigit() for part in parts)


def _valid_string_list(value: Any) -> bool:
    return isinstance(value, list) and all(_is_non_empty_string(item) for item in value)


def _valid_snapshot_block(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    return all(_is_non_empty_string(key) and _is_int(item) for key, item in value.items())


def classify_meta_version(meta: dict[str, Any]) -> str | None:
    """Return the supported top-level schema variant for a genome meta object."""
    keys = set(meta)
    if keys == REQUIRED_META_KEYS:
        return "meta_v1"
    if keys == REQUIRED_META_KEYS | OPTIONAL_META_KEYS:
        return "meta_v2"
    return None


def classify_mutation_version(mutation: dict[str, Any]) -> str | None:
    """Return the supported mutation schema variant for a mutation object."""
    keys = set(mutation)
    if keys == RELEASE_MUTATION_KEYS:
        return "mutation_release_v1"
    if keys == RELEASE_MUTATION_KEYS | {"provenance"}:
        return "mutation_release_v1+provenance_v1"
    if keys == MEMORY_MUTATION_KEYS:
        return "mutation_memory_v1"
    if keys == RELEASE_SESSION_MUTATION_KEYS:
        return "mutation_release_session_v1"
    return None


def validate_provenance(
    provenance: Any,
    *,
    root: Path,
    path: Path,
    agent: str,
    mutation_index: int,
) -> tuple[str | None, list[dict[str, Any]]]:
    """Validate the optional provenance block attached to a release mutation."""
    if not isinstance(provenance, dict):
        return None, [
            _violation(
                root=root,
                path=path,
                agent=agent,
                mutation_index=mutation_index,
                check="provenance_shape",
                detail="provenance must be a JSON object",
            )
        ]

    if set(provenance) != PROVENANCE_KEYS:
        return None, [
            _violation(
                root=root,
                path=path,
                agent=agent,
                mutation_index=mutation_index,
                check="provenance_shape",
                detail="unsupported provenance key set",
                keys=sorted(provenance),
                expected_keys=sorted(PROVENANCE_KEYS),
            )
        ]

    sgr_version = provenance.get("sgr_version")
    if not _is_int(sgr_version):
        return None, [
            _violation(
                root=root,
                path=path,
                agent=agent,
                mutation_index=mutation_index,
                check="provenance_shape",
                detail="sgr_version must be an integer",
                sgr_version=sgr_version,
            )
        ]

    if sgr_version != 1:
        return None, [
            _violation(
                root=root,
                path=path,
                agent=agent,
                mutation_index=mutation_index,
                check="provenance_shape",
                detail="unsupported provenance version",
                sgr_version=sgr_version,
            )
        ]

    proposals = provenance.get("proposals")
    if not isinstance(proposals, list) or not proposals:
        return None, [
            _violation(
                root=root,
                path=path,
                agent=agent,
                mutation_index=mutation_index,
                check="provenance_shape",
                detail="proposals must be a non-empty list",
            )
        ]

    violations: list[dict[str, Any]] = []
    for proposal_index, proposal in enumerate(proposals):
        if not isinstance(proposal, dict):
            violations.append(
                _violation(
                    root=root,
                    path=path,
                    agent=agent,
                    mutation_index=mutation_index,
                    check="provenance_shape",
                    detail="proposal entry must be a JSON object",
                    proposal_index=proposal_index,
                )
            )
            continue

        if set(proposal) != PROPOSAL_KEYS:
            violations.append(
                _violation(
                    root=root,
                    path=path,
                    agent=agent,
                    mutation_index=mutation_index,
                    check="provenance_shape",
                    detail="unsupported proposal key set",
                    proposal_index=proposal_index,
                    keys=sorted(proposal),
                    expected_keys=sorted(PROPOSAL_KEYS),
                )
            )
            continue

        for field_name in (
            "proposal_hash",
            "severity",
            "reflection_summary",
            "verdict",
            "target_section",
        ):
            if not _is_non_empty_string(proposal.get(field_name)):
                violations.append(
                    _violation(
                        root=root,
                        path=path,
                        agent=agent,
                        mutation_index=mutation_index,
                        check="provenance_shape",
                        detail=f"{field_name} must be a non-empty string",
                        proposal_index=proposal_index,
                        field=field_name,
                    )
                )

        experience = proposal.get("experience")
        if not isinstance(experience, dict):
            violations.append(
                _violation(
                    root=root,
                    path=path,
                    agent=agent,
                    mutation_index=mutation_index,
                    check="provenance_shape",
                    detail="experience must be a JSON object",
                    proposal_index=proposal_index,
                )
            )
            continue

        experience_keys = set(experience)
        if experience_keys not in (EXPERIENCE_KEYS, LEGACY_EXPERIENCE_KEYS):
            violations.append(
                _violation(
                    root=root,
                    path=path,
                    agent=agent,
                    mutation_index=mutation_index,
                    check="provenance_shape",
                    detail="unsupported experience key set",
                    proposal_index=proposal_index,
                    keys=sorted(experience),
                    expected_keys=[
                        sorted(LEGACY_EXPERIENCE_KEYS),
                        sorted(EXPERIENCE_KEYS),
                    ],
                )
            )
            continue

        task_id = experience.get("task_id")
        if not (_is_int(task_id) or _is_non_empty_string(task_id)):
            violations.append(
                _violation(
                    root=root,
                    path=path,
                    agent=agent,
                    mutation_index=mutation_index,
                    check="provenance_shape",
                    detail="experience.task_id must be an integer or non-empty string",
                    proposal_index=proposal_index,
                )
            )

        for field_name in ("mechanic", "outcome", "key_moment"):
            if not _is_non_empty_string(experience.get(field_name)):
                violations.append(
                    _violation(
                        root=root,
                        path=path,
                        agent=agent,
                        mutation_index=mutation_index,
                        check="provenance_shape",
                        detail=f"experience.{field_name} must be a non-empty string",
                        proposal_index=proposal_index,
                        field=field_name,
                    )
                )

        if "agent_role" in experience and not _is_non_empty_string(
            experience.get("agent_role")
        ):
            violations.append(
                _violation(
                    root=root,
                    path=path,
                    agent=agent,
                    mutation_index=mutation_index,
                    check="provenance_shape",
                    detail="experience.agent_role must be a non-empty string",
                    proposal_index=proposal_index,
                    field="agent_role",
                )
            )

    return "provenance_v1", violations


def validate_release_mutation(
    mutation: dict[str, Any],
    *,
    root: Path,
    path: Path,
    agent: str,
    mutation_index: int,
) -> tuple[str | None, list[dict[str, Any]]]:
    """Validate the current release mutation schema variant."""
    violations: list[dict[str, Any]] = []

    commit = mutation.get("commit")
    if commit is not None and not isinstance(commit, str):
        violations.append(
            _violation(
                root=root,
                path=path,
                agent=agent,
                mutation_index=mutation_index,
                check="mutation_shape",
                detail="commit must be a string or null",
                field="commit",
            )
        )

    if not _parse_iso_timestamp(mutation.get("date")):
        violations.append(
            _violation(
                root=root,
                path=path,
                agent=agent,
                mutation_index=mutation_index,
                check="timestamp_format",
                detail="release mutation date must be an ISO-8601 timestamp",
                field="date",
                value=mutation.get("date"),
            )
        )

    if not _valid_issue_reference(mutation.get("trigger_issue")):
        violations.append(
            _violation(
                root=root,
                path=path,
                agent=agent,
                mutation_index=mutation_index,
                check="mutation_shape",
                detail="trigger_issue must be an integer or '+'-delimited integers",
                field="trigger_issue",
                value=mutation.get("trigger_issue"),
            )
        )

    if not _is_non_empty_string(mutation.get("author")):
        violations.append(
            _violation(
                root=root,
                path=path,
                agent=agent,
                mutation_index=mutation_index,
                check="mutation_shape",
                detail="author must be a non-empty string",
                field="author",
            )
        )

    if not _valid_string_list(mutation.get("sections_changed")):
        violations.append(
            _violation(
                root=root,
                path=path,
                agent=agent,
                mutation_index=mutation_index,
                check="mutation_shape",
                detail="sections_changed must be a list of non-empty strings",
                field="sections_changed",
            )
        )

    for field_name in ("lines_added", "lines_removed"):
        value = mutation.get(field_name)
        if not _is_int(value) or value < 0:
            violations.append(
                _violation(
                    root=root,
                    path=path,
                    agent=agent,
                    mutation_index=mutation_index,
                    check="mutation_shape",
                    detail=f"{field_name} must be a non-negative integer",
                    field=field_name,
                    value=value,
                )
            )

    if not _is_non_empty_string(mutation.get("summary")):
        violations.append(
            _violation(
                root=root,
                path=path,
                agent=agent,
                mutation_index=mutation_index,
                check="mutation_shape",
                detail="summary must be a non-empty string",
                field="summary",
            )
        )

    for field_name in ("fitness_before", "fitness_after"):
        value = mutation.get(field_name)
        if not _valid_snapshot_block(value):
            violations.append(
                _violation(
                    root=root,
                    path=path,
                    agent=agent,
                    mutation_index=mutation_index,
                    check="mutation_shape",
                    detail=f"{field_name} must be an object with integer values",
                    field=field_name,
                )
            )

    version = "mutation_release_v1"
    if "provenance" in mutation:
        provenance_version, provenance_violations = validate_provenance(
            mutation.get("provenance"),
            root=root,
            path=path,
            agent=agent,
            mutation_index=mutation_index,
        )
        violations.extend(provenance_violations)
        if provenance_version is not None:
            version = f"{version}+{provenance_version}"

    return version, violations


def validate_memory_mutation(
    mutation: dict[str, Any],
    *,
    root: Path,
    path: Path,
    agent: str,
    mutation_index: int,
) -> list[dict[str, Any]]:
    """Validate the compact memory mutation schema variant."""
    violations: list[dict[str, Any]] = []

    if not _valid_issue_reference(mutation.get("trigger_issue")):
        violations.append(
            _violation(
                root=root,
                path=path,
                agent=agent,
                mutation_index=mutation_index,
                check="mutation_shape",
                detail="trigger_issue must be an integer or '+'-delimited integers",
                field="trigger_issue",
                value=mutation.get("trigger_issue"),
            )
        )

    for field_name in ("commit", "severity", "target_section", "key_moment"):
        if not _is_non_empty_string(mutation.get(field_name)):
            violations.append(
                _violation(
                    root=root,
                    path=path,
                    agent=agent,
                    mutation_index=mutation_index,
                    check="mutation_shape",
                    detail=f"{field_name} must be a non-empty string",
                    field=field_name,
                )
            )

    if not _parse_iso_timestamp(mutation.get("applied_at")):
        violations.append(
            _violation(
                root=root,
                path=path,
                agent=agent,
                mutation_index=mutation_index,
                check="timestamp_format",
                detail="memory mutation applied_at must be an ISO-8601 timestamp",
                field="applied_at",
                value=mutation.get("applied_at"),
            )
        )

    return violations


def validate_release_session_mutation(
    mutation: dict[str, Any],
    *,
    root: Path,
    path: Path,
    agent: str,
    mutation_index: int,
) -> list[dict[str, Any]]:
    """Validate the release-session mutation schema variant."""
    violations: list[dict[str, Any]] = []

    if not _is_non_empty_string(mutation.get("release_session")):
        violations.append(
            _violation(
                root=root,
                path=path,
                agent=agent,
                mutation_index=mutation_index,
                check="mutation_shape",
                detail="release_session must be a non-empty string",
                field="release_session",
            )
        )

    date = mutation.get("date")
    if not (_parse_iso_date(date) or _parse_iso_timestamp(date)):
        violations.append(
            _violation(
                root=root,
                path=path,
                agent=agent,
                mutation_index=mutation_index,
                check="timestamp_format",
                detail="release session date must be YYYY-MM-DD or ISO-8601 timestamp",
                field="date",
                value=date,
            )
        )

    if not _valid_string_list(mutation.get("changes")):
        violations.append(
            _violation(
                root=root,
                path=path,
                agent=agent,
                mutation_index=mutation_index,
                check="mutation_shape",
                detail="changes must be a list of non-empty strings",
                field="changes",
            )
        )

    return violations


def validate_genome_meta(
    path: Path,
    root: Path,
) -> tuple[str | None, Counter[str], int, list[dict[str, Any]]]:
    """Validate one genome_meta.json file and return version counts plus violations."""
    agent = path.parent.name

    try:
        payload = load_json(path)
    except ValueError as exc:
        return None, Counter(), 0, [
            _violation(
                root=root,
                path=path,
                agent=agent,
                mutation_index=None,
                check="meta_shape",
                detail=str(exc),
            )
        ]

    if not isinstance(payload, dict):
        return None, Counter(), 0, [
            _violation(
                root=root,
                path=path,
                agent=agent,
                mutation_index=None,
                check="meta_shape",
                detail="genome_meta.json must contain a JSON object",
            )
        ]

    violations: list[dict[str, Any]] = []
    meta_version = classify_meta_version(payload)
    if meta_version is None:
        violations.append(
            _violation(
                root=root,
                path=path,
                agent=agent,
                mutation_index=None,
                check="meta_shape",
                detail="unsupported top-level key set",
                keys=sorted(payload),
                expected_keys=sorted(REQUIRED_META_KEYS),
                optional_keys=sorted(OPTIONAL_META_KEYS),
            )
        )

    agent_id = payload.get("agent_id")
    if not _is_non_empty_string(agent_id):
        violations.append(
            _violation(
                root=root,
                path=path,
                agent=agent,
                mutation_index=None,
                check="agent_identity",
                detail="agent_id must be a non-empty string",
                value=agent_id,
            )
        )
    elif agent_id != agent:
        violations.append(
            _violation(
                root=root,
                path=path,
                agent=agent,
                mutation_index=None,
                check="agent_identity",
                detail="agent_id must match its genome directory name",
                agent_id=agent_id,
                directory=agent,
            )
        )

    generation = payload.get("generation")
    if not _is_int(generation) or generation < 0:
        violations.append(
            _violation(
                root=root,
                path=path,
                agent=agent,
                mutation_index=None,
                check="meta_shape",
                detail="generation must be a non-negative integer",
                value=generation,
            )
        )

    parent = payload.get("parent")
    if parent is not None and not _is_non_empty_string(parent):
        violations.append(
            _violation(
                root=root,
                path=path,
                agent=agent,
                mutation_index=None,
                check="meta_shape",
                detail="parent must be null or a non-empty string",
                value=parent,
            )
        )

    for field_name in ("created_at", "last_snapshot"):
        value = payload.get(field_name)
        if not _parse_iso_timestamp(value):
            violations.append(
                _violation(
                    root=root,
                    path=path,
                    agent=agent,
                    mutation_index=None,
                    check="timestamp_format",
                    detail=f"{field_name} must be an ISO-8601 timestamp",
                    field=field_name,
                    value=value,
                )
            )

    if not _is_non_empty_string(payload.get("role")):
        violations.append(
            _violation(
                root=root,
                path=path,
                agent=agent,
                mutation_index=None,
                check="meta_shape",
                detail="role must be a non-empty string",
                value=payload.get("role"),
            )
        )

    lineage = payload.get("lineage")
    if not _valid_string_list(lineage) and lineage != []:
        violations.append(
            _violation(
                root=root,
                path=path,
                agent=agent,
                mutation_index=None,
                check="meta_shape",
                detail="lineage must be a list of non-empty strings",
                value=lineage,
            )
        )

    donor_lineage = payload.get("donor_lineage")
    if "donor_lineage" in payload and not _valid_string_list(donor_lineage):
        violations.append(
            _violation(
                root=root,
                path=path,
                agent=agent,
                mutation_index=None,
                check="meta_shape",
                detail="donor_lineage must be a list of non-empty strings",
                value=donor_lineage,
            )
        )

    fitness = payload.get("fitness")
    if not isinstance(fitness, dict):
        violations.append(
            _violation(
                root=root,
                path=path,
                agent=agent,
                mutation_index=None,
                check="fitness_shape",
                detail="fitness must be a JSON object",
                value=fitness,
            )
        )
    else:
        if set(fitness) != EXPECTED_FITNESS_KEYS:
            violations.append(
                _violation(
                    root=root,
                    path=path,
                    agent=agent,
                    mutation_index=None,
                    check="fitness_shape",
                    detail="fitness keys do not match the supported schema",
                    keys=sorted(fitness),
                    expected_keys=sorted(EXPECTED_FITNESS_KEYS),
                )
            )

        for field_name in sorted(INTEGER_FITNESS_KEYS):
            value = fitness.get(field_name)
            if not _is_int(value) or value < 0:
                violations.append(
                    _violation(
                        root=root,
                        path=path,
                        agent=agent,
                        mutation_index=None,
                        check="fitness_shape",
                        detail=f"fitness.{field_name} must be a non-negative integer",
                        field=field_name,
                        value=value,
                    )
                )

        for field_name in sorted(OPTIONAL_NUMBER_FITNESS_KEYS):
            value = fitness.get(field_name)
            if not _is_number_or_none(value):
                violations.append(
                    _violation(
                        root=root,
                        path=path,
                        agent=agent,
                        mutation_index=None,
                        check="fitness_shape",
                        detail=f"fitness.{field_name} must be a number or null",
                        field=field_name,
                        value=value,
                    )
                )

    mutations = payload.get("mutations")
    if not isinstance(mutations, list):
        violations.append(
            _violation(
                root=root,
                path=path,
                agent=agent,
                mutation_index=None,
                check="meta_shape",
                detail="mutations must be a list",
                value=mutations,
            )
        )
        return meta_version, Counter(), 0, violations

    mutation_versions: Counter[str] = Counter()

    for mutation_index, mutation in enumerate(mutations):
        if not isinstance(mutation, dict):
            violations.append(
                _violation(
                    root=root,
                    path=path,
                    agent=agent,
                    mutation_index=mutation_index,
                    check="mutation_shape",
                    detail="mutation entry must be a JSON object",
                )
            )
            continue

        mutation_version = classify_mutation_version(mutation)
        if mutation_version is None:
            violations.append(
                _violation(
                    root=root,
                    path=path,
                    agent=agent,
                    mutation_index=mutation_index,
                    check="mutation_shape",
                    detail="unsupported mutation key set",
                    keys=sorted(mutation),
                )
            )
            continue

        mutation_versions[mutation_version] += 1

        if mutation_version.startswith("mutation_release_v1"):
            resolved_version, mutation_violations = validate_release_mutation(
                mutation,
                root=root,
                path=path,
                agent=agent,
                mutation_index=mutation_index,
            )
            if resolved_version is not None and resolved_version != mutation_version:
                mutation_versions[mutation_version] -= 1
                mutation_versions[resolved_version] += 1
            violations.extend(mutation_violations)
        elif mutation_version == "mutation_memory_v1":
            violations.extend(
                validate_memory_mutation(
                    mutation,
                    root=root,
                    path=path,
                    agent=agent,
                    mutation_index=mutation_index,
                )
            )
        else:
            violations.extend(
                validate_release_session_mutation(
                    mutation,
                    root=root,
                    path=path,
                    agent=agent,
                    mutation_index=mutation_index,
                )
            )

    return meta_version, mutation_versions, len(mutations), violations


def build_report(
    *,
    files_checked: int,
    mutations_checked: int,
    meta_versions: Counter[str],
    mutation_versions: Counter[str],
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
            "meta_versions": dict(sorted(meta_versions.items())),
            "mutation_versions": dict(sorted(mutation_versions.items())),
            "violations": len(violations),
        },
        "checks": checks,
        "violations": violations,
    }


def run_check(root: Path) -> tuple[dict[str, Any], int]:
    """Run the checker for a repository root."""
    genomes_dir = root / "genomes"
    if not genomes_dir.is_dir():
        report = build_report(
            files_checked=0,
            mutations_checked=0,
            meta_versions=Counter(),
            mutation_versions=Counter(),
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

    genome_paths = sorted(genomes_dir.glob("*/genome_meta.json"))
    if not genome_paths:
        report = build_report(
            files_checked=0,
            mutations_checked=0,
            meta_versions=Counter(),
            mutation_versions=Counter(),
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

    meta_versions: Counter[str] = Counter()
    mutation_versions: Counter[str] = Counter()
    total_mutations = 0
    violations: list[dict[str, Any]] = []

    for path in genome_paths:
        meta_version, file_mutation_versions, mutation_count, file_violations = (
            validate_genome_meta(path, root)
        )
        if meta_version is not None:
            meta_versions[meta_version] += 1
        mutation_versions.update(file_mutation_versions)
        total_mutations += mutation_count
        violations.extend(file_violations)

    report = build_report(
        files_checked=len(genome_paths),
        mutations_checked=total_mutations,
        meta_versions=meta_versions,
        mutation_versions=mutation_versions,
        violations=violations,
    )
    return report, 1 if violations else 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description="Validate genome_meta.json schema-version consistency.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Repository root directory (default: auto-detected from this script)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint."""
    args = parse_args(argv)
    root = args.root or Path(__file__).resolve().parent.parent
    report, exit_code = run_check(root)
    print(json.dumps(report, indent=2))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
