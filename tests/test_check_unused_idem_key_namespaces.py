from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.check_unused_idem_key_namespaces import (
    SHA256_NAMESPACE,
    build_namespace_report,
    extract_namespace,
    load_recorded_idem_keys,
    main,
    run_check,
)

SCRIPT = (
    Path(__file__).resolve().parent.parent
    / "scripts"
    / "check_unused_idem_key_namespaces.py"
)


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _make_repo(
    root: Path,
    *,
    idem_keys: dict[str, object] | None = None,
    top_level: dict[str, object] | None = None,
) -> Path:
    payload: dict[str, object] = {"version": 5, "keys": idem_keys or {}}
    if top_level:
        payload.update(top_level)
    _write_json(root / "ledger" / "idem_keys.json", payload)
    return root


def test_load_recorded_idem_keys_reads_nested_and_top_level(temp_repo: Path) -> None:
    root = _make_repo(
        temp_repo,
        idem_keys={"payment|7|alice@test": "2026-04-21T10:00:00Z"},
        top_level={"escrow-return-cycle17-700": "2026-04-21T10:01:00Z"},
    )

    keys = load_recorded_idem_keys(root / "ledger" / "idem_keys.json")

    assert sorted(keys) == ["escrow-return-cycle17-700", "payment|7|alice@test"]


def test_load_recorded_idem_keys_rejects_non_object_keys_field(temp_repo: Path) -> None:
    _write_json(root := temp_repo / "ledger" / "idem_keys.json", {"keys": []})

    with pytest.raises(ValueError, match="field 'keys' must be an object"):
        load_recorded_idem_keys(root)


def test_extract_namespace_from_pipe_key() -> None:
    assert extract_namespace("hello_world|gemini-4@google") == "hello_world"


def test_extract_namespace_from_four_segment_trajectory_key() -> None:
    assert extract_namespace("trajectory_mint|T5|12|Codex-2@codex") == "trajectory_mint"


def test_extract_namespace_from_underscore_key() -> None:
    assert extract_namespace("escrow_create_700_t1_gauntlet") == "escrow_create"


def test_extract_namespace_from_dashed_cycle_key() -> None:
    assert extract_namespace("escrow-return-cycle17-700") == "escrow-return-cycle"


def test_extract_namespace_from_sha256_hash() -> None:
    assert (
        extract_namespace(
            "30c1b897d9132a8e3cfebc0ae11f6332861a3bce12ba5354420e19aae469ff50"
        )
        == SHA256_NAMESPACE
    )


def test_extract_namespace_supports_valid_bare_namespace() -> None:
    assert extract_namespace("cleanup") == "cleanup"


def test_extract_namespace_returns_none_for_unclassifiable_key() -> None:
    assert extract_namespace("totally-random-key") is None


def test_build_namespace_report_passes_for_recognized_mix() -> None:
    report = build_namespace_report(
        [
            "payment|7|alice@test",
            "verify|7|alice@test",
            "escrow-return-cycle17-700",
            "escrow_create_700_t1_gauntlet",
            "trajectory_mint|T5|12|Codex-2@codex",
            "30c1b897d9132a8e3cfebc0ae11f6332861a3bce12ba5354420e19aae469ff50",
        ]
    )

    assert report["status"] == "PASS"
    assert report["summary"]["unrecognized_namespace_buckets"] == 0
    assert "payment" in report["used_namespaces"]
    assert "verify" in report["used_namespaces"]


def test_build_namespace_report_flags_unknown_pipe_namespace() -> None:
    report = build_namespace_report(["mystery|7|alice@test"])

    assert report["status"] == "FAIL"
    assert report["unrecognized_namespaces"] == [
        {
            "namespace": "mystery",
            "count": 1,
            "examples": ["mystery|7|alice@test"],
        }
    ]


def test_build_namespace_report_flags_unknown_underscore_namespace() -> None:
    report = build_namespace_report(["mystery_key_7_alice@test"])

    assert report["status"] == "FAIL"
    assert report["unrecognized_namespaces"] == [
        {
            "namespace": "mystery_key",
            "count": 1,
            "examples": ["mystery_key_7_alice@test"],
        }
    ]


def test_build_namespace_report_flags_unclassifiable_key() -> None:
    report = build_namespace_report(["totally-random-key"])

    assert report["status"] == "FAIL"
    assert report["unrecognized_namespaces"] == [
        {
            "namespace": None,
            "count": 1,
            "examples": ["totally-random-key"],
        }
    ]


def test_build_namespace_report_tracks_unused_known_namespaces() -> None:
    report = build_namespace_report(["payment|7|alice@test"])

    assert report["status"] == "PASS"
    assert "payment" in report["used_namespaces"]
    assert "verify" in report["unused_known_namespaces"]
    assert "reject" in report["unused_known_namespaces"]
    assert "payment" not in report["unused_known_namespaces"]


def test_run_check_reads_top_level_and_nested_keys(temp_repo: Path) -> None:
    root = _make_repo(
        temp_repo,
        idem_keys={"payment|7|alice@test": "2026-04-21T10:00:00Z"},
        top_level={"escrow-return-cycle17-700": "2026-04-21T10:01:00Z"},
    )

    report, exit_code = run_check(root)

    assert exit_code == 0
    assert report["status"] == "PASS"
    counts = {item["namespace"]: item["count"] for item in report["namespace_counts"]}
    assert counts["payment"] == 1
    assert counts["escrow-return-cycle"] == 1


def test_run_check_accepts_sha256_hash_key_entries(temp_repo: Path) -> None:
    root = _make_repo(
        temp_repo,
        idem_keys={
            "30c1b897d9132a8e3cfebc0ae11f6332861a3bce12ba5354420e19aae469ff50": {
                "action": "verification",
                "agent": "alice@test",
                "issue": "7",
            }
        },
    )

    report, exit_code = run_check(root)

    assert exit_code == 0
    assert report["status"] == "PASS"
    counts = {item["namespace"]: item["count"] for item in report["namespace_counts"]}
    assert counts[SHA256_NAMESPACE] == 1


def test_run_check_fails_for_unrecognized_top_level_namespace(temp_repo: Path) -> None:
    root = _make_repo(
        temp_repo,
        top_level={"mystery|7|alice@test": "2026-04-21T10:00:00Z"},
    )

    report, exit_code = run_check(root)

    assert exit_code == 1
    assert report["status"] == "FAIL"
    assert report["unrecognized_namespaces"][0]["namespace"] == "mystery"


def test_main_prints_json_report(temp_repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _make_repo(temp_repo, idem_keys={"payment|7|alice@test": "2026-04-21T10:00:00Z"})

    exit_code = main(["--root", str(root)])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["status"] == "PASS"
    assert payload["summary"]["recognized_namespaces_seen"] == 1


def test_cli_returns_exit_one_for_unrecognized_namespace(temp_repo: Path) -> None:
    root = _make_repo(temp_repo, idem_keys={"mystery|7|alice@test": "2026-04-21T10:00:00Z"})

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root)],
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(result.stdout)
    assert result.returncode == 1
    assert payload["status"] == "FAIL"
    assert payload["unrecognized_namespaces"][0]["namespace"] == "mystery"


def test_cli_returns_exit_two_on_corrupt_json(temp_repo: Path) -> None:
    (temp_repo / "ledger" / "idem_keys.json").write_text("{broken json", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(temp_repo)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert "failed to parse idem_keys.json" in result.stderr
