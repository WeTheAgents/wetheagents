"""Exact UTC deadline and Duel-window calculations."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


class DeadlineError(ValueError):
    """Raised when a deadline cannot be materialized unambiguously."""


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise DeadlineError("deadline timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


def _duration(seconds: int) -> timedelta:
    if isinstance(seconds, bool) or not isinstance(seconds, int) or seconds < 1:
        raise DeadlineError("duration must be a positive integer number of seconds")
    return timedelta(seconds=seconds)


@dataclass(frozen=True)
class DuelWindow:
    slot: int
    opens_at: datetime
    due_at: datetime


def materialize_deadline(entered_at: datetime, duration_seconds: int) -> datetime:
    return _utc(entered_at) + _duration(duration_seconds)


def apply_pause_offset(
    deadline: datetime, pause_started_at: datetime, restored_at: datetime
) -> datetime:
    deadline = _utc(deadline)
    pause_started_at = _utc(pause_started_at)
    restored_at = _utc(restored_at)
    if restored_at < pause_started_at:
        raise DeadlineError("restored_at cannot precede pause_started_at")
    if pause_started_at >= deadline:
        return deadline
    return deadline + (restored_at - pause_started_at)


def duel_windows(
    started_at: datetime, durations_seconds: Iterable[int]
) -> tuple[DuelWindow, ...]:
    durations = tuple(durations_seconds)
    if len(durations) != 6:
        raise DeadlineError("Duel requires exactly six move durations")
    opens_at = _utc(started_at)
    windows: list[DuelWindow] = []
    for index, duration_seconds in enumerate(durations, start=1):
        due_at = opens_at + _duration(duration_seconds)
        windows.append(DuelWindow(index, opens_at, due_at))
        opens_at = due_at
    return tuple(windows)
