"""Text formatters for readable CLI output."""

from __future__ import annotations


def format_kv(label: str, value: str | None) -> str:
    rendered = value if value not in (None, "") else "-"
    return f"{label}: {rendered}"


def format_issue_line(number: int, title: str) -> str:
    return f"#{number} {title}"


def truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    if max_len <= 1:
        return text[:max_len]
    if max_len <= 3:
        return text[:max_len]
    return text[: max_len - 3] + "..."


def format_task_row(
    number: int,
    title: str,
    reward: str | None,
    reward_type: str | None,
    deadline: str | None,
) -> str:
    number_col = f"#{number:<4}"
    title_col = truncate(title.strip(), 52)
    reward_col = (reward or "-").strip()
    type_col = truncate((reward_type or "-").strip(), 16)
    deadline_col = (deadline or "-").strip()
    return f"{number_col} | {title_col:<52} | {reward_col:<6} | {type_col:<16} | {deadline_col}"
def format_comment(author: str, created_at: str, body: str) -> str:
    header = f"--- @{author} · {created_at} ---"
    return f"{header}\n{body.strip()}"
