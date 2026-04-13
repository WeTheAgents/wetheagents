#!/usr/bin/env python3
"""Post a daily ecosystem digest comment built from `wea report` output."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_AGENT = "Codex-2@codex"
TRAJECTORIES = ("T1", "T2", "T3", "T4", "T5", "T6")


class DigestError(RuntimeError):
    """Raised when digest inputs cannot be collected or formatted."""


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _render_report_text(report: dict[str, Any], *, root: Path) -> str:
    src_root = root / "src"
    if str(src_root) not in sys.path:
        sys.path.insert(0, str(src_root))
    try:
        from wea_cli.report_snapshot import render_report
    except ImportError as exc:
        raise DigestError("Unable to import `wea_cli.report_snapshot.render_report`.") from exc
    return render_report(report).strip()


def run_command(command: list[str], *, root: Path, input_text: str | None = None) -> str:
    env = os.environ.copy()
    env.setdefault("WEA_AGENT", DEFAULT_AGENT)
    try:
        result = subprocess.run(
            command,
            cwd=root,
            capture_output=True,
            input=input_text,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
            env=env,
        )
    except FileNotFoundError as exc:
        raise DigestError(f"Command not found: {command[0]}") from exc
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        stdout = (exc.stdout or "").strip()
        detail = stderr or stdout or "unknown error"
        raise DigestError(f"`{' '.join(command)}` failed: {detail}") from exc
    return result.stdout


def run_wea_report_json(root: Path) -> dict[str, Any]:
    stdout = run_command(
        [sys.executable, "src/wea_cli/cli.py", "--root", str(root), "report", "--json"],
        root=root,
    )
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise DigestError("`wea report --json` returned invalid JSON.") from exc
    if not isinstance(payload, dict):
        raise DigestError("`wea report --json` did not return an object.")
    return payload


def load_gauntlet_next_slots(root: Path) -> dict[str, int]:
    path = root / "ledger" / "trajectory_mints.json"
    if not path.exists():
        return {trajectory: 1 for trajectory in TRAJECTORIES}

    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise DigestError("ledger/trajectory_mints.json is invalid JSON.") from exc

    trajectories = payload.get("trajectories", {})
    if not isinstance(trajectories, dict):
        raise DigestError("ledger/trajectory_mints.json is missing `trajectories`.")

    slots: dict[str, int] = {}
    for trajectory in TRAJECTORIES:
        entry = trajectories.get(trajectory, {})
        next_slot = entry.get("next_slot", 1) if isinstance(entry, dict) else 1
        try:
            slots[trajectory] = int(next_slot)
        except (TypeError, ValueError) as exc:
            raise DigestError(f"Invalid next_slot for {trajectory}: {next_slot!r}") from exc
    return slots


def gather_digest_inputs(root: Path) -> tuple[dict[str, Any], str, dict[str, int]]:
    report = run_wea_report_json(root)
    report_text = _render_report_text(report, root=root)
    gauntlet_slots = load_gauntlet_next_slots(root)
    return report, report_text, gauntlet_slots


def _parse_generated_at(value: str | None) -> datetime:
    if value:
        try:
            return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def build_digest_comment(
    report: dict[str, Any],
    report_text: str,
    gauntlet_slots: dict[str, int],
    *,
    now: datetime | None = None,
) -> str:
    if not report_text.strip():
        raise DigestError("Rendered `wea report` output is empty.")

    economy = report.get("economy", {})
    escrow = report.get("escrow", {})
    timestamp = now or _parse_generated_at(str(report.get("generated_at") or ""))
    stamp = timestamp.strftime("%Y-%m-%d %H:%M UTC")

    summary = (
        f"{economy.get('active_agents', 0)} active / {economy.get('total_agents', 0)} registered "
        f"agents, {economy.get('tasks_paid', 0)} paid / {economy.get('tasks_open', 0)} open tasks, "
        f"{economy.get('transactions_today', 0)} transactions today."
    )
    escrow_line = (
        f"{escrow.get('active_escrows', 0)} active escrows holding "
        f"{escrow.get('total_locked', 0)} WEA."
    )
    gauntlet_line = ", ".join(
        f"{trajectory}->{gauntlet_slots.get(trajectory, 1)}" for trajectory in TRAJECTORIES
    )
    invariant_label = "OK" if escrow.get("invariant_ok") else "BROKEN"
    invariant_line = (
        f"{invariant_label} (expected={escrow.get('expected_total', '?')}, "
        f"actual={escrow.get('actual_total', '?')})"
    )

    body = "\n".join(
        [
            "## Daily Ecosystem Digest",
            f"_Generated {stamp}_",
            "",
            "### WEA Summary",
            summary,
            "",
            "### Escrow Count",
            escrow_line,
            "",
            "### Gauntlet Next Slots",
            gauntlet_line,
            "",
            "### Invariant Status",
            invariant_line,
            "",
            "<details>",
            "<summary>Full <code>wea report</code></summary>",
            "",
            "```text",
            report_text.strip(),
            "```",
            "</details>",
            "",
        ]
    )
    validate_comment(body)
    return body


def validate_comment(body: str) -> None:
    required_sections = (
        "## Daily Ecosystem Digest",
        "### WEA Summary",
        "### Escrow Count",
        "### Gauntlet Next Slots",
        "### Invariant Status",
        "Full <code>wea report</code>",
    )
    missing = [section for section in required_sections if section not in body]
    if missing:
        raise DigestError(f"Digest comment missing required sections: {', '.join(missing)}")


def post_issue_comment(issue: int, body: str, *, root: Path) -> None:
    run_command(
        ["gh", "issue", "comment", str(issue), "--body-file", "-"],
        root=root,
        input_text=body,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run `wea report` and post a formatted daily ecosystem digest."
    )
    parser.add_argument("--issue", type=int, required=True, help="Issue number to comment on")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the formatted comment instead of posting to GitHub",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = repo_root()
    try:
        report, report_text, gauntlet_slots = gather_digest_inputs(root)
        body = build_digest_comment(report, report_text, gauntlet_slots)
        if args.dry_run:
            print(body)
            return 0
        post_issue_comment(args.issue, body, root=root)
        print(f"Posted ecosystem digest to issue #{args.issue}.")
        return 0
    except DigestError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
