"""Helpers for Pipeline v3 CLI commands."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PIPELINE_STAGES = {"triage", "negativa", "spec", "impl", "verify"}

COMMENT_HEADERS = {
    "negativa": "Negativa Evaluation",
    "spec": "Spec Review",
    "impl": "Impl Evaluation",
    "verify": "Verification Review",
    "triage": "Triage Record",
}


def normalize_stage(stage: str) -> str:
    normalized = stage.strip().lower()
    if normalized not in PIPELINE_STAGES:
        raise ValueError(f"Unknown pipeline stage: {stage!r}")
    return normalized


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(_read_text(path))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


def _genome_path(root: Path, agent_id: str | None) -> Path:
    if agent_id:
        candidate = root / "genomes" / agent_id / "AGENTS.local.md"
        if candidate.exists():
            return candidate
    return root / "genomes" / "base" / "AGENTS.local.template.md"


def _split_constitution_and_genome(markdown: str) -> tuple[str, str]:
    lines = markdown.strip().splitlines()
    for idx, line in enumerate(lines):
        if line.startswith("## "):
            constitution = "\n".join(lines[:idx]).strip()
            genome = "\n".join(lines[idx:]).strip()
            return constitution, genome
    return markdown.strip(), ""


def stage_dir(root: Path, stage: str) -> Path:
    normalized = normalize_stage(stage)
    path = root / "pipeline" / normalized
    if not path.exists():
        raise FileNotFoundError(f"Pipeline stage directory not found: {path}")
    return path


def load_stage_schema(root: Path, stage: str) -> dict[str, Any]:
    return _read_json(stage_dir(root, stage) / "evaluation.schema.json")


def load_stage_checklist(root: Path, stage: str) -> dict[str, Any]:
    return _read_json(stage_dir(root, stage) / "checklist.json")


def load_stage_workflow(root: Path, stage: str) -> str:
    return _read_text(stage_dir(root, stage) / "WORKFLOW.md").strip()


def render_pipeline_context(root: Path, stage: str, agent_id: str | None) -> str:
    normalized = normalize_stage(stage)
    genome_text = _read_text(_genome_path(root, agent_id))
    constitution, genome = _split_constitution_and_genome(genome_text)
    checklist = json.dumps(load_stage_checklist(root, normalized), indent=2, ensure_ascii=False)
    schema = json.dumps(load_stage_schema(root, normalized), indent=2, ensure_ascii=False)
    sections = [
        "## Constitution",
        constitution,
        "## Genome",
        genome or "(No genome sections available.)",
        f"## Stage Rules: {normalized}",
        load_stage_workflow(root, normalized),
        f"## Stage Checklist: {normalized}",
        f"```json\n{checklist}\n```",
        f"## Stage Schema: {normalized}",
        f"```json\n{schema}\n```",
    ]
    return "\n\n".join(sections).strip() + "\n"


def validate_stage_payload(root: Path, stage: str, payload: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_stage(stage)
    try:
        from jsonschema import validate
    except ImportError:
        raise ImportError("jsonschema is required for pipeline commands. Install with: pip install jsonschema")
    validate(instance=payload, schema=load_stage_schema(root, normalized))
    return payload


def compute_overall_score(rubrics: dict[str, dict], weights: dict[str, float]) -> float:
    """Compute weighted average quality score from rubric scores.

    Args:
        rubrics: mapping of rubric_name -> {"score": float, "note": str}
        weights: mapping of rubric_name -> float (must sum to 1.0 within tolerance 1e-9)

    Returns:
        float in [0.0, 1.0] rounded to 10 decimal places

    Raises:
        ValueError: if weights do not sum to 1.0, or rubric keys do not match weight keys
    """
    if abs(sum(weights.values()) - 1.0) > 1e-9:
        raise ValueError(f"weights must sum to 1.0, got {sum(weights.values())}")
    if set(rubrics.keys()) != set(weights.keys()):
        raise ValueError(
            f"rubric keys {set(rubrics.keys())} do not match weight keys {set(weights.keys())}"
        )
    score = sum(rubrics[k]["score"] * w for k, w in weights.items())
    return round(min(1.0, max(0.0, score)), 10)


_VERIFY_WEIGHTS: dict[str, float] = {
    "gaming": 0.15,
    "spec_conformance": 0.15,
    "scope_violation": 0.12,
    "fragility": 0.12,
    "test_coverage": 0.12,
    "dead_code": 0.08,
    "error_handling": 0.08,
    "documentation": 0.08,
    "performance_risk": 0.05,
    "naming_clarity": 0.05,
}

_AUTO_APPROVE_THRESHOLD = 0.85
_REFINEMENT_THRESHOLD = 0.60


def _eval_score(eval_payload: dict[str, Any]) -> float:
    """Extract or compute a score for a single verify evaluation payload.

    Priority order:
    1. overall_score field (recomputed by aggregator from rubrics).
    2. rubrics field — compute via VERIFY_WEIGHTS.
    3. Legacy fallback: APPROVED verdict → 1.0, anything else → 0.0.
    """
    if "overall_score" in eval_payload:
        return float(eval_payload["overall_score"])
    if "rubrics" in eval_payload:
        return compute_overall_score(eval_payload["rubrics"], _VERIFY_WEIGHTS)
    # Legacy format: map verdict to binary score
    return 1.0 if eval_payload.get("verdict") == "APPROVED" else 0.0


def derive_status(
    evaluations: list[dict[str, Any]],
    refinement_requests: list[dict[str, Any]],
    verify_max_iterations: int,
) -> str:
    """Derive the current verify loop status from pre-parsed lists.

    Uses score-based thresholds (same as aggregate_results) so the two tools
    always agree on mixed-verdict groups.

    Pure function — no network access. Suitable for unit testing without mocking.
    Module: src/wea_cli/pipeline_support.py

    Args:
        evaluations: list of verify evaluation payloads (already filtered to station=verify,
            type != refinement_request). Missing 'iteration' defaults to 1.
        refinement_requests: list of refinement_request payloads (type == refinement_request).
        verify_max_iterations: from pipeline/config.json.

    Returns:
        One of: "awaiting_review", "awaiting_fix", "APPROVED", "ESCALATE"
    """
    if not evaluations:
        return "awaiting_review"

    current_iteration = max(int(e.get("iteration", 1)) for e in evaluations)
    latest_group = [e for e in evaluations if int(e.get("iteration", 1)) == current_iteration]

    scores = [_eval_score(e) for e in latest_group]
    avg = sum(scores) / len(scores)

    # APPROVED checked first — mirrors aggregate_results to guarantee agreement
    if avg >= _AUTO_APPROVE_THRESHOLD:
        return "APPROVED"
    if current_iteration >= verify_max_iterations:
        return "ESCALATE"
    rr_iters = {int(rr.get("iteration", 1)) for rr in refinement_requests}
    if current_iteration in rr_iters:
        return "awaiting_fix"
    return "awaiting_review"


def render_pipeline_comment(stage: str, payload: dict[str, Any], agent_id: str) -> str:
    normalized = normalize_stage(stage)
    header = COMMENT_HEADERS.get(normalized, f"{normalized.title()} Evaluation")
    body = json.dumps(payload, indent=2, ensure_ascii=False)
    return f"### {header} by {agent_id}\n\n```json\n{body}\n```"
