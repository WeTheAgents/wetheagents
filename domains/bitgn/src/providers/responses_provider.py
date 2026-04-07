"""OpenAI Responses API provider — supports codex models and reasoning models.

Uses client.responses.create() instead of chat.completions.create().
Key differences from Chat Completions:
- Flat tool definitions (no nested "function" wrapper)
- Input is a list of items (not messages)
- Tool results sent as function_call_output items
- Supports previous_response_id for conversation continuity
"""

import json
import os

from openai import OpenAI

from src.models import (
    DeleteTool,
    ListTool,
    OutlineTool,
    ReadTool,
    ReportCompletion,
    SearchTool,
    WriteTool,
)
from src.providers.base import LLMProvider

MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")


def _make_schema(model_cls) -> dict:
    schema = model_cls.model_json_schema()
    if "properties" in schema and "tool" in schema["properties"]:
        del schema["properties"]["tool"]
    if "properties" in schema:
        schema["required"] = list(schema["properties"].keys())
    schema["additionalProperties"] = False
    return schema


# Responses API uses flat tool definitions (no nested "function" object)
TOOLS = [
    {
        "type": "function",
        "name": "outline",
        "description": "Get a tree outline of a folder in the vault.",
        "parameters": _make_schema(OutlineTool),
        "strict": True,
    },
    {
        "type": "function",
        "name": "read",
        "description": "Read the contents of a file.",
        "parameters": _make_schema(ReadTool),
        "strict": True,
    },
    {
        "type": "function",
        "name": "list",
        "description": "List files in a directory.",
        "parameters": _make_schema(ListTool),
        "strict": True,
    },
    {
        "type": "function",
        "name": "search",
        "description": "Search for a pattern across files. Returns matching snippets.",
        "parameters": _make_schema(SearchTool),
        "strict": True,
    },
    {
        "type": "function",
        "name": "write",
        "description": "Write content to a file (create or overwrite).",
        "parameters": _make_schema(WriteTool),
        "strict": True,
    },
    {
        "type": "function",
        "name": "delete",
        "description": "Delete a file.",
        "parameters": _make_schema(DeleteTool),
        "strict": True,
    },
    {
        "type": "function",
        "name": "report_completion",
        "description": "Report task completion with the final answer.",
        "parameters": _make_schema(ReportCompletion),
        "strict": True,
    },
]

TOOL_MODELS: dict[str, type] = {
    "outline": OutlineTool,
    "read": ReadTool,
    "list": ListTool,
    "search": SearchTool,
    "write": WriteTool,
    "delete": DeleteTool,
    "report_completion": ReportCompletion,
}


class ResponsesProvider(LLMProvider):
    """OpenAI Responses API provider.

    Unlike OpenAIProvider (Chat Completions), this uses the Responses API
    which supports codex models and has a different I/O format.
    """

    def __init__(self, tools=None):
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.tools = tools or TOOLS
        self.model_override: str | None = None
        self._last_response_id: str | None = None

    def provider_name(self) -> str:
        model = self.model_override or MODEL
        return f"responses/{model}"

    def get_next_step(self, messages, system_prompt):
        raise NotImplementedError("Use raw_call() for Responses API")

    def raw_call(self, messages: list[dict], system_prompt: str, *, cache_aware: bool = False):
        """Call Responses API.

        Converts chat-format messages to Responses API input format.
        Returns the raw Response object.

        The agent loop in agent.py handles OpenAI format, so we return
        a wrapper that mimics chat.completions response structure.
        """
        model = self.model_override or MODEL

        # Convert chat messages to Responses API input items
        input_items = self._convert_messages(messages)

        resp = self.client.responses.create(
            model=model,
            instructions=system_prompt,
            input=input_items,
            tools=self.tools,
            max_output_tokens=4096,
        )

        self._last_response_id = resp.id

        # Convert to chat-completions-compatible format
        return _ResponseAdapter(resp)

    def _convert_messages(self, messages: list[dict]) -> list[dict]:
        """Convert chat-format messages to Responses API input items."""
        items = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if role == "user":
                items.append({
                    "type": "message",
                    "role": "user",
                    "content": content,
                })
            elif role == "assistant":
                # Assistant messages with tool calls
                tool_calls = msg.get("tool_calls")
                if tool_calls:
                    for tc in tool_calls:
                        items.append({
                            "type": "function_call",
                            "call_id": tc.id if hasattr(tc, "id") else tc.get("id", ""),
                            "name": tc.function.name if hasattr(tc, "function") else tc.get("function", {}).get("name", ""),
                            "arguments": tc.function.arguments if hasattr(tc, "function") else tc.get("function", {}).get("arguments", "{}"),
                        })
                else:
                    items.append({
                        "type": "message",
                        "role": "assistant",
                        "content": content,
                    })
            elif role == "tool":
                items.append({
                    "type": "function_call_output",
                    "call_id": msg.get("tool_call_id", ""),
                    "output": content,
                })

        return items


class _ToolCall:
    """Mimics openai chat completion tool call object."""

    def __init__(self, call_id: str, name: str, arguments: str):
        self.id = call_id
        self.type = "function"
        self.function = _Function(name, arguments)


class _Function:
    def __init__(self, name: str, arguments: str):
        self.name = name
        self.arguments = arguments


class _Choice:
    """Mimics openai chat completion choice."""

    def __init__(self, resp):
        self.message = _Message(resp)
        self.finish_reason = "stop"


class _Message:
    """Mimics openai chat completion message, built from Responses API output."""

    def __init__(self, resp):
        self.role = "assistant"
        self.tool_calls = []
        self.content = None

        text_parts = []
        for item in resp.output:
            if item.type == "function_call":
                self.tool_calls.append(
                    _ToolCall(item.call_id, item.name, item.arguments)
                )
            elif item.type == "message":
                for block in item.content:
                    if hasattr(block, "text"):
                        text_parts.append(block.text)

        if text_parts:
            self.content = "\n".join(text_parts)
        if not self.tool_calls:
            self.tool_calls = None


class _ResponseAdapter:
    """Wraps Responses API response to look like chat.completions response."""

    def __init__(self, resp):
        self._resp = resp
        self.choices = [_Choice(resp)]
        self.id = resp.id
        self.model = resp.model
