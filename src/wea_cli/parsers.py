"""Parsers for issue/task markdown bodies."""

from __future__ import annotations

from dataclasses import dataclass
import re

_CHECKBOX_RE = re.compile(r"^\s*-\s*\[[ xX]?\]\s*(.+?)\s*$", re.MULTILINE)
_STRUCTURED_CRITERION_RE = re.compile(r"^(MUST NOT|MUST)\s*:\s*(.+)$", re.IGNORECASE)
_MANUAL_PREFIX_RE = re.compile(r"^manual\s*:\s*(.+)$", re.IGNORECASE)
_SECTION_RE = re.compile(r"(?ms)^##+\s*(.+?)\s*$\n+(.*?)(?=^##+\s|\Z)")


@dataclass(frozen=True)
class AcceptanceCriterion:
    requirement: str
    text: str
    is_manual: bool
    raw: str


@dataclass(frozen=True)
class AcceptanceCriteriaCheck:
    source: str
    criteria: tuple[AcceptanceCriterion, ...]
    errors: tuple[str, ...]

    @property
    def machine_criteria(self) -> tuple[AcceptanceCriterion, ...]:
        return tuple(criterion for criterion in self.criteria if not criterion.is_manual)

    @property
    def human_criteria(self) -> tuple[AcceptanceCriterion, ...]:
        return tuple(criterion for criterion in self.criteria if criterion.is_manual)

    @property
    def has_machine_checks(self) -> bool:
        return bool(self.machine_criteria)

    @property
    def is_valid(self) -> bool:
        return not self.errors


def normalize_header(header: str) -> str:
    lowered = header.lower().strip().rstrip(":")
    lowered = re.sub(r"\s*\([^)]*\)\s*", " ", lowered)
    lowered = re.sub(r"\s+", " ", lowered).strip()
    return lowered


def parse_field(body: str, aliases: list[str]) -> str | None:
    normalized_aliases = {normalize_header(alias) for alias in aliases}

    # Pattern 1: ## Header\nvalue  (markdown heading style)
    heading_pattern = re.compile(r"^##+\s*(.+?)\s*$\n+([^\n]+)", re.MULTILINE)
    for match in heading_pattern.finditer(body):
        header = normalize_header(match.group(1))
        if header in normalized_aliases:
            value = match.group(2).strip()
            return value or None

    # Pattern 2: **Header:** value  (bold inline style used in WEA task bodies)
    inline_pattern = re.compile(r"^\*\*(.+?)\*\*[:\s]+(.+?)\s*$", re.MULTILINE)
    for match in inline_pattern.finditer(body):
        header = normalize_header(match.group(1))
        if header in normalized_aliases:
            value = match.group(2).strip()
            return value or None

    return None


def parse_section(body: str, aliases: list[str]) -> str | None:
    normalized_aliases = {normalize_header(alias) for alias in aliases}
    normalized_body = body.replace("\r\n", "\n").replace("\r", "\n")

    for match in _SECTION_RE.finditer(normalized_body):
        header = normalize_header(match.group(1))
        if header in normalized_aliases:
            value = match.group(2).strip()
            if value and value.lower() not in {"_no response_", "none"}:
                return value
            return None

    return None


def _build_criterion(requirement: str, raw_text: str) -> AcceptanceCriterion:
    text = raw_text.strip()
    manual_match = _MANUAL_PREFIX_RE.match(text)
    is_manual = manual_match is not None
    if manual_match:
        text = manual_match.group(1).strip()
    return AcceptanceCriterion(
        requirement=requirement,
        text=text,
        is_manual=is_manual,
        raw=raw_text.strip(),
    )


def inspect_acceptance_criteria(body: str) -> AcceptanceCriteriaCheck:
    if not body or not body.strip():
        return AcceptanceCriteriaCheck(
            source="missing",
            criteria=(),
            errors=("Issue body is empty.",),
        )

    section = parse_section(body, ["Verification Criteria", "Acceptance Criteria"])
    if not section:
        return AcceptanceCriteriaCheck(
            source="missing",
            criteria=(),
            errors=("No acceptance criteria section found.",),
        )

    items = tuple(match.group(1).strip() for match in _CHECKBOX_RE.finditer(section) if match.group(1).strip())
    if not items:
        return AcceptanceCriteriaCheck(
            source="malformed",
            criteria=(),
            errors=("Acceptance criteria must be written as markdown checkboxes.",),
        )

    parsed_items: list[AcceptanceCriterion] = []
    structured_flags: list[bool] = []
    for item in items:
        match = _STRUCTURED_CRITERION_RE.match(item)
        structured_flags.append(match is not None)
        if match:
            requirement = "must_not" if match.group(1).upper() == "MUST NOT" else "must"
            parsed_items.append(_build_criterion(requirement, match.group(2)))
        else:
            parsed_items.append(_build_criterion("legacy", item))

    errors: list[str] = []

    if any(structured_flags):
        if not all(structured_flags):
            errors.append(
                "Structured acceptance criteria must prefix every checkbox with `MUST:` or `MUST NOT:`."
            )
        criteria = tuple(parsed_items)
        requirements = {criterion.requirement for criterion in criteria}
        if "must" not in requirements:
            errors.append("Structured acceptance criteria must include at least one `MUST:` item.")
        if "must_not" not in requirements:
            errors.append("Structured acceptance criteria must include at least one `MUST NOT:` item.")
    else:
        criteria = tuple(parsed_items)

    if criteria and not any(not criterion.is_manual for criterion in criteria):
        errors.append(
            "Acceptance criteria must include at least one non-manual machine-checkable criterion."
        )

    source = "malformed" if errors else ("structured" if any(structured_flags) else "legacy")
    return AcceptanceCriteriaCheck(source=source, criteria=criteria, errors=tuple(errors))


def parse_task_metadata(body: str) -> dict[str, str | None]:
    return {
        "agent_id": parse_field(body, ["Your Agent ID"]),
        "reward_type": parse_field(body, ["Reward Type"]),
        "reward": parse_field(body, ["Reward (WEA)", "Reward"]),
        "deadline": parse_field(body, ["Deadline", "Deadline (optional)"]),
        "skills_needed": parse_field(body, ["Skills Needed", "Skills"]),
    }
