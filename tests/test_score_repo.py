"""Tests for scripts/score_repo.py and scripts/circle1/zone_template.py."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS = _REPO_ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from circle1.zone_template import (
    compute_conformity,
    is_template_declared,
    known_zones,
    load_zone_template,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_scripts_zone(tmp: Path) -> Path:
    """Create a minimal scripts/ zone with one conforming and one non-conforming file."""
    zone = tmp / "scripts"
    zone.mkdir()
    # Conforming: shebang + docstring + future import + main() + main guard
    (zone / "good.py").write_text(
        '#!/usr/bin/env python3\n"""Good script."""\n\nfrom __future__ import annotations\n\n\ndef main() -> None:\n    pass\n\n\nif __name__ == "__main__":\n    main()\n',
        encoding="utf-8",
    )
    # Non-conforming: missing shebang and main guard
    (zone / "bad.py").write_text(
        '"""Bad script — no shebang, no main guard."""\n\nfrom __future__ import annotations\n\n\ndef run() -> None:\n    pass\n',
        encoding="utf-8",
    )
    return zone


def _make_wea_cli_zone(tmp: Path) -> Path:
    """Create a minimal src/wea_cli/ zone."""
    zone = tmp / "src" / "wea_cli"
    zone.mkdir(parents=True)
    # Conforming: docstring + future import + no shebang
    (zone / "mod.py").write_text(
        '"""Module docstring."""\n\nfrom __future__ import annotations\n\n\ndef do_thing() -> None:\n    pass\n',
        encoding="utf-8",
    )
    # Non-conforming: missing docstring
    (zone / "bare.py").write_text(
        "from __future__ import annotations\n\n\ndef do_thing() -> None:\n    pass\n",
        encoding="utf-8",
    )
    return zone


def _add_templates(tmp: Path) -> None:
    """Copy real zone templates into a fixture repo structure."""
    tmpl_dir = tmp / "domains" / "circle-1" / "templates"
    tmpl_dir.mkdir(parents=True)
    real_tmpl = _REPO_ROOT / "domains" / "circle-1" / "templates"
    for src in real_tmpl.glob("*.json"):
        (tmpl_dir / src.name).write_bytes(src.read_bytes())


# ---------------------------------------------------------------------------
# is_template_declared
# ---------------------------------------------------------------------------


def test_is_template_declared_false_when_no_templates(tmp_path: Path) -> None:
    """Without template files, is_template_declared returns False for all zones."""
    for zone in known_zones():
        assert is_template_declared(tmp_path, zone) is False


def test_is_template_declared_true_after_template_added(tmp_path: Path) -> None:
    """Adding template files makes is_template_declared return True."""
    _add_templates(tmp_path)
    for zone in known_zones():
        assert is_template_declared(tmp_path, zone) is True, (
            f"Expected template_declared=True for zone {zone!r}"
        )


def test_is_template_declared_real_repo() -> None:
    """After task #780, both zone templates must be present in the real repo."""
    for zone in known_zones():
        assert is_template_declared(_REPO_ROOT, zone) is True, (
            f"Zone template missing for {zone!r} — did zone_template files get committed?"
        )


# ---------------------------------------------------------------------------
# load_zone_template
# ---------------------------------------------------------------------------


def test_load_zone_template_returns_none_when_absent(tmp_path: Path) -> None:
    assert load_zone_template(tmp_path, "scripts") is None


def test_load_zone_template_returns_dict_when_present(tmp_path: Path) -> None:
    _add_templates(tmp_path)
    tmpl = load_zone_template(tmp_path, "scripts")
    assert isinstance(tmpl, dict)
    assert tmpl["zone"] == "scripts"
    assert "required_elements" in tmpl


def test_zone_templates_have_required_fields() -> None:
    """Each zone template in the real repo has the mandatory structural fields."""
    required_fields = {"zone", "version", "required_elements"}
    for zone in known_zones():
        tmpl = load_zone_template(_REPO_ROOT, zone)
        assert tmpl is not None, f"Template missing for zone {zone!r}"
        missing = required_fields - tmpl.keys()
        assert not missing, f"Zone {zone!r} template missing fields: {missing}"


