"""Vault warm-up — pre-load vault structure and AGENTS.MD before agent loop.

Saves 1-2 tool calls per task by injecting pre-loaded context into the system prompt.
"""

from __future__ import annotations

import json
import re

from src.models import OutlineTool, ReadTool
from src.tools import Dispatcher


def warmup_vault(
    dispatcher: Dispatcher,
    read_agents_md: bool = True,
    use_tree: bool = False,
) -> tuple[str, set[str]]:
    """Pre-load vault outline and optionally AGENTS.MD.

    Args:
        dispatcher: The base (un-enriched) dispatcher for raw tool calls.
        read_agents_md: Whether to also read AGENTS.MD if it exists.
        use_tree: If True, use PCM TreeTool instead of mini OutlineTool.

    Returns:
        (warmup_text, trust_chain):
            warmup_text: Formatted context to append to the system prompt.
            trust_chain: Set of file paths referenced in AGENTS.MD (normalized, no leading slash).
    """
    parts: list[str] = []
    trust_chain: set[str] = set()

    # 1. Get vault outline (tree for PCM, outline for mini)
    if use_tree:
        from src.pcm_models import ReadTool as PcmReadTool
        from src.pcm_models import TreeTool

        outline_result = dispatcher(TreeTool(tool="tree", root=""))
        root_tool_name = "tree"
    else:
        outline_result = dispatcher(OutlineTool(tool="outline", path="/"))
        root_tool_name = "outline"
    parts.append(f"## VAULT STRUCTURE (pre-loaded — do NOT call {root_tool_name} again)")
    parts.append(outline_result)

    # 2. Read AGENTS.MD if it exists in the outline
    if read_agents_md and _file_in_outline(outline_result, "AGENTS.MD"):
        read_tool = PcmReadTool(tool="read", path="AGENTS.MD") if use_tree else ReadTool(tool="read", path="AGENTS.MD")
        agents_md = dispatcher(read_tool)
        parts.append("\n## AGENTS.MD (pre-loaded — do NOT call read on AGENTS.MD again)")
        parts.append(agents_md)

        # Extract trust chain from AGENTS.MD content
        trust_chain = _extract_trust_chain(agents_md)
        trust_chain.add("agents.md")

    warmup_text = "\n".join(parts)
    return warmup_text, trust_chain


def _file_in_outline(outline_json: str, filename: str) -> bool:
    """Check if a filename appears in the outline result."""
    try:
        data = json.loads(outline_json)
        return _search_outline(data, filename)
    except (json.JSONDecodeError, TypeError):
        # Fallback: check raw string
        return filename in outline_json


def _search_outline(node: dict, filename: str) -> bool:
    """Recursively search outline tree for a filename."""
    for f in node.get("files", []):
        path = f if isinstance(f, str) else f.get("path", "")
        if path.endswith(filename) or path.lstrip("/") == filename:
            return True
    for folder in node.get("folders", []):
        if isinstance(folder, dict) and _search_outline(folder, filename):
            return True
    return False


def _extract_trust_chain(agents_md_json: str) -> set[str]:
    """Extract file paths referenced in AGENTS.MD content.

    Looks for patterns like:
      See 'docs/ROOT.MD'
      See "docs/ROOT.MD"
      read docs/setup.md
      reference: policies/rules.md
    """
    trust_chain: set[str] = set()

    # Extract the actual content from JSON
    try:
        data = json.loads(agents_md_json)
        content = data.get("content", agents_md_json)
    except (json.JSONDecodeError, TypeError):
        content = agents_md_json

    # Pattern: quoted file paths (single or double quotes)
    for match in re.finditer(r"""['"]([^'"]+\.(?:md|txt|MD|TXT))['"]""", content):
        path = match.group(1).lstrip("/").lower()
        trust_chain.add(path)

    # Pattern: See/Read/Check <filepath>
    for match in re.finditer(
        r"(?:See|Read|Check|see|read|check|refer to|consult)\s+([^\s,.'\"]+\.(?:md|txt|MD|TXT))",
        content,
    ):
        path = match.group(1).lstrip("/").lower()
        trust_chain.add(path)

    return trust_chain
