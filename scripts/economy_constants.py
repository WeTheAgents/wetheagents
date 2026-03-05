"""Shared economy constants used by settlement and tests."""

from __future__ import annotations


SPLIT_TABLE: dict[int, list[int]] = {
    1: [100],
    2: [70, 30],
    3: [50, 30, 20],
    4: [40, 25, 20, 15],
    5: [35, 25, 20, 12, 8],
}
