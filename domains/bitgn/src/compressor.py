"""Deterministic history compression — no LLM calls.

Compresses older messages in the conversation to save context window space.
Keeps first message (task instruction) and last K messages intact.
Middle messages are summarized as brief tool call logs.
"""

from __future__ import annotations


def compress_history(
    messages: list[dict],
    keep_last: int = 4,
) -> list[dict]:
    """Compress conversation history, preserving first and last messages.

    Args:
        messages: Full message history (Anthropic or OpenAI format).
        keep_last: Number of recent messages to keep uncompressed.

    Returns:
        New list with middle messages compressed. Does not mutate original.
    """
    if len(messages) <= keep_last + 1:
        # Nothing to compress
        return list(messages)

    first = messages[0]

    # Find tail boundary — walk back from keep_last to include
    # the parent assistant message for any orphaned OpenAI tool messages.
    cut = len(messages) - keep_last
    while cut > 1 and messages[cut].get("role") == "tool":
        cut -= 1  # include the assistant with tool_calls

    middle = messages[1:cut]
    tail = messages[cut:]

    summary_text = _build_summary(middle)

    # Maintain alternating user/assistant pattern required by Anthropic API.
    # Insert as an assistant message (summary of what agent did) followed by
    # a user message (acknowledgment) so the tail's first message role is valid.
    compressed = [first]
    compressed.append({
        "role": "assistant",
        "content": f"[COMPRESSED HISTORY — earlier steps summarized]\n{summary_text}",
    })

    # If tail starts with assistant, add a bridging user message
    if tail and tail[0].get("role") == "assistant":
        compressed.append({
            "role": "user",
            "content": "[Continue with the task.]",
        })

    compressed.extend(tail)
    return compressed


def _build_summary(messages: list[dict]) -> str:
    """Build a text summary of a sequence of middle messages."""
    lines: list[str] = []

    for msg in messages:
        role = msg.get("role", "?")
        content = msg.get("content", "")

        if role == "assistant":
            # Anthropic format: content is a list of blocks
            if isinstance(content, list):
                tool_names = []
                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") == "tool_use":
                            tool_names.append(block.get("name", "?"))
                    elif hasattr(block, "type") and block.type == "tool_use":
                        tool_names.append(block.name)
                if tool_names:
                    lines.append(f"  Called: {', '.join(tool_names)}")
            # OpenAI format: content is a string, tool_calls is a list
            elif msg.get("tool_calls"):
                names = [tc.get("function", {}).get("name", "?")
                         if isinstance(tc, dict) else tc.function.name
                         for tc in msg["tool_calls"]]
                lines.append(f"  Called: {', '.join(names)}")
            elif isinstance(content, str) and content.strip():
                lines.append(f"  Thought: {content[:80]}...")

        elif role == "user":
            if isinstance(content, list):
                # Anthropic tool_result blocks
                summaries = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        result_text = block.get("content", "")
                        if not isinstance(result_text, str):
                            result_text = str(result_text)
                        preview = result_text[:60] + "..." if len(result_text) > 60 else result_text
                        summaries.append(preview)
                if summaries:
                    lines.append(f"  Results: {'; '.join(summaries)}")
            elif isinstance(content, str) and content.strip():
                lines.append(f"  System: {content[:80]}...")

        elif role == "tool":
            # OpenAI tool result message
            result_text = content if isinstance(content, str) else str(content)
            preview = result_text[:60] + "..." if len(result_text) > 60 else result_text
            lines.append(f"  Result: {preview}")

    return "\n".join(lines)
