"""Circle-1 CRAP/observability risk harness for Python functions.

The harness scans function and method definitions under scripts/ and
src/wea_cli/, computes a static cyclomatic-complexity signal, optionally joins
line coverage from coverage.py JSON or Cobertura-style XML, annotates scripts/
with the existing Circle-1 observability inventory, and emits checkpointable
JSON plus a concise markdown top-risk report.

It is advisory only. Missing coverage stays unknown; it is never converted into
0% or 100% coverage.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
_ROOT_HINT = _HERE.parents[1]
if str(_ROOT_HINT) not in sys.path:
    sys.path.insert(0, str(_ROOT_HINT))

from scripts.circle1.observability_inventory import scan_observability  # noqa: E402

HARNESS_VERSION = "v0"
DEFAULT_INCLUDE_PATTERNS = ("scripts/**/*.py", "src/wea_cli/**/*.py")
COMPLEXITY_SOURCE = "python_ast_cyclomatic_v0"
COVERAGE_SOURCE_UNKNOWN = "none_supplied"

SIDE_EFFECT_WEIGHTS: dict[str, int] = {
    "ledger_or_protocol_write_candidate": 4,
    "github_comment_side_effect_candidate": 4,
    "subprocess_launch": 3,
    "network_external_call": 3,
    "file_artifact_write": 2,
    "stderr_output": 2,
    "unknown_ambiguous_side_effect": 2,
    "stdout_cli_output": 1,
    "logging": 1,
}


@dataclass(frozen=True)
class FunctionRecord:
    path: str
    symbol: str
    start_line: int
    end_line: int
    complexity: int
    function_type: str


@dataclass(frozen=True)
class CoverageFile:
    executed_lines: set[int] = field(default_factory=set)
    missing_lines: set[int] = field(default_factory=set)
    excluded_lines: set[int] = field(default_factory=set)
    source: str = ""

    @property
    def measured_lines(self) -> set[int]:
        return self.executed_lines | self.missing_lines


class ComplexityVisitor(ast.NodeVisitor):
    """Compute a small, deterministic cyclomatic-complexity approximation."""

    def __init__(self) -> None:
        self.complexity = 1

    def visit_If(self, node: ast.If) -> None:
        self.complexity += 1
        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:
        self.complexity += 1
        self.generic_visit(node)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self.complexity += 1
        self.generic_visit(node)

    def visit_While(self, node: ast.While) -> None:
        self.complexity += 1
        self.generic_visit(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        self.complexity += 1
        self.generic_visit(node)

    def visit_IfExp(self, node: ast.IfExp) -> None:
        self.complexity += 1
        self.generic_visit(node)

    def visit_Assert(self, node: ast.Assert) -> None:
        self.complexity += 1
        self.generic_visit(node)

    def visit_BoolOp(self, node: ast.BoolOp) -> None:
        self.complexity += max(0, len(node.values) - 1)
        self.generic_visit(node)

    def visit_comprehension(self, node: ast.comprehension) -> None:
        self.complexity += 1 + len(node.ifs)
        self.generic_visit(node)

    def visit_Match(self, node: ast.Match) -> None:
        self.complexity += len(node.cases)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        # Nested function bodies are separate review units.
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        return

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self.complexity += 1


def compute_complexity(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    visitor = ComplexityVisitor()
    for statement in node.body:
        visitor.visit(statement)
    return visitor.complexity


def _rel(path: Path, root: Path) -> str:
    return str(path.relative_to(root)).replace("\\", "/")


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    seen: set[Path] = set()
    result: list[Path] = []
    for path in sorted(paths):
        resolved = path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            result.append(path)
    return result


def discover_python_files(root: Path, patterns: tuple[str, ...]) -> list[Path]:
    paths: list[Path] = []
    for pattern in patterns:
        paths.extend(p for p in root.glob(pattern) if p.is_file())
    return _dedupe_paths(paths)


def _function_type(node: ast.AST) -> str:
    if isinstance(node, ast.AsyncFunctionDef):
        return "async_function"
    return "function"


class FunctionCollector(ast.NodeVisitor):
    def __init__(self, path: Path, root: Path) -> None:
        self.path = path
        self.root = root
        self.scope: list[str] = []
        self.records: list[FunctionRecord] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.scope.append(node.name)
        for statement in node.body:
            self.visit(statement)
        self.scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._record(node)
        self.scope.append(node.name)
        for statement in node.body:
            self.visit(statement)
        self.scope.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._record(node)
        self.scope.append(node.name)
        for statement in node.body:
            self.visit(statement)
        self.scope.pop()

    def _record(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        symbol = ".".join([*self.scope, node.name])
        self.records.append(
            FunctionRecord(
                path=_rel(self.path, self.root),
                symbol=symbol,
                start_line=node.lineno,
                end_line=getattr(node, "end_lineno", node.lineno),
                complexity=compute_complexity(node),
                function_type=_function_type(node),
            )
        )


def collect_functions(
    path: Path, root: Path
) -> tuple[list[FunctionRecord], str | None]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return [], f"read_error: {exc}"
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return [], f"parse_error: {exc}"
    collector = FunctionCollector(path, root)
    collector.visit(tree)
    return collector.records, None


def load_coverage_artifact(path: Path, root: Path) -> dict[str, CoverageFile]:
    suffix = path.suffix.lower()
    if suffix == ".json":
        return _load_coverage_json(path, root)
    if suffix == ".xml":
        return _load_coverage_xml(path, root)
    raise ValueError(f"unsupported coverage artifact extension: {path.suffix}")


def _normalize_coverage_path(raw: str, root: Path) -> str:
    path = Path(raw)
    if path.is_absolute():
        try:
            return _rel(path.resolve(), root)
        except ValueError:
            return str(path).replace("\\", "/")
    return raw.replace("\\", "/").lstrip("./")


def _lines_from_json_file(entry: dict[str, Any], source: str) -> CoverageFile:
    executed = {int(line) for line in entry.get("executed_lines", [])}
    missing = {int(line) for line in entry.get("missing_lines", [])}
    excluded = {int(line) for line in entry.get("excluded_lines", [])}
    return CoverageFile(executed, missing, excluded, source)


def _load_coverage_json(path: Path, root: Path) -> dict[str, CoverageFile]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    files = payload.get("files")
    if not isinstance(files, dict):
        raise ValueError("coverage JSON has no files object")
    result: dict[str, CoverageFile] = {}
    for raw_name, entry in files.items():
        if isinstance(entry, dict):
            result[_normalize_coverage_path(raw_name, root)] = _lines_from_json_file(
                entry, f"coverage_json:{path.name}"
            )
    return result


def _load_coverage_xml(path: Path, root: Path) -> dict[str, CoverageFile]:
    tree = ET.parse(path)
    result: dict[str, CoverageFile] = {}
    for class_node in tree.findall(".//class"):
        filename = class_node.attrib.get("filename")
        if not filename:
            continue
        executed: set[int] = set()
        missing: set[int] = set()
        for line_node in class_node.findall(".//line"):
            number = line_node.attrib.get("number")
            if number is None:
                continue
            line_no = int(number)
            hits = int(line_node.attrib.get("hits", "0"))
            if hits > 0:
                executed.add(line_no)
            else:
                missing.add(line_no)
        result[_normalize_coverage_path(filename, root)] = CoverageFile(
            executed, missing, set(), f"coverage_xml:{path.name}"
        )
    return result


def coverage_for_function(
    record: FunctionRecord, coverage_files: dict[str, CoverageFile] | None
) -> dict[str, Any]:
    if coverage_files is None:
        return {
            "coverage_state": "unknown",
            "coverage_percent": None,
            "coverage_source": COVERAGE_SOURCE_UNKNOWN,
            "covered_lines": None,
            "measured_lines": None,
        }
    file_cov = coverage_files.get(record.path)
    if file_cov is None:
        return {
            "coverage_state": "unknown",
            "coverage_percent": None,
            "coverage_source": "artifact_missing_file",
            "covered_lines": None,
            "measured_lines": None,
        }
    function_lines = set(range(record.start_line, record.end_line + 1))
    measured = function_lines & file_cov.measured_lines
    if not measured:
        return {
            "coverage_state": "not_applicable",
            "coverage_percent": None,
            "coverage_source": file_cov.source,
            "covered_lines": 0,
            "measured_lines": 0,
        }
    covered = measured & file_cov.executed_lines
    percent = round(len(covered) / len(measured), 6)
    return {
        "coverage_state": "known",
        "coverage_percent": percent,
        "coverage_source": file_cov.source,
        "covered_lines": len(covered),
        "measured_lines": len(measured),
    }


def compute_crap_score(complexity: int, coverage_percent: float) -> float:
    return round((complexity**2) * ((1 - coverage_percent) ** 3) + complexity, 6)


def _observability_by_file(
    root: Path, scan_date: str | None
) -> dict[str, dict[str, Any]]:
    scripts_dir = root / "scripts"
    if not scripts_dir.is_dir():
        return {}
    report = scan_observability(root, scan_date=scan_date, include_init=True)
    return {entry["path"]: entry for entry in report.get("files", [])}


def observability_annotation(
    record: FunctionRecord, obs_by_file: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    entry = obs_by_file.get(record.path)
    if entry is None:
        return {
            "observability_channels": [],
            "side_effect_weight": 0,
            "side_effect_reason": "no scripts/ observability entry",
        }
    channels: set[str] = set()
    for detection in entry.get("channels", []):
        for evidence in detection.get("evidence", []):
            line_no = evidence.get("line")
            if (
                isinstance(line_no, int)
                and record.start_line <= line_no <= record.end_line
            ):
                channels.add(detection["channel"])
    ordered = sorted(channels)
    weight = max(
        (SIDE_EFFECT_WEIGHTS.get(channel, 1) for channel in ordered), default=0
    )
    if ordered:
        reason = "function body contains scripts/ observability channel evidence"
    else:
        reason = "no function-local scripts/ observability channel evidence"
    return {
        "observability_channels": ordered,
        "side_effect_weight": weight,
        "side_effect_reason": reason,
    }


def risk_for_known_coverage(
    complexity: int, crap_score: float, side_effect_weight: int
) -> tuple[str, str, float]:
    review_score = crap_score + (side_effect_weight * 2)
    if crap_score >= 30 or (complexity >= 10 and side_effect_weight >= 3):
        return (
            "critical",
            "known coverage CRAP is high or high complexity has hard side effects",
            review_score,
        )
    if crap_score >= 15 or (complexity >= 7 and side_effect_weight >= 2):
        return (
            "high",
            "known coverage CRAP or side-effect-adjusted complexity is elevated",
            review_score,
        )
    if crap_score >= 7 or complexity >= 5 or side_effect_weight >= 3:
        return (
            "medium",
            "known coverage CRAP is moderate or side effects need review",
            review_score,
        )
    return (
        "low",
        "known coverage and complexity are low-risk by this advisory rule",
        review_score,
    )


def risk_for_unknown_coverage(
    complexity: int, side_effect_weight: int
) -> tuple[str, str, float]:
    review_score = complexity + (side_effect_weight * 2)
    if complexity >= 12 or (complexity >= 8 and side_effect_weight >= 3):
        return (
            "critical",
            "coverage_unknown with high complexity and hard side-effect surface",
            review_score,
        )
    if complexity >= 8 or (complexity >= 5 and side_effect_weight >= 3):
        return (
            "high",
            "coverage_unknown with elevated complexity or hard side-effect surface",
            review_score,
        )
    if complexity >= 4 or side_effect_weight >= 2:
        return (
            "medium",
            "coverage_unknown fallback: modest complexity or observable side effect",
            review_score,
        )
    return (
        "low",
        "coverage_unknown fallback: simple function and low side-effect evidence",
        review_score,
    )


def build_entry(
    record: FunctionRecord,
    coverage_files: dict[str, CoverageFile] | None,
    obs_by_file: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    cov = coverage_for_function(record, coverage_files)
    obs = observability_annotation(record, obs_by_file)
    coverage_state = cov["coverage_state"]
    crap_score = None
    if coverage_state == "known":
        crap_score = compute_crap_score(record.complexity, cov["coverage_percent"])
        risk_band, risk_reason, review_score = risk_for_known_coverage(
            record.complexity, crap_score, obs["side_effect_weight"]
        )
    elif coverage_state == "not_applicable":
        risk_band, risk_reason, review_score = risk_for_unknown_coverage(
            record.complexity, obs["side_effect_weight"]
        )
        risk_reason = risk_reason.replace(
            "coverage_unknown", "coverage_not_applicable"
        )
    else:
        risk_band, risk_reason, review_score = risk_for_unknown_coverage(
            record.complexity, obs["side_effect_weight"]
        )
    return {
        "path": record.path,
        "symbol": record.symbol,
        "start_line": record.start_line,
        "end_line": record.end_line,
        "function_type": record.function_type,
        "complexity": record.complexity,
        "complexity_source": COMPLEXITY_SOURCE,
        "coverage_state": coverage_state,
        "coverage_percent": cov["coverage_percent"],
        "coverage_source": cov["coverage_source"],
        "covered_lines": cov["covered_lines"],
        "measured_lines": cov["measured_lines"],
        "crap_score": crap_score,
        "risk_band": risk_band,
        "risk_reason": risk_reason,
        "review_priority_score": round(review_score, 6),
        "observability_channels": obs["observability_channels"],
        "side_effect_weight": obs["side_effect_weight"],
        "side_effect_reason": obs["side_effect_reason"],
        "tracking_status": "new",
        "tracking_notes": "",
        "evidence_refs": [],
    }


def _sort_key(entry: dict[str, Any]) -> tuple[Any, ...]:
    return (
        -float(entry["review_priority_score"]),
        -int(entry["complexity"]),
        entry["path"],
        int(entry["start_line"]),
        entry["symbol"],
    )


def summarize(
    entries: list[dict[str, Any]],
    scanned_files: int,
    skipped_files: list[dict[str, str]],
    parse_errors: list[dict[str, str]],
) -> dict[str, Any]:
    bands = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    coverage_states = {"known": 0, "unknown": 0, "not_applicable": 0}
    for entry in entries:
        bands[entry["risk_band"]] += 1
        coverage_states[entry["coverage_state"]] += 1
    return {
        "scanned_files": scanned_files,
        "functions": len(entries),
        "risk_bands": bands,
        "coverage_states": coverage_states,
        "skipped_files": skipped_files,
        "parse_errors": parse_errors,
    }


def build_report(
    root: Path,
    coverage_path: Path | None = None,
    scan_date: str | None = None,
    include_patterns: tuple[str, ...] = DEFAULT_INCLUDE_PATTERNS,
    max_json_functions: int | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    scan_date = scan_date or date.today().isoformat()
    files = discover_python_files(root, include_patterns)
    skipped_files: list[dict[str, str]] = []
    parse_errors: list[dict[str, str]] = []
    records: list[FunctionRecord] = []
    for path in files:
        file_records, error = collect_functions(path, root)
        if error is not None:
            parse_errors.append({"path": _rel(path, root), "reason": error})
        records.extend(file_records)

    coverage_files = None
    coverage_artifact = None
    if coverage_path is not None:
        coverage_artifact = str(coverage_path)
        coverage_files = load_coverage_artifact(coverage_path, root)

    obs_by_file = _observability_by_file(root, scan_date)
    entries = [
        build_entry(record, coverage_files, obs_by_file)
        for record in sorted(
            records, key=lambda item: (item.path, item.start_line, item.symbol)
        )
    ]
    entries = sorted(entries, key=_sort_key)
    omitted = 0
    if max_json_functions is not None and max_json_functions >= 0:
        omitted = max(0, len(entries) - max_json_functions)
        entries = entries[:max_json_functions]

    summary = summarize(
        entries if omitted == 0 else [
            build_entry(record, coverage_files, obs_by_file) for record in records
        ],
        scanned_files=len(files),
        skipped_files=skipped_files,
        parse_errors=parse_errors,
    )
    return {
        "scan_date": scan_date,
        "harness_version": HARNESS_VERSION,
        "scope": {
            "include": list(include_patterns),
            "default_exclusions": [],
            "coverage_artifact": coverage_artifact,
        },
        "scoring": {
            "complexity_source": COMPLEXITY_SOURCE,
            "crap_formula": "complexity^2 * (1 - coverage)^3 + complexity",
            "missing_coverage_rule": "coverage_unknown; CRAP not computed",
            "side_effect_weights": SIDE_EFFECT_WEIGHTS,
        },
        "summary": summary,
        "truncation": {
            "max_json_functions": max_json_functions,
            "omitted_functions": omitted,
        },
        "tracking_contract": {
            "allowed_statuses": [
                "new",
                "watched",
                "correlated",
                "retired",
                "inconclusive",
            ],
            "future_evidence_refs": [
                "review_finding",
                "bug_fix",
                "redteam_note",
                "follow_up_hardening_task",
                "test_addition",
            ],
            "inspection_window": (
                "next Circle-1 checkpoint after merge plus the next five accepted "
                "Python code-change tasks touching scripts/ or src/wea_cli"
            ),
        },
        "functions": entries,
    }


def render_markdown(report: dict[str, Any], top: int = 20) -> str:
    summary = report["summary"]
    coverage = summary["coverage_states"]
    bands = summary["risk_bands"]
    lines = [
        "# Circle-1 CRAP Risk Pilot",
        "",
        f"- scan_date: {report['scan_date']}",
        f"- harness_version: {report['harness_version']}",
        f"- scanned_files: {summary['scanned_files']}",
        f"- functions_seen: {summary['functions']}",
        (
            "- coverage_states: "
            f"known={coverage['known']}, unknown={coverage['unknown']}, "
            f"not_applicable={coverage['not_applicable']}"
        ),
        (
            "- risk_bands: "
            f"critical={bands['critical']}, high={bands['high']}, "
            f"medium={bands['medium']}, low={bands['low']}"
        ),
        "",
        "## Top Risk Functions",
        "",
        "| rank | path | symbol | complexity | coverage | CRAP | side effects | risk |",
        "|---:|---|---|---:|---|---:|---|---|",
    ]
    shown = report["functions"][:top]
    if not shown:
        lines.append("| - | - | - | - | - | - | - | - |")
    for index, entry in enumerate(shown, 1):
        coverage_text = entry["coverage_state"]
        if entry["coverage_percent"] is not None:
            coverage_text = f"{entry['coverage_percent']:.2%}"
        crap = "" if entry["crap_score"] is None else f"{entry['crap_score']:.3f}"
        side_effects = ", ".join(entry["observability_channels"]) or "none"
        lines.append(
            "| "
            f"{index} | {entry['path']}:{entry['start_line']} | "
            f"{entry['symbol']} | {entry['complexity']} | {coverage_text} | "
            f"{crap} | {side_effects} | {entry['risk_band']} |"
        )
    omitted = report["truncation"]["omitted_functions"]
    if omitted:
        lines.extend(
            [
                "",
                "JSON checkpoint is compact: "
                f"{omitted} lower-priority functions omitted.",
            ]
        )
    if summary["parse_errors"]:
        lines.extend(["", "## Parse Errors", ""])
        for error in summary["parse_errors"]:
            lines.append(f"- {error['path']}: {error['reason']}")
    lines.extend(
        [
            "",
            "## Tracking",
            "",
            "Future sweeps update `tracking_status`, `tracking_notes`, and "
            "`evidence_refs` when a watched function later correlates with a "
            "review finding, bug fix, redteam note, hardening task, or test addition.",
            "",
        ]
    )
    return "\n".join(lines)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + ("" if text.endswith("\n") else "\n"), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Circle-1 CRAP/observability risk harness"
    )
    parser.add_argument("--root", default=".", help="Repo root directory")
    parser.add_argument("--coverage", default=None, help="coverage.py JSON or XML")
    parser.add_argument("--output", default=None, help="Optional JSON output path")
    parser.add_argument(
        "--markdown-output", default=None, help="Optional markdown report path"
    )
    parser.add_argument("--scan-date", default=None, help="ISO scan date")
    parser.add_argument("--top", type=int, default=20, help="Markdown top-risk rows")
    parser.add_argument(
        "--max-json-functions",
        type=int,
        default=None,
        help="Limit JSON functions to top N for compact checkpoints",
    )
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"ERROR: not a directory: {root}", file=sys.stderr)
        return 1
    coverage_path = Path(args.coverage).resolve() if args.coverage else None
    if coverage_path is not None and not coverage_path.is_file():
        print(f"ERROR: coverage artifact not found: {coverage_path}", file=sys.stderr)
        return 1

    try:
        report = build_report(
            root,
            coverage_path=coverage_path,
            scan_date=args.scan_date,
            max_json_functions=args.max_json_functions,
        )
    except (OSError, ValueError, ET.ParseError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    payload = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        _write_text(Path(args.output), payload)
        print(f"Saved JSON: {args.output}", file=sys.stderr)
    else:
        print(payload)
    if args.markdown_output:
        _write_text(Path(args.markdown_output), render_markdown(report, top=args.top))
        print(f"Saved markdown: {args.markdown_output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
