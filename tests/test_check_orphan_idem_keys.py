from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from scripts.check_orphan_idem_keys import find_orphans, main, run_check

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_orphan_idem_keys.py"
FIXED_NOW = datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_history(root: Path, filename: str, events: list[dict]) -> None:
    history_dir = root / "ledger" / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(event) for event in events]
    text = "\n".join(lines)
    if text:
        text += "\n"
    (history_dir / filename).write_text(text, encoding="utf-8")


def _make_repo(
    tmp_path: Path,
    *,
    idem_keys: dict[str, object] | None = None,
    top_level: dict[str, object] | None = None,
    aliases: dict[str, str] | None = None,
) -> Path:
    root = tmp_path
    payload: dict[str, object] = {"version": 1, "keys": idem_keys or {}}
    if top_level:
        payload.update(top_level)
    _write_json(root / "ledger" / "idem_keys.json", payload)
    _write_json(root / "ledger" / "agent_aliases.json", aliases or {})
    (root / "ledger" / "history").mkdir(parents=True, exist_ok=True)
    return root


def test_key_matches_event_pass(temp_repo: Path) -> None:
    root = _make_repo(
        temp_repo,
        idem_keys={"payment|123|alice@claude": "2026-04-12T00:00:00Z"},
    )
    _write_history(
        root,
        "2026-04-12.jsonl",
        [{"type": "payment", "issue": 123, "agent": "alice@claude"}],
    )

    report, exit_code = run_check(root, now=FIXED_NOW)

    assert exit_code == 0
    assert report["status"] == "PASS"
    assert report["orphans"] == []


def test_key_with_no_matching_event_warn(temp_repo: Path) -> None:
    root = _make_repo(
        temp_repo,
        idem_keys={"payment|123|alice@claude": "2026-04-12T00:00:00Z"},
    )

    report, exit_code = run_check(root, now=FIXED_NOW)

    assert exit_code == 0
    assert report["status"] == "WARN"
    assert report["orphans"][0]["key"] == "payment|123|alice@claude"
    assert report["orphans"][0]["age_days"] == 3.5


def test_strict_mode_fail(temp_repo: Path) -> None:
    root = _make_repo(
        temp_repo,
        idem_keys={"payment|123|alice@claude": "2026-04-12T00:00:00Z"},
    )

    report, exit_code = run_check(root, strict=True, now=FIXED_NOW)

    assert exit_code == 1
    assert report["status"] == "FAIL"


def test_empty_idem_keys_pass(temp_repo: Path) -> None:
    root = _make_repo(temp_repo, idem_keys={})
    _write_history(root, "2026-04-12.jsonl", [{"type": "payment", "issue": 123, "agent": "alice@claude"}])

    report, exit_code = run_check(root, now=FIXED_NOW)

    assert exit_code == 0
    assert report["status"] == "PASS"
    assert report["orphans"] == []


def test_empty_history_with_keys_present_warn(temp_repo: Path) -> None:
    root = _make_repo(
        temp_repo,
        idem_keys={"escrow|123|agent0@system": "2026-04-12T00:00:00Z"},
    )

    report, _ = run_check(root, now=FIXED_NOW)

    assert report["status"] == "WARN"
    assert [orphan["key"] for orphan in report["orphans"]] == ["escrow|123|agent0@system"]


def test_trajectory_mint_key_matched_by_history_entry_pass(temp_repo: Path) -> None:
    root = _make_repo(
        temp_repo,
        top_level={
            "trajectory_mint|T1|14|agent@codex": {
                "created_at": "2026-04-12T00:00:00Z",
                "op": "trajectory_mint",
            }
        },
    )
    _write_history(
        root,
        "2026-04-12.jsonl",
        [{"type": "trajectory_mint", "trajectory": "T1", "slot": 14, "agent": "agent@codex"}],
    )

    report, _ = run_check(root, now=FIXED_NOW)

    assert report["status"] == "PASS"


def test_escrow_return_key_matched_pass(temp_repo: Path) -> None:
    root = _make_repo(
        temp_repo,
        idem_keys={"escrow_return|123|agent0@system": "2026-04-12T00:00:00Z"},
    )
    _write_history(
        root,
        "2026-04-12.jsonl",
        [{"type": "escrow_return", "issue": 123, "recipient": "agent0@system"}],
    )

    report, _ = run_check(root, now=FIXED_NOW)

    assert report["status"] == "PASS"


def test_malformed_key_warns(temp_repo: Path) -> None:
    root = _make_repo(
        temp_repo,
        top_level={"escrow_create_507_t5s12_gauntlet": "2026-04-15T07:04:43Z"},
    )

    report, _ = run_check(root, now=FIXED_NOW)

    assert report["status"] == "WARN"
    assert report["orphans"][0]["key"] == "escrow_create_507_t5s12_gauntlet"


def test_multiple_orphans_reported_in_list(temp_repo: Path) -> None:
    root = _make_repo(
        temp_repo,
        idem_keys={
            "payment|123|alice@claude": "2026-04-12T00:00:00Z",
            "escrow|124|agent0@system": "2026-04-12T00:00:00Z",
        },
    )

    report, _ = run_check(root, now=FIXED_NOW)

    assert report["status"] == "WARN"
    assert [item["key"] for item in report["orphans"]] == [
        "escrow|124|agent0@system",
        "payment|123|alice@claude",
    ]


def test_main_json_output(temp_repo: Path, capsys) -> None:
    root = _make_repo(
        temp_repo,
        idem_keys={"payment|123|alice@claude": "2026-04-12T00:00:00Z"},
    )

    exit_code = main(["--root", str(root)])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["status"] == "WARN"
    assert payload["orphans"][0]["key"] == "payment|123|alice@claude"


def test_aliases_allow_history_match(temp_repo: Path) -> None:
    root = _make_repo(
        temp_repo,
        idem_keys={"payment|70|cursor-3@cursor|ranking|1": "2026-04-12T00:00:00Z"},
        aliases={"Cursor-1@cursor": "cursor-3@cursor"},
    )
    _write_history(
        root,
        "2026-04-12.jsonl",
        [{"type": "payment", "issue": 70, "agent": "Cursor-1@cursor"}],
    )

    report, _ = run_check(root, now=FIXED_NOW)

    assert report["status"] == "PASS"


def test_find_orphans_can_run_in_memory() -> None:
    idem_entries = [("payment|123|alice@claude", "2026-04-12T00:00:00Z")]
    history_events = [{"type": "payment", "issue": 999, "agent": "alice@claude"}]

    orphans = find_orphans(idem_entries, history_events, now=FIXED_NOW)

    assert len(orphans) == 1
    assert orphans[0]["key"] == "payment|123|alice@claude"


def test_cli_strict_returns_exit_one(temp_repo: Path) -> None:
    root = _make_repo(
        temp_repo,
        idem_keys={"payment|123|alice@claude": "2026-04-12T00:00:00Z"},
    )

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root), "--strict"],
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(result.stdout)
    assert result.returncode == 1
    assert payload["status"] == "FAIL"
