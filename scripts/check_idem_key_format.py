#!/usr/bin/env python3
"""
check_idem_key_format.py — validate idem key naming conventions in ledger/idem_keys.json

Known patterns:
  register|{agent}
  trajectory_mint|T{N}|{slot}
  escrow_create_{issue}_{type}_gauntlet
  escrow_return|{issue}
  escrow_return|{issue}|{agent}
  escrow_return|{issue}|{agent}|{reason}
  claim|{issue}|{agent}
  accept|{issue}|{agent}
  verify|{issue}|{agent}
  payment|{issue}|{agent}
  payment|{issue}|{agent}|{role}
  reject|{issue}|{agent}
  settle|{issue}|{agent}
  cleanup|...
  hello_world|{agent}
  join|{agent}
  create_task|{issue}

Exits 0 if all keys match known patterns; exits 1 if unknown keys found.
"""

import json
import re
import sys
from pathlib import Path

AGENT = r"[A-Za-z0-9@._-]+"
ISSUE = r"\d+"
SLOT = r"\d+"
TRAJ = r"T\d+"
REASON = r"[A-Za-z0-9_-]+"
ROLE = r"[A-Za-z0-9_-]+"

KNOWN_PATTERNS = [
    # Current patterns
    re.compile(rf"^register\|{AGENT}$"),
    re.compile(rf"^trajectory_mint\|{TRAJ}\|{SLOT}$"),
    re.compile(rf"^escrow_create_{ISSUE}_{REASON}_gauntlet$"),
    re.compile(rf"^escrow_return\|{ISSUE}$"),
    re.compile(rf"^escrow_return\|{ISSUE}\|{AGENT}$"),
    re.compile(rf"^escrow_return\|{ISSUE}\|{AGENT}\|{REASON}$"),
    re.compile(rf"^claim\|{ISSUE}\|{AGENT}$"),
    re.compile(rf"^accept\|{ISSUE}\|{AGENT}$"),
    re.compile(rf"^accept\|{ISSUE}\|{AGENT}\|{REASON}$"),
    re.compile(rf"^verify\|{ISSUE}\|{AGENT}$"),
    re.compile(rf"^payment\|{ISSUE}\|{AGENT}$"),
    re.compile(rf"^payment\|{ISSUE}\|{AGENT}\|{ROLE}$"),
    re.compile(rf"^payment\|{ISSUE}\|{AGENT}\|{ROLE}\|\d+$"),
    re.compile(rf"^reject\|{ISSUE}\|{AGENT}$"),
    re.compile(rf"^settle\|{ISSUE}\|{AGENT}$"),
    re.compile(rf"^cleanup(\|.*)?$"),
    re.compile(rf"^hello_world(\|{AGENT})?$"),
    re.compile(rf"^join(\|{ISSUE})?\|{AGENT}$"),
    re.compile(rf"^join$"),
    re.compile(rf"^create_task(\|{ISSUE})?$"),
    # Legacy escrow create (pre-gauntlet pattern)
    re.compile(rf"^escrow\|{ISSUE}\|{AGENT}$"),
    re.compile(rf"^escrow\|{ISSUE}\|{AGENT}\|{REASON}$"),
    # Legacy heartbeat/one-off formats
    re.compile(rf"^escrow-create-{ISSUE}$"),
    re.compile(rf"^escrow-return-cycle\d+-{ISSUE}$"),
    re.compile(rf"^escrow_return_{ISSUE}_{REASON}_orphan$"),
    # Legacy Tide SHA-256 hash keys
    re.compile(r"^[0-9a-f]{64}$"),
]


def load_idem_keys(root: Path) -> dict:
    path = root / "ledger" / "idem_keys.json"
    with open(path) as f:
        return json.load(f)


def is_known(key: str) -> bool:
    return any(p.match(key) for p in KNOWN_PATTERNS)


def run_check(idem_keys: dict) -> dict:
    keys = list(idem_keys.get("keys", {}).keys())
    unknown = [k for k in keys if not is_known(k)]
    return {
        "passed": len(unknown) == 0,
        "unknown_keys": unknown,
        "total_checked": len(keys),
    }


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=None, help="Repo root (default: script's parent parent)")
    args = parser.parse_args()
    root = Path(args.root) if args.root else Path(__file__).parent.parent
    idem_keys = load_idem_keys(root)
    result = run_check(idem_keys)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
