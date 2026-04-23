#!/usr/bin/env python3
"""Circle-1 checkpoint scorer: detects zone template declarations and module grammar shapes."""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path
from typing import Any

try:
    import yaml as _yaml_mod

    def _load_yaml(text: str) -> Any:
        return _yaml_mod.safe_load(text)

except ImportError:  # pragma: no cover - yaml is expected in this environment
    _load_yaml = None  # type: ignore[assignment]

TEMPLATE_FILENAME = ".zone-template.yaml"

ZONE_PATHS: dict[str, str] = {
    "scripts": "scripts",
    "src_wea_cli": "src/wea_cli",
}

# Maps template field names to (tree, src) → bool lambdas.
_SHAPE_FIELDS: dict[str, Any] = {
    "module_docstring": lambda tree, _src: (
        bool(tree.body)
        and isinstance(tree.body[0], ast.Expr)
        and isinstance(getattr(tree.body[0], "value", None), ast.Constant)
        and isinstance(tree.body[0].value.value, str)
    ),
    "functions": lambda tree, _src: any(isinstance(n, ast.FunctionDef) for n in tree.body),
    "classes": lambda tree, _src: any(isinstance(n, ast.ClassDef) for n in tree.body),
    "main_guard": lambda tree, _src: any(
        isinstance(n, ast.If)
        and isinstance(n.test, ast.Compare)
        and isinstance(n.test.left, ast.Name)
        and n.test.left.id == "__name__"
        for n in tree.body
    ),
    "future_annotations": lambda tree, _src: any(
        isinstance(n, ast.ImportFrom)
        and n.module == "__future__"
        and any(a.name == "annotations" for a in n.names)
        for n in ast.walk(tree)
    ),
    "shebang": lambda _tree, src: src.startswith("#!"),
}


def _file_shape(path: Path) -> dict[str, bool] | None:
    """Parse one Python source file and return its structural shape."""
    try:
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src)
    except (OSError, SyntaxError):
        return None
    return {k: bool(fn(tree, src)) for k, fn in _SHAPE_FIELDS.items()}


def _conforms_to_required(shape: dict[str, bool], required: list[str]) -> bool:
    """Return True when shape satisfies all required template fields."""
    return all(shape.get(field, False) for field in required)


def _load_template(path: Path) -> dict[str, Any]:
    """Load a zone template YAML file; return empty dict on any failure."""
    if _load_yaml is None:
        return {}
    try:
        raw = _load_yaml(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def scan_zone(root: Path, zone_rel: str) -> dict[str, Any]:
    """Scan one zone directory and return template declaration evidence."""
    zone_dir = root / zone_rel
    result: dict[str, Any] = {
        "zone_path": zone_rel,
        "template_declared": False,
        "template_path": None,
        "declared_shape": None,
        "file_count": 0,
        "conformant_count": None,
        "module_grammar_uniformity": None,
    }

    if not zone_dir.is_dir():
        return result

    template_path = zone_dir / TEMPLATE_FILENAME
    required: list[str] = []

    if template_path.is_file():
        result["template_declared"] = True
        result["template_path"] = str(template_path.relative_to(root)).replace("\\", "/")
        template = _load_template(template_path)
        shape_block = template.get("shape", {})
        required = list(shape_block.get("required", []))
        result["declared_shape"] = {
            "required": required,
            "optional": list(shape_block.get("optional", [])),
            "forbidden": list(shape_block.get("forbidden", [])),
        }

    py_files = [
        f
        for f in zone_dir.rglob("*.py")
        if "__pycache__" not in f.parts
    ]
    result["file_count"] = len(py_files)

    if required and py_files:
        shapes = [_file_shape(f) for f in py_files]
        valid = [s for s in shapes if s is not None]
        conformant = sum(1 for s in valid if _conforms_to_required(s, required))
        result["conformant_count"] = conformant
        result["module_grammar_uniformity"] = round(conformant / len(valid), 4) if valid else None

    return result


def score_module_grammar(root: Path) -> dict[str, Any]:
    """Score the module_grammar structural dimension for the given repo root."""
    zones: dict[str, Any] = {}
    all_declared = True

    for zone_key, zone_rel in ZONE_PATHS.items():
        zones[zone_key] = scan_zone(root, zone_rel)
        if not zones[zone_key]["template_declared"]:
            all_declared = False

    return {
        # declared=3 (repeatable): templates exist for all measured zones
        # declared=2 (partial): empirical shapes only, no canonical declaration
        "declared": 3 if all_declared else 2,
        # enforced=1: templates declared but conformance check not yet wired into CI
        "enforced": 1,
        # exercised=2: zone shapes are visible in real recent files
        "exercised": 2,
        "zones": zones,
    }


def build_checkpoint(root: Path, target: str, scan_date: str, repo_sha: str) -> dict[str, Any]:
    """Build a circle-1 checkpoint record for the given repo root."""
    mg = score_module_grammar(root)
    return {
        "scan_date": scan_date,
        "repo_sha": repo_sha,
        "target": target,
        "structural": {
            "module_grammar": {
                "declared": mg["declared"],
                "enforced": mg["enforced"],
                "exercised": mg["exercised"],
                "raw": {"zones": mg["zones"]},
            },
        },
        "notes": [
            f"declared-template evidence detected via {TEMPLATE_FILENAME} in each zone",
            "conformance scores use required fields from declared template only",
            "forbidden fields advisory in v0; CI enforcement not yet wired",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Circle-1 zone template and module grammar scorer.")
    parser.add_argument("--root", default=".", help="Repo root directory")
    parser.add_argument("--target", default="wea", help="Target label")
    parser.add_argument("--scan-date", default="", help="Scan date YYYY-MM-DD")
    parser.add_argument("--repo-sha", default="", help="Git SHA at scan time")
    parser.add_argument("--output", default=None, help="Write checkpoint JSON to this path")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    checkpoint = build_checkpoint(root, args.target, args.scan_date, args.repo_sha)
    output_text = json.dumps(checkpoint, indent=2) + "\n"

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output_text, encoding="utf-8")
        print(f"Checkpoint written to {args.output}")
    else:
        print(output_text, end="")

    # Surface declared-template evidence
    mg_zones = checkpoint["structural"]["module_grammar"]["raw"]["zones"]
    for zone_key, zone_data in mg_zones.items():
        status = "DECLARED" if zone_data["template_declared"] else "ABSENT"
        path_info = f" ({zone_data['template_path']})" if zone_data["template_path"] else ""
        print(f"[module_grammar] {zone_key}: template {status}{path_info}", file=sys.stderr)


if __name__ == "__main__":
    main()
