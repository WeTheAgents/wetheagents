"""Tool definition builders for Anthropic and OpenAI providers.

Generates the TOOLS list and TOOL_MODELS dict for each runtime (mini / PCM).
"""

from src import models as mini
from src import pcm_models as pcm


def _anthropic_tool(name: str, description: str, model_cls: type) -> dict:
    return {
        "name": name,
        "description": description,
        "input_schema": model_cls.model_json_schema(),
    }


def _openai_tool(name: str, description: str, model_cls: type) -> dict:
    schema = model_cls.model_json_schema()
    if "properties" in schema and "tool" in schema["properties"]:
        del schema["properties"]["tool"]
    if "properties" in schema:
        schema["required"] = list(schema["properties"].keys())
    schema["additionalProperties"] = False
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": schema,
            "strict": True,
        },
    }


# --- Mini runtime (bitgn/sandbox) ---

_MINI_TOOLS = [
    ("outline", "Get a tree outline of a folder in the vault.", mini.OutlineTool),
    ("read", "Read the contents of a file.", mini.ReadTool),
    ("list", "List files in a directory.", mini.ListTool),
    ("search", "Search for a pattern across files. Returns matching snippets.", mini.SearchTool),
    ("write", "Write content to a file (create or overwrite).", mini.WriteTool),
    ("delete", "Delete a file.", mini.DeleteTool),
    (
        "report_completion",
        "Report task completion with the final answer.",
        mini.ReportCompletion,
    ),
]


def mini_anthropic_tools() -> list[dict]:
    return [_anthropic_tool(n, d, m) for n, d, m in _MINI_TOOLS]


def mini_openai_tools() -> list[dict]:
    return [_openai_tool(n, d, m) for n, d, m in _MINI_TOOLS]


def mini_tool_models() -> dict[str, type]:
    return {n: m for n, d, m in _MINI_TOOLS}


# --- PCM runtime (bitgn/pac1-dev) ---

_PCM_TOOLS = [
    ("tree", "Get a tree view of the repository structure. Use level to limit depth.", pcm.TreeTool),
    ("find", "Find files or directories by name.", pcm.FindTool),
    ("search", "Search for a text pattern across files.", pcm.SearchTool),
    ("list", "List files in a directory.", pcm.ListTool),
    ("read", "Read file contents. Supports line numbers and range (start_line/end_line).", pcm.ReadTool),
    ("context", "Get runtime context metadata.", pcm.ContextTool),
    ("write", "Write content to a file. Supports ranged edits via start_line/end_line.", pcm.WriteTool),
    ("delete", "Delete a file.", pcm.DeleteTool),
    ("mkdir", "Create a directory.", pcm.MkDirTool),
    ("move", "Move or rename a file or directory.", pcm.MoveTool),
    (
        "report_completion",
        "Report task completion with a message, grounding refs, and outcome.",
        pcm.PcmReportCompletion,
    ),
]


def pcm_anthropic_tools() -> list[dict]:
    return [_anthropic_tool(n, d, m) for n, d, m in _PCM_TOOLS]


def pcm_openai_tools() -> list[dict]:
    return [_openai_tool(n, d, m) for n, d, m in _PCM_TOOLS]


def pcm_tool_models() -> dict[str, type]:
    return {n: m for n, d, m in _PCM_TOOLS}
