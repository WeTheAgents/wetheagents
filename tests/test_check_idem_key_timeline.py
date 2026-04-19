from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.check_idem_key_timeline import (
    collect_known_idem_keys,
    load_idem_keys,
    main,
    parse_known_idem_key,
    run_check,
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, events: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(event) for event in events) + "\n",
        encoding="utf-8",
    )


def _make_repo(
    root: Path,
    *,
    idem_keys: dict[str, object] | None = None,
    top_level: dict[str, object] | None = None,
    aliases: dict[str, str] | None = None,
) -> Path:
    _write_json(
        root / "ledger" / "idem_keys.json",
        {
            "version": 1,
            "keys": idem_keys or {},
            **(top_level or {}),
        },
    )
    _write_json(root / "ledger" / "agent_aliases.json", aliases or {})
    (root / "ledger" / "history").mkdir(parents=True, exist_ok=True)
    return root


def test_load_idem_keys_merges_nested_and_top_level(temp_repo: Path) -> None:
    root = _make_repo(
        temp_repo,
        idem_keys={"accept|10|alice@test": "2026-04-10T00:00:00Z"},
        top_level={"trajectory_mint|T1|1": "2026-04-10T00:05:00Z"},
    )

    merged = load_idem_keys(root / "ledger" / "idem_keys.json")

    assert merged["accept|10|alice@test"] == "2026-04-10T00:00:00Z"
    assert merged["trajectory_mint|T1|1"] == "2026-04-10T00:05:00Z"


def test_parse_known_idem_key_normalizes_accept_alias() -> None:
    parsed = parse_known_idem_key(
        "accept|5|Antigravity-1@Google|slot1",
        aliases={
            "AntigravityWea@Google": "gemini-4@google",
            "Antigravity-1@Google": "gemini-4@google",
        },
    )

    assert parsed is not None
    assert parsed.kind == "accept"
    assert parsed.actor == "gemini-4@google"
    assert parsed.variant == ("slot1",)


def test_accept_key_matches_payment_event_via_explicit_idem_key_and_alias(temp_repo: Path) -> None:
    root = _make_repo(
        temp_repo,
        idem_keys={"accept|5|Antigravity-1@Google|slot1": "2026-03-04T18:10:00Z"},
        aliases={
            "AntigravityWea@Google": "gemini-4@google",
            "Antigravity-1@Google": "gemini-4@google",
        },
    )
    _write_jsonl(
        root / "ledger" / "history" / "2026-03-04.jsonl",
        [
            {
                "type": "payment",
                "issue": 5,
                "agent": "AntigravityWea@Google",
                "event_at": "2026-03-03T20:05:00Z",
                "started_at": "2026-03-04T18:10:00Z",
                "idem_key": "accept|5|AntigravityWea@Google|slot1",
            }
        ],
    )

    report = run_check(root)

    assert report["status"] == "PASS"
    assert report["phantom_keys"] == []
    assert report["counts"]["events_by_operation"]["accept"] == 1


def test_escrow_create_key_matches_op_based_history_event(temp_repo: Path) -> None:
    root = _make_repo(
        temp_repo,
        top_level={"escrow_create_631_t1_gauntlet": "2026-04-18T20:13:23Z"},
    )
    _write_jsonl(
        root / "ledger" / "history" / "2026-04-18.jsonl",
        [
            {
                "op": "escrow_create",
                "issue": 631,
                "amount": 42,
                "ts": "2026-04-18T20:13:23Z",
                "idem_key": "escrow_create_631_t1_gauntlet",
            }
        ],
    )

    report = run_check(root)

    assert report["status"] == "PASS"
    assert report["counts"]["events_by_operation"]["escrow_create"] == 1
    assert report["phantom_keys"] == []


def test_escrow_create_key_matches_event_based_history_event(temp_repo: Path) -> None:
    root = _make_repo(
        temp_repo,
        top_level={"escrow_create_632_t2_gauntlet": "2026-04-18T20:13:23Z"},
    )
    _write_jsonl(
        root / "ledger" / "history" / "2026-04-18.jsonl",
        [
            {
                "event": "escrow_create",
                "type": "ledger_write",
                "issue": 632,
                "author": "agent0@system",
                "amount": 43,
                "timestamp": "2026-04-18T20:13:23Z",
                "idem_key": "escrow_create_632_t2_gauntlet",
            }
        ],
    )

    report = run_check(root)

    assert report["status"] == "PASS"
    assert report["counts"]["events_by_operation"]["escrow_create"] == 1
    assert report["phantom_keys"] == []


def test_actor_specific_trajectory_key_matches_to_field(temp_repo: Path) -> None:
    root = _make_repo(
        temp_repo,
        top_level={
            "trajectory_mint|T1|23|Claude-1@claude": {
                "created_at": "2026-04-19T03:02:15Z",
                "op": "trajectory_mint",
            }
        },
    )
    _write_jsonl(
        root / "ledger" / "history" / "2026-04-19.jsonl",
        [
            {
                "type": "trajectory_mint",
                "trajectory": "T1",
                "slot": 23,
                "to": "Claude-1@claude",
                "ts": "2026-04-19T03:02:56Z",
            }
        ],
    )

    report = run_check(root)

    assert report["status"] == "PASS"
    assert report["phantom_keys"] == []


