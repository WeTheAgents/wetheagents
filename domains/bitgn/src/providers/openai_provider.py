"""OpenAI provider for BitGN agent using native function calling (tools API)."""

import os
import time

from openai import BadRequestError, OpenAI

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

# Tool definitions for OpenAI function calling
# We strip the "tool" literal field from schemas since it's redundant with function name
def _make_schema(model_cls) -> dict:
    schema = model_cls.model_json_schema()
    # Remove the "tool" field — it's always the function name
    if "properties" in schema and "tool" in schema["properties"]:
        del schema["properties"]["tool"]
    # OpenAI strict mode: ALL properties must be in required
    if "properties" in schema:
        schema["required"] = list(schema["properties"].keys())
    schema["additionalProperties"] = False
    return schema


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "outline",
            "description": "Get a tree outline of a folder in the vault.",
            "parameters": _make_schema(OutlineTool),
            "strict": True,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read",
            "description": "Read the contents of a file.",
            "parameters": _make_schema(ReadTool),
            "strict": True,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list",
            "description": "List files in a directory.",
            "parameters": _make_schema(ListTool),
            "strict": True,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search",
            "description": "Search for a pattern across files. Returns matching snippets.",
            "parameters": _make_schema(SearchTool),
            "strict": True,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write",
            "description": "Write content to a file (create or overwrite).",
            "parameters": _make_schema(WriteTool),
            "strict": True,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete",
            "description": "Delete a file.",
            "parameters": _make_schema(DeleteTool),
            "strict": True,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "report_completion",
            "description": "Report task completion with the final answer. Use when you have gathered enough information to answer the task.",
            "parameters": _make_schema(ReportCompletion),
            "strict": True,
        },
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


class OpenAIProvider(LLMProvider):
    def __init__(self, tools=None):
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.tools = tools or TOOLS
        self.model_override: str | None = None  # set per-task by agent loop

    def provider_name(self) -> str:
        model = self.model_override or MODEL
        return f"openai/{model}"

    def get_next_step(self, messages: list[dict], system_prompt: str):
        """Not used for OpenAI native tool calling — kept for interface compat."""
        raise NotImplementedError("Use raw_call() for OpenAI native tool calling")

    def _build_messages(self, messages: list[dict], system_prompt: str) -> list[dict]:
        full_messages = [{"role": "system", "content": str(system_prompt)}]
        for message in messages:
            normalized = dict(message)
            if "content" in normalized and normalized["content"] is not None:
                normalized["content"] = str(normalized["content"])
            full_messages.append(normalized)
        return full_messages

    def raw_call(self, messages: list[dict], system_prompt: str, *, cache_aware: bool = False):
        """Make a raw API call with tools and return the response."""
        model = self.model_override or MODEL
        full_messages = self._build_messages(messages, system_prompt)
        try:
            return self.client.chat.completions.create(
                model=model,
                tools=self.tools,
                messages=full_messages,
                max_completion_tokens=4096,
            )
        except BadRequestError as exc:
            message = str(exc)
            if "parse the JSON body" not in message:
                raise
            # Defensive retry for rare payload serialization glitches observed on PAC.
            time.sleep(0.5)
            self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
            return self.client.chat.completions.create(
                model=model,
                tools=self.tools,
                messages=self._build_messages(messages, system_prompt),
                max_completion_tokens=4096,
            )
