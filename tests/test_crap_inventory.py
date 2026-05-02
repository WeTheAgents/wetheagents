"""Tests for scripts/circle1/crap_inventory.py."""

from __future__ import annotations

import ast
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from scripts.circle1.crap_inventory import (
    HARNESS_VERSION,
    _compute_complexity,
    _coverage_for_function,
    _crap_score,
    _risk,
    _side_effect_weight,
    build_checkpoint,
    render_markdown,
    scan_crap,
    top_risk,
)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content), encoding="utf-8")
    return path


def _temp_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    (root / "src" / "wea_cli").mkdir(parents=True)
    return root


def _func_node(source: str) -> ast.AST:
    return ast.parse(textwrap.dedent(source)).body[0]


def _record_for(report: dict, path: str, symbol: str) -> dict:
    for entry in report["functions"]:
        if entry["path"] == path and entry["symbol"] == symbol:
            return entry
    raise AssertionError(f"{path}::{symbol} not found")


# --------------------------------------------------------------------------- #
# complexity
# --------------------------------------------------------------------------- #


def test_complexity_baseline_is_one() -> None:
    node = _func_node(
        """
        def f(x):
            return x + 1
        """
    )
    assert _compute_complexity(node) == 1


def test_complexity_counts_branches_loops_excepts_comprehension_ifs() -> None:
    node = _func_node(
        """
        def f(items, flag):
            total = 0
            for x in items:                      # +1 (For)
                if x > 0 and x < 10:             # +1 (If) +1 (BoolOp 2 values)
                    total += x
                elif flag:                       # +1 (If)
                    total -= 1
            try:
                total = total / len(items)
            except ZeroDivisionError:            # +1 (ExceptHandler)
                total = 0
            squares = [v * v for v in items if v]  # +1 (comprehension if)
            assert total >= 0                    # +1 (assert)
            return total + (1 if flag else 2)    # +1 (IfExp)
        """
    )
    assert _compute_complexity(node) == 1 + 8


def test_complexity_does_not_count_nested_function() -> None:
    node = _func_node(
        """
        def outer(x):
            def inner(y):
                if y > 0:
                    return y
                return -y
            return inner(x)
        """
    )
    assert _compute_complexity(node) == 1


def test_complexity_handles_match_cases() -> None:
    node = _func_node(
        """
        def classify(value):
            match value:
                case 0:
                    return "zero"
                case 1:
                    return "one"
                case _:
                    return "many"
        """
    )
    # 3 cases -> +2 (cases after first); base 1 -> 3
    assert _compute_complexity(node) == 3


# --------------------------------------------------------------------------- #
# coverage ingestion (known / unknown / not_applicable)
# --------------------------------------------------------------------------- #


def test_coverage_unknown_when_no_artifact() -> None:
    state, pct = _coverage_for_function(None, "scripts/x.py", 1, 10)
    assert state == "unknown"
    assert pct is None


def test_coverage_unknown_when_artifact_lacks_file() -> None:
    cov = {"scripts/other.py": {"executed": {1, 2}, "missing": set()}}
    state, pct = _coverage_for_function(cov, "scripts/x.py", 1, 10)
    assert state == "unknown"
    assert pct is None


def test_coverage_known_partial() -> None:
    cov = {
        "scripts/x.py": {
            "executed": {10, 12, 14},
            "missing": {11, 13, 15},
        }
    }
    state, pct = _coverage_for_function(cov, "scripts/x.py", 10, 15)
    assert state == "known"
    assert pct == pytest.approx(0.5)


def test_coverage_not_applicable_when_no_executable_lines_in_range() -> None:
    cov = {"scripts/x.py": {"executed": {1}, "missing": {2}}}
    state, pct = _coverage_for_function(cov, "scripts/x.py", 50, 60)
    assert state == "not_applicable"
    assert pct is None


# --------------------------------------------------------------------------- #
# CRAP calculation
# --------------------------------------------------------------------------- #


def test_crap_score_full_coverage_collapses_to_complexity() -> None:
    assert _crap_score(7, 1.0) == 7  # 49 * 0 + 7


def test_crap_score_zero_coverage_blows_up() -> None:
    # 5*5*1 + 5 = 30
    assert _crap_score(5, 0.0) == pytest.approx(30.0)


def test_crap_score_partial_coverage() -> None:
    # complexity=4, coverage=0.5 -> 16 * 0.125 + 4 = 6.0
    assert _crap_score(4, 0.5) == pytest.approx(6.0)


def test_crap_score_none_when_coverage_unknown() -> None:
    assert _crap_score(10, None) is None


# --------------------------------------------------------------------------- #
# side-effect weight + risk band
# --------------------------------------------------------------------------- #


def test_side_effect_weight_picks_worst_channel() -> None:
    assert _side_effect_weight(["logging", "subprocess_launch"]) == 3
    assert _side_effect_weight(["ledger_or_protocol_write_candidate"]) == 4
    assert _side_effect_weight([]) == 0