# ---------------------------------------------------------------------------
# compute_conformity — fixture repo (no templates)
# ---------------------------------------------------------------------------


def test_compute_conformity_scripts_empirical(tmp_path: Path) -> None:
    """Without templates, conformity uses empirical dominant shape."""
    _make_scripts_zone(tmp_path)
    result = compute_conformity(tmp_path, "scripts")
    assert result["template_declared"] is False
    assert result["method"] == "empirical_dominant_shape"
    assert result["file_count"] == 2
    assert result["conforming_count"] == 1
    assert result["uniformity"] == pytest.approx(0.5, abs=1e-4)


def test_compute_conformity_src_wea_cli_empirical(tmp_path: Path) -> None:
    """Without templates, wea_cli conformity uses empirical dominant shape."""
    _make_wea_cli_zone(tmp_path)
    result = compute_conformity(tmp_path, "src_wea_cli")
    assert result["template_declared"] is False
    assert result["method"] == "empirical_dominant_shape"
    assert result["file_count"] == 2
    assert result["conforming_count"] == 1


# ---------------------------------------------------------------------------
# compute_conformity — fixture repo WITH templates
# ---------------------------------------------------------------------------


def test_compute_conformity_scripts_declared(tmp_path: Path) -> None:
    """With templates, conformity switches to declared_template method."""
    _make_scripts_zone(tmp_path)
    _add_templates(tmp_path)
    result = compute_conformity(tmp_path, "scripts")
    assert result["template_declared"] is True
    assert result["method"] == "declared_template"
    assert result["file_count"] == 2
    assert result["conforming_count"] == 1


def test_compute_conformity_src_wea_cli_declared(tmp_path: Path) -> None:
    """With templates, wea_cli conformity switches to declared_template method."""
    _make_wea_cli_zone(tmp_path)
    _add_templates(tmp_path)
    result = compute_conformity(tmp_path, "src_wea_cli")
    assert result["template_declared"] is True
    assert result["method"] == "declared_template"


# ---------------------------------------------------------------------------
# score_repo.py CLI — end-to-end
# ---------------------------------------------------------------------------


def test_score_repo_cli_surfaces_declared_templates() -> None:
    """score_repo.py --root . returns all_templates_declared=True after task #780."""
    result = subprocess.run(
        [
            sys.executable,
            str(_SCRIPTS / "score_repo.py"),
            "--root", str(_REPO_ROOT),
            "--target", "wea",
            "--scan-date", "2026-04-23",
            "--repo-sha", "c07e079",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    output = json.loads(result.stdout)
    assert output["module_grammar"]["all_templates_declared"] is True, (
        "score_repo.py did not detect declared templates for both zones"
    )
    for zone in known_zones():
        zone_data = output["module_grammar"]["zones"][zone]
        assert zone_data["template_declared"] is True, (
            f"Zone {zone!r} not reported as template_declared=True"
        )


def test_score_repo_cli_fixture_no_templates(tmp_path: Path) -> None:
    """score_repo.py on a fixture repo without templates reports all_templates_declared=False."""
    _make_scripts_zone(tmp_path)
    _make_wea_cli_zone(tmp_path)
    result = subprocess.run(
        [
            sys.executable,
            str(_SCRIPTS / "score_repo.py"),
            "--root", str(tmp_path),
            "--target", "wea",
            "--scan-date", "2026-04-23",
            "--repo-sha", "test",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    output = json.loads(result.stdout)
    assert output["module_grammar"]["all_templates_declared"] is False


def test_score_repo_cli_fixture_with_templates(tmp_path: Path) -> None:
    """score_repo.py on a fixture repo with templates reports all_templates_declared=True."""
    _make_scripts_zone(tmp_path)
    _make_wea_cli_zone(tmp_path)
    _add_templates(tmp_path)
    result = subprocess.run(
        [
            sys.executable,
            str(_SCRIPTS / "score_repo.py"),
            "--root", str(tmp_path),
            "--target", "wea",
            "--scan-date", "2026-04-23",
            "--repo-sha", "test",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    output = json.loads(result.stdout)
    assert output["module_grammar"]["all_templates_declared"] is True
