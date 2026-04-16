"""Release Sessions — agents reflect on their performance and propose genome mutations.

Three phases:
1. Individual reflection: each agent (planner, executor, watchdog) analyzes its traces
2. Discussion: coordinator resolves conflicts and prioritizes mutations (max 3)
3. Validation: sandbox + regression check (handled by caller in gene_evolve.py)
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=True)

from src.gene_redteam import GeneMutation, attribute_failures
from src.genome import Genome, load_genome
from src.trace import BenchmarkTrace, TaskTrace

REFLECTION_MODEL = os.getenv("REFLECTION_MODEL", os.getenv("DELIBERATION_MODEL", "gpt-5.4-mini"))
COORDINATOR_MODEL = os.getenv("COORDINATOR_MODEL", os.getenv("DELIBERATION_MODEL", "gpt-5.4-mini"))

CLI_BLUE = "\x1B[34m"
CLI_YELLOW = "\x1B[33m"
CLI_CLR = "\x1B[0m"


@dataclass
class Reflection:
    agent: str
    raw_text: str
    proposals: list[GeneMutation] = field(default_factory=list)


@dataclass
class SessionResult:
    approved: list[GeneMutation] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)
    discussion_log: str = ""
    reflections: list[Reflection] = field(default_factory=list)


def _call_model(prompt: str, model: str) -> str:
    if model.startswith("claude"):
        import anthropic
        client = anthropic.Anthropic()
        resp = client.messages.create(
            model=model, max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.content[0].text
    else:
        import openai
        client = openai.OpenAI()
        resp = client.chat.completions.create(
            model=model, max_completion_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.choices[0].message.content


def _format_traces_for_reflection(
    traces: list[TaskTrace],
    max_failed: int = 10,
    max_passing: int = 3,
) -> str:
    """Format traces for agent reflection — failed tasks in detail, passing as summary."""
    failed = [t for t in traces if t.score < 1.0]
    passed = [t for t in traces if t.score >= 1.0]

    parts = []
    parts.append(f"## Failed Tasks ({len(failed)} total, showing up to {max_failed})")
    for t in failed[:max_failed]:
        parts.append(f"\n### {t.task_id} — score {t.score:.2f}")
        parts.append(f"Instruction: {t.instruction}")
        if t.score_detail:
            parts.append("Score detail: " + "; ".join(t.score_detail))
        if t.genes_used:
            parts.append(f"Genes used: {', '.join(t.genes_used)}")
        parts.append(f"Steps: {t.total_steps}")
        for i, step in enumerate(t.steps[-8:]):
            args = ", ".join(f"{k}={str(v)[:40]!r}" for k, v in step.tool_input.items() if k != "tool")
            out = step.output[:120].replace("\n", " ")
            parts.append(f"  {i+1}. {step.tool_name}({args}) → {out}")

    parts.append(f"\n## Passing Tasks ({len(passed)} total, summary only)")
    for t in passed[:max_passing]:
        parts.append(f"  {t.task_id}: {t.total_steps} steps, score {t.score:.2f}")
    if len(passed) > max_passing:
        parts.append(f"  ... and {len(passed) - max_passing} more passing tasks")

    return "\n".join(parts)


def _format_genome_for_reflection(genome: Genome) -> str:
    """Format genome genes as readable list."""
    parts = [f"# {genome.name} genome (gen {genome.generation}, {len(genome.genes)} genes)"]
    for name, gene in genome.genes.items():
        preview = gene.content[:150].replace("\n", " ").strip()
        meta = []
        if gene.routes:
            meta.append(f"routes={gene.routes}")
        if gene.slot:
            meta.append(f"slot={gene.slot}")
        meta_str = f" ({', '.join(meta)})" if meta else ""
        parts.append(f"\n## {name}{meta_str}")
        parts.append(preview + ("..." if len(gene.content) > 150 else ""))
    return "\n".join(parts)


def _format_mutation_history(history: list[dict], agent: str) -> str:
    """Format relevant mutation history for an agent."""
    relevant = [h for h in history if h.get("agent", "executor") == agent][-10:]
    if not relevant:
        return "No previous mutations."
    lines = []
    for h in relevant:
        status = "ACCEPTED" if h.get("accepted") else "REJECTED"
        lines.append(f"  [{status}] gen {h.get('gen', '?')}: {h.get('gene', '?')} — "
                      f"{h.get('desc', '?')} (delta {h.get('delta', 0):+.2%})")
    return "\n".join(lines)


# --- Phase 1: Individual Reflection ---

_REFLECTION_PROMPT = """\
You are the {agent_name} agent in a multi-agent vault system. You just ran a benchmark. \
Now reflect honestly on your performance.

## Your Genome
{genome_text}

## Benchmark Results
{traces_text}

## Gene Attribution Hints
These genes are suspected of causing failures (automated analysis):
{attribution_hints}

## Your Mutation History
{history_text}

