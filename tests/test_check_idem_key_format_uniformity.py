from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts.check_idem_key_format_uniformity import (
    PIPE_FORMAT,
    UNDERSCORE_FORMAT,
    build_format_report,
    classify_idem_key,
    load_history_idem_keys,
    load_registered_idem_keys,
    main,
    run_check,
)

SCRIPT = (
    Path(__file__).resolve().parent.parent
    / "scripts"
    / "check_idem_key_format_uniformity.py"
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_history(root: Path, filename: str, events: list[dict | object]) -> None:
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
) -> Path:
    root = tmp_path
    payload: dict[str, object] = {"version": 1, "keys": idem_keys or {}}
    if top_level:
        payload.update(top_level)
    _write_json(root / "ledger" / "idem_keys.json", payload)
    (root / "ledger" / "history").mkdir(parents=True, exist_ok=True)
    return root


def test_classify_pipe_key_with_underscores_in_prefix() -> None:
    assert classify_idem_key("hello_world|gemini-4@google") == (
        "hello_world",
        PIPE_FORMAT,
    )


def test_classify_underscore_key_with_multiword_prefix() -> None:
    assert classify_idem_key("escrow_return_486_t3s10_orphan") == (
        "escrow_return",
        UNDERSCORE_FORMAT,
    )


def test_classify_opaque_key_returns_none() -> None:
    assert classify_idem_key(
        "30c1b897d9132a8e3cfebc0ae11f6332861a3bce12ba5354420e19aae469ff50"
    ) == (None, None)


def test_load_registered_idem_keys_reads_nested_and_top_level(temp_repo: Path) -> None:
    root = _make_repo(
        temp_repo,
        idem_keys={"payment|7|alice@test": "2026-04-20T10:00:00Z"},
        top_level={"escrow_return_7_t1s1_orphan": {"timestamp": "2026-04-20T10:01:00Z"}},
    )

    keys = load_registered_idem_keys(root / "ledger" / "idem_keys.json")

    assert sorted(keys) == ["escrow_return_7_t1s1_orphan", "payment|7|alice@test"]


def test_load_history_idem_keys_ignores_invalid_lines(temp_repo: Path) -> None:
    root = _make_repo(temp_repo)
    history_file = root / "ledger" / "history" / "2026-04-20.jsonl"
    history_file.write_text(
        '\n'.join(
            [
                json.dumps({"type": "payment", "idem_key": "payment|1|alice@test"}),
                '{"type": "payment", "idem_key": "broken"',
                json.dumps({"type": "payment"}),
                json.dumps(["not", "a", "dict"]),
                "",
            ]
        ),
        encoding="utf-8",
    )

    keys = load_history_idem_keys(root / "ledger" / "history")

    assert keys == ["payment|1|alice@test"]


def test_build_format_report_flags_mixed_type() -> None:
    report = build_format_report(
        ["payment|7|alice@test", "payment_8_alice@test_legacy"]
    )

    assert report["status"] == "FAIL"
    assert report["summary"]["mixed_types"] == 1
    assert report["mixed_types"][0]["type"] == "payment"
    assert report["mixed_types"][0][PIPE_FORMAT] == 1
    assert report["mixed_types"][0][UNDERSCORE_FORMAT] == 1


def test_build_format_report_passes_when_types_are_uniform() -> None:
    report = build_format_report(
        ["payment|7|alice@test", "payment|8|bob@test", "escrow_return_7_t1s1_orphan"]
    )

    assert report["status"] == "PASS"
    assert report["summary"]["mixed_types"] == 0
    payment = next(
        item for item in report["type_distributions"] if item["type"] == "payment"
    )
    escrow_return = next(
        item
        for item in report["type_distributions"]
        if item["type"] == "escrow_return"
    )
    assert payment[PIPE_FORMAT] == 2
    assert payment[UNDERSCORE_FORMAT] == 0
    assert escrow_return[PIPE_FORMAT] == 0
    assert escrow_return[UNDERSCORE_FORMAT] == 1


def test_build_format_report_deduplicates_same_key() -> None:
    report = build_format_report(
        ["payment|7|alice@test", "payment|7|alice@test", "payment|7|alice@test"]
    )

    payment = next(
        item for item in report["type_distributions"] if item["type"] == "payment"
    )
    assert payment[PIPE_FORMAT] == 3
    assert report["summary"]["observations_checked"] == 3
    assert report["summary"]["unique_keys_checked"] == 1


def test_run_check_reads_history_and_registered_keys(temp_repo: Path) -> None:
    root = _make_repo(
        temp_repo,
        idem_keys={"payment|7|alice@test": "2026-04-20T10:00:00Z"},
    )
    _write_history(
        root,
        "2026-04-20.jsonl",
        [{"type": "escrow_return", "idem_key": "escrow_return_7_t1s1_orphan"}],
    )

    report, exit_code = run_check(root)

    assert exit_code == 0
    assert report["status"] == "PASS"
    types = {item["type"]: item for item in report["type_distributions"]}
    assert types["payment"][PIPE_FORMAT] == 1
    assert types["escrow_return"][UNDERSCORE_FORMAT] == 1


def test_run_check_fails_when_same_type_is_mixed_across_sources(temp_repo: Path) -> None:
    root = _make_repo(
        temp_repo,
        idem_keys={"escrow_return|7|agent0@system": "2026-04-20T10:00:00Z"},
    )
    _write_history(
        root,
        "2026-04-20.jsonl",
        [{"type": "escrow_return", "idem_key": "escrow_return_7_t1s1_orphan"}],
    )

    report, exit_code = run_check(root)

    assert exit_code == 1
    assert report["status"] == "FAIL"
    assert report["mixed_types"][0]["type"] == "escrow_return"


def test_run_check_ignores_unclassified_keys_for_failure(temp_repo: Path) -> None:
    root = _make_repo(
        temp_repo,
        idem_keys={
            "payment|7|alice@test": "2026-04-20T10:00:00Z",
            "30c1b897d9132a8e3cfebc0ae11f6332861a3bce12ba5354420e19aae469ff50": {
                "action": "payment"
            },
        },
    )

    report, exit_code = run_check(root)

    assert exit_code == 0
    assert report["status"] == "PASS"
    assert report["summary"]["unclassified_observations"] == 1


def test_main_prints_json_report(temp_repo: Path, capsys) -> None:
    root = _make_repo(temp_repo, idem_keys={"payment|7|alice@test": "2026-04-20T10:00:00Z"})

    exit_code = main(["--root", str(root)])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["status"] == "PASS"
    assert payload["summary"]["types_checked"] == 1


def test_cli_exit_one_on_mixed_formats(temp_repo: Path) -> None:
    root = _make_repo(
        temp_repo,
        idem_keys={"payment|7|alice@test": "2026-04-20T10:00:00Z"},
    )
    _write_history(
        root,
        "2026-04-20.jsonl",
        [{"type": "payment", "idem_key": "payment_8_alice@test_legacy"}],
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
    assert payload["mixed_types"][0]["type"] == "payment"


def test_cli_exit_zero_on_uniform_formats(temp_repo: Path) -> None:
    root = _make_repo(
        temp_repo,
        idem_keys={"payment|7|alice@test": "2026-04-20T10:00:00Z"},
    )
    _write_history(
        root,
        "2026-04-20.jsonl",
        [{"type": "escrow_return", "idem_key": "escrow_return_7_t1s1_orphan"}],
    )

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root)],
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(result.stdout)
    assert result.returncode == 0
    assert payload["status"] == "PASS"
