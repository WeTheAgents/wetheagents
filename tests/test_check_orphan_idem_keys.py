from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

from scripts.check_orphan_idem_keys import (
    build_history_key_evidence,
    find_orphan_idem_keys,
    is_history_backed_idem_key,
    load_history_idem_keys,
    load_idem_entries,
    load_idem_keys,
    main,
    run_check,
    select_history_backed_idem_keys,
)

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_orphan_idem_keys.py"


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_history(root: Path, filename: str, *events: object) -> None:
    history_dir = root / "ledger" / "history"
    history_dir.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    for event in events:
        if isinstance(event, str):
            lines.append(event)
        else:
            lines.append(json.dumps(event))

    text = "\n".join(lines)
    if text:
        text += "\n"

    (history_dir / filename).write_text(text, encoding="utf-8")


def _make_repo(
    temp_repo: Path,
    *,
    idem_payload: object | None = None,
    create_history: bool = True,
) -> Path:
    root = temp_repo
    if idem_payload is not None:
        _write_json(root / "ledger" / "idem_keys.json", idem_payload)
    if create_history:
        (root / "ledger" / "history").mkdir(parents=True, exist_ok=True)
    return root


def test_load_idem_entries_merges_top_level_and_nested_entries(temp_repo: Path) -> None:
    root = _make_repo(
        temp_repo,
        idem_payload={
            "version": 1,
            "escrow|10": True,
            "keys": {
                "payment|10|alice@test": {"action": "payment"},
                "register|alice@test": True,
            },
        },
    )

    entries = load_idem_entries(root / "ledger" / "idem_keys.json")

    assert entries == {
        "escrow|10": True,
        "payment|10|alice@test": {"action": "payment"},
        "register|alice@test": True,
    }


def test_load_idem_keys_returns_every_recorded_key_name(temp_repo: Path) -> None:
    root = _make_repo(
        temp_repo,
        idem_payload={"version": 1, "escrow_return|11": True, "keys": {"payment|11|alice@test": {}}},
    )

    assert load_idem_keys(root / "ledger" / "idem_keys.json") == {
        "escrow_return|11",
        "payment|11|alice@test",
    }


def test_load_idem_keys_returns_empty_set_when_file_missing(temp_repo: Path) -> None:
    idem_path = temp_repo / "ledger" / "missing_idem_keys.json"

    assert load_idem_keys(idem_path) == set()


def test_load_idem_entries_returns_empty_dict_for_non_dict_payload(temp_repo: Path) -> None:
    root = _make_repo(temp_repo, idem_payload=["not", "an", "object"])

    assert load_idem_entries(root / "ledger" / "idem_keys.json") == {}


def test_is_history_backed_idem_key_accepts_prefixes_and_metadata() -> None:
    assert is_history_backed_idem_key("accept|10|alice@test", True) is True
    assert is_history_backed_idem_key("register|alice@test", True) is False
    assert is_history_backed_idem_key("abc123", {"action": "payment"}) is True
    assert is_history_backed_idem_key("abc123", {"action": "register"}) is False


def test_select_history_backed_idem_keys_filters_non_history_namespaces() -> None:
    entries = {
        "escrow|10": True,
        "claim|10|alice@test": True,
        "register|alice@test": True,
        "hash-payment": {"action": "payment"},
        "hash-register": {"action": "register"},
    }

    assert select_history_backed_idem_keys(entries) == {"escrow|10", "hash-payment"}


def test_load_history_idem_keys_collects_only_literal_idem_keys(temp_repo: Path) -> None:
    root = _make_repo(temp_repo, idem_payload={"keys": {}})
    _write_history(
        root,
        "2026-04-21-a.jsonl",
        {"type": "payment", "idem_key": "payment|10|alice@test"},
        {"type": "payment", "idem_key": 123},
        {"type": "payment"},
    )
    _write_history(
        root,
        "2026-04-21-b.jsonl",
        {"type": "escrow", "idem_key": "escrow|10"},
        {"type": "escrow", "idem_key": "payment|10|alice@test"},
    )

    history_keys = load_history_idem_keys(root / "ledger" / "history")

    assert history_keys == {"payment|10|alice@test", "escrow|10"}


def test_load_history_idem_keys_ignores_invalid_json_lines(temp_repo: Path) -> None:
    root = _make_repo(temp_repo, idem_payload={"keys": {}})
    _write_history(
        root,
        "2026-04-21.jsonl",
        '{"type":"payment","idem_key":"payment|10|alice@test"}',
        "{broken json",
        '{"type":"escrow","idem_key":"escrow|10"}',
    )

    history_keys = load_history_idem_keys(root / "ledger" / "history")

    assert history_keys == {"payment|10|alice@test", "escrow|10"}


def test_build_history_key_evidence_includes_hashed_variants() -> None:
    history_keys = {"payment|10|alice@test"}

    evidence = build_history_key_evidence(history_keys)

    assert "payment|10|alice@test" in evidence
    assert hashlib.sha256("payment|10|alice@test".encode("utf-8")).hexdigest() in evidence


