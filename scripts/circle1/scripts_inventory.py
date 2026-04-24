"""Generate and persist machine-readable scripts/ role inventory outputs."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.circle1 import role_grammar


def _default_output_path(root: Path, scan_date: str) -> Path:
    return root / "scripts" / f"inventory_scripts_{scan_date.replace('-', '')}.json"


def main(argv: list[str] | None = None) -> int:
    args = role_grammar.parse_args(argv)
    root = Path(args.root).resolve()
    template = role_grammar.load_template(Path(args.template))

    output = _default_output_path(root, args.scan_date)
    if args.out:
        output = Path(args.out)

    payload = role_grammar.build_inventory_payload(root, template, args.scan_date)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