## Your Task
For each FAILED task, write a reflection:
1. What happened? (your perspective — what did you see, what did you do?)
2. What SHOULD have happened? (the correct behavior)
3. Root cause: which of YOUR genes is responsible? Be specific — name the gene.
4. Proposal: what should change in that gene's content? Write the actual new text.

Also reflect on PASSING tasks — is there anything fragile that might break?

SEVERITY TIERS (for each proposal):
- memory: a new observation or lesson learned
- example: a specific pattern that should be followed
- instruction: a new rule (only if you see this pattern in 3+ failed tasks)

Respond with JSON:
{{
  "agent": "{agent_id}",
  "reflections": [
    {{
      "task_id": "...",
      "score": 0.0,
      "what_happened": "...",
      "what_should_have_happened": "...",
      "root_cause": "which gene and why",
      "proposal": {{
        "gene": "gene_name",
        "severity": "memory|example|instruction",
        "change_description": "what to change and why",
        "new_content": "the complete new gene content"
      }}
    }}
  ],
  "meta_reflection": "overall patterns you notice across all tasks"
}}
"""

_AGENT_DESCRIPTIONS = {
    "planner": {
        "name": "Planner",
        "role": "You classify tasks (route, complexity) and select which genes the Executor gets. "
                "You also write a strategic brief. Think about: Did I route correctly? "
                "Did I select the right genes? Was my brief helpful or misleading?",
    },
    "executor": {
        "name": "Executor",
        "role": "You execute vault tasks using tools. You receive a curated prompt assembled from genes "
                "the Planner selected, plus a strategic brief. Think about: Did I follow instructions? "
                "Was I missing information that should have been in my genes? Did I over/under-react?",
    },
    "watchdog": {
        "name": "Watchdog",
        "role": "You monitor the Executor in real-time and check its final answer. "
                "Think about: Did I catch real problems? Did I false-positive on valid behavior? "
                "Did I miss violations I should have caught? Should I have escalated to Planner?",
    },
}


def _run_reflection(
    agent_id: str,
    genome: Genome,
    traces: BenchmarkTrace,
    attribution: dict[str, list[str]],
    mutation_history: list[dict],
    model: str,
) -> Reflection:
    """Run individual reflection for one agent."""
    desc = _AGENT_DESCRIPTIONS[agent_id]

    # Build attribution hints for this agent
    agent_genes = set(genome.genes.keys())
    hints = {g: tasks for g, tasks in attribution.items() if g in agent_genes}
    hints_text = "\n".join(f"  {g}: {', '.join(t)}" for g, t in hints.items()) if hints else "None"

    prompt = _REFLECTION_PROMPT.format(
        agent_name=f"{desc['name']} — {desc['role']}",
        agent_id=agent_id,
        genome_text=_format_genome_for_reflection(genome),
        traces_text=_format_traces_for_reflection(traces.traces),
        attribution_hints=hints_text,
        history_text=_format_mutation_history(mutation_history, agent_id),
    )

    raw = _call_model(prompt, model)

    # Parse proposals from JSON
    proposals = []
    try:
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            data = json.loads(text[start:end])
            for r in data.get("reflections", []):
                prop = r.get("proposal")
                if prop and prop.get("gene") and prop.get("new_content"):
                    proposals.append(GeneMutation(
                        gene_name=prop["gene"],
                        agent=agent_id,
                        old_content="",  # filled by caller
                        new_content=prop["new_content"],
                        description=prop.get("change_description", "no description"),
                        target_failures=[r.get("task_id", "unknown")],
                    ))
    except (json.JSONDecodeError, KeyError):
        pass  # raw text still captured in Reflection

    return Reflection(agent=agent_id, raw_text=raw, proposals=proposals)


# --- Phase 2: Coordinator Discussion ---

_COORDINATOR_PROMPT = """\
You are the coordinator for a release session. Three agents just reflected on their performance. \
Your job: resolve conflicts, prioritize mutations, and produce a final approved list.

## Planner Reflection
{planner_reflection}

## Executor Reflection
{executor_reflection}

## Watchdog Reflection
{watchdog_reflection}

## Rules
1. Maximum 3 approved mutations per session — prioritize by expected impact.
2. If two agents propose conflicting changes (e.g., Executor wants relaxed security, \
Watchdog wants stricter checks), explain the conflict and choose the safer option.
3. If multiple agents agree on the same problem, that's strong signal — prioritize it.
4. severity=instruction requires 3+ tasks showing the same pattern. Downgrade to example/memory if evidence is weak.
5. Each approved mutation must include the COMPLETE new gene content — not a diff.
6. Reject mutations that are too vague, duplicate existing content, or self-serving.

