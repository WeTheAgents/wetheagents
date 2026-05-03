"""Tests for scripts/circle1/crap_risk_harness.py."""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

from scripts.circle1.crap_risk_harness import (
    build_report,
    compact_checkpoint,
    compute_complexity,
    compute_crap_score,
)


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content), encoding="utf-8")
    return path


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    (root / "src" / "wea_cli").mkdir(parents=True)
    return root


def _function(report: dict, symbol: str) -> dict:
    for item in report["functions"]:
        if item["symbol"] == symbol:
            return item
    raise AssertionError(f"function not found: {symbol}")


def test_complexity_scoring_counts_control_flow() -> None:
    import ast

    node = ast.parse(
        textwrap.dedent(
            """
            def risky(items, flag):
                if flag and items:
                    return [x for x in items if x > 0]
                try:
                    return 1 if flag else 0
                except ValueError:
                    return 2
            """
        )
    ).body[0]

    assert compute_complexity(node) == 7


def test_coverage_unknown_without_explicit_artifact(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    _write(
        root / "src" / "wea_cli" / "tool.py",
        """
        def simple():
            return 1
        """,
    )

    report = build_report(root, scan_date="2026-05-02")
    item = _function(report, "simple")

    assert item["coverage_state"] == "unknown"
    assert item["coverage_percent"] is None
    assert item["crap_score"] is None
    assert "coverage_unknown" in item["risk_reason"]


def test_coverage_known_and_crap_calculation(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    script = _write(
        root / "scripts" / "covered.py",
        """
        def partly(flag):
            if flag:
                return 1
            return 0
        """,
    )
    coverage = {
        "files": {
            str(script.relative_to(root)).replace("\\", "/"): {
                "executed_lines": [2, 3],
                "missing_lines": [4, 5],
            }
        }
    }
    coverage_path = _write(root / "coverage.json", json.dumps(coverage))

    report = build_report(
        root,
        coverage_path=coverage_path,
        coverage_format="json",
        scan_date="2026-05-02",
    )
    item = _function(report, "partly")

    assert item["coverage_state"] == "known"
    assert item["coverage_percent"] == 33.33
    assert item["complexity"] == 2
    assert item["crap_score"] == compute_crap_score(2, 33.33)


def test_coverage_path_normalization_handles_literal_relative_prefix(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    _write(
        root / "scripts" / "prefixed.py",
        """
        def known():
            return 1
        """,
    )
    coverage = {
        "files": {
            "./scripts/prefixed.py": {
                "executed_lines": [3],
                "missing_lines": [],
            }
        }
    }
    coverage_path = _write(root / "coverage.json", json.dumps(coverage))

    report = build_report(root, coverage_path=coverage_path, coverage_format="json")
    item = _function(report, "known")

    assert item["coverage_state"] == "known"
    assert item["coverage_percent"] == 100.0


def test_review_priority_uses_crap_before_complexity_within_band(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    high_complex_lines = [
        "def complex_but_less_crap(x):",
        "    total = 0",
    ]
    for index in range(14):
        high_complex_lines.extend(
            [
                f"    if x == {index}:",
                f"        total += {index}",
            ]
        )
    high_complex_lines.append("    return total")
    script = _write(
        root / "scripts" / "priority.py",
        "\n".join(
            [
                *high_complex_lines,
                "",
                "def crappier(a, b, c):",
                "    total = 0",
                "    if a:",
                "        total += 1",
                "    if b:",
                "        total += 1",
                "    if c:",
                "        total += 1",
                "    return total",
            ]
        ),
    )
    coverage = {
        "files": {
            str(script.relative_to(root)).replace("\\", "/"): {
                "executed_lines": [line for line in range(2, 32) if line != 10],
                "missing_lines": [10, *range(34, 42)],
            }
        }
    }
    coverage_path = _write(root / "coverage.json", json.dumps(coverage))

    report = build_report(root, coverage_path=coverage_path, coverage_format="json")
    symbols = [item["symbol"] for item in report["functions"]]
    complex_item = _function(report, "complex_but_less_crap")
    crappier_item = _function(report, "crappier")

    assert complex_item["risk_band"] == "high"
    assert crappier_item["risk_band"] == "high"
    assert crappier_item["complexity"] < complex_item["complexity"]
    assert crappier_item["crap_score"] > complex_item["crap_score"]
    assert symbols.index("crappier") < symbols.index("complex_but_less_crap")


def test_coverage_artifact_file_without_function_lines_is_not_applicable(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    script = _write(
        root / "scripts" / "not_applicable.py",
        """
        def empty_marker():
            pass
        """,
    )
    coverage = {
        "files": {
            str(script.relative_to(root)).replace("\\", "/"): {
                "executed_lines": [20],
                "missing_lines": [],
            }
        }
    }
    coverage_path = _write(root / "coverage.json", json.dumps(coverage))

    report = build_report(root, coverage_path=coverage_path, coverage_format="json")
    item = _function(report, "empty_marker")

    assert item["coverage_state"] == "not_applicable"
    assert item["crap_score"] is None


def test_observability_annotation_weights_script_function(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    _write(
        root / "scripts" / "publisher.py",
        """
        import subprocess

        def publish(issue):
            subprocess.run(["gh", "issue", "comment", str(issue), "--body", "ok"])
        """,
    )

    report = build_report(root)
    item = _function(report, "publish")

    assert "subprocess_launch" in item["observability_channels"]
    assert "github_comment_side_effect_candidate" in item["observability_channels"]
    assert item["side_effect_weight"] == 3


def test_stable_checkpoint_output_shape(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    _write(
        root / "scripts" / "one.py",
        """
        def alpha(flag):
            if flag:
                return 1
            return 0
        """,
    )
    _write(
        root / "src" / "wea_cli" / "two.py",
        """
        def beta():
            return 2
        """,
    )

    report = build_report(root, scan_date="2026-05-02")
    checkpoint = compact_checkpoint(report, top_n=1)

    assert checkpoint["scan_date"] == "2026-05-02"
    assert checkpoint["summary"]["functions_scanned"] == 2
    assert len(checkpoint["top_risk"]) == 1
    top = checkpoint["top_risk"][0]
    assert {
        "path",
        "symbol",
        "start_line",
        "end_line",
        "complexity",
        "coverage_state",
        "risk_band",
        "tracking_status",
        "evidence_refs",
    } <= set(top)
    assert top["tracking_status"] == "new"
    assert top["evidence_refs"] == []


def test_cli_writes_json_markdown_and_checkpoint(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    _write(root / "scripts" / "tool.py", "def main():\n    print('ok')\n")
    repo_root = Path(__file__).resolve().parents[1]

    json_out = tmp_path / "report.json"
    md_out = tmp_path / "report.md"
    checkpoint_out = tmp_path / "checkpoint.json"
    result = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "circle1" / "crap_risk_harness.py"),
            "--root",
            str(root),
            "--scan-date",
            "2026-05-02",
            "--json-output",
            str(json_out),
            "--markdown-output",
            str(md_out),
            "--checkpoint-output",
            str(checkpoint_out),
            "--max-top",
            "1",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout == ""
    payload = json.loads(json_out.read_text(encoding="utf-8"))
    checkpoint = json.loads(checkpoint_out.read_text(encoding="utf-8"))
    markdown = md_out.read_text(encoding="utf-8")

    assert payload["summary"]["functions_scanned"] == 1
    assert checkpoint["top_risk"][0]["symbol"] == "main"
    assert "Circle-1 CRAP/Observability Risk Report" in markdown
