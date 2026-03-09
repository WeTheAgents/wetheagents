from __future__ import annotations

import argparse
import builtins
import json
from pathlib import Path

import pytest

from wea_cli import cli


def _make_run_dir(tmp_path: Path, run_id: str = "run_123") -> Path:
    run_dir = tmp_path / ".wea_runs" / run_id
    run_dir.mkdir(parents=True)
    return run_dir


def test_parser_supports_trace_emit_subcommand() -> None:
    parser = cli.build_parser()
    args = parser.parse_args(
        [
            "trace",
            "emit",
            "--run-dir",
            "D:/tmp/.wea_runs/run_123",
            "--event-type",
            "run_started",
            "--source",
            "cli",
            "--payload-json",
            "{\"ok\":true}",
        ]
    )

    assert args.command == "trace"
    assert args.trace_command == "emit"
    assert args.run_dir == "D:/tmp/.wea_runs/run_123"
    assert args.event_type == "run_started"
    assert args.source == "cli"
    assert args.payload_json == "{\"ok\":true}"
    assert args._handler is cli.cmd_trace_emit


def test_cmd_trace_emit_writes_event(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run_dir = _make_run_dir(tmp_path)
    args = argparse.Namespace(
        run_dir=str(run_dir),
        run_id=None,
        event_type="run_started",
        source="cli",
        payload_json='{"command":"demo"}',
        timestamp="2026-03-09T14:00:00Z",
    )

    rc = cli.cmd_trace_emit(args)
    assert rc == cli.EXIT_OK

    out = capsys.readouterr().out.strip()
    payload = json.loads(out)
    assert payload["run_id"] == "run_123"
    assert payload["status"] == "running"
    assert payload["event_count"] == 1


def test_cmd_trace_emit_rejects_invalid_payload_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run_dir = _make_run_dir(tmp_path)
    args = argparse.Namespace(
        run_dir=str(run_dir),
        run_id=None,
        event_type="run_started",
        source="cli",
        payload_json="{bad json",
        timestamp=None,
    )

    rc = cli.cmd_trace_emit(args)
    assert rc == cli.EXIT_RUNTIME_ERROR
    assert "invalid --payload-json" in capsys.readouterr().out


def test_cmd_trace_emit_rejects_missing_directory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = argparse.Namespace(
        run_dir=str(tmp_path / ".wea_runs" / "run_missing"),
        run_id=None,
        event_type="run_started",
        source="cli",
        payload_json="{}",
        timestamp="2026-03-09T14:00:00Z",
    )

    rc = cli.cmd_trace_emit(args)
    assert rc == cli.EXIT_RUNTIME_ERROR
    assert "Run directory not found" in capsys.readouterr().out


def test_cmd_trace_emit_survives_unicode_stdout_encoding_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = _make_run_dir(tmp_path)
    args = argparse.Namespace(
        run_dir=str(run_dir),
        run_id=None,
        event_type="run_started",
        source="cli",
        payload_json='{"message":"привет"}',
        timestamp="2026-03-09T14:00:00Z",
    )
    printed: list[str] = []

    def fake_print(text: str) -> None:
        printed.append(text)
        if len(printed) == 1:
            raise UnicodeEncodeError("cp1252", text, 0, 1, "boom")

    monkeypatch.setattr(builtins, "print", fake_print)

    rc = cli.cmd_trace_emit(args)

    assert rc == cli.EXIT_OK
    assert len(printed) == 2
    payload = json.loads(printed[-1])
    assert payload["last_payload"]["message"] == "привет"
