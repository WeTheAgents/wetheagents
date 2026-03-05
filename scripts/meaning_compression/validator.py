"""Deterministic validator for Meaning Compression submissions."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PACKAGE_ROOT = Path(__file__).resolve().parent
DEFAULT_ATOMS_PATH = PACKAGE_ROOT / "atoms.json"
DEFAULT_SCHEMA_PATH = PACKAGE_ROOT / "submission.schema.json"

WORD_RE = re.compile(r"\S+")

REQUIRED_TOP_LEVEL = {"text_en", "atoms_claimed", "metrics", "agent", "cost"}
OPTIONAL_TOP_LEVEL = {"text_other"}
ALLOWED_TOP_LEVEL = REQUIRED_TOP_LEVEL | OPTIONAL_TOP_LEVEL
METRIC_KEYS = {"word_count", "atoms_count"}
COST_KEYS = {"model", "tokens_input", "tokens_output"}


@dataclass(slots=True)
class ValidationReport:
    errors: list[str]
    baseline_metrics: dict[str, int]
    submission_metrics: dict[str, int]

    @property
    def ok(self) -> bool:
        return not self.errors


def load_json_file(path: Path | str) -> Any:
    payload_path = Path(path)
    return json.loads(payload_path.read_text(encoding="utf-8-sig"))


def load_atom_index(path: Path | str = DEFAULT_ATOMS_PATH) -> dict[str, dict[str, Any]]:
    payload = load_json_file(path)
    if not isinstance(payload, list):
        raise ValueError(f"Atom set must be a JSON array: {path}")

    index: dict[str, dict[str, Any]] = {}
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError("Each atom must be a JSON object.")
        atom_id = item.get("id")
        statement = item.get("statement")
        if not isinstance(atom_id, str) or not atom_id.strip():
            raise ValueError("Each atom must have a non-empty string id.")
        if not isinstance(statement, str) or not statement.strip():
            raise ValueError(f"Atom {atom_id!r} must have a non-empty statement.")
        if atom_id in index:
            raise ValueError(f"Duplicate atom id: {atom_id}")
        index[atom_id] = item
    return index


def count_words(text: str) -> int:
    """Count words using whitespace-delimited tokens from text_en only."""
    return len(WORD_RE.findall(text.strip()))


def _check_object_keys(
    payload: dict[str, Any],
    *,
    label: str,
    required: set[str],
    allowed: set[str],
    errors: list[str],
) -> None:
    missing = sorted(required - payload.keys())
    extras = sorted(set(payload.keys()) - allowed)
    if missing:
        errors.append(f"{label}: missing required fields: {', '.join(missing)}")
    if extras:
        errors.append(f"{label}: unexpected fields: {', '.join(extras)}")


def _validate_metrics(
    metrics: Any,
    *,
    label: str,
    computed_metrics: dict[str, int],
    errors: list[str],
) -> None:
    if not isinstance(metrics, dict):
        errors.append(f"{label}: metrics must be an object.")
        return

    _check_object_keys(
        metrics,
        label=f"{label}.metrics",
        required=METRIC_KEYS,
        allowed=METRIC_KEYS,
        errors=errors,
    )
    for key in sorted(METRIC_KEYS):
        value = metrics.get(key)
        if type(value) is not int or value < 0:
            errors.append(f"{label}.metrics.{key} must be a non-negative integer.")
            continue
        expected = computed_metrics[key]
        if value != expected:
            errors.append(
                f"{label}.metrics.{key}={value} does not match computed value {expected}."
            )


def _validate_cost(cost: Any, *, label: str, errors: list[str]) -> None:
    if not isinstance(cost, dict):
        errors.append(f"{label}: cost must be an object.")
        return

    _check_object_keys(
        cost,
        label=f"{label}.cost",
        required=COST_KEYS,
        allowed=COST_KEYS,
        errors=errors,
    )

    model = cost.get("model")
    if not isinstance(model, str) or not model.strip():
        errors.append(f"{label}.cost.model must be a non-empty string.")

    for key in ("tokens_input", "tokens_output"):
        value = cost.get(key)
        if value is None:
            continue
        if type(value) is not int or value < 0:
            errors.append(f"{label}.cost.{key} must be null or a non-negative integer.")


def validate_submission_payload(
    payload: Any,
    *,
    label: str,
    known_atoms: dict[str, dict[str, Any]],
) -> tuple[list[str], dict[str, int]]:
    """Validate one submission payload and compute deterministic metrics."""
    errors: list[str] = []
    computed_metrics = {"word_count": 0, "atoms_count": 0}

    if not isinstance(payload, dict):
        return [f"{label}: submission must be a JSON object."], computed_metrics

    _check_object_keys(
        payload,
        label=label,
        required=REQUIRED_TOP_LEVEL,
        allowed=ALLOWED_TOP_LEVEL,
        errors=errors,
    )

    text_en = payload.get("text_en")
    if not isinstance(text_en, str) or not text_en.strip():
        errors.append(f"{label}: text_en must be a non-empty string.")
    else:
        computed_metrics["word_count"] = count_words(text_en)

    if "text_other" in payload:
        text_other = payload.get("text_other")
        if text_other is not None and not isinstance(text_other, str):
            errors.append(f"{label}: text_other must be a string or null.")

    atoms_claimed = payload.get("atoms_claimed")
    normalized_atoms: list[str] = []
    if not isinstance(atoms_claimed, list) or not atoms_claimed:
        errors.append(f"{label}: atoms_claimed must be a non-empty array.")
    else:
        duplicates: set[str] = set()
        seen: set[str] = set()
        for atom in atoms_claimed:
            if not isinstance(atom, str) or not atom.strip():
                errors.append(f"{label}: each atoms_claimed entry must be a non-empty string.")
                continue
            atom_id = atom.strip()
            normalized_atoms.append(atom_id)
            if atom_id in seen:
                duplicates.add(atom_id)
            seen.add(atom_id)

        if duplicates:
            errors.append(
                f"{label}: atoms_claimed contains duplicates: {', '.join(sorted(duplicates))}"
            )

        unknown_atoms = sorted({atom_id for atom_id in normalized_atoms if atom_id not in known_atoms})
        if unknown_atoms:
            errors.append(f"{label}: unknown atom IDs: {', '.join(unknown_atoms)}")

        computed_metrics["atoms_count"] = len(normalized_atoms)

    _validate_metrics(payload.get("metrics"), label=label, computed_metrics=computed_metrics, errors=errors)

    agent = payload.get("agent")
    if not isinstance(agent, str) or not agent.strip():
        errors.append(f"{label}: agent must be a non-empty string.")

    _validate_cost(payload.get("cost"), label=label, errors=errors)

    return errors, computed_metrics


def validate_pair(
    baseline_payload: Any,
    submission_payload: Any,
    *,
    atom_index: dict[str, dict[str, Any]] | None = None,
) -> ValidationReport:
    """Validate a baseline record against a challenger submission."""
    known_atoms = atom_index or load_atom_index()

    baseline_errors, baseline_metrics = validate_submission_payload(
        baseline_payload,
        label="baseline",
        known_atoms=known_atoms,
    )
    submission_errors, submission_metrics = validate_submission_payload(
        submission_payload,
        label="submission",
        known_atoms=known_atoms,
    )

    errors = [*baseline_errors, *submission_errors]

    if not errors:
        if submission_metrics["word_count"] >= baseline_metrics["word_count"]:
            errors.append(
                "escalation: submission word_count must be smaller than baseline "
                f"({submission_metrics['word_count']} >= {baseline_metrics['word_count']})."
            )
        if submission_metrics["atoms_count"] <= baseline_metrics["atoms_count"]:
            errors.append(
                "escalation: submission atoms_count must be greater than baseline "
                f"({submission_metrics['atoms_count']} <= {baseline_metrics['atoms_count']})."
            )

    return ValidationReport(
        errors=errors,
        baseline_metrics=baseline_metrics,
        submission_metrics=submission_metrics,
    )


def format_report(report: ValidationReport) -> str:
    status = "PASS" if report.ok else "FAIL"
    lines = [
        status,
        f"baseline: words={report.baseline_metrics['word_count']} atoms={report.baseline_metrics['atoms_count']}",
        f"submission: words={report.submission_metrics['word_count']} atoms={report.submission_metrics['atoms_count']}",
    ]
    if report.errors:
        lines.append("errors:")
        lines.extend(f"- {error}" for error in report.errors)
    return "\n".join(lines)
