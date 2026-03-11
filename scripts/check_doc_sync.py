#!/usr/bin/env python3
"""
Doc-Sync Drift Checker.

Validates that MAP.md paths exist, operations.md commands match
tide_parser.py patterns, and CLI subcommands are discoverable.
Exits 1 on any violation with remediation instructions.
"""

import os
import re
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ERRORS: list[str] = []


def err(file: str, msg: str, fix: str) -> None:
    ERRORS.append(f"  FAIL [{file}]: {msg}\n        Fix: {fix}")


def main() -> None:
    # -------------------------------------------------------------------
    # Assert 1: All paths in MAP.md exist on disk
    # -------------------------------------------------------------------

    map_path = os.path.join(BASE_DIR, "MAP.md")
    if not os.path.isfile(map_path):
        err("MAP.md", "file not found", "create MAP.md at repo root")
    else:
        with open(map_path, "r", encoding="utf-8") as f:
            map_lines = f.readlines()

        for line in map_lines:
            # Match table rows: | `path` | ... | ... |
            m = re.match(r"^\|\s*`([^`]+)`\s*\|", line)
            if not m:
                continue
            rel_path = m.group(1)
            abs_path = os.path.join(BASE_DIR, rel_path)
            if rel_path.endswith("/"):
                if not os.path.isdir(abs_path):
                    err("MAP.md", f"directory not found: {rel_path}",
                        f"create {rel_path} or remove from MAP.md")
            else:
                if not os.path.isfile(abs_path):
                    err("MAP.md", f"file not found: {rel_path}",
                        f"create {rel_path} or remove from MAP.md")

    # -------------------------------------------------------------------
    # Assert 2: operations.md commands subset of tide_parser.py patterns
    # -------------------------------------------------------------------

    ops_path = os.path.join(BASE_DIR, "agent0", "operations.md")
    tide_path = os.path.join(BASE_DIR, "scripts", "tide_parser.py")

    if not os.path.isfile(ops_path):
        err("operations.md", "file not found", "create agent0/operations.md")
    elif not os.path.isfile(tide_path):
        err("tide_parser.py", "file not found", "create scripts/tide_parser.py")
    else:
        with open(ops_path, "r", encoding="utf-8") as f:
            ops_text = f.read()

        with open(tide_path, "r", encoding="utf-8") as f:
            tide_text = f.read()

        # Extract command names from operations.md backtick blocks
        # Pattern: **`command ...`** or **`command`**
        cmd_pattern = re.compile(r"\*\*`(\S+?)(?:\s[^`]*)?\s*`\*\*")
        ops_commands = list(dict.fromkeys(cmd_pattern.findall(ops_text)))

        for cmd in ops_commands:
            # Normalize: strip leading !, trailing :, replace - with _
            normalized = cmd.lstrip("!").rstrip(":").replace("-", "_").upper()
            var_name = f"_{normalized}"
            # Match variable assignment, not substring
            # (avoids _ACCEPT matching _ACCEPT_TRANSFORM)
            if not re.search(rf'\b{re.escape(var_name)}\s*=', tide_text):
                err("operations.md", f"command '{cmd}' has no matching "
                    f"pattern {var_name} in tide_parser.py",
                    f"add {var_name} = re.compile(...) to tide_parser.py")

    # -------------------------------------------------------------------
    # Assert 3 (WARN only): Undocumented CLI subcommands
    # -------------------------------------------------------------------

    cli_path = os.path.join(BASE_DIR, "src", "wea_cli", "cli.py")

    if os.path.isfile(cli_path) and os.path.isfile(map_path):
        with open(cli_path, "r", encoding="utf-8") as f:
            cli_text = f.read()

        with open(map_path, "r", encoding="utf-8") as f:
            map_text = f.read()

        # Extract top-level subparser names (exclude nested sub-subparsers)
        sp_pattern = re.compile(r'\bsubparsers\.add_parser\(\s*"([^"]+)"')
        cli_commands = sp_pattern.findall(cli_text)

        missing = [c for c in cli_commands if c not in map_text]
        if missing:
            print(f"  WARN: CLI subcommands not mentioned in MAP.md: "
                  f"{', '.join(missing)}")

    # -------------------------------------------------------------------
    # Result
    # -------------------------------------------------------------------

    if ERRORS:
        print(f"\n{len(ERRORS)} doc-sync violation(s) found:\n")
        for e in ERRORS:
            print(e)
        print("\nStatus: FAIL")
        sys.exit(1)
    else:
        print("All doc-sync checks pass.")
        print("\nStatus: PASS")
        sys.exit(0)


if __name__ == "__main__":
    main()
