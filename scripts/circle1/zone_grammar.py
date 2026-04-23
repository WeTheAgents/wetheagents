"""Zone grammar detection and conformance scoring for circle-1 module_grammar dimension.

Measures whether declared zone templates exist and how well existing files
match their zone's required shape.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

SESSION_1_ZONES: list[str] = ["scripts", "src_wea_cli"]

_ZONE_PATHS: dict[str, str] = {
    "scripts": "scripts",
    "src_wea_cli": "src/wea_cli",
}


def template_dir(root: Path) -> Path:
    return root / "domains" / "circle-1" / "zone_templates"


def detect_zone_templates(root: Path) -> dict[str, Path | None]:
    """Return zone_name -> template Path if declared, else None."""
    tmpl_dir = template_dir(root)
    return {
        zone: (tmpl_dir / f"{zone}.json")
        if (tmpl_dir / f"{zone}.json").exists()
        else None
        for zone in SESSION_1_ZONES
    }


def load_template(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def file_features(path: Path) -> dict[str, bool]:
    """Detect machine-checkable shape features of a Python file."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    lines = text.splitlines()
    has_shebang = bool(lines) and lines[0].startswith("#!")
    has_future = "from __future__ import annotations" in text
    has_main_guard = (
        "if __name__ == '__main__'" in text
        or 'if __name__ == "__main__"' in text
    )
    has_argparse = "argparse.ArgumentParser" in text
    has_docstring = False
    has_class = False
    has_function = False
    try:
        tree = ast.parse(text)
        if tree.body:
            node0 = tree.body[0]
            has_docstring = (
                isinstance(node0, ast.Expr)
                and isinstance(node0.value, ast.Constant)
                and isinstance(node0.value.value, str)
            )
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                has_class = True
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                has_function = True
    except SyntaxError:
        pass
    return {
        "has_module_docstring": has_docstring,
        "has_future_annotations": has_future,
        "has_main_guard": has_main_guard,
        "has_shebang": has_shebang,
        "has_argparse": has_argparse,
        "has_class": has_class,
        "has_function": has_function,
    }


def file_conforms(path: Path, template: dict[str, Any]) -> bool:
    """Return True if a file satisfies all required/excluded constraints in the template."""
    features = file_features(path)
    for item in template.get("required", []):
        check = item.get("machine_check")
        if check and not features.get(check, False):
            return False
    for item in template.get("excluded", []):
        check = item.get("machine_check")
        if check and features.get(check, False):
            return False
    return True


# Empirical dominant shape used before templates are declared.
_EMPIRICAL_REQUIRED: dict[str, list[str]] = {
    "scripts": ["has_module_docstring", "has_future_annotations", "has_main_guard"],
    "src_wea_cli": ["has_module_docstring", "has_future_annotations"],
}
_EMPIRICAL_EXCLUDED: dict[str, list[str]] = {
    "scripts": [],
    "src_wea_cli": ["has_main_guard"],
}


def _empirical_conforms(path: Path, zone: str) -> bool:
    features = file_features(path)
    for feat in _EMPIRICAL_REQUIRED.get(zone, []):
        if not features.get(feat, False):
            return False
    for feat in _EMPIRICAL_EXCLUDED.get(zone, []):
        if features.get(feat, False):
            return False
    return True


def compute_zone_conformance(
    root: Path,
    zone: str,
    template: dict[str, Any] | None,
) -> dict[str, Any]:
    """Compute conformance stats for one zone.

    Uses the declared template if present; falls back to empirical dominant shape.
    """
    zone_dir = root / _ZONE_PATHS[zone]
    py_files = [
        p for p in zone_dir.glob("*.py")
        if p.name != "__init__.py" and p.is_file()
    ]
    total = len(py_files)
    if total == 0:
        return {
            "conforming": 0,
            "total": 0,
            "rate": 1.0,
            "template_declared": template is not None,
            "basis": "declared" if template is not None else "empirical",
        }
    if template is not None:
        conforming = sum(1 for p in py_files if file_conforms(p, template))
        basis = "declared"
    else:
        conforming = sum(1 for p in py_files if _empirical_conforms(p, zone))
        basis = "empirical"
    return {
        "conforming": conforming,
        "total": total,
        "rate": round(conforming / total, 6),
        "template_declared": template is not None,
        "basis": basis,
    }


def score_module_grammar(root: Path) -> dict[str, Any]:
    """Compute module_grammar dimension scores and raw signals for a repo root.

    Returns a dict with declared/enforced/exercised scores (0..4 scale),
    the list of zones that have declared templates, and per-zone conformance data.
    """
    templates = detect_zone_templates(root)
    zones_with_templates = [z for z, p in templates.items() if p is not None]

    zone_data: dict[str, Any] = {}
    for zone in SESSION_1_ZONES:
        tmpl = load_template(templates[zone]) if templates[zone] is not None else None
        zone_data[zone] = compute_zone_conformance(root, zone, tmpl)

    # declared: 0=absent, 1=ad hoc, 2=partial, 3=repeatable, 4=canonical
    n_declared = len(zones_with_templates)
    n_session = len(SESSION_1_ZONES)
    if n_declared == 0:
        # Empirical shapes exist but nothing written down as a template
        declared = 1
    elif n_declared < n_session:
        declared = 2
    else:
        declared = 3

    # enforced: 0 until a CI check or pre-commit hook validates zone conformance
    enforced = 0

    # exercised: derived from average conformance rate across both zones.
    # Without declared templates, the path is not "frozen" — cap exercised at 2
    # even if empirical conformance is high.
    rates = [z["rate"] for z in zone_data.values() if z["total"] > 0]
    avg_rate = sum(rates) / len(rates) if rates else 0.0
    if avg_rate >= 0.90:
        exercised = 3
    elif avg_rate >= 0.70:
        exercised = 2
    else:
        exercised = 1
    if n_declared == 0:
        exercised = min(exercised, 2)

    return {
        "declared": declared,
        "enforced": enforced,
        "exercised": exercised,
        "zones_with_declared_templates": zones_with_templates,
        "zone_signals": zone_data,
    }
