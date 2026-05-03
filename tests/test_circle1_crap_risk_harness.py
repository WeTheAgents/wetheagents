"""Tests for scripts/circle1/crap_risk_harness.py."""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

from scripts.circle1.crap_risk_harness import (
    build_report,
    collect_functions,
    compute_crap_score,
    load_coverage_artifact,
    render_markdown,
)


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content), encoding="utf-8")
    return path


def _temp_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    (root / "src" / "wea_cli").mkdir(parents=True)
    return root


def _entry(report: dict, symbol: str) -> dict:
    for item in report["functions"]:
        if item["symbol"] == symbol:
            return item
    raise AssertionError(f"{symbol} not found")


def test_complexity_scoring_counts_branch_shapes(tmp_path: Path) -> None:
    root = _temp_repo(tmp_path)
    sample = _write(
        root / "scripts" / "risk.py",
        """
        def risky(x):
            if x and x > 0:
                return 1
            for item in range(x):
                if item % 2:
                    return item
            return 0
        """,
    )

    records, error = collect_functions(sample, root)

    assert error is None
    assert records[0].symbol == "risky"
    assert records[0].complexity == 5


def test_coverage_unknown_without_explicit_artifact(tmp_path: Path) -> None:
    root = _temp_repo(tmp_path)
    _write(
        root / "src" / "wea_cli" / "tool.py",
        """
        def simple():
            return "ok"
        """,
    )

    report = build_report(root, scan_date="2026-05-02")
    entry = _entry(report, "simple")

    assert entry["coverage_state"] == "unknown"
    assert entry["coverage_percent"] is None
    assert entry["crap_score"] is None
    assert "coverage_unknown" in entry["risk_reason"]


def test_coverage_json_known_state_and_crap_calculation(tmp_path: Path) -> None:
    root = _temp_repo(tmp_path)
    _write(
        root / "src" / "wea_cli" / "covered.py",
        """
        def covered(flag):
            if flag:
                return 1
            return 0
        """,
    )
    coverage_path = _write(
        root / "coverage.json",
        json.dumps(
            {
                "files": {
                    "src/wea_cli/covered.py": {
                        "executed_lines": [2, 3],
                        "missing_lines": [4, 5],
                        "excluded_lines": [],
                    }
                }
            }
        ),
    )

    report = build_report(root, coverage_path=coverage_path, scan_date="2026-05-02")
    entry = _entry(report, "covered")

    assert entry["coverage_state"] == "known"
    assert entry["coverage_percent"] == 0.5
    assert entry["complexity"] == 2
    assert entry["crap_score"] == compute_crap_score(2, 0.5)


def test_coverage_xml_ingestion(tmp_path: Path) -> None:
    root = _temp_repo(tmp_path)
    coverage_path = _write(
        root / "coverage.xml",
        """
        <coverage>
          <packages>
            <package>
              <classes>
                <class filename="scripts/tool.py">
                  <lines>
                    <line number="1" hits="1"/>
                    <line number="2" hits="0"/>
                  </lines>
                </class>
              </classes>
            </package>
          </packages>
        </coverage>
        """,
    )

    coverage = load_coverage_artifact(coverage_path, root)

    assert coverage["scripts/tool.py"].executed_lines == {1}
    assert coverage["scripts/tool.py"].missing_lines == {2}


def test_coverage_path_normalization_only_removes_literal_dot_slash_prefix(
    tmp_path: Path,
) -> None:
    root = _temp_repo(tmp_path)
    coverage_path = _write(
        root / "coverage.json",
        json.dumps(
            {
                "files": {
                    "./scripts/tool.py": {
                        "executed_lines": [1],
                        "missing_lines": [],
                    },
                    ".hidden/scripts/tool.py": {
                        "executed_lines": [2],
                        "missing_lines": [],
                    },
                }
            }
        ),
    )

    coverage = load_coverage_artifact(coverage_path, root)

    assert "scripts/tool.py" in coverage
    assert ".hidden/scripts/tool.py" in coverage
    assert "hidden/scripts/tool.py" not in coverage


