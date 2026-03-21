"""Anthropic (Claude) provider for BitGN agent using tool_use."""

import os

from anthropic import Anthropic

from src.models import (
    DeleteTool,
    ListTool,
    NextStep,
    OutlineTool,
    ReadTool,
    ReportCompletion,
    SearchTool,
    WriteTool,
)
from src.providers.base import LLMProvider

MODEL = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")

# Tool definitions for Claude's native tool_use
TOOLS = [
    {
        "name": "outline",
        "description": "Get a tree outline of a folder in the vault.",
        "input_schema": OutlineTool.model_json_schema(),
    },
    {
        "name": "read",
        "description": "Read the contents of a file.",
        "input_schema": ReadTool.model_json_schema(),
    },
    {
        "name": "list",
        "description": "List files in a directory.",
        "input_schema": ListTool.model_json_schema(),
    },
    {
        "name": "search",
        "description": "Search for a pattern across files. Returns matching snippets.",
        "input_schema": SearchTool.model_json_schema(),
    },
    {
        "name": "write",
        "description": "Write content to a file (create or overwrite).",
        "input_schema": WriteTool.model_json_schema(),
    },
    {
        "name": "delete",
        "description": "Delete a file.",
        "input_schema": DeleteTool.model_json_schema(),
    },
    {
        "name": "report_completion",
        "description": "Report task completion with the final answer. Use when you have gathered enough information to answer the task.",
        "input_schema": ReportCompletion.model_json_schema(),
    },
]

# Map tool name -> Pydantic model class
TOOL_MODELS: dict[str, type] = {
    "outline": OutlineTool,
    "read": ReadTool,
    "list": ListTool,
    "search": SearchTool,
    "write": WriteTool,
    "delete": DeleteTool,
    "report_completion": ReportCompletion,
}


class AnthropicProvider(LLMProvider):
    def __init__(self):
        self.client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    def provider_name(self) -> str:
        return f"anthropic/{MODEL}"

    def get_next_step(self, messages: list[dict], system_prompt: str) -> NextStep:
        resp = self.client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=system_prompt,
            tools=TOOLS,
            messages=messages,
        )

        # Extract thinking (text) and tool use from response
        text_parts = []
        tool_call = None
        for block in resp.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_call = block

        thinking = "\n".join(text_parts) if text_parts else ""

        if tool_call is None:
            # No tool call — model just wants to talk. Force a completion report.
            return NextStep(
                current_state=thinking or "No tool call returned",
                plan_remaining_steps_brief=["submit answer"],
                task_completed=True,
                function=ReportCompletion(
                    tool="report_completion",
                    completed_steps_laconic=["agent did not call a tool"],
                    answer=thinking or "Unable to determine answer",
                    refs=[],
                    code="failed",
                ),
            )

        # Parse tool input into the right Pydantic model
        model_cls = TOOL_MODELS[tool_call.name]
        tool_input = tool_call.input
        if "tool" not in tool_input:
            tool_input["tool"] = tool_call.name
        function = model_cls.model_validate(tool_input)

        is_completion = isinstance(function, ReportCompletion)

        # Parse thinking for plan (best-effort)
        plan_lines = [line.strip("- ") for line in thinking.split("\n") if line.strip()][:5]
        if not plan_lines:
            plan_lines = [tool_call.name]

        return NextStep(
            current_state=thinking[:200] if thinking else tool_call.name,
            plan_remaining_steps_brief=plan_lines,
            task_completed=is_completion,
            function=function,
        )

    def format_tool_result(self, tool_call_id: str, result_text: str) -> dict:
        """Format a tool result for the Anthropic messages API."""
        return {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_call_id,
                    "content": result_text,
                }
            ],
        }

    def format_assistant_response(self, resp) -> dict:
        """Format the raw API response as an assistant message for history."""
        return {"role": "assistant", "content": resp.content}

    def raw_call(self, messages: list[dict], system_prompt: str, *, cache_aware: bool = False):
        """Make a raw API call and return the full response object.

        Args:
            messages: Conversation messages.
            system_prompt: System prompt string.
            cache_aware: If True, split system prompt into a cacheable prefix
                        block + task-specific suffix. This improves Anthropic
                        prompt caching hit rates across tasks.
        """
        if cache_aware:
            # Split at the task section — everything before "YOUR TASK" is cacheable
            marker = "\nYOUR TASK"
            idx = system_prompt.find(marker)
            if idx > 0:
                static_part = system_prompt[:idx]
                task_part = system_prompt[idx:]
                system_blocks = [
                    {
                        "type": "text",
                        "text": static_part,
                        "cache_control": {"type": "ephemeral"},
                    },
                    {"type": "text", "text": task_part},
                ]
            else:
                # Marker not found — cache the whole thing
                system_blocks = [
                    {
                        "type": "text",
                        "text": system_prompt,
                        "cache_control": {"type": "ephemeral"},
                    }
                ]
            return self.client.messages.create(
                model=MODEL,
                max_tokens=4096,
                system=system_blocks,
                tools=TOOLS,
                messages=messages,
            )

        return self.client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=system_prompt,
            tools=TOOLS,
            messages=messages,
        )