def test_risk_band_known_high_with_crap_30() -> None:
    band, reason = _risk("known", 5, 30.0, 0)
    assert band == "high"
    assert "crap" in reason


def test_risk_band_known_low_with_crap_below_5() -> None:
    band, _ = _risk("known", 3, 4.0, 4)  # high weight does not affect known
    assert band == "low"


def test_risk_band_unknown_escalates_with_side_effect_weight() -> None:
    base, _ = _risk("unknown", 6, None, 0)
    assert base == "unknown_medium"
    escalated, reason = _risk("unknown", 6, None, 3)
    assert escalated == "unknown_high"
    assert "escalated" in reason


def test_risk_band_unknown_no_escalation_at_low_complexity() -> None:
    band, _ = _risk("unknown", 2, None, 4)
    assert band == "unknown_low"


def test_risk_band_unknown_low_to_medium_when_complexity_3_and_weight_3() -> None:
    band, _ = _risk("unknown", 3, None, 3)
    assert band == "unknown_medium"


# --------------------------------------------------------------------------- #
# observability annotation in scan
# --------------------------------------------------------------------------- #


def test_observability_annotation_joined_for_scripts() -> None:
    inventory = {
        "files": [
            {
                "path": "scripts/foo.py",
                "channels": [
                    {"channel": "subprocess_launch"},
                    {"channel": "logging"},
                ],
            }
        ]
    }
    report = _scan_with_inventory(inventory)
    rec = _record_for(report, "scripts/foo.py", "do_thing")
    assert rec["observability_state"] == "joined"
    assert rec["observability_channels"] == ["logging", "subprocess_launch"]
    assert rec["side_effect_weight"] == 3


def test_observability_state_missing_when_inventory_silent() -> None:
    inventory = {"files": []}
    report = _scan_with_inventory(inventory)
    rec = _record_for(report, "scripts/foo.py", "do_thing")
    assert rec["observability_state"] == "missing"
    assert rec["observability_channels"] == []
    assert rec["side_effect_weight"] == 0


def test_observability_state_not_applicable_for_wea_cli() -> None:
    inventory = {"files": []}
    report = _scan_with_inventory(inventory)
    rec = _record_for(report, "src/wea_cli/cli_module.py", "compute")
    assert rec["observability_state"] == "not_applicable"
    assert rec["observability_channels"] == []


def _scan_with_inventory(inventory: dict) -> dict:
    """Build a fixed temp repo and run scan_crap with a custom inventory."""
    import tempfile

    tmp = Path(tempfile.mkdtemp())
    try:
        root = _temp_repo(tmp)
        _write(
            root / "scripts" / "foo.py",
            """
            import subprocess
            def do_thing(x):
                if x:
                    subprocess.run(["gh", "issue", "comment", "1"])
                return x
            """,
        )
        _write(
            root / "src" / "wea_cli" / "cli_module.py",
            """
            def compute(a, b):
                return a + b
            """,
        )
        return scan_crap(
            root,
            observability_inventory=inventory,
            scan_date="2026-05-02",
        )
    finally:
        # leave tmp tree for pytest tmpdir cleanup; we're inside the test
        # process and don't need to remove it manually
        pass


# --------------------------------------------------------------------------- #
# stable output shape + determinism
# --------------------------------------------------------------------------- #


def test_scan_emits_stable_shape(tmp_path: Path) -> None:
    root = _temp_repo(tmp_path)
    _write(
        root / "scripts" / "a.py",
        """
        def alpha(x):
            return x
        """,
    )
    _write(
        root / "src" / "wea_cli" / "b.py",
        """
        def beta(x):
            if x: return 1
            return 0
        """,
    )

    report = scan_crap(root, observability_inventory={"files": []}, scan_date="2026-05-02")

    assert report["harness_version"] == HARNESS_VERSION
    assert report["scan_date"] == "2026-05-02"
    assert report["coverage_artifact"] is None
    assert report["coverage_artifact_format"] is None
    assert report["scope"]["include"] == ["scripts", "src/wea_cli"]
    assert report["summary"]["function_count"] == 2
    # functions are sorted by (path, start_line, symbol)
    paths = [f["path"] for f in report["functions"]]
    assert paths == sorted(paths)
    # required fields present on every record
    required = {
        "path",
        "symbol",
        "start_line",
        "end_line",
        "complexity",
        "complexity_source",
        "coverage_state",
        "coverage_percent",
        "crap_score",
        "risk_band",
        "risk_reason",
        "observability_channels",
        "observability_state",
        "side_effect_weight",
        "tracking_status",
        "tracking_notes",
        "evidence_refs",
        "notes",
    }
    for f in report["functions"]:
        assert required <= set(f)
        assert f["tracking_status"] == "new"


