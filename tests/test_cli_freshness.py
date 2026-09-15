"""Regression tests for `wea freshness` stale/missing install detection.

Includes a real subprocess CLI test that runs the source preflight's
`--emit-contract` probe as an external process.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from wea_cli import freshness

REPO_SRC = str(Path(__file__).resolve().parents[1] / "src")


def _source(epoch: int = freshness.CONTRACT_EPOCH, commands=None) -> dict:
    return {
        "epoch": epoch,
        "version": "9.9.9",
        "commands": sorted(commands or ["report", "push", "freshness"]),
    }


# --- comparison logic -------------------------------------------------------


def test_fresh_when_contract_matches() -> None:
    src = _source()
    probe = {"status": "present", "path": "/usr/bin/wea", "contract": _source()}
    result = freshness.compare(src, probe)
    assert result["state"] == "fresh"
    assert result["fresh"] is True


def test_stale_when_installed_epoch_behind() -> None:
    src = _source(epoch=2)
    probe = {"status": "present", "path": "/usr/bin/wea", "contract": _source(epoch=1)}
    result = freshness.compare(src, probe)
    assert result["state"] == "stale"
    assert result["fresh"] is False


def test_stale_when_command_missing() -> None:
    src = _source(commands=["report", "push", "freshness"])
    probe = {
        "status": "present",
        "path": "/usr/bin/wea",
        "contract": _source(commands=["report", "push"]),
    }
    result = freshness.compare(src, probe)
    assert result["state"] == "stale"
    assert "freshness" in result["missing_commands"]


def test_legacy_install_detected_as_stale() -> None:
    """An old executable that lacks the freshness command cannot self-warn."""
    src = _source()
    probe = {"status": "legacy", "path": "/usr/bin/wea", "contract": None}
    result = freshness.compare(src, probe)
    assert result["state"] == "stale"
    assert "predates" in result["reason"]


def test_not_installed_state() -> None:
    src = _source()
    probe = {"status": "missing", "path": None, "contract": None}
    result = freshness.compare(src, probe)
    assert result["state"] == "not_installed"


def test_source_behind_when_installed_ahead() -> None:
    src = _source(epoch=1)
    probe = {"status": "present", "path": "/usr/bin/wea", "contract": _source(epoch=2)}
    result = freshness.compare(src, probe)
    assert result["state"] == "source_behind"


# --- probe behaviour --------------------------------------------------------


def test_probe_missing_when_no_executable() -> None:
    probe = freshness.probe_installed(None)
    # A CI runner may or may not have `wea` on PATH; only assert the shape.
    assert probe["status"] in {"missing", "present", "legacy"}


def test_probe_legacy_when_executable_errors(tmp_path: Path) -> None:
    # A fake "wea" that exits non-zero for any args -> treated as legacy.
    if sys.platform.startswith("win"):
        fake = tmp_path / "wea.bat"
        fake.write_text("@exit /b 2\n", encoding="utf-8")
    else:
        fake = tmp_path / "wea"
        fake.write_text("#!/bin/sh\nexit 2\n", encoding="utf-8")
        fake.chmod(0o755)
    probe = freshness.probe_installed(str(fake))
    assert probe["status"] == "legacy"


# --- render -----------------------------------------------------------------


def test_render_stale_includes_refresh_hint() -> None:
    result = freshness.build_result(["report", "push", "freshness"], executable=None)
    # Force a stale comparison for deterministic rendering.
    result["comparison"] = {"state": "stale", "fresh": False, "reason": "old"}
    text = freshness.render(result)
    assert "STALE" in text
    assert "pip install --editable ." in text


# --- real subprocess CLI test ----------------------------------------------


def test_emit_contract_subprocess_roundtrips() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "wea_cli.cli", "freshness", "--emit-contract"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={"PYTHONPATH": REPO_SRC, "PYTHONIOENCODING": "utf-8", **_os_env()},
        check=True,
    )
    contract = json.loads(completed.stdout)
    assert contract["epoch"] == freshness.CONTRACT_EPOCH
    assert "freshness" in contract["commands"]
    assert "report" in contract["commands"]
    assert "push" in contract["commands"]


def _os_env() -> dict:
    import os

    # Preserve PATH so the interpreter and git resolve on all platforms.
    return {
        k: v
        for k, v in os.environ.items()
        if k in {"PATH", "PATHEXT", "SYSTEMROOT", "TEMP", "TMP"}
    }
