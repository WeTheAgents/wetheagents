"""Gene-level RedTeam — attributes failures to specific genes and proposes surgical mutations.

Unlike the legacy RedTeam (mutates entire prompt blob), GeneRedTeam:
1. Attributes each failure to the gene(s) most likely responsible
2. Proposes mutations scoped to ONE gene at a time (~5-20 lines)
3. Tracks per-gene mutation history
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from src.genome import Gene, Genome
from src.trace import TaskTrace

REDTEAM_MODEL = os.getenv("REDTEAM_MODEL", "claude-haiku-4-5-20251001")

# Failure mode → candidate genes mapping
_FAILURE_GENE_MAP: dict[str, list[str]] = {
    # Keywords in score_detail or failure patterns → likely responsible genes
    "injection": ["security_posture", "injection_defense", "trust_model"],
    "obeyed": ["security_posture", "injection_defense", "trust_model"],
    "blocked": ["security_posture", "overlay_inbox_chat", "inbox_processing"],
    "over-block": ["security_posture", "overlay_inbox_chat", "inbox_processing"],
    "denied": ["security_posture", "overlay_inbox_chat", "inbox_processing"],
    "format": ["answer_rules"],
    "refs": ["answer_rules"],
    "missing": ["answer_rules", "side_effect_discipline"],
    "not found": ["contact_lookup", "vault_discovery"],
    "contact": ["contact_lookup"],
    "sender": ["inbox_processing", "overlay_inbox_email"],
    "domain": ["inbox_processing", "overlay_inbox_email"],
    "otp": ["overlay_inbox_chat", "inbox_processing"],
    "trust": ["overlay_inbox_chat", "inbox_processing", "trust_model"],
    "handle": ["overlay_inbox_chat", "inbox_processing"],
    "batch": ["side_effect_discipline", "overlay_vault_ops"],
    "incomplete": ["side_effect_discipline", "overlay_vault_ops"],
    "date": ["overlay_vault_ops", "side_effect_discipline"],
    "arithmetic": ["overlay_vault_ops"],
    "count": ["overlay_query", "task_assessment"],
    "write": ["side_effect_discipline"],
    "delete": ["side_effect_discipline"],
    "hold": ["side_effect_discipline"],
    "freeze": ["side_effect_discipline"],
    "filename": ["side_effect_discipline", "policy_compliance"],
    "exfiltration": ["security_posture"],
    "credential": ["security_posture"],
    "unsupported": ["capability_boundaries"],
    "truncat": ["first_check", "clarification"],
    "clarification": ["clarification", "first_check"],
    "ambiguous": ["clarification"],
}


@dataclass
class GeneMutation:
    """A proposed mutation to a single gene."""

    gene_name: str
    agent: str  # "executor" / "planner" / "watchdog"
    old_content: str
    new_content: str
    description: str
    target_failures: list[str]  # task_ids this aims to fix


def _call_redteam_model(prompt: str, model: str = REDTEAM_MODEL) -> str:
    """Call the redteam model."""
    if model.startswith("claude"):
        import anthropic
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        resp = client.messages.create(
            model=model, max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.content[0].text
    else:
        import openai
        client = openai.OpenAI()
        resp = client.chat.completions.create(
            model=model, max_completion_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.choices[0].message.content


def attribute_failures(
    genome: Genome,
    failed_traces: list[TaskTrace],
) -> dict[str, list[str]]:
    """Map each failed task to the gene(s) most likely responsible.

    Returns {gene_name: [task_ids]} — genes sorted by attribution count.
    """
    gene_failures: dict[str, list[str]] = {}

    for trace in failed_traces:
        attributed_genes = set()

        # 1. Route-based attribution: the route overlay is always a candidate
        for gene_name in genome.genes:
            if gene_name.startswith("overlay_"):
                # Check if this overlay was used (from genes_used in trace)
                if trace.genes_used and gene_name in trace.genes_used:
                    attributed_genes.add(gene_name)

        # 2. Score detail keyword matching
        detail_text = " ".join(trace.score_detail).lower()
        instruction_text = trace.instruction.lower()
        combined = f"{detail_text} {instruction_text}"

        for keyword, genes in _FAILURE_GENE_MAP.items():
            if keyword in combined:
                for g in genes:
                    if g in genome.genes:
                        attributed_genes.add(g)

        # 3. Step trace analysis — what did the agent do wrong?
        for step in trace.steps:
            output_lower = step.output.lower()
            if "injection" in output_lower or "blocked" in output_lower:
                attributed_genes.update(["security_posture", "injection_defense"])
            if step.tool_name in ("write", "delete") and trace.score < 1.0:
                attributed_genes.add("side_effect_discipline")

        # 4. Fallback: if no specific attribution, blame the route overlay
        if not attributed_genes:
            for gene_name in genome.genes:
                if gene_name.startswith("overlay_") and trace.genes_used and gene_name in trace.genes_used:
                    attributed_genes.add(gene_name)
            if not attributed_genes:
                attributed_genes.add("task_assessment")  # ultimate fallback

        # Record attributions
        for gene in attributed_genes:
            gene_failures.setdefault(gene, []).append(trace.task_id)

    return gene_failures


def propose_mutation(
    genome: Genome,
    gene_name: str,
    relevant_traces: list[TaskTrace],
    mutation_history: list[dict],
    model: str = REDTEAM_MODEL,
) -> GeneMutation:
    """Propose a mutation for a single gene based on failure analysis.

    The LLM sees only: the gene content, the failure traces, and the
    mutation history for this gene. Much more surgical than full-prompt mutation.
    """
    gene = genome.genes[gene_name]

    # Format failure traces
    traces_text = ""
    for t in relevant_traces[:5]:  # limit to 5 most relevant
        traces_text += f"\n### Task: {t.task_id}\n"
        traces_text += f"Instruction: {t.instruction}\n"
        traces_text += f"Score: {t.score:.2f}\n"
        if t.score_detail:
            traces_text += "Score detail:\n"
            for d in t.score_detail:
                traces_text += f"  - {d}\n"
        traces_text += f"Steps: {t.total_steps}\n"
        for i, step in enumerate(t.steps[-10:]):  # last 10 steps
            args = ", ".join(
                f"{k}={str(v)[:50]!r}" for k, v in step.tool_input.items() if k != "tool"
            )
            output_preview = step.output[:150] + "..." if len(step.output) > 150 else step.output
            traces_text += f"  {i+1}. {step.tool_name}({args})\n     → {output_preview}\n"

    # Format relevant mutation history
    gene_history = [h for h in mutation_history if h.get("gene") == gene_name]
    history_text = "No previous mutations for this gene." if not gene_history else ""
    for h in gene_history[-5:]:
        status = "ACCEPTED" if h.get("accepted") else "REJECTED"
        history_text += f"  [{status}] {h.get('description', '?')} (score delta: {h.get('delta', 0):+.2%})\n"

    prompt = f"""\
