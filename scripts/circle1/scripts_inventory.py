"""Scan scripts/ tree and emit per-file role classification.

Usage:
    python scripts/circle1/scripts_inventory.py [--root PATH] [--out FILE]

Output is a JSON object with a per-file list sorted by relative path.
Intended to produce a checked-in deterministic inventory artifact.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT_HINT = _HERE.parent.parent
if str(_ROOT_HINT) not in sys.path:
    sys.path.insert(0, str(_ROOT_HINT))

from scripts.circle1.role_grammar import classify_file  # noqa: E402


def scan_scripts(root: Path) -> list[dict]:
    """Return per-file classification records for all Python files under scripts/."""
    scripts_dir = root / "scripts"
    py_files = sorted(
        p for p in scripts_dir.rglob("*.py")
        if p.name != "__init__.py" and p.is_file()
    )
    return [classify_file(p) for p in py_files]


def summarise(records: list[dict]) -> dict:
    from collections import Counter
    counts: Counter[str] = Counter(r["role"] for r in records)
    return {
        "total": len(records),
        "by_role": dict(counts),
    }


def build_output(root: Path, scan_date: str) -> dict:
    records = scan_scripts(root)

    # Use relative paths in the output for portability
    root_str = str(root)
    portable = []
    for r in records:
        rec = dict(r)
        file_path = rec.get("file", "")
        if file_path.startswith(root_str):
            rec["file"] = file_path[len(root_str):].lstrip("/\\")
        portable.append(rec)

    return {
        "scan_date": scan_date,
        "root": root_str,
        "summary": summarise(records),
        "files": portable,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="scripts/ role inventory")
    parser.add_argument("--root", default=".", help="Repo root directory")
    parser.add_argument("--out", default="-", help="Output file (- for stdout)")
    parser.add_argument(
        "--scan-date",
        default="",
        help="ISO date to embed in the output (defaults to today)",
    )
    args = parser.parse_args(argv)

    if not args.scan_date:
        from datetime import datetime, timezone
        args.scan_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"ERROR: not a directory: {root}", file=sys.stderr)
        return 1

    output = build_output(root, args.scan_date)
    payload = json.dumps(output, indent=2)

    if args.out == "-":
        print(payload)
    else:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(payload + "\n", encoding="utf-8")
        print(f"Saved: {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
