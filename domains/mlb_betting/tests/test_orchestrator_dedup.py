"""Regression tests for orchestrator dedup logic.

Bug E (plans/§2): the legacy `(date, team, vh)` dedup silently collapsed one
doubleheader game per pair because both games of a DH share that key. Fixed
by switching to `(event_id, team, vh)` in `_dedup_games`. These tests pin
the new behavior so the bug cannot regress.
"""

from __future__ import annotations

import pandas as pd
import pytest

from data.fetch_2026.orchestrator import _dedup_games


def _row(event_id: str, date: int, team: str, vh: str, final: int) -> dict:
    return {
        "event_id": event_id,
        "date": date,
        "team": team,
        "vh": vh,
        "final": final,
    }


def test_doubleheader_both_games_survive():
    """Two games on the same day with the same team but different event_ids
    must both survive dedup. The legacy key collapsed one of them."""
    df = pd.DataFrame(
        [
            _row("event_A", 415, "BAL", "V", 4),
            _row("event_A", 415, "TOR", "H", 3),
            _row("event_B", 415, "BAL", "V", 2),  # second game of DH
            _row("event_B", 415, "TOR", "H", 5),
        ]
    )
    out = _dedup_games(df)
    assert len(out) == 4, f"Expected 4 rows (DH preserved), got {len(out)}"
    assert set(out["event_id"]) == {"event_A", "event_B"}
    # Both BAL rows present
    bal_rows = out[out["team"] == "BAL"]
    assert len(bal_rows) == 2
    assert sorted(bal_rows["final"].tolist()) == [2, 4]


def test_simple_dedup_still_collapses_true_duplicates():
    """Two rows with the SAME event_id+team+vh (e.g., a re-fetch of the same
    game) must collapse to one, keeping the latest values."""
    df = pd.DataFrame(
        [
            _row("event_A", 415, "BAL", "V", 4),
            _row("event_A", 415, "TOR", "H", 3),
            _row("event_A", 415, "BAL", "V", 7),  # later re-fetch overrides
            _row("event_A", 415, "TOR", "H", 2),
        ]
    )
    out = _dedup_games(df)
    assert len(out) == 2
    assert out[out["team"] == "BAL"]["final"].iloc[0] == 7
    assert out[out["team"] == "TOR"]["final"].iloc[0] == 2


def test_legacy_rows_without_event_id_use_date_team_vh():
    """Legacy rows from before the event_id column existed must still dedup
    by (date, team, vh) — we don't want to crash on historical data."""
    rows = [
        {"event_id": None, "date": 415, "team": "BAL", "vh": "V", "final": 4},
        {"event_id": None, "date": 415, "team": "TOR", "vh": "H", "final": 3},
        {"event_id": None, "date": 415, "team": "BAL", "vh": "V", "final": 7},
    ]
    df = pd.DataFrame(rows)
    out = _dedup_games(df)
    assert len(out) == 2
    assert out[out["team"] == "BAL"]["final"].iloc[0] == 7


def test_mixed_event_id_and_legacy_rows():
    """A frame with some rows that have event_id and some that don't
    must dedup each group with its own key without crashing."""
    df = pd.DataFrame(
        [
            # Legacy rows
            {"event_id": None, "date": 401, "team": "BAL", "vh": "V", "final": 4},
            {"event_id": None, "date": 401, "team": "TOR", "vh": "H", "final": 3},
            # New DH rows with event_ids
            {"event_id": "evt_1", "date": 415, "team": "BAL", "vh": "V", "final": 4},
            {"event_id": "evt_2", "date": 415, "team": "BAL", "vh": "V", "final": 2},
        ]
    )
    out = _dedup_games(df)
    # Legacy: 2 rows, DH: 2 rows = 4 total
    assert len(out) == 4
    bal_415 = out[(out["team"] == "BAL") & (out["date"] == 415)]
    assert len(bal_415) == 2


def test_empty_frame():
    df = pd.DataFrame(columns=["event_id", "date", "team", "vh", "final"])
    out = _dedup_games(df)
    assert out.empty


def test_no_event_id_column_at_all():
    df = pd.DataFrame(
        [
            {"date": 415, "team": "BAL", "vh": "V", "final": 4},
            {"date": 415, "team": "TOR", "vh": "H", "final": 3},
            {"date": 415, "team": "BAL", "vh": "V", "final": 7},
        ]
    )
    out = _dedup_games(df)
    assert len(out) == 2
    assert out[out["team"] == "BAL"]["final"].iloc[0] == 7


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