You are a prompt engineer improving ONE specific section of an AI agent's system prompt.

## GENE TO IMPROVE: "{gene_name}"
```
{gene.content}
```

## FAILED TASKS (the gene above is likely responsible for these failures)
{traces_text}

## MUTATION HISTORY FOR THIS GENE
{history_text}

## RULES
- Output a COMPLETE replacement for the gene content above (not a diff)
- Make ONE focused change — fix what's broken, preserve what works
- Keep the gene concise — every word costs context window space
- Don't repeat strategies that were already rejected in the history
- The improved gene should fix the failed tasks WITHOUT breaking other tasks

## OUTPUT FORMAT
First line: DESCRIPTION: <one-line description of what you changed and why>
Then a separator: ---
Then the complete new gene content (everything between --- and end of response).
"""

    raw = _call_redteam_model(prompt, model)

    # Parse response
    description = "unknown mutation"
    new_content = raw

    lines = raw.split("\n")
    separator_idx = None
    for i, line in enumerate(lines):
        if line.strip().startswith("DESCRIPTION:"):
            description = line.split(":", 1)[1].strip()
        if line.strip() == "---":
            separator_idx = i
            break

    if separator_idx is not None:
        new_content = "\n".join(lines[separator_idx + 1:]).strip()

    return GeneMutation(
        gene_name=gene_name,
        agent="executor",  # default; planner/watchdog handled separately
        old_content=gene.content,
        new_content=new_content,
        description=description,
        target_failures=[t.task_id for t in relevant_traces],
    )


def select_gene_to_mutate(
    attribution: dict[str, list[str]],
    mutation_history: list[dict],
) -> str | None:
    """Select the best gene to mutate next.

    Strategy: pick the gene with the most failure attributions that
    hasn't been recently mutated (or was rejected).
    """
    if not attribution:
        return None

    # Count recent mutations per gene (last 10 generations)
    recent_mutations: dict[str, int] = {}
    for h in mutation_history[-10:]:
        gene = h.get("gene", "")
        recent_mutations[gene] = recent_mutations.get(gene, 0) + 1

    # Score: attribution_count - recent_mutation_count
    scored = []
    for gene, task_ids in attribution.items():
        score = len(task_ids) - recent_mutations.get(gene, 0) * 2
        scored.append((score, gene))

    scored.sort(reverse=True)
    return scored[0][1] if scored else None