def test_coverage_artifact_with_no_function_lines_is_not_applicable(
    tmp_path: Path,
) -> None:
    root = _temp_repo(tmp_path)
    _write(
        root / "src" / "wea_cli" / "empty_span.py",
        """
        def outside_artifact():
            return "ok"
        """,
    )
    coverage_path = _write(
        root / "coverage.json",
        json.dumps(
            {
                "files": {
                    "src/wea_cli/empty_span.py": {
                        "executed_lines": [99],
                        "missing_lines": [],
                        "excluded_lines": [],
                    }
                }
            }
        ),
    )

    report = build_report(root, coverage_path=coverage_path, scan_date="2026-05-02")
    entry = _entry(report, "outside_artifact")

    assert entry["coverage_state"] == "not_applicable"
    assert entry["crap_score"] is None
    assert "coverage_unknown" not in entry["risk_reason"]


def test_observability_annotation_is_function_local(tmp_path: Path) -> None:
    root = _temp_repo(tmp_path)
    _write(
        root / "scripts" / "observable.py",
        """
        def quiet():
            return "ok"

        def noisy():
            print("human")
            return "ok"
        """,
    )

    report = build_report(root, scan_date="2026-05-02")
    quiet = _entry(report, "quiet")
    noisy = _entry(report, "noisy")

    assert quiet["observability_channels"] == []
    assert noisy["observability_channels"] == ["stdout_cli_output"]
    assert noisy["side_effect_weight"] == 1


def test_stable_checkpoint_shape_and_tracking_fields(tmp_path: Path) -> None:
    root = _temp_repo(tmp_path)
    _write(
        root / "scripts" / "a.py",
        """
        def alpha(value):
            if value:
                print(value)
            return value
        """,
    )
    _write(root / "src" / "wea_cli" / "b.py", "def beta():\n    return 1\n")

    report = build_report(
        root, scan_date="2026-05-02", max_json_functions=1
    )

    assert list(report) == [
        "scan_date",
        "harness_version",
        "scope",
        "scoring",
        "summary",
        "truncation",
        "tracking_contract",
        "compact_functions",
        "functions",
    ]
    assert report["summary"]["functions"] == 2
    assert report["truncation"]["canonical_functions_truncated"] is False
    assert report["truncation"]["omitted_functions"] == 1
    assert report["truncation"]["omitted_from_compact"] == 1
    assert len(report["compact_functions"]) == 1
    assert len(report["functions"]) == 2
    assert {
        "tracking_id",
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
        "side_effect_weight",
        "tracking_status",
        "tracking_notes",
        "evidence_refs",
    } <= set(report["compact_functions"][0])
    assert report["compact_functions"][0]["tracking_id"] == (
        f"{report['compact_functions'][0]['path']}:"
        f"{report['compact_functions'][0]['start_line']}:"
        f"{report['compact_functions'][0]['symbol']}"
    )


def test_markdown_warns_when_all_coverage_is_unknown(tmp_path: Path) -> None:
    root = _temp_repo(tmp_path)
    _write(root / "scripts" / "tool.py", "def main():\n    return 'ok'\n")

    markdown = render_markdown(build_report(root, scan_date="2026-05-02"))

    assert "WARNING: no coverage artifact was supplied" in markdown
    assert "blank CRAP cells mean CRAP was not computed" in markdown


def test_cli_writes_json_and_markdown(tmp_path: Path) -> None:
    root = _temp_repo(tmp_path)
    _write(root / "scripts" / "tool.py", "def main():\n    print('ok')\n")
    out_json = tmp_path / "checkpoint.json"
    out_md = tmp_path / "checkpoint.md"
    repo_root = Path(__file__).resolve().parents[1]

    result = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "circle1" / "crap_risk_harness.py"),
            "--root",
            str(root),
            "--scan-date",
            "2026-05-02",
            "--output",
            str(out_json),
            "--markdown-output",
            str(out_md),
            "--max-json-functions",
            "5",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "Saved JSON" in result.stderr
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    markdown = out_md.read_text(encoding="utf-8")
    assert payload["scan_date"] == "2026-05-02"
    assert len(payload["functions"]) == 1
    assert len(payload["compact_functions"]) == 1
    assert payload["functions"][0]["coverage_state"] == "unknown"
    assert "# Circle-1 CRAP Risk Pilot" in markdown
    assert "WARNING: no coverage artifact was supplied" in markdown
