"""Structured task taxonomy stage for genome-mode planning."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field

from src.genome import Genome, load_genome

_TAXONOMY_MODEL = os.getenv("TAXONOMY_MODEL", os.getenv("PLANNER_MODEL", os.getenv("OPENAI_MODEL", "gpt-4o-mini")))

VALID_ROUTE_CANDIDATES = frozenset({"vault_ops", "inbox_email", "inbox_chat", "query", "security_reject", "beyond"})
VALID_TASK_FAMILIES = frozenset({"direct_command", "process_task", "query", "outbound_action", "refusal"})
VALID_AUTH_MODES = frozenset({"none", "sender_verify", "channel_otp", "injection_sensitive"})
VALID_MATCH_POLICIES = frozenset({"exact", "fuzzy_allowed", "role_resolution"})
VALID_SIDE_EFFECT_POLICIES = frozenset({"no_delete", "delete_if_explicit", "delete_if_policy_allows"})
VALID_EXTERNAL_SUPPORT = frozenset({"vault_native", "maybe_proxy", "unsupported_if_no_mechanism"})
VALID_INBOX_MODES = frozenset({"none", "generic_inbox", "email_inbox", "chat_inbox"})
VALID_DELETION_DEFAULTS = frozenset({"forbid", "allow_explicit", "allow_process"})


@dataclass
class TaxonomyResult:
    route_candidate: str = "beyond"
    task_family: str = "process_task"
    auth_mode: str = "none"
    match_policy: str = "exact"
    side_effect_policy: str = "no_delete"
    external_support: str = "maybe_proxy"
    risk_flags: list[str] = field(default_factory=list)
    requires_exact_match: bool = False
    inbox_mode: str = "none"
    deletion_default: str = "forbid"
    reasoning: str = ""
    taxonomy_trace: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self, dict_factory=dict) | {"taxonomy_trace": list(self.taxonomy_trace)}


def _call_taxonomy_model(prompt: str, model: str) -> str:
    if model.startswith("claude"):
        import anthropic

        client = anthropic.Anthropic()
        resp = client.messages.create(
            model=model,
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.content[0].text.strip()

    import openai

    client = openai.OpenAI()
    resp = client.chat.completions.create(
        model=model,
        max_completion_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.choices[0].message.content.strip()


def _build_taxonomy_prompt(
    genome: Genome,
    task_text: str,
    warmup_context: str | None = None,
    prior_taxonomy: TaxonomyResult | None = None,
    replan_context: str | None = None,
) -> str:
    parts = []
    for gene in genome.genes.values():
        if gene.content.strip():
            parts.append(gene.content.strip())

    prompt = "\n\n".join(parts)
    if warmup_context:
        prompt += f"\n\nVAULT CONTEXT:\n{warmup_context}"
    if prior_taxonomy is not None:
        prompt += f"\n\nPRIOR TAXONOMY:\n{json.dumps(prior_taxonomy.as_dict(), ensure_ascii=False)}"
    if replan_context:
        prompt += f"\n\nREPLAN CONTEXT:\n{replan_context}"
    prompt += f"\n\nTASK TO CLASSIFY:\n{task_text}"
    return prompt


def _fallback_taxonomy(reason: str) -> TaxonomyResult:
    return TaxonomyResult(
        route_candidate="beyond",
        task_family="process_task",
        auth_mode="none",
        match_policy="exact",
        side_effect_policy="no_delete",
        external_support="maybe_proxy",
        risk_flags=["taxonomy_fallback"],
        requires_exact_match=False,
        inbox_mode="none",
        deletion_default="forbid",
        reasoning=f"[Taxonomy fallback: {reason}]",
    )


def _validated_str(value, valid: set[str] | frozenset[str], default: str) -> str:
    if isinstance(value, str) and value in valid:
        return value
    return default


def _parse_taxonomy_result(raw: str) -> TaxonomyResult:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                data = json.loads(text[start:end])
            except json.JSONDecodeError:
                return _fallback_taxonomy("JSON parse failed")
        else:
            return _fallback_taxonomy("No JSON found in response")

    risk_flags = data.get("risk_flags", [])
    if not isinstance(risk_flags, list):
        risk_flags = []
    risk_flags = [str(flag) for flag in risk_flags[:12]]

    return TaxonomyResult(
        route_candidate=_validated_str(data.get("route_candidate"), VALID_ROUTE_CANDIDATES, "beyond"),
        task_family=_validated_str(data.get("task_family"), VALID_TASK_FAMILIES, "process_task"),
        auth_mode=_validated_str(data.get("auth_mode"), VALID_AUTH_MODES, "none"),
        match_policy=_validated_str(data.get("match_policy"), VALID_MATCH_POLICIES, "exact"),
        side_effect_policy=_validated_str(data.get("side_effect_policy"), VALID_SIDE_EFFECT_POLICIES, "no_delete"),
        external_support=_validated_str(data.get("external_support"), VALID_EXTERNAL_SUPPORT, "maybe_proxy"),
        risk_flags=risk_flags,
        requires_exact_match=bool(data.get("requires_exact_match", False)),
        inbox_mode=_validated_str(data.get("inbox_mode"), VALID_INBOX_MODES, "none"),
        deletion_default=_validated_str(data.get("deletion_default"), VALID_DELETION_DEFAULTS, "forbid"),
        reasoning=str(data.get("reasoning", "")),
    )


def run_taxonomy(
    task_text: str,
    warmup_context: str | None = None,
    genome: Genome | None = None,
    model: str | None = None,
    prior_taxonomy: TaxonomyResult | None = None,
    replan_context: str | None = None,
) -> TaxonomyResult:
    if genome is None:
        try:
            genome = load_genome("taxonomy")
        except FileNotFoundError:
            return _fallback_taxonomy("taxonomy genome not found")

    model = model or _TAXONOMY_MODEL
    prompt = _build_taxonomy_prompt(
        genome,
        task_text,
        warmup_context=warmup_context,
        prior_taxonomy=prior_taxonomy,
        replan_context=replan_context,
    )
    trace_entry = {"step": "taxonomy", "model": model}
    try:
        raw = _call_taxonomy_model(prompt, model)
        trace_entry["raw_output"] = raw[:500]
        result = _parse_taxonomy_result(raw)
        result.taxonomy_trace.append(trace_entry)
    except Exception as exc:
        trace_entry["error"] = str(exc)
        result = _fallback_taxonomy(str(exc))
        result.taxonomy_trace.append(trace_entry)

    return result


def should_rerun_taxonomy(kind: str, reason: str) -> bool:
    if kind in {"conflict", "action_brake", "final_gate"}:
        return True
    lowered = reason.lower()
    return "route mismatch" in lowered or "route_mismatch" in lowered
