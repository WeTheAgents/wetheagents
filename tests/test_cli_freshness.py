"""Regression tests for `wea freshness` stale/missing install detection.

Covers the content-fingerprint comparison (an older runtime with the same
command names must be STALE) and a real subprocess CLI test for the probe.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from wea_cli import freshness

REPO_SRC = str(Path(__file__).resolve().parents[1] / "src")


def _contract(
    *,
    epoch: int = freshness.CONTRACT_EPOCH,
    commands=None,
    fingerprint: str | None = "fp-src",
) -> dict:
    return {
        "epoch": epoch,
        "version": "9.9.9",
        "commands": sorted(commands or ["report", "push", "freshness"]),
        "fingerprint": fingerprint,
    }


# --- comparison logic -------------------------------------------------------


def test_fresh_when_fingerprints_match() -> None:
    src = _contract(fingerprint="same")
    probe = {
        "status": "present",
        "path": "/usr/bin/wea",
        "contract": _contract(fingerprint="same"),
    }
    result = freshness.compare(src, probe)
    assert result["state"] == "fresh"
    assert result["fresh"] is True


def test_stale_when_runtime_bytes_differ_same_commands() -> None:
    """Same command names + same epoch, but older shipped bytes -> STALE."""
    src = _contract(fingerprint="checkout-aaaa")
    probe = {
        "status": "present",
        "path": "/usr/bin/wea",
        "contract": _contract(fingerprint="installed-bbbb"),
    }
    result = freshness.compare(src, probe)
    assert result["state"] == "stale"
    assert "bytes differ" in result["reason"]


def test_stale_when_installed_epoch_behind_without_fingerprint() -> None:
    src = _contract(epoch=2, fingerprint=None)
    probe = {
        "status": "present",
        "path": "/usr/bin/wea",
        "contract": _contract(epoch=1, fingerprint=None),
    }
    result = freshness.compare(src, probe)
    assert result["state"] == "stale"


def test_stale_when_command_missing_without_fingerprint() -> None:
    src = _contract(commands=["report", "push", "freshness"], fingerprint=None)
    probe = {
        "status": "present",
        "path": "/usr/bin/wea",
        "contract": _contract(commands=["report", "push"], fingerprint=None),
    }
    result = freshness.compare(src, probe)
    assert result["state"] == "stale"
    assert "freshness" in result["missing_commands"]


def test_legacy_install_detected_as_stale() -> None:
    """An old executable that lacks the freshness command cannot self-warn."""
    src = _contract()
    probe = {"status": "legacy", "path": "/usr/bin/wea", "contract": None}
    result = freshness.compare(src, probe)
    assert result["state"] == "stale"
    assert "predates" in result["reason"]


def test_not_installed_state() -> None:
    src = _contract()
    probe = {"status": "missing", "path": None, "contract": None}
    result = freshness.compare(src, probe)
    assert result["state"] == "not_installed"


def test_source_behind_when_installed_ahead_without_fingerprint() -> None:
    src = _contract(epoch=1, fingerprint=None)
    probe = {
        "status": "present",
        "path": "/usr/bin/wea",
        "contract": _contract(epoch=2, fingerprint=None),
    }
    result = freshness.compare(src, probe)
    assert result["state"] == "source_behind"


def test_missing_source_fingerprint_never_certifies_fresh() -> None:
    """Equal epoch/commands but no source fingerprint must not report fresh."""
    src = _contract(fingerprint=None)
    probe = {
        "status": "present",
        "path": "/usr/bin/wea",
        "contract": _contract(fingerprint="installed-real"),
    }
    result = freshness.compare(src, probe)
    assert result["state"] == "unknown"
    assert result["fresh"] is False


def test_missing_installed_fingerprint_never_certifies_fresh() -> None:
    """Equal epoch/commands but no installed fingerprint must not report fresh."""
    src = _contract(fingerprint="checkout-real")
    probe = {
        "status": "present",
        "path": "/usr/bin/wea",
        "contract": _contract(fingerprint=None),
    }
    result = freshness.compare(src, probe)
    assert result["state"] == "unknown"
    assert result["fresh"] is False


def test_both_fingerprints_missing_never_certifies_fresh() -> None:
    src = _contract(fingerprint=None)
    probe = {
        "status": "present",
        "path": "/usr/bin/wea",
        "contract": _contract(fingerprint=None),
    }
    result = freshness.compare(src, probe)
    assert result["state"] == "unknown"
    assert result["fresh"] is False


# --- fingerprint over shipped files -----------------------------------------


def _make_src_tree(root: Path, *, cli_body: str, engine_body: str) -> Path:
    src = root / "src"
    (src / "wea_cli").mkdir(parents=True)
    (src / "wea_cli" / "cli.py").write_text(cli_body, encoding="utf-8")
    # sibling protocol package: engine.py + executors/ marker
    proto = src / "wea_proto"
    (proto / "executors").mkdir(parents=True)
    (proto / "engine.py").write_text(engine_body, encoding="utf-8")
    (proto / "executors" / "manifest.json").write_text('{"v": 1}', encoding="utf-8")
    return src


def test_fingerprint_changes_when_a_byte_changes(tmp_path: Path) -> None:
    a = tmp_path / "a"
    _make_src_tree(a, cli_body="print(1)\n", engine_body="X = 1\n")
    b = tmp_path / "b"
    _make_src_tree(b, cli_body="print(1)\n", engine_body="X = 2\n")  # one byte differs
    fa = freshness.fingerprint(a / "src")
    fb = freshness.fingerprint(b / "src")
    assert fa and fb and fa != fb


def test_fingerprint_matches_identical_trees(tmp_path: Path) -> None:
    a = tmp_path / "a"
    _make_src_tree(a, cli_body="print(1)\n", engine_body="X = 1\n")
    b = tmp_path / "b"
    _make_src_tree(b, cli_body="print(1)\n", engine_body="X = 1\n")
    assert freshness.fingerprint(a / "src") == freshness.fingerprint(b / "src")


def test_fingerprint_none_when_no_packages(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    assert freshness.fingerprint(tmp_path / "src") is None


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


# --- build_result integration ----------------------------------------------


def _fake_wea(tmp_path: Path, contract: dict) -> str:
    # Emit the contract from a file to avoid shell quoting differences.
    contract_file = tmp_path / "contract.json"
    contract_file.write_text(json.dumps(contract), encoding="utf-8")
    if sys.platform.startswith("win"):
        fake = tmp_path / "wea.bat"
        fake.write_text(f'@type "{contract_file}"\n', encoding="utf-8")
    else:
        fake = tmp_path / "wea"
        fake.write_text(f'#!/bin/sh\ncat "{contract_file}"\n', encoding="utf-8")
        fake.chmod(0o755)
    return str(fake)


def test_build_result_stale_when_installed_bytes_differ(tmp_path: Path) -> None:
    checkout = tmp_path / "co"
    _make_src_tree(checkout, cli_body="print('new')\n", engine_body="X = 1\n")
    installed = {
        "epoch": freshness.CONTRACT_EPOCH,
        "version": "0.2.0",
        "commands": sorted(["report", "push", "freshness"]),
        "fingerprint": "totally-different-installed",
    }
    exe = _fake_wea(tmp_path, installed)
    result = freshness.build_result(["report", "push", "freshness"], checkout, exe)
    assert result["comparison"]["state"] == "stale"
    assert result["source_contract"]["fingerprint"]


def test_build_result_fresh_when_installed_matches_checkout(tmp_path: Path) -> None:
    checkout = tmp_path / "co"
    _make_src_tree(checkout, cli_body="print('x')\n", engine_body="X = 1\n")
    fp = freshness.fingerprint(checkout / "src")
    installed = {
        "epoch": freshness.CONTRACT_EPOCH,
        "version": "0.2.0",
        "commands": sorted(["report", "push", "freshness"]),
        "fingerprint": fp,
    }
    exe = _fake_wea(tmp_path, installed)
    result = freshness.build_result(["report", "push", "freshness"], checkout, exe)
    assert result["comparison"]["state"] == "fresh"


# --- render -----------------------------------------------------------------


def test_render_stale_includes_refresh_hint(tmp_path: Path) -> None:
    checkout = tmp_path / "co"
    _make_src_tree(checkout, cli_body="print('x')\n", engine_body="X = 1\n")
    result = freshness.build_result(["report", "push", "freshness"], checkout, None)
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
    # The running installation fingerprint is present (real shipped bytes).
    assert contract["fingerprint"]


def _os_env() -> dict:
    import os

    # Preserve PATH so the interpreter and git resolve on all platforms.
    return {
        k: v
        for k, v in os.environ.items()
        if k in {"PATH", "PATHEXT", "SYSTEMROOT", "TEMP", "TMP"}
    }
