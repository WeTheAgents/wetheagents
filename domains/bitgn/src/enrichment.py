"""Enriched dispatcher — wraps a base dispatcher with contextual metadata.

Adds step budget, trust chain hints, large result warnings, and injection defense
to every tool result before the agent sees it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from src.config import AgentConfig
from src.defense import DefenseMode, sanitize_content
from src.models import ReadTool, ToolAction
from src.tools import Dispatcher

MAX_STEPS = 30


@dataclass
class AgentContext:
    """Mutable context updated by the agent loop each iteration."""

    step: int = 0
    max_steps: int = MAX_STEPS
    trust_chain: set[str] = field(default_factory=set)

    @property
    def remaining(self) -> int:
        return self.max_steps - self.step


def _step_budget_line(ctx: AgentContext) -> str:
    """Graduated urgency based on step budget."""
    n, total = ctx.step, ctx.max_steps
    if n <= 15:
        return f"[Step {n}/{total}]"
    if n <= 22:
        return f"[Step {n}/{total} — plan carefully]"
    return f"[Step {n}/{total} — SUBMIT NOW]"


def _defense_mode_from_str(s: str) -> DefenseMode:
    mapping = {
        "hard": DefenseMode.HARD,
        "soft_block": DefenseMode.SOFT_BLOCK,
        "soft_hint": DefenseMode.SOFT_HINT,
    }
    normalized = s.lower().replace("-", "_")
    if normalized not in mapping:
        raise ValueError(
            f"Unknown defense_mode {s!r}. "
            f"Valid: {', '.join(mapping)}"
        )
    return mapping[normalized]


def enriched_dispatcher(
    base: Dispatcher,
    ctx: AgentContext,
    config: AgentConfig,
) -> Dispatcher:
    """Wrap a base dispatcher with enrichment layers.

    Returns a new Dispatcher callable.  The caller must update
    ``ctx.step`` before each agent iteration.
    """
    mode = _defense_mode_from_str(config.defense_mode)

    def _dispatch(tool: ToolAction) -> str:
        result = base(tool)

        parts: list[str] = []

        # 1. Step budget
        if config.step_budget_in_results:
            parts.append(_step_budget_line(ctx))

        # 2. Defense sanitization on read results
        if isinstance(tool, ReadTool):
            # Parse the JSON result to extract content for sanitization
            try:
                data = json.loads(result)
                content = data.get("content", "")
                if content:
                    # Determine effective mode: trust chain files get soft_hint
                    path = tool.path.lstrip("/").lower()
                    effective_mode = (
                        DefenseMode.SOFT_HINT
                        if path in ctx.trust_chain
                        else mode
                    )
                    sanitized = sanitize_content(content, tool.path, effective_mode)
                    data["content"] = sanitized
                    result = json.dumps(data, indent=2)
            except (json.JSONDecodeError, TypeError):
                pass  # non-JSON result, skip sanitization

            # Trust chain hint
            if config.trust_chain_hints:
                path = tool.path.lstrip("/").lower()
                if path in ctx.trust_chain:
                    parts.append("[Trust chain: referenced by AGENTS.MD]")

        # 3. Large result warning
        if len(result) > 3000:
            parts.append(f"[Large result: {len(result)} chars. Focus on relevant sections.]")

        if parts:
            prefix = " ".join(parts)
            return f"{prefix}\n{result}"
        return result

    return _dispatch
