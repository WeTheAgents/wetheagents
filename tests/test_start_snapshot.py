from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys

# Force local package import from this worktree.
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from wea_cli.start_snapshot import build_start_snapshot, render_start_snapshot


def _issue(
    *,
    number: int,
    title: str,
    body: str = "",
    state: str = "OPEN",
    comments: list[dict] | None = None,
    labels: list[str] | None = None,
) -> dict:
    return {
        "number": number,
        "title": title,
        "body": body,
        "state": state,
        "url": f"https://github.com/WeTheAgents/wetheagents/issues/{number}",
        "comments": {"nodes": comments or []},
        "labels": {"nodes": [{"name": label} for label in (labels or [])]},
    }


def _comment(login: str, body: str, created_at: str) -> dict:
    return {
        "author": {"login": login},
        "body": body,
        "createdAt": created_at,
        "url": "https://github.com/WeTheAgents/wetheagents/issues/1#issuecomment-1",
    }


def test_start_snapshot_new_agent_no_activity() -> None:
    now = datetime(2026, 3, 5, 12, 0, 0, tzinfo=timezone.utc)
    open_tasks = [
        _issue(
            number=39,
            title="wea start",
            body="**Reward:** 20 WEA\n**Reward Type:** Winner Take All\n**Deadline:** 2026-03-06T08:00:00Z",
        )
    ]

    snapshot = build_start_snapshot(
        repo="WeTheAgents/wetheagents",
        agent_id="newbie@cursor",
        balance_info=None,
        now=now,
        open_task_issues=open_tasks,
        involved_issues=[],
    )
    rendered = render_start_snapshot(snapshot, use_color=False)

    assert "Open tasks (1)" in rendered
    assert "My active work (0)" in rendered
    assert "Agent0 mentions (0)" in rendered
    assert "My balance: agent missing in local ledger" in rendered
    assert "DUE <24h" in rendered


def test_start_snapshot_only_created_tasks_not_counted_as_active_work() -> None:
    involved = [
        _issue(
            number=12,
            title="Task created by me",
            comments=[_comment("peachgabba22", "Please review", "2026-03-05T10:00:00Z")],
        )
    ]

    snapshot = build_start_snapshot(
        repo="WeTheAgents/wetheagents",
        agent_id="CursorWea@cursor",
        balance_info={"balance": 150, "github_username": "CursorWEA"},
        open_task_issues=[],
        involved_issues=involved,
    )
    rendered = render_start_snapshot(snapshot, use_color=False)

    assert "My active work (0)" in rendered
    assert "My balance: 150 WEA" in rendered


def test_start_snapshot_groups_statuses_and_detects_unseen_agent0_reply() -> None:
    involved = [
        _issue(
            number=22,
            title="Deep parser task",
            comments=[
                _comment("CursorWEA", "## Work\nImplemented parser.", "2026-03-05T09:00:00Z"),
                _comment("peachgabba22", "Accepted. payout queued.", "2026-03-05T10:00:00Z"),
            ],
        ),
        _issue(
            number=23,
            title="Validation task",
            comments=[_comment("CursorWEA", "## Work\nAdded tests.", "2026-03-05T11:00:00Z")],
        ),
    ]
    open_tasks = [
        _issue(
            number=50,
            title="Open test task",
            body="**Reward:** 5 WEA\n**Reward Type:** standard",
            comments=[_comment("SomeAgent", "claim SomeAgent@gpt", "2026-03-05T12:00:00Z")],
        )
    ]

    snapshot = build_start_snapshot(
        repo="WeTheAgents/wetheagents",
        agent_id="CursorWea@cursor",
        balance_info={"balance": 222, "github_username": "CursorWEA"},
        open_task_issues=open_tasks,
        involved_issues=involved,
    )
    rendered = render_start_snapshot(snapshot, use_color=False)

    assert "My active work (2)" in rendered
    assert "Accepted (1)" in rendered
    assert "Awaiting review (1)" in rendered
    assert "Agent0 mentions (1)" in rendered
    assert "unread Agent0: 1" in rendered
    assert "claimed (1)" in rendered


def test_start_snapshot_falls_back_to_repo_labels_for_mechanic_names() -> None:
    snapshot = build_start_snapshot(
        repo="WeTheAgents/wetheagents",
        agent_id="newbie@cursor",
        balance_info=None,
        open_task_issues=[
            _issue(number=60, title="Progressive task", labels=["task", "progressive-pod"]),
            _issue(number=61, title="Ranked task", labels=["task", "best-x"]),
        ],
        involved_issues=[],
    )

    rendered = render_start_snapshot(snapshot, use_color=False)

    assert "#60 Progressive task | - | Progressive Every Good | unclaimed" in rendered
    assert "#61 Ranked task | - | [X] Best | unclaimed" in rendered
