from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from scripts import check_stale_escrows

NOW = datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc)


def _ts(days_ago: float) -> str:
    return (NOW - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _escrows(entries: dict[str, dict]) -> dict:
    return {"version": 1, "active": entries}


def test_fresh_escrow_pass() -> None:
    report = check_stale_escrows.build_report(
        _escrows({"308": {"created_at": _ts(1), "amount": 8}}),
        now=NOW,
    )

    assert report["status"] == "PASS"
    assert report["stale"] == []


def test_over_threshold_warn() -> None:
    report = check_stale_escrows.build_report(
        _escrows({"308": {"created_at": _ts(10), "amount": 8}}),
        now=NOW,
    )

    assert report["status"] == "WARN"
    assert report["stale"] == [
        {
            "issue": "308",
            "age_days": 10.0,
            "amount": 8,
            "created_at": _ts(10),
        }
    ]


def test_exactly_at_threshold_warn() -> None:
    report = check_stale_escrows.build_report(
        _escrows({"308": {"created_at": _ts(7.0), "amount": 8}}),
        now=NOW,
    )

    assert report["status"] == "WARN"
    assert report["stale"][0]["age_days"] == 7.0


def test_strict_mode_fail_on_stale() -> None:
    report = check_stale_escrows.build_report(
        _escrows({"308": {"created_at": _ts(10), "amount": 8}}),
        now=NOW,
        strict=True,
    )

    assert report["status"] == "FAIL"


def test_empty_escrows_pass() -> None:
    report = check_stale_escrows.build_report(_escrows({}), now=NOW)

    assert report["status"] == "PASS"
    assert report["stale"] == []


def test_missing_created_at_handled_gracefully() -> None:
    report = check_stale_escrows.build_report(
        _escrows({"308": {"amount": 8}}),
        now=NOW,
    )

    assert report["status"] == "PASS"
    assert report["stale"] == []
    assert "skipped 1" in report["summary"]


def test_multiple_escrows_one_stale_warn() -> None:
    report = check_stale_escrows.build_report(
        _escrows(
            {
                "307": {"created_at": _ts(1), "amount": 5},
                "308": {"created_at": _ts(14.5), "amount": 8},
            }
        ),
        now=NOW,
    )

    assert report["status"] == "WARN"
    assert len(report["stale"]) == 1
    assert report["stale"][0]["issue"] == "308"
    assert report["stale"][0]["age_days"] == 14.5


def test_threshold_days_override_marks_previous_fresh_stale() -> None:
    report = check_stale_escrows.build_report(
        _escrows({"308": {"created_at": _ts(1), "amount": 8}}),
        now=NOW,
        threshold_days=1,
    )

    assert report["status"] == "WARN"
    assert report["stale"][0]["issue"] == "308"


def test_threshold_days_30_nothing_stale() -> None:
    report = check_stale_escrows.build_report(
        _escrows(
            {
                "308": {"created_at": _ts(10), "amount": 8},
                "309": {"created_at": _ts(29.9), "amount": 9},
            }
        ),
        now=NOW,
        threshold_days=30,
    )

    assert report["status"] == "PASS"
    assert report["stale"] == []


def test_main_json_output(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        check_stale_escrows,
        "load_json",
        lambda *args, **kwargs: _escrows({"308": {"created_at": _ts(10), "amount": 8}}),
    )
    monkeypatch.setattr(
        check_stale_escrows,
        "datetime",
        type(
            "FixedDateTime",
            (),
            {
                "now": staticmethod(lambda tz=None: NOW),
                "fromisoformat": staticmethod(datetime.fromisoformat),
            },
        ),
    )

    exit_code = check_stale_escrows.main([])
    output = capsys.readouterr().out.strip()
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["status"] == "WARN"
    assert payload["stale"][0]["issue"] == "308"
