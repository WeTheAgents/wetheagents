"""Real-time watchdog — injects corrective guidance into the agent loop.

Monitors recent tool call history every N steps and injects a corrective
user message when the agent appears stuck, looping, or exploring unproductively.

Works independently of the enriched_dispatcher and step_validator.
Supports both OpenAI and Anthropic models — auto-detected by model name prefix.
Set WATCHDOG_MODEL env var to switch (e.g. "claude-haiku-4-5-20251001").
"""

from __future__ import annotations

import os

from src.trace import StepRecord

_WATCHDOG_MODEL = os.getenv("WATCHDOG_MODEL", os.getenv("OPENAI_MODEL", "gpt-4o-mini"))

_PROMPT = """\
You are monitoring an AI agent solving a task in a document vault.
Your job: detect if the agent is stuck, looping, or exploring unproductively.

TASK: {task_text}

RECENT ACTIONS (last {n} steps):
{step_summary}

Analyze only these recent steps. Is the agent making progress toward the answer?

Respond with exactly one of:
- "OK" — agent is clearly on the right track
- "UNCERTAIN: [brief reason]" — agent may be going wrong, watch closely \
(use when you see early signs of trouble but aren't sure yet)
- A short correction directive (1-3 sentences) — agent is clearly stuck, \
re-reading the same files, or going in the wrong direction. \
Be specific: tell the agent what to do next.

Do not invent information. Base your assessment solely on the action list above.\
"""

_PROMPT_FINAL = """\
You are a pre-submission gate for an AI agent. Your ONLY job is to catch three \
specific failure modes — nothing else. Default stance: OK. Only reject if you \
see clear, unambiguous evidence of one of the three issues below.

TASK: {task_text}

ALL STEPS TAKEN (with key file contents):
{step_summary}

PROPOSED ANSWER:
  code: {code}
  answer: {answer}
  refs: {refs}

Check ONLY these three things:

1. HOLD/FREEZE VIOLATION: did the agent read a file containing HOLD, FREEZE, \
PENDING APPROVAL, LEGAL REVIEW, or "do not distribute" — AND then write a file? \
If yes → reject. Tell the agent: delete the written file, resubmit with code="blocked".

2. FILENAME ERROR: did the agent write a file? If yes, check the filename against \
the policy template. Flag only if: (a) the policy shows lowercase-hyphenated format \
but the agent used spaces or uppercase, OR (b) the date in the filename is clearly \
today's date when vault data shows a different date (e.g. "Week of March 17").

3. MISSED ITEMS: did the task require acting on ALL items in a set (e.g. "move all \
ready files")? If yes, count items the agent read vs acted on. Flag only if the \
count is clearly off by one or more.

DO NOT flag: math details, calculation transparency, truncated reads, \
derived vs stated figures, or any other concerns not in the three checks above. \
If the answer is internally consistent and none of the three issues apply → OK.

If all three checks pass → respond with exactly: OK
If one check fails → 1-2 sentences naming the exact problem and fix.\
"""


