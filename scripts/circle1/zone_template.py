"""Zone template detection and module_grammar uniformity for circle-1 scoring."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


# Where zone template JSON files live relative to repo root
_TEMPLATES_SUBDIR = "domains/circle-1/templates"

# Zone definitions: zone key → (subdir, glob pattern, required element ids)
_ZONE_CONFIG: dict[str, dict[str, Any]] = {
    "scripts": {
        "subdir": "scripts",
        "glob": "*.py",
        "template_file": "scripts_zone.json",
        "required": ["shebang", "module_docstring", "future_annotations", "main_function", "main_guard"],
    },
    "src_wea_cli": {
        "subdir": "src/wea_cli",
        "glob": "*.py",
        "template_file": "src_wea_cli_zone.json",
        "required": ["module_docstring", "future_annotations"],
    },
}


def _has_module_docstring(text: str) -> bool:
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        return stripped.startswith('"""') or stripped.startswith("'''")
    return False


def _has_future_annotations(text: str) -> bool:
    return "from __future__ import annotations" in text


def _starts_with_shebang(text: str) -> bool:
    return text.startswith("#!/usr/bin/env python3")


def _has_main_function(text: str) -> bool:
    return bool(re.search(r"^def main\(", text, re.MULTILINE))


def _has_main_guard(text: str) -> bool:
    return bool(re.search(r"""if __name__\s*==\s*['"]__main__['"]""", text))


_ELEMENT_CHECK = {
    "shebang": _starts_with_shebang,
    "module_docstring": _has_module_docstring,
    "future_annotations": _has_future_annotations,
    "main_function": _has_main_function,
    "main_guard": _has_main_guard,
}


def is_template_declared(root: Path, zone: str) -> bool:
    """Return True if a zone template JSON file exists for the given zone."""
    cfg = _ZONE_CONFIG.get(zone)
    if not cfg:
        return False
    return (root / _TEMPLATES_SUBDIR / cfg["template_file"]).is_file()


def load_zone_template(root: Path, zone: str) -> dict[str, Any] | None:
    """Load and return the zone template JSON, or None if not declared."""
    cfg = _ZONE_CONFIG.get(zone)
    if not cfg:
        return None
    path = root / _TEMPLATES_SUBDIR / cfg["template_file"]
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _zone_files(root: Path, zone: str) -> list[Path]:
    cfg = _ZONE_CONFIG.get(zone)
    if not cfg:
        return []
    zone_dir = root / cfg["subdir"]
    if not zone_dir.is_dir():
        return []
    excludes = set((load_zone_template(root, zone) or {}).get("excludes", ["__init__.py"]))
    return [f for f in zone_dir.glob(cfg["glob"]) if f.name not in excludes]


def _file_conforms(text: str, required_ids: list[str]) -> bool:
    return all(_ELEMENT_CHECK.get(eid, lambda _: False)(text) for eid in required_ids)


def compute_conformity(root: Path, zone: str) -> dict[str, Any]:
    """Return conformity stats for a zone.

    Uses the declared template's required_elements if a template exists,
    otherwise falls back to the hardcoded required list in _ZONE_CONFIG.
    """
    cfg = _ZONE_CONFIG.get(zone)
    if not cfg:
        return {"error": f"unknown zone: {zone}"}

    template = load_zone_template(root, zone)
    declared = template is not None

    if declared:
        required_ids = [e["id"] for e in template.get("required_elements", [])]
        method = "declared_template"
    else:
        required_ids = cfg["required"]
        method = "empirical_dominant_shape"

    files = _zone_files(root, zone)
    if not files:
        return {
            "template_declared": declared,
            "file_count": 0,
            "conforming_count": 0,
            "uniformity": None,
            "method": method,
        }

    conforming = 0
    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if _file_conforms(text, required_ids):
            conforming += 1

    return {
        "template_declared": declared,
        "file_count": len(files),
        "conforming_count": conforming,
        "uniformity": round(conforming / len(files), 6),
        "method": method,
    }


def known_zones() -> list[str]:
    """Return the list of zone keys known to this module."""
    return list(_ZONE_CONFIG.keys())
