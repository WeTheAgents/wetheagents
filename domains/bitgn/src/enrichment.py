"""Enriched dispatcher — wraps a base dispatcher with contextual metadata.

Adds step budget, trust chain hints, large result warnings, and injection defense
to every tool result before the agent sees it.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field

from src.config import AgentConfig
from src.defense import DefenseMode, sanitize_content
from src.step_validator import StepValidator
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


_LINE_STATUS_RE = re.compile(
    r"\b(blacklist|verified|valid|admin|blocked|banned|trusted|active|inactive|pending)\b",
    re.IGNORECASE,
)


def _auto_count_lines(content: str) -> str | None:
    """Generate line-count stats for large read results.

    Returns a stats string like '[Auto-count: 200 lines, 143 "blacklist", 57 "verified"]'
    or None if the content is small.
    """
    lines = content.splitlines()
    if len(lines) < 50:
        return None

    # Count status-like keywords per line
    counts: Counter[str] = Counter()
    for line in lines:
        found = _LINE_STATUS_RE.findall(line)
        for word in found:
            counts[word.lower()] += 1

    stat = f"[Auto-count: {len(lines)} lines in this chunk"
    if counts:
        top = counts.most_common(5)
        details = ", ".join(f'{c} "{w}"' for w, c in top)
        stat += f"; {details}"
    stat += "]"
    return stat


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
    validator = StepValidator() if config.step_validator else None

    def _dispatch(tool) -> str:
        result = base(tool)

        parts: list[str] = []

        # 0. Loop detection (before everything else — most impactful)
        if validator is not None:
            warning = validator.check(tool)
            if warning:
                parts.append(warning)

        # 1. Step budget
        if config.step_budget_in_results:
            parts.append(_step_budget_line(ctx))

        # 2a. Search-failure hint: nudge agent to try alternatives when contact search fails
        if getattr(tool, "tool", None) == "search":
            search_path = getattr(tool, "path", getattr(tool, "root", ""))
            is_empty = (
                result.strip() in ("", "{}", "[]", '{\n  "snippets": []\n}')
                or ('"snippets": []' in result)
                or (result.strip().endswith("//") and "\n" not in result.strip())  # empty rg output
            )
            if is_empty and "contact" in search_path.lower():
                parts.append(
                    "[No results in contacts. Try: split name into individual words, "
                    "reverse name order, use OR-regex like (Word1|Word2), "
                    "or list() the contacts/ folder and read files.]"
                )

        # 2b. Defense sanitization on read results (works for both mini and PCM ReadTool)
        if getattr(tool, "tool", None) == "read":
            # Parse result — JSON (mini runtime) or shell-formatted (PCM runtime)
            is_json = False
            try:
                data = json.loads(result)
                content = data.get("content", "")
                is_json = True
            except (json.JSONDecodeError, TypeError):
                # Shell-formatted: "cat {path}\n{content}"
                first_nl = result.find("\n")
                content = result[first_nl + 1:] if first_nl >= 0 else result

            file_path = getattr(tool, "path", "")
            if content:
                path = tool.path.lstrip("/").lower()
                effective_mode = (
                    DefenseMode.SOFT_HINT
                    if path in ctx.trust_chain
                    else mode
                )
                sanitized = sanitize_content(
                    content, tool.path, effective_mode,
                    extra_scan_text=file_path,
                )
                if is_json:
                    data["content"] = sanitized
                    result = json.dumps(data, indent=2)
                else:
                    command_line = result[:first_nl] if first_nl >= 0 else ""
                    result = (
                        f"{command_line}\n{sanitized}" if command_line else sanitized
                    )

            # Auto-count: line stats for large read results
            line_stats = _auto_count_lines(content)
            if line_stats:
                parts.append(line_stats)

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
