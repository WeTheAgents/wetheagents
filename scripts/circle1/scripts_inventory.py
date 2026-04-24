"""Scan scripts/*.py and classify each file by role family (V1 role grammar).

Produces a JSON inventory with per-file role classification and aggregate stats.
Skips __init__.py and files in subdirectories.

Usage:
    python scripts/circle1/scripts_inventory.py --root . --save
    python scripts/circle1/scripts_inventory.py --root . > inventory.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT_HINT = _HERE.parent.parent
if str(_ROOT_HINT) not in sys.path:
    sys.path.insert(0, str(_ROOT_HINT))

from scripts.circle1.role_grammar import ROLES, classify_file  # noqa: E402


def scan_scripts(root: Path) -> dict:
    """Classify all scripts/*.py files. Returns a structured inventory dict."""
    scripts_dir = root / "scripts"
    py_files = sorted(
        p for p in scripts_dir.glob("*.py")
        if p.name != "__init__.py" and p.is_file()
    )

    files_out: list[dict] = []
    counts: dict[str, int] = {role: 0 for role in sorted(ROLES)}

    for path in py_files:
        result = classify_file(path)
        role = result["role"]
        counts[role] = counts.get(role, 0) + 1
        entry: dict = {
            "file": path.name,
            "role": role,
        }
        if result.get("reason"):
            entry["reason"] = result["reason"]
        # Include key feature signals for auditability
        feat = result.get("features", {})
        entry["signals"] = {
            "has_main_guard": feat.get("has_main_guard", False),
            "has_function_or_class": feat.get("has_function_or_class", False),
            "has_only_data": feat.get("has_only_data", False),
            "has_syspath_mutation_at_top_level": feat.get("has_syspath_mutation_at_top_level", False),
            "has_sysexit_at_top_level": feat.get("has_sysexit_at_top_level", False),
        }
        files_out.append(entry)

    total = len(py_files)
    return {
        "scan_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "grammar_version": "v1",
        "zone": "scripts",
        "total_files": total,
        "role_counts": counts,
        "files": files_out,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="scripts/ role grammar V1 inventory scanner")
    parser.add_argument("--root", default=".", help="Repo root directory")
    parser.add_argument(
        "--save",
        action="store_true",
        help="Save output to scripts/inventory_scripts_YYYYMMDD.json",
    )
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"ERROR: {root} is not a directory", file=sys.stderr)
        return 1

    result = scan_scripts(root)
    payload = json.dumps(result, indent=2)

    if args.save:
        date_str = result["scan_date"].replace("-", "")
        out_path = root / "scripts" / f"inventory_scripts_{date_str}.json"
        out_path.write_text(payload + "\n", encoding="utf-8")
        print(f"Saved: {out_path}", file=sys.stderr)
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