def test_scan_is_deterministic(tmp_path: Path) -> None:
    root = _temp_repo(tmp_path)
    _write(
        root / "scripts" / "a.py",
        """
        def alpha(x):
            if x:
                return x
            return 0
        """,
    )
    inv = {"files": []}
    a = scan_crap(root, observability_inventory=inv, scan_date="2026-05-02")
    b = scan_crap(root, observability_inventory=inv, scan_date="2026-05-02")
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


# --------------------------------------------------------------------------- #
# coverage end-to-end and refusal to compute crap when unknown
# --------------------------------------------------------------------------- #


def test_scan_with_coverage_artifact_computes_crap(tmp_path: Path) -> None:
    root = _temp_repo(tmp_path)
    _write(
        root / "scripts" / "a.py",
        """
        def alpha(x):
            if x > 0 and x < 10:
                return x
            elif x == 0:
                return 0
            return -1
        """,
    )
    cov = {
        "files": {
            "scripts/a.py": {
                "executed_lines": [2, 3],
                "missing_lines": [4, 5, 6],
            }
        }
    }
    cov_path = tmp_path / "coverage.json"
    cov_path.write_text(json.dumps(cov), encoding="utf-8")

    report = scan_crap(
        root,
        coverage_path=cov_path,
        observability_inventory={"files": []},
        scan_date="2026-05-02",
    )
    rec = _record_for(report, "scripts/a.py", "alpha")
    assert rec["coverage_state"] == "known"
    assert rec["coverage_percent"] is not None
    assert rec["crap_score"] is not None
    assert report["coverage_artifact_format"] == "coverage.py-json"


def test_scan_without_coverage_refuses_to_compute_crap(tmp_path: Path) -> None:
    root = _temp_repo(tmp_path)
    _write(
        root / "scripts" / "a.py",
        """
        def alpha(x):
            if x:
                return x
            return 0
        """,
    )
    report = scan_crap(
        root, observability_inventory={"files": []}, scan_date="2026-05-02"
    )
    for f in report["functions"]:
        assert f["coverage_state"] == "unknown"
        assert f["coverage_percent"] is None
        assert f["crap_score"] is None
        assert f["risk_band"].startswith("unknown")


# --------------------------------------------------------------------------- #
# top_risk + checkpoint + markdown
# --------------------------------------------------------------------------- #


def test_top_risk_orders_high_bands_first(tmp_path: Path) -> None:
    records = [
        {
            "path": "scripts/a.py", "symbol": "low_one", "start_line": 1,
            "end_line": 2, "complexity": 1, "coverage_state": "unknown",
            "coverage_percent": None, "crap_score": None,
            "risk_band": "unknown_low", "side_effect_weight": 0,
            "observability_channels": [], "observability_state": "missing",
        },
        {
            "path": "scripts/b.py", "symbol": "high_one", "start_line": 1,
            "end_line": 30, "complexity": 12, "coverage_state": "unknown",
            "coverage_percent": None, "crap_score": None,
            "risk_band": "unknown_high", "side_effect_weight": 3,
            "observability_channels": ["subprocess_launch"], "observability_state": "joined",
        },
    ]
    ranked = top_risk(records, 10)
    assert ranked[0]["symbol"] == "high_one"
    assert ranked[1]["symbol"] == "low_one"


def test_checkpoint_is_compact_and_carries_tracking_protocol(tmp_path: Path) -> None:
    root = _temp_repo(tmp_path)
    _write(
        root / "scripts" / "a.py",
        """
        def alpha(x):
            return x
        """,
    )
    report = scan_crap(
        root, observability_inventory={"files": []}, scan_date="2026-05-02"
    )
    cp = build_checkpoint(report, top_n=5)
    assert cp["top_n"] == 5
    assert "items" in cp
    assert "functions" not in cp
    assert cp["tracking_protocol"]["default_status"] == "new"
    assert "new" in cp["tracking_protocol"]["valid_statuses"]


def test_markdown_emits_unknown_coverage_banner(tmp_path: Path) -> None:
    root = _temp_repo(tmp_path)
    _write(
        root / "scripts" / "a.py",
        """
        def alpha(x):
            return x
        """,
    )
    report = scan_crap(
        root, observability_inventory={"files": []}, scan_date="2026-05-02"
    )
    md = render_markdown(report, limit=5)
    assert "No coverage artifact supplied" in md
    assert "Risk band counts" in md


# --------------------------------------------------------------------------- #
# CLI black-box smoke
# --------------------------------------------------------------------------- #


def test_cli_runs_against_fixture(tmp_path: Path) -> None:
    root = _temp_repo(tmp_path)
    _write(
        root / "scripts" / "a.py",
        """
        def alpha(x):
            return x
        """,
    )
    repo_root = Path(__file__).resolve().parent.parent
    env = {
        "PYTHONPATH": str(repo_root),
    }
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.circle1.crap_inventory",
            "--root",
            str(root),
            "--scan-date",
            "2026-05-02",
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
        cwd=str(repo_root),
        env={**__import__("os").environ, **env},
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["harness_version"] == HARNESS_VERSION
    assert payload["summary"]["function_count"] >= 1