def test_missing_history_event_reports_phantom_key(temp_repo: Path) -> None:
    root = _make_repo(
        temp_repo,
        idem_keys={"accept|10|alice@test": "2026-04-10T00:00:00Z"},
    )
    _write_jsonl(root / "ledger" / "history" / "2026-04-10.jsonl", [])

    report = run_check(root)

    assert report["status"] == "FAIL"
    assert report["phantom_keys"] == [
        {
            "idem_key": "accept|10|alice@test",
            "operation": "accept",
            "registered_at": "2026-04-10T00:00:00Z",
        }
    ]


def test_concatenated_history_objects_are_counted(temp_repo: Path) -> None:
    root = _make_repo(
        temp_repo,
        top_level={"trajectory_mint|T1|1": "2026-04-10T00:00:00Z"},
    )
    path = root / "ledger" / "history" / "2026-04-10.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"type": "noise", "message": "ignore"})
        + json.dumps(
            {
                "type": "trajectory_mint",
                "trajectory": "T1",
                "slot": 1,
                "agents": ["alice@test"],
                "timestamp": "2026-04-10T00:00:00Z",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    report = run_check(root)

    assert report["status"] == "PASS"
    assert report["counts"]["events_by_operation"]["trajectory_mint"] == 1


def test_backdated_event_fails_when_timestamp_predates_first_history_file(temp_repo: Path) -> None:
    root = _make_repo(
        temp_repo,
        idem_keys={"accept|10|alice@test": "2026-04-10T00:00:00Z"},
    )
    _write_jsonl(
        root / "ledger" / "history" / "2026-04-10.jsonl",
        [
            {
                "type": "accept",
                "issue": 10,
                "agent": "alice@test",
                "timestamp": "2026-04-09T23:59:59Z",
            }
        ],
    )

    report = run_check(root)

    assert report["status"] == "FAIL"
    assert report["backdated_events"] == [
        {
            "operation": "accept",
            "event_type": "accept",
            "file": "2026-04-10.jsonl",
            "line": 1,
            "timestamp": "2026-04-09T23:59:59Z",
            "earliest_history_file_date": "2026-04-10",
        }
    ]


def test_count_check_fails_when_history_has_more_required_events_than_keys(temp_repo: Path) -> None:
    root = _make_repo(
        temp_repo,
        idem_keys={"accept|10|alice@test": "2026-04-10T00:00:00Z"},
    )
    _write_jsonl(
        root / "ledger" / "history" / "2026-04-10.jsonl",
        [
            {
                "type": "accept",
                "issue": 10,
                "agent": "alice@test",
                "timestamp": "2026-04-10T00:00:00Z",
            },
            {
                "type": "trajectory_mint",
                "trajectory": "T1",
                "slot": 1,
                "agents": ["alice@test"],
                "timestamp": "2026-04-10T00:05:00Z",
            },
        ],
    )

    report = run_check(root)

    assert report["status"] == "FAIL"
    assert report["count_check"]["status"] == "FAIL"
    assert report["count_check"]["unique_idem_keys"] == 1
    assert report["count_check"]["required_history_events"] == 2


def test_collect_known_idem_keys_ignores_unrelated_keys(temp_repo: Path) -> None:
    root = _make_repo(
        temp_repo,
        idem_keys={
            "accept|10|alice@test": "2026-04-10T00:00:00Z",
            "verify|10|alice@test": "2026-04-10T00:00:00Z",
        },
        top_level={"hello_world|alice@test": "2026-04-10T00:00:00Z"},
    )

    entries = collect_known_idem_keys(
        load_idem_keys(root / "ledger" / "idem_keys.json"),
        aliases={},
    )

    assert [entry.raw_key for entry in entries] == ["accept|10|alice@test"]


def test_main_returns_zero_and_json_on_pass(temp_repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _make_repo(
        temp_repo,
        idem_keys={"accept|10|alice@test": "2026-04-10T00:00:00Z"},
    )
    _write_jsonl(
        root / "ledger" / "history" / "2026-04-10.jsonl",
        [
            {
                "type": "accept",
                "issue": 10,
                "agent": "alice@test",
                "timestamp": "2026-04-10T00:00:00Z",
            }
        ],
    )

    exit_code = main(["--root", str(root)])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["status"] == "PASS"


def test_main_returns_skip_when_history_is_missing(temp_repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = temp_repo
    _write_json(root / "ledger" / "idem_keys.json", {"keys": {}})

    exit_code = main(["--root", str(root)])
    captured = capsys.readouterr()

    assert exit_code == 2
    assert "no YYYY-MM-DD history files found" in captured.err
