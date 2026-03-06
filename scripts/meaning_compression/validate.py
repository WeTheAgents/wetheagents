"""CLI entry point for Meaning Compression validation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .schema import build_submission_schema
from .validator import (
    DEFAULT_ATOMS_PATH,
    DEFAULT_SCHEMA_PATH,
    format_report,
    load_atom_index,
    load_json_file,
    validate_pair,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.meaning_compression.validate",
        description="Deterministically validate a Meaning Compression challenger against a baseline.",
    )
    parser.add_argument("--baseline", help="Path to the baseline JSON record.")
    parser.add_argument("--submission", help="Path to the challenger JSON record.")
    parser.add_argument(
        "--atoms",
        default=str(DEFAULT_ATOMS_PATH),
        help="Path to the canonical atom set JSON file.",
    )
    parser.add_argument(
        "--schema",
        default=str(DEFAULT_SCHEMA_PATH),
        help="Path to the canonical JSON schema file.",
    )
    parser.add_argument(
        "--dump-atoms",
        action="store_true",
        help="Print the canonical atom set and exit.",
    )
    parser.add_argument(
        "--dump-schema",
        action="store_true",
        help="Print the canonical JSON schema and exit.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        atoms_payload = load_json_file(Path(args.atoms))
        schema_path = Path(args.schema)
        schema_payload = load_json_file(schema_path)

        if args.dump_atoms:
            print(json.dumps(atoms_payload, indent=2, ensure_ascii=False))
            return 0
        if args.dump_schema:
            print(json.dumps(build_submission_schema(), indent=2, ensure_ascii=False))
            return 0

        if not args.baseline or not args.submission:
            parser.error("--baseline and --submission are required unless using --dump-atoms/--dump-schema.")

        # Read the schema file to guarantee that the canonical JSON artifact is present and parseable.
        if schema_payload != build_submission_schema():
            raise ValueError(f"Schema file does not match schema builder: {schema_path}")

        atom_index = load_atom_index(Path(args.atoms))
        baseline_payload = load_json_file(Path(args.baseline))
        submission_payload = load_json_file(Path(args.submission))
        report = validate_pair(
            baseline_payload,
            submission_payload,
            atom_index=atom_index,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}")
        return 2

    print(format_report(report))
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
