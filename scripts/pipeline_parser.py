"""Parse Pipeline v3 evaluation comments."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from wea_cli.pipeline_support import (
    compute_overall_score,
    load_stage_schema,
    normalize_stage,
)

ROOT = Path(__file__).resolve().parents[1]

VERIFY_WEIGHTS: dict[str, float] = {
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

VERIFY_LEGACY_WEIGHTS: dict[str, float] = {
    "gaming": 0.40,
    "out_of_scope": 0.20,
    "fragility": 0.25,
    "removable_code": 0.15,
}

JSON_BLOCK_RE = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)
HEADER_RE = re.compile(r"^###\s+.+?\s+by\s+([^\n]+)\s*$", re.MULTILINE)
LEGACY_SEPARATOR_RE = r"\s+[—-]\s+"


@dataclass
class EvaluationResult:
    station: str
    agent_id: str
    verdict: str
    format: str
    payload: dict[str, Any]
    raw_comment: str

    @property
    def checks(self) -> dict[str, Any]:
        for key in ("checks", "checklist"):
            value = self.payload.get(key)
            if isinstance(value, dict):
                return value
        return {}

    @property
    def reasoning(self) -> str:
        for key in ("reasoning", "summary", "notes"):
            value = self.payload.get(key)
            if isinstance(value, str):
                return value
        return ""


@dataclass
class AggregateResult:
    station: str
    verdict: str
    evaluations: list[EvaluationResult] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    iteration: int = 1  # highest iteration group that produced the verdict
    a_c: float | None = None  # Normalized Change metric from ci_delta (verify only)


def load_station_schema(station: str, root: Path | None = None) -> dict[str, Any]:
    return load_stage_schema(root or ROOT, station)


def _extract_json_payloads(body: str) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for match in JSON_BLOCK_RE.finditer(body):
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError as e:
            raise ValueError(f"Malformed JSON in evaluation block at line {e.lineno}, col {e.colno}: {e.msg}") from e
        if not isinstance(payload, dict):
            raise ValueError("JSON evaluation block must be an object.")
        payloads.append(payload)
    return payloads


def _extract_agent_from_header(body: str) -> str:
    match = HEADER_RE.search(body)
    if not match:
        return "unknown"
    return match.group(1).strip()


def _payload_verdict(station: str, payload: dict[str, Any]) -> str:
    keys = ("approval",) if normalize_stage(station) == "spec" else ("verdict",)
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "UNKNOWN"


def _validate_json_payload(station: str, payload: dict[str, Any], root: Path | None) -> dict[str, Any]:
    try:
        from jsonschema import validate
    except ImportError:
        raise ImportError("jsonschema is required for pipeline commands. Install with: pip install jsonschema")
    validate(instance=payload, schema=load_station_schema(station, root=root))
    return payload


def _parse_negativa_legacy(body: str) -> EvaluationResult:
    checks: dict[str, dict[str, str]] = {}
    for label, slug in (
        ("Architecture compatible", "architecture_compatible"),
        ("No fragility", "no_fragility"),
    ):
        pattern = rf"^\d+\.\s+{re.escape(label)}:\s+(PASS|FAIL){LEGACY_SEPARATOR_RE}(.+)$"
        match = re.search(pattern, body, re.MULTILINE)
        if not match:
            raise ValueError(f"Missing legacy negativa check: {label}.")
        checks[slug] = {"status": match.group(1), "note": match.group(2).strip()}

    verdict_match = re.search(r"^Verdict:\s+(PROCEED|KILL)(?:\s*\((.+)\))?$", body, re.MULTILINE)
    if not verdict_match:
        raise ValueError("Missing legacy negativa verdict.")

    payload = {
        "station": "negativa",
        "agent_id": _extract_agent_from_header(body),
        "verdict": verdict_match.group(1),
        "summary": (verdict_match.group(2) or "legacy negative evaluation").strip(),
        "checks": checks,
    }
    return EvaluationResult("negativa", payload["agent_id"], payload["verdict"], "legacy", payload, body)


def _parse_spec_legacy(body: str) -> EvaluationResult:
    red_team_match = re.search(
        r"^Red Team result:\s+(GAMING FOUND|NO GAMING FOUND)\s*$", body, re.MULTILINE
    )
    approval_match = re.search(r"^Approval:\s+(APPROVED|REJECTED)\s*$", body, re.MULTILINE)
    if not red_team_match or not approval_match:
        raise ValueError("Missing legacy spec review fields.")

    findings = [
        line[2:].strip()
        for line in body.splitlines()
        if line.startswith("- ") and line[2:].strip() and line[2:].strip().lower() != "none"
    ]
    payload = {
        "station": "spec",
        "agent_id": _extract_agent_from_header(body),
        "red_team_result": red_team_match.group(1).replace(" ", "_"),
        "approval": approval_match.group(1),
        "findings": findings,
        "notes": "legacy spec review",
    }
    return EvaluationResult("spec", payload["agent_id"], payload["approval"], "legacy", payload, body)


def _parse_verify_legacy(body: str) -> EvaluationResult:
    checklist: dict[str, dict[str, str]] = {}
    mapping = {
        "Gaming": "gaming",
        "Out-of-scope": "out_of_scope",
        "Fragility": "fragility",
        "Removable code": "removable_code",
    }
    for label, slug in mapping.items():
        pattern = rf"^- {re.escape(label)}:\s+(NONE|FOUND){LEGACY_SEPARATOR_RE}(.+)$"
        match = re.search(pattern, body, re.MULTILINE)
        if not match:
            raise ValueError(f"Missing legacy verify checklist item: {label}")
        checklist[slug] = {"status": match.group(1), "note": match.group(2).strip()}

    blocking_match = re.search(r"^Blocking comments:\s+(YES|NO)\s*$", body, re.MULTILINE)
    verdict_match = re.search(r"^Verdict:\s+(APPROVED|CHANGES REQUESTED)\s*$", body, re.MULTILINE)
    if not blocking_match or not verdict_match:
        raise ValueError("Missing legacy verification verdict fields.")

    payload = {
        "station": "verify",
        "agent_id": _extract_agent_from_header(body),
        "checklist": checklist,
        "blocking_comments": [] if blocking_match.group(1) == "NO" else ["legacy blocking comments present"],
        "verdict": verdict_match.group(1).replace(" ", "_"),
        "summary": "legacy verification review",
    }
    return EvaluationResult("verify", payload["agent_id"], payload["verdict"], "legacy", payload, body)


def _parse_triage_legacy(body: str) -> EvaluationResult:
    verdict_match = re.search(r"^Verdict:\s+(GO|NO_GO)(?:\s*\((.+)\))?$", body, re.MULTILINE)
    agent_id = _extract_agent_from_header(body)
    if not verdict_match:
        payload = {"station": "triage", "agent_id": agent_id, "verdict": "UNKNOWN", "summary": "unparseable triage evaluation"}
        return EvaluationResult("triage", agent_id, "UNKNOWN", "legacy_unparsed", payload, body)
    payload = {
        "station": "triage",
        "agent_id": agent_id,
        "verdict": verdict_match.group(1),
        "summary": (verdict_match.group(2) or "legacy triage evaluation").strip(),
    }
    return EvaluationResult("triage", agent_id, payload["verdict"], "legacy", payload, body)


def _parse_impl_legacy(body: str) -> EvaluationResult:
    verdict_match = re.search(r"^Verdict:\s+(PASS|FAIL)(?:\s*\((.+)\))?$", body, re.MULTILINE)
    agent_id = _extract_agent_from_header(body)
    if not verdict_match:
        payload = {"station": "impl", "agent_id": agent_id, "verdict": "UNKNOWN", "summary": "unparseable impl evaluation"}
        return EvaluationResult("impl", agent_id, "UNKNOWN", "legacy_unparsed", payload, body)
    payload = {
        "station": "impl",
        "agent_id": agent_id,
        "verdict": verdict_match.group(1),
        "summary": (verdict_match.group(2) or "legacy impl evaluation").strip(),
    }
    return EvaluationResult("impl", agent_id, payload["verdict"], "legacy", payload, body)


def _parse_legacy_comment(body: str, station: str) -> EvaluationResult:
    normalized = normalize_stage(station)
    if normalized == "negativa":
        return _parse_negativa_legacy(body)
    if normalized == "spec":
        return _parse_spec_legacy(body)
    if normalized == "verify":
        return _parse_verify_legacy(body)
    if normalized == "triage":
        return _parse_triage_legacy(body)
    if normalized == "impl":
        return _parse_impl_legacy(body)
    raise ValueError(f"Legacy parser not implemented for stage {station!r}")


def parse_evaluation_comment(body: str, station: str, root: Path | None = None) -> EvaluationResult:
    payloads = _extract_json_payloads(body)
    if len(payloads) > 1:
        raise ValueError("Exactly one JSON evaluation block is allowed per comment.")
    if payloads:
        validated = _validate_json_payload(station, payloads[0], root=root)
        agent_id = str(validated.get("agent_id", "")).strip() or _extract_agent_from_header(body)
        return EvaluationResult(
            station=normalize_stage(station),
            agent_id=agent_id,
            verdict=_payload_verdict(station, validated),
            format="json",
            payload=validated,
            raw_comment=body,
        )
    return _parse_legacy_comment(body, station)


def aggregate_results(
    station: str,
    evaluations: list[EvaluationResult],
    evaluators_required: int | None = None,
    kill_on_any_failure: bool | None = None,
    config: dict | None = None,
) -> AggregateResult:
    normalized = normalize_stage(station)
    if not evaluations:
        raise ValueError("At least one evaluation is required.")
    if evaluators_required is not None and len(evaluations) < evaluators_required:
        raise ValueError(
            f"Expected at least {evaluators_required} evaluations for {normalized}, got {len(evaluations)}."
        )

    verdicts = [item.verdict for item in evaluations]
    reasons = [str(item.payload.get("summary", "")).strip() for item in evaluations if item.payload.get("summary")]
    max_iteration = 1  # overwritten inside the verify branch
    a_c_avg: float | None = None  # set inside verify branch when ci_delta present

    if normalized == "negativa":
        kill_wins = True if kill_on_any_failure is None else kill_on_any_failure
        if kill_wins:
            verdict = "KILL" if "KILL" in verdicts else "PROCEED"
        else:
            verdict = "KILL" if all(v == "KILL" for v in verdicts) else "PROCEED"
    elif normalized == "spec":
        verdict = "APPROVED" if all(v == "APPROVED" for v in verdicts) else "REJECTED"
    elif normalized == "verify":
        # Group by iteration. Missing field defaults to 1 (backward compat).
        iter_groups: dict[int, list[EvaluationResult]] = {}
        for ev in evaluations:
            it = int(ev.payload.get("iteration", 1))
            iter_groups.setdefault(it, []).append(ev)
        max_iteration = max(iter_groups)
        latest_evals = iter_groups[max_iteration]

        thresholds = config or {}
        auto_approve = thresholds.get("auto_approve", 0.85)
        refinement = thresholds.get("refinement", 0.6)
        verify_max = int(thresholds.get("verify_max_iterations", 3))

        scores: list[float] = []
        for item in latest_evals:
            if "rubrics" in item.payload:
                scores.append(compute_overall_score(item.payload["rubrics"], VERIFY_WEIGHTS))
            else:
                # Legacy binary checklist: FOUND->0.0, NONE->1.0
                checklist = item.payload.get("checklist", {})
                legacy_rubrics = {
                    k: {"score": 0.0 if v.get("status") == "FOUND" else 1.0, "note": v.get("note", "")}
                    for k, v in checklist.items()
                }
                scores.append(compute_overall_score(legacy_rubrics, VERIFY_LEGACY_WEIGHTS))

        avg = sum(scores) / len(scores)
        # APPROVED checked first — mirrors derive_status to guarantee agreement
        if avg >= auto_approve:
            verdict = "APPROVED"
        elif max_iteration >= verify_max:
            verdict = "ESCALATE"
        elif avg >= refinement:
            verdict = "HUMAN_REVIEW"
        else:
            verdict = "CHANGES_REQUESTED"

        # Extract a(c) from ci_delta if present in latest evaluations
        a_c_values = [
            float(item.payload["ci_delta"]["a_c"])
            for item in latest_evals
            if "ci_delta" in item.payload
        ]
        if a_c_values:
            a_c_avg = sum(a_c_values) / len(a_c_values)
    elif normalized == "triage":
        go_threshold = (config or {}).get("go_threshold", 3)
        no_go_threshold = (config or {}).get("no_go_threshold", 3)
        go_count = sum(1 for v in verdicts if v == "GO")
        nogo_count = sum(1 for v in verdicts if v == "NO_GO")
        if go_count >= go_threshold:
            verdict = "GO"
        elif nogo_count >= no_go_threshold:
            verdict = "NO_GO"
        else:
            verdict = "TIE"
    elif normalized == "impl":
        verdict = verdicts[-1]
    else:
        raise ValueError(f"Unknown stage for aggregation: {normalized!r}")

    return AggregateResult(station=normalized, verdict=verdict, evaluations=evaluations, reasons=reasons, iteration=max_iteration, a_c=a_c_avg)


def aggregate_evaluations(
    station: str,
    evaluations: list[EvaluationResult],
    evaluators_required: int | None = None,
    kill_on_any_failure: bool | None = None,
    config: dict | None = None,
) -> AggregateResult:
    return aggregate_results(
        station,
        evaluations,
        evaluators_required=evaluators_required,
        kill_on_any_failure=kill_on_any_failure,
        config=config,
    )
