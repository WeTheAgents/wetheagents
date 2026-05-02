"""Tests for scripts/circle1/observability_inventory.py."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

from scripts.circle1.observability_inventory import scan_observability


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content), encoding="utf-8")
    return path


def _temp_scripts_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    return root


def _channels_for(report: dict, rel_path: str) -> list[dict]:
    for entry in report["files"]:
        if entry["path"] == rel_path:
            return entry["channels"]
    raise AssertionError(f"{rel_path} not found in report")


def _channel_names(channels: list[dict]) -> set[str]:
    return {item["channel"] for item in channels}


def test_detects_required_channel_families(tmp_path: Path) -> None:
    root = _temp_scripts_repo(tmp_path)
    _write(
        root / "scripts" / "sample.py",
        """
        from __future__ import annotations

        import json
        import logging
        import subprocess
        import sys
        from pathlib import Path

        def main() -> None:
            print("human output")
            print("bad", file=sys.stderr)
            logging.info("diagnostic")
            Path("reports/out.json").write_text(json.dumps({"ok": True}))
            subprocess.run(["python", "-m", "tool"], check=True)
            Path("ledger/balances.json").write_text("{}")
        """,
    )

    report = scan_observability(root, scan_date="2026-05-02")
    channels = _channels_for(report, "scripts/sample.py")
    names = _channel_names(channels)

    assert "stdout_cli_output" in names
    assert "stderr_output" in names
    assert "logging" in names
    assert "file_artifact_write" in names
    assert "subprocess_launch" in names
    assert "ledger_or_protocol_write_candidate" in names

    for detection in channels:
        assert detection["reason"]
        assert detection["evidence"]
        assert {"line", "col", "symbol", "snippet"} <= set(detection["evidence"][0])


def test_detects_github_network_and_ambiguous_channels(tmp_path: Path) -> None:
    root = _temp_scripts_repo(tmp_path)
    _write(
        root / "scripts" / "githuby.py",
        """
        from __future__ import annotations

        import requests
        import subprocess

        def publish(writer, action):
            subprocess.run(["gh", "issue", "comment", "884", "--body", "done"])
            requests.post("https://api.github.com/repos/WeTheAgents/wetheagents/issues/884/comments")
            writer.write("maybe a file, maybe a stream")
            getattr(writer, action)("dynamic")
        """,
    )

    report = scan_observability(root)
    names = _channel_names(_channels_for(report, "scripts/githuby.py"))

    assert "github_comment_side_effect_candidate" in names
    assert "network_external_call" in names
    assert "unknown_ambiguous_side_effect" in names


def test_ledger_write_detection_uses_simple_path_bindings(tmp_path: Path) -> None:
    root = _temp_scripts_repo(tmp_path)
    _write(
        root / "scripts" / "ledger_writer.py",
        """
        from __future__ import annotations

        from pathlib import Path

        LEDGER = Path(".") / "ledger"

        def save(path, payload):
            path.write_text(payload)

        def main(root: Path) -> None:
            bal_path = root / "ledger" / "balances.json"
            bal_path.write_text("{}")
            save(LEDGER / "escrows.json", "{}")
        """,
    )

    report = scan_observability(root)
    channels = _channels_for(report, "scripts/ledger_writer.py")
    ledger_detections = [
        item
        for item in channels
        if item["channel"] == "ledger_or_protocol_write_candidate"
    ]

    assert len(ledger_detections) == 2
    assert any("write call targets" in item["reason"] for item in ledger_detections)
    assert any("helper call targets" in item["reason"] for item in ledger_detections)


def test_ledger_detection_uses_write_target_not_payload_or_bare_history(
    tmp_path: Path,
) -> None:
    root = _temp_scripts_repo(tmp_path)
    _write(
        root / "scripts" / "release_notes.py",
        """
        from __future__ import annotations

        from pathlib import Path

        def main() -> None:
            Path("notes.md").write_text("operator note mentions ledger/balances.json")
            Path("docs/release_history.md").write_text("ordinary release notes")
            Path("commit_history.json").write_text("{}")
        """,
    )

    report = scan_observability(root)
    channels = _channels_for(report, "scripts/release_notes.py")

    assert "file_artifact_write" in _channel_names(channels)
    assert "ledger_or_protocol_write_candidate" not in _channel_names(channels)


def test_import_aliases_and_direct_subprocess_imports_are_detected(
    tmp_path: Path,
) -> None:
    root = _temp_scripts_repo(tmp_path)
    _write(
        root / "scripts" / "aliases.py",
        """
        from __future__ import annotations

        import logging as L
        import subprocess as sp
        import sys as s
        from subprocess import Popen, call, check_call, check_output, run

        def main() -> None:
            s.stdout.write("ok")
            s.stderr.write("bad")
            L.info("diagnostic")
            sp.run(["python", "-m", "tool"], check=True)
            run([
                "gh",
                "issue",
                "list",
            ])
            check_call(["gh", "pr", "review", "--comment"])
            check_output(["python", "--version"])
            call("gh issue view 884", shell=True)
            Popen(["python", "--version"])
        """,
    )

    report = scan_observability(root)
    channels = _channels_for(report, "scripts/aliases.py")
    names = _channel_names(channels)
    gh_detections = [
        item
        for item in channels
        if item["channel"] == "github_comment_side_effect_candidate"
    ]
    subprocess_detections = [
        item for item in channels if item["channel"] == "subprocess_launch"
    ]
    multiline_snippets = [
        item["evidence"][0]["snippet"]
        for item in channels
        if item["evidence"] and item["evidence"][0]["symbol"] == "subprocess.run"
    ]

    assert {"stdout_cli_output", "stderr_output", "logging"} <= names
    assert len(subprocess_detections) == 6
    assert len(gh_detections) == 3
    assert any("gh" in snippet and "issue" in snippet for snippet in multiline_snippets)


def test_unresolved_write_is_ambiguous_not_artifact_write(tmp_path: Path) -> None:
    root = _temp_scripts_repo(tmp_path)
    _write(
        root / "scripts" / "writer.py",
        """
        from __future__ import annotations

        def main(writer) -> None:
            writer.write("maybe file, maybe stream")
        """,
    )

    report = scan_observability(root)
    channels = _channels_for(report, "scripts/writer.py")
    names = _channel_names(channels)

    assert "unknown_ambiguous_side_effect" in names
    assert "file_artifact_write" not in names


def test_uppercase_loggers_are_detected(tmp_path: Path) -> None:
    root = _temp_scripts_repo(tmp_path)
    _write(
        root / "scripts" / "uppercase_logger.py",
        """
        from __future__ import annotations

        import logging

        LOGGER = logging.getLogger(__name__)
        LOG = logging.getLogger("script")

        def main() -> None:
            LOGGER.info("diagnostic")
            LOG.error("problem")
        """,
    )

    report = scan_observability(root)
    channels = _channels_for(report, "scripts/uppercase_logger.py")
    logging_detections = [item for item in channels if item["channel"] == "logging"]

    assert len(logging_detections) == 4


def test_recursive_scan_and_init_exclusion_are_explicit(tmp_path: Path) -> None:
    root = _temp_scripts_repo(tmp_path)
    _write(root / "scripts" / "__init__.py", "print('package marker')\n")
    _write(root / "scripts" / "nested" / "tool.py", "print('nested')\n")

    report = scan_observability(root)
    paths = {entry["path"] for entry in report["files"]}
    skipped = {entry["path"]: entry["reason"] for entry in report["skipped_files"]}

    assert "scripts/nested/tool.py" in paths
    assert "scripts/__init__.py" not in paths
    assert "scripts/__init__.py" in skipped
    assert "__init__.py excluded" in skipped["scripts/__init__.py"]
    assert report["summary"]["skipped_files"] == 1


def test_parse_error_becomes_ambiguous_detection(tmp_path: Path) -> None:
    root = _temp_scripts_repo(tmp_path)
    _write(root / "scripts" / "broken.py", "def nope(:\n")

    report = scan_observability(root)
    entry = next(
        item for item in report["files"] if item["path"] == "scripts/broken.py"
    )

    assert entry["status"] == "parse_error"
    assert entry["channels"][0]["channel"] == "unknown_ambiguous_side_effect"
    assert "AST parse error" in entry["channels"][0]["reason"]


def test_cli_emits_checkpointable_json(tmp_path: Path) -> None:
    root = _temp_scripts_repo(tmp_path)
    _write(root / "scripts" / "tool.py", "print('hello')\n")
    repo_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo_root)

    result = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "circle1" / "observability_inventory.py"),
            "--root",
            str(root),
            "--scan-date",
            "2026-05-02",
        ],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    payload = json.loads(result.stdout)

    assert payload["scan_date"] == "2026-05-02"
    assert payload["summary"]["total_files"] == 1
    assert payload["files"][0]["path"] == "scripts/tool.py"
    assert payload["files"][0]["channels"][0]["channel"] == "stdout_cli_output"