Respond with JSON:
{{
  "approved": [
    {{
      "agent": "planner|executor|watchdog",
      "gene": "gene_name",
      "new_content": "the complete new gene content",
      "rationale": "why this was approved",
      "target_tasks": ["task_id_1", "task_id_2"]
    }}
  ],
  "rejected": [
    {{
      "agent": "...",
      "gene": "...",
      "reason": "why rejected"
    }}
  ],
  "discussion": "1-3 paragraph narrative of the discussion and key decisions"
}}
"""


def _run_coordinator(
    reflections: list[Reflection],
    model: str,
) -> SessionResult:
    """Coordinate discussion between agent reflections."""
    refl_by_agent = {r.agent: r.raw_text for r in reflections}

    prompt = _COORDINATOR_PROMPT.format(
        planner_reflection=refl_by_agent.get("planner", "(no reflection)"),
        executor_reflection=refl_by_agent.get("executor", "(no reflection)"),
        watchdog_reflection=refl_by_agent.get("watchdog", "(no reflection)"),
    )

    raw = _call_model(prompt, model)

    # Parse coordinator output
    result = SessionResult(reflections=reflections, discussion_log=raw)

    try:
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            data = json.loads(text[start:end])

            for a in data.get("approved", []):
                if a.get("gene") and a.get("new_content"):
                    result.approved.append(GeneMutation(
                        gene_name=a["gene"],
                        agent=a.get("agent", "executor"),
                        old_content="",
                        new_content=a["new_content"],
                        description=a.get("rationale", "coordinator approved"),
                        target_failures=a.get("target_tasks", []),
                    ))

            for r in data.get("rejected", []):
                result.rejected.append(r)

            if "discussion" in data:
                result.discussion_log = data["discussion"]

    except (json.JSONDecodeError, KeyError):
        pass

    return result


# --- Main Entry Point ---

def run_release_session(
    traces: BenchmarkTrace,
    executor_genome: Genome | None = None,
    planner_genome: Genome | None = None,
    watchdog_genome: Genome | None = None,
    mutation_history: list[dict] | None = None,
    reflection_model: str | None = None,
    coordinator_model: str | None = None,
) -> SessionResult:
    """Run a full release session: reflection → discussion → approved mutations.

    Args:
        traces: Benchmark trace from the most recent run.
        *_genome: Genomes for each agent (loaded if None).
        mutation_history: Previous mutation history for context.
        reflection_model: Model for individual reflections.
        coordinator_model: Model for coordinator discussion.

    Returns:
        SessionResult with approved mutations, rejections, and discussion log.
    """
    reflection_model = reflection_model or REFLECTION_MODEL
    coordinator_model = coordinator_model or COORDINATOR_MODEL
    mutation_history = mutation_history or []

    # Load genomes if not provided
    if executor_genome is None:
        executor_genome = load_genome("executor")
    if planner_genome is None:
        planner_genome = load_genome("planner")
    if watchdog_genome is None:
        watchdog_genome = load_genome("watchdog")

    # Get failure attribution hints
    failed = [t for t in traces.traces if t.score < 1.0]
    attribution = attribute_failures(executor_genome, failed) if failed else {}

    print(f"\n{CLI_YELLOW}=== Release Session ==={CLI_CLR}")
    print(f"Failed tasks: {len(failed)} / {len(traces.traces)}")
    print(f"Reflection model: {reflection_model}")
    print(f"Coordinator model: {coordinator_model}")

    # Phase 1: Individual reflections
    print(f"\n{CLI_BLUE}Phase 1: Individual Reflections{CLI_CLR}")
    reflections = []
    for agent_id, genome in [
        ("planner", planner_genome),
        ("executor", executor_genome),
        ("watchdog", watchdog_genome),
    ]:
        print(f"  {agent_id}...", end=" ", flush=True)
        refl = _run_reflection(
            agent_id, genome, traces, attribution, mutation_history, reflection_model,
        )
        reflections.append(refl)
        print(f"{len(refl.proposals)} proposals")

    total_proposals = sum(len(r.proposals) for r in reflections)
    print(f"  Total proposals: {total_proposals}")

    if total_proposals == 0:
        print(f"  {CLI_YELLOW}No proposals — agents found nothing to change{CLI_CLR}")
        return SessionResult(reflections=reflections)

    # Phase 2: Coordinator discussion
    print(f"\n{CLI_BLUE}Phase 2: Coordinator Discussion{CLI_CLR}")
    result = _run_coordinator(reflections, coordinator_model)
    result.reflections = reflections

    print(f"  Approved: {len(result.approved)}")
    for m in result.approved:
        print(f"    {m.agent}/{m.gene_name}: {m.description[:60]}")
    print(f"  Rejected: {len(result.rejected)}")
    for r in result.rejected:
        print(f"    {r.get('agent', '?')}/{r.get('gene', '?')}: {r.get('reason', '?')[:60]}")

    # Fill old_content for approved mutations
    genome_map = {
        "planner": planner_genome,
        "executor": executor_genome,
        "watchdog": watchdog_genome,
    }
    for m in result.approved:
        genome = genome_map.get(m.agent)
        if genome and m.gene_name in genome.genes:
            m.old_content = genome.genes[m.gene_name].content

    return result