def test_find_orphan_idem_keys_returns_sorted_difference() -> None:
    orphans = find_orphan_idem_keys(
        {"payment|2|bob@test", "escrow|1", "payment|1|alice@test"},
        {"escrow|1"},
    )

    assert orphans == ["payment|1|alice@test", "payment|2|bob@test"]


def test_find_orphan_idem_keys_honors_agent_aliases() -> None:
    orphans = find_orphan_idem_keys(
        {"accept|5|Antigravity-1@Google|slot1"},
        {"accept|5|gemini-4@google|slot1"},
        {
            "Antigravity-1@Google": "gemini-4@google",
            "AntigravityWea@Google": "gemini-4@google",
        },
    )

    assert orphans == []


def test_run_check_passes_when_all_checked_keys_appear_in_history(temp_repo: Path) -> None:
    root = _make_repo(
        temp_repo,
        idem_payload={
            "version": 1,
            "escrow|10": True,
            "keys": {"payment|10|alice@test": {"action": "payment"}},
        },
    )
    _write_history(
        root,
        "2026-04-21.jsonl",
        {"type": "escrow", "idem_key": "escrow|10"},
        {"type": "payment", "idem_key": "payment|10|alice@test"},
    )

    report, exit_code = run_check(root)

    assert exit_code == 0
    assert report["status"] == "PASS"
    assert report["checked_idem_keys"] == 2
    assert report["orphan_keys"] == []


def test_run_check_normalizes_aliases_before_comparing_keys(temp_repo: Path) -> None:
    root = _make_repo(
        temp_repo,
        idem_payload={"version": 1, "accept|5|Antigravity-1@Google|slot1": True},
    )
    _write_json(
        root / "ledger" / "agent_aliases.json",
        {
            "Antigravity-1@Google": "gemini-4@google",
            "AntigravityWea@Google": "gemini-4@google",
        },
    )
    _write_history(
        root,
        "2026-04-21.jsonl",
        {"type": "accept", "idem_key": "accept|5|AntigravityWea@Google|slot1"},
    )

    report, exit_code = run_check(root)

    assert exit_code == 0
    assert report["status"] == "PASS"
    assert report["orphan_keys"] == []


def test_run_check_ignores_non_history_backed_keys(temp_repo: Path) -> None:
    root = _make_repo(
        temp_repo,
        idem_payload={
            "version": 1,
            "register|alice@test": True,
            "claim|10|alice@test": True,
            "escrow|10": True,
        },
    )
    _write_history(root, "2026-04-21.jsonl", {"type": "escrow", "idem_key": "escrow|10"})

    report, exit_code = run_check(root)

    assert exit_code == 0
    assert report["recorded_idem_keys"] == 3
    assert report["checked_idem_keys"] == 1
    assert report["orphan_keys"] == []


def test_run_check_matches_hashed_recorded_key_to_raw_history_key(temp_repo: Path) -> None:
    raw_key = "payment|10|alice@test"
    hashed_key = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    root = _make_repo(
        temp_repo,
        idem_payload={"version": 1, "keys": {hashed_key: {"action": "payment"}}},
    )
    _write_history(root, "2026-04-21.jsonl", {"type": "payment", "idem_key": raw_key})

    report, exit_code = run_check(root)

    assert exit_code == 0
    assert report["status"] == "PASS"
    assert report["orphan_keys"] == []


def test_run_check_fails_for_orphan_history_backed_key(temp_repo: Path) -> None:
    root = _make_repo(
        temp_repo,
        idem_payload={"version": 1, "escrow|10": True},
    )

    report, exit_code = run_check(root)

    assert exit_code == 1
    assert report["status"] == "FAIL"
    assert report["orphan_keys"] == ["escrow|10"]


def test_run_check_fails_when_history_directory_is_missing(temp_repo: Path) -> None:
    root = _make_repo(
        temp_repo,
        idem_payload={"version": 1, "escrow|10": True},
    )
    shutil.rmtree(root / "ledger" / "history")

    report, exit_code = run_check(root)

    assert exit_code == 1
    assert report["orphan_keys"] == ["escrow|10"]


def test_main_prints_pass_json(temp_repo: Path, capsys) -> None:
    root = _make_repo(
        temp_repo,
        idem_payload={"version": 1, "escrow|10": True},
    )
    _write_history(root, "2026-04-21.jsonl", {"type": "escrow", "idem_key": "escrow|10"})

    exit_code = main(["--root", str(root)])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["status"] == "PASS"
    assert payload["orphan_keys"] == []


def test_cli_returns_exit_one_and_lists_orphans(temp_repo: Path) -> None:
    root = _make_repo(
        temp_repo,
        idem_payload={
            "version": 1,
            "register|alice@test": True,
            "escrow|10": True,
        },
    )

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root)],
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(result.stdout)
    assert result.returncode == 1
    assert payload["status"] == "FAIL"
    assert payload["orphan_keys"] == ["escrow|10"]


def test_cli_returns_exit_two_for_corrupt_idem_keys_json(temp_repo: Path) -> None:
    root = _make_repo(temp_repo, idem_payload={"version": 1})
    (root / "ledger" / "idem_keys.json").write_text("{broken json", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "failed to parse" in result.stderr
