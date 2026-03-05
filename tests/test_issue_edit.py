from __future__ import annotations

import pytest

from wea_cli.issue_edit import IssueEditError, safe_edit_issue_labels


def _issue_payload(state: str, labels: set[str]) -> dict:
    return {
        "state": state,
        "labels": [{"name": name} for name in sorted(labels)],
    }


def test_safe_edit_normal_swap() -> None:
    issue_store = {
        "state": "OPEN",
        "labels": {"task", "open", "paid-on-delivery"},
    }

    def get_issue(_: int) -> dict:
        return _issue_payload(issue_store["state"], issue_store["labels"])

    def set_labels(_: int, labels: list[str]) -> None:
        issue_store["labels"] = set(labels)

    def set_state(_: int, state: str) -> None:
        issue_store["state"] = state

    result = safe_edit_issue_labels(
        38,
        add_labels=[],
        remove_labels=[],
        swaps=[("paid-on-delivery", "winner-take-all")],
        get_issue=get_issue,
        set_labels=set_labels,
        set_state=set_state,
    )

    assert result["state_before"] == "OPEN"
    assert result["state_after"] == "OPEN"
    assert "paid-on-delivery" not in issue_store["labels"]
    assert "winner-take-all" in issue_store["labels"]


def test_safe_edit_remove_non_existent_label_is_noop() -> None:
    issue_store = {
        "state": "OPEN",
        "labels": {"task", "open"},
    }
    set_labels_calls = 0

    def get_issue(_: int) -> dict:
        return _issue_payload(issue_store["state"], issue_store["labels"])

    def set_labels(_: int, labels: list[str]) -> None:
        nonlocal set_labels_calls
        set_labels_calls += 1
        issue_store["labels"] = set(labels)

    def set_state(_: int, state: str) -> None:
        issue_store["state"] = state

    result = safe_edit_issue_labels(
        38,
        add_labels=[],
        remove_labels=["claimed"],  # does not exist
        swaps=[],
        get_issue=get_issue,
        set_labels=set_labels,
        set_state=set_state,
    )

    assert result["changed"] is False
    assert set_labels_calls == 0
    assert issue_store["labels"] == {"task", "open"}
    assert issue_store["state"] == "OPEN"


def test_safe_edit_detects_state_flip_and_rolls_back() -> None:
    issue_store = {
        "state": "OPEN",
        "labels": {"task", "open"},
    }
    set_labels_calls = 0
    state_calls: list[str] = []

    def get_issue(_: int) -> dict:
        return _issue_payload(issue_store["state"], issue_store["labels"])

    def set_labels(_: int, labels: list[str]) -> None:
        nonlocal set_labels_calls
        set_labels_calls += 1
        issue_store["labels"] = set(labels)
        # Simulate unexpected side effect after first label edit.
        if set_labels_calls == 1:
            issue_store["state"] = "CLOSED"

    def set_state(_: int, state: str) -> None:
        issue_store["state"] = state
        state_calls.append(state)

    with pytest.raises(IssueEditError, match="Rollback was applied"):
        safe_edit_issue_labels(
            38,
            add_labels=["winner-take-all"],
            remove_labels=["open"],
            swaps=[],
            get_issue=get_issue,
            set_labels=set_labels,
            set_state=set_state,
        )

    assert set_labels_calls == 2  # initial edit + rollback
    assert issue_store["labels"] == {"task", "open"}
    assert issue_store["state"] == "OPEN"
    assert state_calls == ["OPEN"]
