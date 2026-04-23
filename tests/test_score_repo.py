"""Tests for scripts/score_repo.py — zone template detection and module grammar scoring."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Module import
# ---------------------------------------------------------------------------

_MODULE_PATH = Path(__file__).resolve().parent.parent / "scripts" / "score_repo.py"
_SPEC = importlib.util.spec_from_file_location("score_repo", _MODULE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)

scan_zone = _MOD.scan_zone
score_module_grammar = _MOD.score_module_grammar
build_checkpoint = _MOD.build_checkpoint
TEMPLATE_FILENAME = _MOD.TEMPLATE_FILENAME


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


_TEMPLATE_SCRIPTS = """\
version: 1
zone: scripts
shape:
  required:
    - module_docstring
    - functions
    - main_guard
  optional:
    - shebang
    - future_annotations
  forbidden: []
"""

_TEMPLATE_WEA_CLI = """\
version: 1
zone: src_wea_cli
shape:
  required:
    - module_docstring
    - future_annotations
    - functions
  optional:
    - classes
  forbidden:
    - main_guard
"""

_CONFORMANT_SCRIPT = '''\
"""A conformant script."""

def run():
    pass

if __name__ == "__main__":
    run()
'''

_NON_CONFORMANT_SCRIPT = '''\
# no docstring, no main guard
x = 1
'''

_CONFORMANT_CLI_MODULE = '''\
"""A conformant CLI module."""

from __future__ import annotations


def do_thing() -> None:
    pass
'''


# ---------------------------------------------------------------------------
# scan_zone — template detection
# ---------------------------------------------------------------------------

def test_scan_zone_template_absent(tmp_path: Path) -> None:
    zone = tmp_path / "scripts"
    zone.mkdir()
    _write(zone / "foo.py", _CONFORMANT_SCRIPT)

    result = scan_zone(tmp_path, "scripts")

    assert result["template_declared"] is False
    assert result["template_path"] is None
    assert result["declared_shape"] is None
    assert result["conformant_count"] is None


def test_scan_zone_template_declared(tmp_path: Path) -> None:
    zone = tmp_path / "scripts"
    zone.mkdir()
    _write(zone / TEMPLATE_FILENAME, _TEMPLATE_SCRIPTS)
    _write(zone / "foo.py", _CONFORMANT_SCRIPT)

    result = scan_zone(tmp_path, "scripts")

    assert result["template_declared"] is True
    assert result["template_path"] == f"scripts/{TEMPLATE_FILENAME}"
    assert result["declared_shape"] is not None
    assert "module_docstring" in result["declared_shape"]["required"]
    assert "functions" in result["declared_shape"]["required"]
    assert "main_guard" in result["declared_shape"]["required"]


def test_scan_zone_nonexistent_zone(tmp_path: Path) -> None:
    result = scan_zone(tmp_path, "nonexistent")

    assert result["template_declared"] is False
    assert result["file_count"] == 0


# ---------------------------------------------------------------------------
# scan_zone — conformance counting
# ---------------------------------------------------------------------------

def test_scan_zone_conformant_file_counted(tmp_path: Path) -> None:
    zone = tmp_path / "scripts"
    zone.mkdir()
    _write(zone / TEMPLATE_FILENAME, _TEMPLATE_SCRIPTS)
    _write(zone / "good.py", _CONFORMANT_SCRIPT)
    _write(zone / "bad.py", _NON_CONFORMANT_SCRIPT)

    result = scan_zone(tmp_path, "scripts")

    assert result["file_count"] == 2
    assert result["conformant_count"] == 1
    assert result["module_grammar_uniformity"] == 0.5


def test_scan_zone_all_conformant(tmp_path: Path) -> None:
    zone = tmp_path / "scripts"
    zone.mkdir()
    _write(zone / TEMPLATE_FILENAME, _TEMPLATE_SCRIPTS)
    _write(zone / "a.py", _CONFORMANT_SCRIPT)
    _write(zone / "b.py", _CONFORMANT_SCRIPT)

    result = scan_zone(tmp_path, "scripts")

    assert result["conformant_count"] == 2
    assert result["module_grammar_uniformity"] == 1.0


def test_scan_zone_cli_module_required_fields(tmp_path: Path) -> None:
    zone = tmp_path / "src" / "wea_cli"
    zone.mkdir(parents=True)
    _write(zone / TEMPLATE_FILENAME, _TEMPLATE_WEA_CLI)
    _write(zone / "module.py", _CONFORMANT_CLI_MODULE)
    _write(zone / "missing_future.py", '"""No future."""\ndef f(): pass\n')

    result = scan_zone(tmp_path, "src/wea_cli")

    assert result["template_declared"] is True
    assert result["conformant_count"] == 1
    assert result["module_grammar_uniformity"] == 0.5


# ---------------------------------------------------------------------------
# score_module_grammar — declared score
# ---------------------------------------------------------------------------

def test_score_both_templates_present(tmp_path: Path) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    _write(scripts / TEMPLATE_FILENAME, _TEMPLATE_SCRIPTS)

    cli = tmp_path / "src" / "wea_cli"
    cli.mkdir(parents=True)
    _write(cli / TEMPLATE_FILENAME, _TEMPLATE_WEA_CLI)

    result = score_module_grammar(tmp_path)

    assert result["declared"] == 3
    assert result["zones"]["scripts"]["template_declared"] is True
    assert result["zones"]["src_wea_cli"]["template_declared"] is True


def test_score_no_templates(tmp_path: Path) -> None:
    (tmp_path / "scripts").mkdir()
    (tmp_path / "src" / "wea_cli").mkdir(parents=True)

    result = score_module_grammar(tmp_path)

    assert result["declared"] == 2
    assert result["zones"]["scripts"]["template_declared"] is False
    assert result["zones"]["src_wea_cli"]["template_declared"] is False


def test_score_partial_templates(tmp_path: Path) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    _write(scripts / TEMPLATE_FILENAME, _TEMPLATE_SCRIPTS)
    (tmp_path / "src" / "wea_cli").mkdir(parents=True)

    result = score_module_grammar(tmp_path)

    # Only one zone declared → still partial
    assert result["declared"] == 2


# ---------------------------------------------------------------------------
# build_checkpoint — output structure
# ---------------------------------------------------------------------------

def test_build_checkpoint_structure(tmp_path: Path) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    _write(scripts / TEMPLATE_FILENAME, _TEMPLATE_SCRIPTS)
    cli = tmp_path / "src" / "wea_cli"
    cli.mkdir(parents=True)
    _write(cli / TEMPLATE_FILENAME, _TEMPLATE_WEA_CLI)

    cp = build_checkpoint(tmp_path, "test", "2026-04-23", "abc1234")

    assert cp["scan_date"] == "2026-04-23"
    assert cp["repo_sha"] == "abc1234"
    assert cp["target"] == "test"
    mg = cp["structural"]["module_grammar"]
    assert mg["declared"] == 3
    assert "zones" in mg["raw"]


def test_build_checkpoint_json_serialisable(tmp_path: Path) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    cli = tmp_path / "src" / "wea_cli"
    cli.mkdir(parents=True)

    cp = build_checkpoint(tmp_path, "wea", "2026-04-23", "c07e079")
    # Should not raise
    text = json.dumps(cp, indent=2)
    assert '"scan_date"' in text


# ---------------------------------------------------------------------------
# Integration: actual repo detects both templates
# ---------------------------------------------------------------------------

def test_actual_repo_has_both_templates_declared() -> None:
    """Running against the real repo root must detect templates in both zones."""
    repo_root = Path(__file__).resolve().parent.parent
    result = score_module_grammar(repo_root)

    scripts_zone = result["zones"]["scripts"]
    cli_zone = result["zones"]["src_wea_cli"]

    assert scripts_zone["template_declared"] is True, (
        "scripts/.zone-template.yaml not found — template must be declared"
    )
    assert cli_zone["template_declared"] is True, (
        "src/wea_cli/.zone-template.yaml not found — template must be declared"
    )
    assert result["declared"] == 3


def test_actual_repo_conformance_above_baseline() -> None:
    """Declared-template conformance rate should exceed the baseline dominant shape shares."""
    repo_root = Path(__file__).resolve().parent.parent
    result = score_module_grammar(repo_root)

    scripts_u = result["zones"]["scripts"]["module_grammar_uniformity"]
    cli_u = result["zones"]["src_wea_cli"]["module_grammar_uniformity"]

    # Required-field conformance should be well above the old empirical dominant share
    assert scripts_u is not None and scripts_u >= 0.78, (
        f"scripts conformance {scripts_u} below baseline dominant share 0.783582"
    )
    assert cli_u is not None and cli_u >= 0.60, (
        f"src/wea_cli conformance {cli_u} below baseline dominant share 0.65"
    )
