"""Scan harness for scripts/ role grammar V1.

Applies the role grammar to all Python files in scripts/ and outputs a
deterministic inventory JSON sorted by file path.

Usage:
    python scripts/circle1/scripts_inventory.py --root . [--output path]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT_HINT = _HERE.parents[1]
if str(_ROOT_HINT) not in sys.path:
    sys.path.insert(0, str(_ROOT_HINT))

from scripts.circle1.role_grammar import Role, classify_role  # noqa: E402


def scan_scripts(root: Path, scan_date: str = "2026-04-24") -> dict:
    """Classify all .py files under scripts/ and return an inventory dict."""
    scripts_dir = root / "scripts"
    py_files = sorted(
        p
        for p in scripts_dir.rglob("*.py")
        if p.name != "__init__.py" and p.is_file()
    )

    role_counts: dict[str, int] = {r.value: 0 for r in Role}
    file_entries: list[dict] = []

    for path in py_files:
        result = classify_role(path)
        role_counts[result.role.value] += 1
        entry: dict = {
            "path": str(path.relative_to(root)).replace("\\", "/"),
            "role": result.role.value,
            "reasons": result.reasons,
        }
        if result.bypass_notes:
            entry["bypass_notes"] = result.bypass_notes
        file_entries.append(entry)

    return {
        "scan_date": scan_date,
        "zone": "scripts",
        "grammar_version": "v1_roles",
        "summary": {
            "total": len(file_entries),
            "by_role": role_counts,
        },
        "files": file_entries,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scripts zone role inventory")
    parser.add_argument("--root", default=".", help="Repo root directory")
    parser.add_argument("--output", default=None, help="Output JSON file path")
    parser.add_argument(
        "--scan-date",
        default="2026-04-24",
        help="ISO date to embed in the inventory record",
    )
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"ERROR: not a directory: {root}", file=sys.stderr)
        return 1

    inventory = scan_scripts(root, scan_date=args.scan_date)
    payload = json.dumps(inventory, indent=2)

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(payload + "\n", encoding="utf-8")
        print(f"Saved: {out_path}", file=sys.stderr)
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
