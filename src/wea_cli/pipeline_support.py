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


def render_pipeline_comment(stage: str, payload: dict[str, Any], agent_id: str) -> str:
    normalized = normalize_stage(stage)
    header = COMMENT_HEADERS.get(normalized, f"{normalized.title()} Evaluation")
    body = json.dumps(payload, indent=2, ensure_ascii=False)
    return f"### {header} by {agent_id}\n\n```json\n{body}\n```"
