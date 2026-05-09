"""Tests for score_repo.py and scripts/circle1/zone_grammar.py.

Verifies that:
- detect_zone_templates() returns None when no templates exist
- detect_zone_templates() returns Paths when templates are declared
- module_grammar declared score moves from 1 (ad hoc) to 3 (repeatable)
- the live WEA repo exposes declared templates for both session-1 zones
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.circle1.zone_grammar import (
    SESSION_1_ZONES,
    compute_zone_conformance,
    detect_zone_templates,
    file_features,
    score_module_grammar,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_fixture_repo(tmp_path: Path) -> Path:
    """Create a minimal fixture repo with one file per zone."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "src" / "wea_cli").mkdir(parents=True)
    (tmp_path / "domains" / "circle-1" / "zone_templates").mkdir(parents=True)

    _good_script = '''\
#!/usr/bin/env python3
"""A conforming script."""

from __future__ import annotations


def main() -> None:
    pass


if __name__ == "__main__":
    main()
'''
    _good_module = '''\
"""A conforming library module."""

from __future__ import annotations


def do_thing() -> None:
    pass
'''
    (tmp_path / "scripts" / "check_foo.py").write_text(_good_script, encoding="utf-8")
    (tmp_path / "src" / "wea_cli" / "foo.py").write_text(_good_module, encoding="utf-8")
    return tmp_path


_SCRIPTS_TEMPLATE: dict = {
    "zone": "scripts",
    "path": "scripts/",
    "description": "Test scripts zone template",
    "required": [
        {"name": "module_docstring", "machine_check": "has_module_docstring"},
        {"name": "future_annotations", "machine_check": "has_future_annotations"},
        {"name": "main_guard", "machine_check": "has_main_guard"},
    ],
    "optional": [],
    "excluded": [],
}

_WEA_CLI_TEMPLATE: dict = {
    "zone": "src_wea_cli",
    "path": "src/wea_cli/",
    "description": "Test wea_cli zone template",
    "required": [
        {"name": "module_docstring", "machine_check": "has_module_docstring"},
        {"name": "future_annotations", "machine_check": "has_future_annotations"},
    ],
    "optional": [],
    "excluded": [
        {"name": "main_guard", "machine_check": "has_main_guard"},
    ],
}

_SCRIPTS_ROLE_TEMPLATE: dict = {
    "zone": "scripts",
    "version": "v1_roles",
    "description": "Role-aware test scripts template",
    "roles": {
        "runnable_entrypoint": {},
        "import_safe_support": {},
        "declaration_module": {},
        "unclassified": {},
    },
}


def _write_templates(root: Path) -> None:
    tmpl_dir = root / "domains" / "circle-1" / "zone_templates"
    (tmpl_dir / "scripts.json").write_text(
        json.dumps(_SCRIPTS_TEMPLATE), encoding="utf-8"
    )
    (tmpl_dir / "src_wea_cli.json").write_text(
        json.dumps(_WEA_CLI_TEMPLATE), encoding="utf-8"
    )


