"""Parse Pipeline v3 evaluation comments."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import re
import sys
from typing import Any

from jsonschema import validate

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from wea_cli.pipeline_support import load_stage_schema, normalize_stage  # noqa: E402
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


def load_station_schema(station: str, root: Path | None = None) -> dict[str, Any]:
    return load_stage_schema(root or ROOT, station)


def _extract_json_payloads(body: str) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for match in JSON_BLOCK_RE.finditer(body):
        payload = json.loads(match.group(1))
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


def _parse_legacy_comment(body: str, station: str) -> EvaluationResult:
    normalized = normalize_stage(station)
    if normalized == "negativa":
        return _parse_negativa_legacy(body)
    if normalized == "spec":
        return _parse_spec_legacy(body)
    if normalized == "verify":
        return _parse_verify_legacy(body)
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

    if normalized == "negativa":
        kill_wins = True if kill_on_any_failure is None else kill_on_any_failure
        if kill_wins:
            verdict = "KILL" if "KILL" in verdicts else "PROCEED"
        else:
            verdict = "KILL" if all(verdict == "KILL" for verdict in verdicts) else "PROCEED"
    elif normalized == "spec":
        verdict = "APPROVED" if all(verdict == "APPROVED" for verdict in verdicts) else "REJECTED"
    elif normalized == "verify":
        verdict = (
            "APPROVED"
            if all(verdict == "APPROVED" for verdict in verdicts)
            else "CHANGES_REQUESTED"
        )
    else:
        verdict = verdicts[-1]

    return AggregateResult(station=normalized, verdict=verdict, evaluations=evaluations, reasons=reasons)


def aggregate_evaluations(
    station: str,
    evaluations: list[EvaluationResult],
    evaluators_required: int | None = None,
    kill_on_any_failure: bool | None = None,
) -> AggregateResult:
    return aggregate_results(
        station,
        evaluations,
        evaluators_required=evaluators_required,
        kill_on_any_failure=kill_on_any_failure,
    )
