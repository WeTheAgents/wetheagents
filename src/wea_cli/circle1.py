"""Circle-1 offline director utilities (read-only)."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


def _load_build_sweep() -> Callable[..., dict[str, Any]]:
    """Load scripts.circle1_director_sweep.build_sweep with a worktree-safe fallback."""
    try:
        from scripts.circle1_director_sweep import build_sweep  # type: ignore[import-not-found]

        return build_sweep
    except ModuleNotFoundError:
        sweep_path = Path(__file__).resolve().parents[2] / "scripts" / "circle1_director_sweep.py"
        spec = importlib.util.spec_from_file_location("circle1_director_sweep", sweep_path)
        if spec is None or spec.loader is None:
            raise
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        return mod.build_sweep  # type: ignore[attr-defined]


def _print_human(sweep: dict[str, Any]) -> None:
    print(f"has_drift={sweep['has_drift']}")

    drift_counts: dict[str, int] = sweep.get("drift_counts", {}) or {}
    if drift_counts:
        print("task_index_drift_counts:")
        for key in sorted(drift_counts.keys()):
            print(f"  - {key}={drift_counts[key]}")

    print("")
    print("returncodes:")
    rc = sweep.get("return_codes", {}) or {}
    for name in [
        "check_invariant",
        "check_task_escrow_sync",
        "report_task_index_stale_open",
        "report_task_index_drift_json",
    ]:
        if name in rc:
            print(f"  - {name}={rc[name]}")

    print("")
    print(f"next={sweep['recommended_next_action']}")


def cmd_circle1_sweep(args: argparse.Namespace) -> int:
    """Run the offline Circle-1 director sweep (no ledger writes)."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    build_sweep = _load_build_sweep()

    repo_root = Path(getattr(args, "root", ".")).resolve()
    limit = int(getattr(args, "limit", 20))
    sweep = build_sweep(repo_root, limit=limit)

    out = getattr(args, "out", None)
    if out:
        out_path = Path(out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(sweep, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        latest_path = out_path.parent / "circle1_sweep_latest.json"
        latest_path.write_text(json.dumps(sweep, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    as_json = bool(getattr(args, "json", False) or out)
    if as_json:
        print(json.dumps(sweep, indent=2, ensure_ascii=False))
    else:
        _print_human(sweep)

    fail = bool(getattr(args, "fail", False))
    return 1 if (fail and sweep.get("has_drift")) else 0


def default_sweep_out_path(repo_root: Path) -> Path:
    """Return a safe default `.wea_runs` JSON path for the current wall-clock time."""
    ts = datetime.now().astimezone().strftime("%Y-%m-%dT%H-%M-%S%z")
    return repo_root / ".wea_runs" / f"circle1_sweep_{ts}.json"