def _write_role_template(root: Path) -> None:
    tmpl_dir = root / "domains" / "circle-1" / "zone_templates"
    (tmpl_dir / "scripts_v1_roles.json").write_text(
        json.dumps(_SCRIPTS_ROLE_TEMPLATE), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# detect_zone_templates
# ---------------------------------------------------------------------------

class TestDetectZoneTemplates:
    def test_absent_without_declaration(self, tmp_path):
        """With no zone_templates directory, all zones return None."""
        repo = _make_fixture_repo(tmp_path)
        # Remove the templates dir to simulate baseline state
        shutil.rmtree(repo / "domains" / "circle-1" / "zone_templates")

        result = detect_zone_templates(repo)
        assert result["scripts"] is None
        assert result["src_wea_cli"] is None

    def test_both_detected_when_declared(self, tmp_path):
        """With both template files present, both zones are detected."""
        repo = _make_fixture_repo(tmp_path)
        _write_templates(repo)

        result = detect_zone_templates(repo)
        assert result["scripts"] is not None
        assert result["scripts"].exists()
        assert result["src_wea_cli"] is not None
        assert result["src_wea_cli"].exists()

    def test_partial_detection(self, tmp_path):
        """Only one template file → one zone detected, other None."""
        repo = _make_fixture_repo(tmp_path)
        tmpl_dir = repo / "domains" / "circle-1" / "zone_templates"
        (tmpl_dir / "scripts.json").write_text(
            json.dumps(_SCRIPTS_TEMPLATE), encoding="utf-8"
        )

        result = detect_zone_templates(repo)
        assert result["scripts"] is not None
        assert result["src_wea_cli"] is None


# ---------------------------------------------------------------------------
# score_module_grammar — declared score
# ---------------------------------------------------------------------------

class TestScoreModuleGrammarDeclared:
    def test_declared_is_1_without_templates(self, tmp_path):
        """No template files → declared=1 (ad hoc empirical shapes only)."""
        repo = _make_fixture_repo(tmp_path)
        shutil.rmtree(repo / "domains" / "circle-1" / "zone_templates")

        mg = score_module_grammar(repo)
        assert mg["declared"] == 1, f"Expected declared=1, got {mg['declared']}"
        assert mg["zones_with_declared_templates"] == []

    def test_declared_is_2_with_one_template(self, tmp_path):
        """One template file → declared=2 (partial)."""
        repo = _make_fixture_repo(tmp_path)
        tmpl_dir = repo / "domains" / "circle-1" / "zone_templates"
        (tmpl_dir / "scripts.json").write_text(
            json.dumps(_SCRIPTS_TEMPLATE), encoding="utf-8"
        )

        mg = score_module_grammar(repo)
        assert mg["declared"] == 2, f"Expected declared=2, got {mg['declared']}"
        assert "scripts" in mg["zones_with_declared_templates"]
        assert "src_wea_cli" not in mg["zones_with_declared_templates"]

    def test_scripts_role_template_takes_precedence_over_flat_template(self, tmp_path):
        """scripts_v1_roles.json is the declared scripts template when both exist."""
        repo = _make_fixture_repo(tmp_path)
        _write_templates(repo)
        _write_role_template(repo)

        result = detect_zone_templates(repo)
        assert result["scripts"].name == "scripts_v1_roles.json"

    def test_declared_is_3_with_both_templates(self, tmp_path):
        """Both template files → declared=3 (repeatable)."""
        repo = _make_fixture_repo(tmp_path)
        _write_templates(repo)

        mg = score_module_grammar(repo)
        assert mg["declared"] == 3, f"Expected declared=3, got {mg['declared']}"
        assert set(mg["zones_with_declared_templates"]) == {"scripts", "src_wea_cli"}


# ---------------------------------------------------------------------------
# Template-based conformance from fixture repo
# ---------------------------------------------------------------------------

class TestConformanceFromFixture:
    def test_conforming_script_matches_template(self, tmp_path):
        """A well-formed script file passes the scripts zone template."""
        repo = _make_fixture_repo(tmp_path)
        _write_templates(repo)

        zone_data = compute_zone_conformance(
            repo, "scripts", _SCRIPTS_TEMPLATE
        )
        assert zone_data["rate"] == 1.0
        assert zone_data["conforming"] == zone_data["total"]
        assert zone_data["basis"] == "declared"

    def test_script_missing_main_guard_fails(self, tmp_path):
        """A script without main guard does not conform to scripts template."""
        repo = _make_fixture_repo(tmp_path)
        bad_script = (
            '"""Script without main guard."""\n\n'
            "from __future__ import annotations\n"
        )
        (tmp_path / "scripts" / "bad.py").write_text(bad_script, encoding="utf-8")
        _write_templates(repo)

        zone_data = compute_zone_conformance(repo, "scripts", _SCRIPTS_TEMPLATE)
        assert zone_data["rate"] < 1.0
        assert zone_data["conforming"] < zone_data["total"]

    def test_library_module_with_main_guard_fails(self, tmp_path):
        """A wea_cli module with __main__ guard violates the excluded constraint."""
        repo = _make_fixture_repo(tmp_path)
        bad_module = (
            '"""Library module with __main__ guard — violates wea_cli template."""\n\n'
            "from __future__ import annotations\n\n"
            'if __name__ == "__main__":\n    pass\n'
        )
        (tmp_path / "src" / "wea_cli" / "bad_lib.py").write_text(
            bad_module, encoding="utf-8"
        )
        _write_templates(repo)

        zone_data = compute_zone_conformance(repo, "src_wea_cli", _WEA_CLI_TEMPLATE)
        assert zone_data["conforming"] < zone_data["total"]

    def test_recursive_python_files_are_included_in_zone_census(self, tmp_path):
        """Nested Python files inside a zone must count toward conformance totals."""
        repo = _make_fixture_repo(tmp_path)
        nested_dir = repo / "scripts" / "circle1"
        nested_dir.mkdir()
        (nested_dir / "nested.py").write_text(
            '"""Nested helper without main guard."""\n\n'
            "from __future__ import annotations\n",
            encoding="utf-8",
        )
        _write_templates(repo)

        zone_data = compute_zone_conformance(repo, "scripts", _SCRIPTS_TEMPLATE)
        assert zone_data["total"] == 2
        assert zone_data["conforming"] == 1
        assert zone_data["rate"] == 0.5

    def test_role_template_allows_import_safe_support_without_main_guard(self, tmp_path):
        """With role-aware scoring, support modules do not need __main__ guards."""
        repo = _make_fixture_repo(tmp_path)
        (repo / "scripts" / "helper.py").write_text(
            '"""Import-safe helper."""\n\n'
            "from __future__ import annotations\n\n"
            "def helper() -> int:\n"
            "    return 1\n",
            encoding="utf-8",
        )
        _write_templates(repo)
        _write_role_template(repo)

        mg = score_module_grammar(repo)
        zone_data = mg["zone_signals"]["scripts"]
        assert zone_data["scoring_basis"] == "role_aware"
        assert zone_data["grammar_version"] == "v1_roles"
        assert zone_data["role_inventory"]["import_safe_support"] == 1
        assert zone_data["conforming"] == zone_data["total"] == 2
        assert zone_data["rate"] == 1.0

    def test_flat_template_fallback_still_requires_main_guard(self, tmp_path):
        """Without scripts_v1_roles.json, the legacy flat scripts template still applies."""
        repo = _make_fixture_repo(tmp_path)
        (repo / "scripts" / "helper.py").write_text(
            '"""Import-safe helper."""\n\n'
            "from __future__ import annotations\n\n"
            "def helper() -> int:\n"
            "    return 1\n",
            encoding="utf-8",
        )
        _write_templates(repo)

        mg = score_module_grammar(repo)
        zone_data = mg["zone_signals"]["scripts"]
        assert zone_data["basis"] == "declared"
        assert "scoring_basis" not in zone_data
        assert zone_data["conforming"] == 1
        assert zone_data["total"] == 2
        assert zone_data["rate"] == 0.5

    def test_unclassified_counts_against_role_aware_conformance(self, tmp_path):
        """unclassified is diagnostic debt: visible in detail and excluded from conforming."""
        repo = _make_fixture_repo(tmp_path)
        (repo / "scripts" / "side_effect.py").write_text(
            '"""Looks reusable but mutates sys.path at import time."""\n\n'
            "from __future__ import annotations\n"
            "import sys\n\n"
            "sys.path.insert(0, 'x')\n\n"
            "def helper() -> int:\n"
            "    return 1\n",
            encoding="utf-8",
        )
        _write_templates(repo)
        _write_role_template(repo)

        mg = score_module_grammar(repo)
        zone_data = mg["zone_signals"]["scripts"]
        assert zone_data["conforming"] == 1
        assert zone_data["total"] == 2
        assert zone_data["rate"] == 0.5
        assert zone_data["role_inventory"]["unclassified"] == 1
        assert zone_data["unclassified"] == [
            {
                "path": "scripts/side_effect.py",
                "reasons": [
                    "module-level sys.path mutation detected (inside control flow, not a bare call)",
                    "bare function calls at module top level (called for side effects)",
                ],
            }
        ]


# ---------------------------------------------------------------------------
# file_features
# ---------------------------------------------------------------------------

class TestFileFeatures:
    def test_good_script_features(self, tmp_path):
        src = (
            '#!/usr/bin/env python3\n'
            '"""Module docstring."""\n\n'
            "from __future__ import annotations\n\n"
            "def main(): pass\n\n"
            'if __name__ == "__main__":\n    main()\n'
        )
        p = tmp_path / "script.py"
        p.write_text(src, encoding="utf-8")
        feat = file_features(p)
        assert feat["has_module_docstring"]
        assert feat["has_future_annotations"]
        assert feat["has_main_guard"]
        assert feat["has_shebang"]

    def test_library_module_features(self, tmp_path):
        src = (
            '"""Library module."""\n\n'
            "from __future__ import annotations\n\n"
            "def fn(): pass\n"
        )
        p = tmp_path / "lib.py"
        p.write_text(src, encoding="utf-8")
        feat = file_features(p)
        assert feat["has_module_docstring"]
        assert feat["has_future_annotations"]
        assert not feat["has_main_guard"]
        assert not feat["has_shebang"]


# ---------------------------------------------------------------------------
# Live WEA repo: templates detected after task #780
# ---------------------------------------------------------------------------

class TestLiveWEARepo:
    """Integration tests against the actual WEA repo."""

    @pytest.fixture
    def wea_root(self) -> Path:
        return Path(__file__).resolve().parents[1]

    def test_templates_declared_for_both_zones(self, wea_root):
        """After task #780, both session-1 zones must have declared templates."""
        result = detect_zone_templates(wea_root)
        assert result["scripts"] is not None, (
            "scripts zone template missing — task #780 should have created it"
        )
        assert result["src_wea_cli"] is not None, (
            "src_wea_cli zone template missing — task #780 should have created it"
        )

    def test_declared_score_is_3_for_live_repo(self, wea_root):
        """module_grammar.declared must be 3 (repeatable) after task #780."""
        mg = score_module_grammar(wea_root)
        assert mg["declared"] == 3, (
            f"Expected declared=3 after task #780, got {mg['declared']}. "
            f"Zones with templates: {mg['zones_with_declared_templates']}"
        )

    def test_zone_signals_use_declared_basis(self, wea_root):
        """After templates are present, zone_signals should report basis='declared'."""
        mg = score_module_grammar(wea_root)
        for zone in SESSION_1_ZONES:
            basis = mg["zone_signals"][zone]["basis"]
            assert basis == "declared", (
                f"Zone {zone} reports basis={basis!r}, expected 'declared'"
            )

    def test_live_scripts_zone_uses_role_aware_scoring(self, wea_root):
        """After task #798, scripts zone detail should expose role-aware scoring."""
        mg = score_module_grammar(wea_root)
        scripts = mg["zone_signals"]["scripts"]
        assert scripts["grammar_version"] == "v1_roles"
        assert scripts["scoring_basis"] == "role_aware"
        assert scripts["role_inventory"]["runnable_entrypoint"] > 0
        assert scripts["role_inventory"]["import_safe_support"] > 0
        assert scripts["role_inventory"]["unclassified"] > 0
        assert scripts["unclassified"], "Live scripts role scan should expose review debt"

    def test_score_repo_cli_surfaces_template_evidence(self, wea_root):
        """score_repo._scan_wea surfaces declared-template evidence for both zones."""
        sys.path.insert(0, str(wea_root))
        from scripts.score_repo import _scan_wea

        result = _scan_wea(wea_root, "2026-04-23", "c07e079")

        mg = result["structural"]["module_grammar"]
        assert mg["declared"] == 3

        detail = result["module_grammar_detail"]
        assert "scripts" in detail["zones_with_declared_templates"]
        assert "src_wea_cli" in detail["zones_with_declared_templates"]
        scripts = detail["zone_signals"]["scripts"]
        assert scripts["grammar_version"] == "v1_roles"
        assert scripts["scoring_basis"] == "role_aware"
        assert scripts["role_inventory"]["unclassified"] > 0
        assert scripts["unclassified"]

        notes_text = " ".join(result["notes"])
        assert "scripts" in notes_text
        assert "src_wea_cli" in notes_text


class TestScoreRepoCLI:
    def test_invalid_root_exits_nonzero(self, tmp_path):
        missing_root = tmp_path / "missing-repo-root"
        result = subprocess.run(
            [
                sys.executable,
                "scripts/score_repo.py",
                "--root",
                str(missing_root),
                "--target",
                "wea",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
        assert "does not exist" in result.stderr