class Watchdog:
    """Real-time watchdog for the main agent loop.

    Mid-stream: fires every ``check_every`` steps (starting from ``min_step``),
    injects a corrective message when the agent appears lost or looping.
    Switches to double-frequency "doubt mode" after an UNCERTAIN signal.

    Pre-final gate: fires once before report_completion is accepted,
    checking for constraint violations, naming errors, and missed items.

    Stateless across tasks — safe to reuse for a full benchmark run.
    Always calls the watchdog model independently of the main agent's provider.
    """

    def __init__(
        self,
        *,
        model: str = _WATCHDOG_MODEL,
        gate_model: str | None = None,
        check_every: int = 5,
        min_step: int = 4,
        lookback: int = 10,
    ) -> None:
        self.model = model
        self.gate_model = gate_model or model  # fallback to mid-stream model
        self.check_every = check_every
        self.min_step = min_step
        self.lookback = lookback
        self._doubt_mode = False
        # Lazy-init clients keyed by model name — each model gets its own client
        self._openai_clients: dict[str, object] = {}
        self._anthropic_client = None

    def _call_model(self, prompt: str, model: str) -> str:
        """Call a model by name, auto-detecting provider (claude-* → Anthropic, else OpenAI)."""
        if model.startswith("claude"):
            if self._anthropic_client is None:
                import anthropic
                self._anthropic_client = anthropic.Anthropic(
                    api_key=os.getenv("ANTHROPIC_API_KEY")
                )
            msg = self._anthropic_client.messages.create(
                model=model,
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}],
            )
            return (msg.content[0].text or "").strip()
        else:
            if model not in self._openai_clients:
                from openai import OpenAI
                self._openai_clients[model] = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
            client = self._openai_clients[model]
            resp = client.chat.completions.create(
                model=model,
                max_completion_tokens=500,
                messages=[{"role": "user", "content": prompt}],
            )
            return (resp.choices[0].message.content or "").strip()

    def should_check(self, executed_steps: int) -> bool:
        """True if watchdog should fire at this point in execution.

        In doubt mode (after an UNCERTAIN signal) the interval halves,
        so the watchdog watches more closely until the agent gets back on track.

        Args:
            executed_steps: Number of tool calls recorded in trace.steps.
        """
        if executed_steps < self.min_step:
            return False
        effective_interval = max(2, self.check_every // 2) if self._doubt_mode else self.check_every
        return (executed_steps - self.min_step) % effective_interval == 0

    def check(self, task_text: str, steps: list[StepRecord]) -> str | None:
        """Analyze recent steps. Returns correction string, or None if OK.

        Sets doubt mode when response is UNCERTAIN (increases check frequency
        without injecting a message). Clears doubt mode on OK.

        Args:
            task_text: The task instruction for context.
            steps: All recorded StepRecords so far (last ``lookback`` are used).

        Returns:
            A 1-3 sentence correction directive, or None if agent is on track.
            Returns None silently on any API error (fail-open: never crash a run).
        """
        recent = steps[-self.lookback:] if len(steps) > self.lookback else steps
        summary = self._format_steps(recent)

        prompt = _PROMPT.format(
            task_text=task_text[:400],
            n=len(recent),
            step_summary=summary,
        )

        try:
            text = self._call_model(prompt, self.model)
        except Exception as e:
            print(f"  [WATCHDOG skipped: {type(e).__name__}: {e}]")
            return None

        if text.upper().startswith("OK"):
            self._doubt_mode = False
            return None
        if text.upper().startswith("UNCERTAIN"):
            self._doubt_mode = True
            return None  # monitor more closely, but don't inject yet
        self._doubt_mode = False
        return text

    def check_final(
        self,
        task_text: str,
        steps: list[StepRecord],
        completion_args: dict,
    ) -> str | None:
        """Pre-submission gate. Fires once before report_completion is accepted.

        Reviews the full step trace and the proposed answer for constraint
        violations, naming errors, missed items, and wrong dates.

        Args:
            task_text: The task instruction.
            steps: All recorded StepRecords (full trace, not just lookback).
            completion_args: The raw tool_input dict from report_completion.

        Returns:
            A correction string describing the problem, or None if answer looks
            correct. Returns None silently on any API error (fail-open).
        """
        summary = self._format_steps_verbose(steps)
        answer = (completion_args.get("answer") or "")[:500]
        refs = completion_args.get("refs") or []
        code = completion_args.get("code") or ""

        prompt = _PROMPT_FINAL.format(
            task_text=task_text[:400],
            step_summary=summary,
            code=code,
            answer=answer,
            refs=", ".join(refs) if refs else "(none)",
        )

        try:
            text = self._call_model(prompt, self.gate_model)
        except Exception as e:
            print(f"  [GATE skipped: {type(e).__name__}: {e}]")
            return None

        if text.upper().startswith("OK"):
            return None
        return text

    def _format_steps(self, steps: list[StepRecord]) -> str:
        """Compact representation: tool_name(key=val, ...) per step."""
        lines = []
        for s in steps:
            args_str = ", ".join(
                f"{k}={str(v)[:50]!r}"
                for k, v in s.tool_input.items()
                if k != "tool"
            )
            lines.append(f"  {s.tool_name}({args_str})")
        return "\n".join(lines)

    def _format_steps_verbose(self, steps: list[StepRecord]) -> str:
        """Verbose: includes truncated output for read/search/write steps.

        Used by check_final so the reviewer can see file contents and
        detect date mismatches, legal holds, and naming errors.
        """
        lines = []
        for s in steps:
            args_str = ", ".join(
                f"{k}={str(v)[:60]!r}"
                for k, v in s.tool_input.items()
                if k != "tool" and k != "content"  # skip large write content
            )
            line = f"  {s.tool_name}({args_str})"
            # Append truncated output for informational steps
            if s.output and s.tool_name in ("read", "search", "write", "delete"):
                output_preview = s.output[:300].replace("\n", " ")
                line += f"\n    → {output_preview}"
            lines.append(line)
        return "\n".join(lines)
