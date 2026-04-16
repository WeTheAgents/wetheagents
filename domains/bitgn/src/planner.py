"""Full Planner agent — analyzes tasks and produces execution plans.

Unlike the old router (single LLM call), the Planner is a multi-step agent that:
1. Reads vault outline + AGENTS.MD context
2. Analyzes the task: route, complexity, strategy
3. Selects which executor genes are relevant
4. Writes a planning brief with vault-specific advice
5. Can re-plan after Watchdog escalation
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from src.genome import Genome, load_genome
from src.taxonomy import TaxonomyResult

_PLANNER_MODEL = os.getenv("PLANNER_MODEL", os.getenv("OPENAI_MODEL", "gpt-4o-mini"))

# Mandatory genes that are always included regardless of planner selection
_MANDATORY_GENES = frozenset({
    "identity", "first_check", "task_assessment", "trust_model",
    "security_posture", "injection_defense", "conflict_detection",
    "answer_rules", "self_roast",
})


@dataclass
class PlanResult:
    """Output from the Planner agent."""

    route: str = "vault_ops"
    complexity: str = "complex"
    model_tier: str = "deliberation"  # "action" (gpt-4.1) or "deliberation" (gpt-5.4-mini)
    executor_mode: str = "complete"  # "lean" (hybrid controller) or "complete" (genome)
    genes: list[str] = field(default_factory=list)
    brief: str = ""
    is_replan: bool = False
    replan_kind: str = ""
    planner_trace: list[dict] = field(default_factory=list)
    taxonomy_used: dict = field(default_factory=dict)
    taxonomy_override: bool = False
    taxonomy_override_reason: str = ""

    @property
    def needs_strong_model(self) -> bool:
        """Backwards compat: deliberation = strong model."""
        return self.model_tier == "deliberation"

    @property
    def gene_selection(self) -> list[str]:
        """Genes with mandatory ones always included."""
        return sorted(set(self.genes) | _MANDATORY_GENES)


def _call_planner_model(prompt: str, model: str) -> str:
    """Call the planner model. Auto-detects Anthropic vs OpenAI."""
    if model.startswith("claude"):
        import anthropic
        client = anthropic.Anthropic()
        resp = client.messages.create(
            model=model,
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.content[0].text.strip()
    else:
        import openai
        client = openai.OpenAI()
        resp = client.chat.completions.create(
            model=model,
            max_completion_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.choices[0].message.content.strip()


def _build_planner_prompt(
    genome: Genome,
    task_text: str,
    taxonomy_result: TaxonomyResult | None = None,
    warmup_context: str | None = None,
    executor_trace: str | None = None,
    escalation_reason: str | None = None,
    replan_kind: str | None = None,
    current_plan_summary: str | None = None,
    side_effect_count: int = 0,
) -> str:
    """Build the planner prompt from genome genes + context."""
    parts = []
    for gene in genome.genes.values():
        if gene.content.strip():
            parts.append(gene.content.strip())

    prompt = "\n\n".join(parts)

    # Add vault context
    if warmup_context:
        prompt += f"\n\nVAULT CONTEXT:\n{warmup_context}"

    if taxonomy_result is not None:
        prompt += (
            "\n\nMANDATORY TASK TAXONOMY INPUT:\n"
            f"{json.dumps(taxonomy_result.as_dict(), ensure_ascii=False)}\n"
            "Treat this taxonomy as the default task classification. "
            "You may override it only when vault context, executor trace, or policy structure gives concrete evidence. "
            "If your final route differs from taxonomy.route_candidate, you MUST set taxonomy_override_reason."
        )

    # Add task
    prompt += f"\n\nTASK TO PLAN FOR:\n{task_text}"

    # Add re-plan context if escalated
    if executor_trace and escalation_reason:
        prompt += (
            f"\n\nPREVIOUS ATTEMPT FAILED. Replan kind: {replan_kind or 'unspecified'}."
            f"\nEscalation reason:\n{escalation_reason}"
            f"\nCurrent plan summary:\n{current_plan_summary or '(none)'}"
            f"\nSide effects already executed: {side_effect_count}"
            f"\n\nExecutor's trace from previous attempt:\n{executor_trace}"
        )

    return prompt


def _parse_plan_result(raw: str) -> PlanResult:
    """Parse LLM response into PlanResult. Handles JSON extraction robustly."""
    # Try to extract JSON from response
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Try to find JSON in the response
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                data = json.loads(text[start:end])
            except json.JSONDecodeError:
                return _fallback_result("JSON parse failed")
        else:
            return _fallback_result("No JSON found in response")

    # Validate route
    route = data.get("route", "vault_ops")
    valid_routes = {"vault_ops", "inbox_email", "inbox_chat", "query", "security_reject", "beyond"}
    if route not in valid_routes:
        route = "beyond"  # unknown route → safest fallback

    # Validate complexity — "beyond" route is always complex
    complexity = data.get("complexity", "complex")
    if complexity not in ("simple", "complex"):
        complexity = "complex"
    if route == "beyond":
        complexity = "complex"

    # Validate model tier
    model_tier = data.get("model_tier", "deliberation")
    if model_tier not in ("action", "deliberation"):
        model_tier = "deliberation"
    if route == "beyond":
        model_tier = "deliberation"

    # Validate executor mode
    executor_mode = data.get("executor_mode", "complete")
    if executor_mode not in ("lean", "complete"):
        executor_mode = "complete"

    genes = data.get("genes", [])
    if not isinstance(genes, list):
        genes = []

    return PlanResult(
        route=route,
        complexity=complexity,
        model_tier=model_tier,
        executor_mode=executor_mode,
        genes=genes,
        brief=str(data.get("brief", "")),
        is_replan=bool(data.get("is_replan", False)),
        taxonomy_override_reason=str(data.get("taxonomy_override_reason", "")),
    )


def _fallback_result(reason: str) -> PlanResult:
    """Default fallback when planner fails — conservative full-gene selection."""
    return PlanResult(
        route="beyond",
        complexity="complex",
        model_tier="deliberation",
        genes=[],  # empty = use all genes (no override)
        brief=f"[Planner fallback: {reason}. Using full gene set.]",
    )


def run_planner(
    task_text: str,
    taxonomy_result: TaxonomyResult | None = None,
    warmup_context: str | None = None,
    genome: Genome | None = None,
    model: str | None = None,
    executor_trace: str | None = None,
    escalation_reason: str | None = None,
    replan_kind: str | None = None,
    current_plan_summary: str | None = None,
    side_effect_count: int = 0,
) -> PlanResult:
    """Run the Planner agent.

    Args:
        task_text: The task instruction.
        warmup_context: Vault outline + AGENTS.MD content.
        genome: Planner genome (loaded if None).
        model: LLM model override.
        executor_trace: Previous attempt trace (for re-planning).
        escalation_reason: Why Watchdog escalated (for re-planning).
        replan_kind: checkpoint | watchdog_midstream | action_brake | final_gate | conflict.
        current_plan_summary: Brief summary of the active plan.
        side_effect_count: Number of writes/deletes/moves already executed.

    Returns:
        PlanResult with route, genes, brief, etc.
    """
    if genome is None:
        try:
            genome = load_genome("planner")
        except FileNotFoundError:
            return _fallback_result("planner genome not found")

    model = model or _PLANNER_MODEL

    # NOTE: No fast-path injection check here. The planner is a planner, not a
    # security gate. "delete all completed tasks" is a legitimate owner request.
    # Defense is handled by executor's enrichment layer + defense genes.
    # The planner LLM decides if a task is security_reject based on genome genes.

    # Build prompt and call model
    prompt = _build_planner_prompt(
        genome,
        task_text,
        taxonomy_result,
        warmup_context,
        executor_trace,
        escalation_reason,
        replan_kind,
        current_plan_summary,
        side_effect_count,
    )

    trace_entry = {"step": "plan", "model": model}
    try:
        raw = _call_planner_model(prompt, model)
        trace_entry["raw_output"] = raw[:500]
        result = _parse_plan_result(raw)
        result.planner_trace.append(trace_entry)
    except Exception as e:
        trace_entry["error"] = str(e)
        result = _fallback_result(str(e))
        result.planner_trace.append(trace_entry)

    # Ensure mandatory genes are included
    if result.genes:
        result.genes = result.gene_selection

    if taxonomy_result is not None:
        result.taxonomy_used = taxonomy_result.as_dict()
        if result.route != taxonomy_result.route_candidate:
            result.taxonomy_override = True
            if not result.taxonomy_override_reason:
                result.taxonomy_override_reason = (
                    f"Planner selected route '{result.route}' instead of taxonomy route_candidate "
                    f"'{taxonomy_result.route_candidate}' based on stronger context."
                )
        elif result.taxonomy_override_reason:
            result.taxonomy_override = True

    # Tag re-plan
    if executor_trace:
        result.is_replan = True
        result.replan_kind = replan_kind or "replan"

    return result


def format_executor_trace_for_replan(steps: list) -> str:
    """Format executor trace compactly for re-planning context.

    Args:
        steps: list of StepRecord from the failed executor run.
    """
    lines = []
    for i, step in enumerate(steps):
        args = ", ".join(
            f"{k}={str(v)[:40]!r}"
            for k, v in step.tool_input.items()
            if k != "tool"
        )
        lines.append(f"  {i+1}. {step.tool_name}({args})")
        if step.output:
            preview = step.output[:100].replace("\n", " ")
            lines.append(f"     → {preview}")
    return "\n".join(lines)
