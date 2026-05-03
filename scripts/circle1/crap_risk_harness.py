"""Circle-1 CRAP/observability risk harness for Python functions.

This scanner is advisory inventory only. It reads Python source, optional
coverage.py JSON or Cobertura XML artifacts, and the Circle-1 scripts
observability inventory. It does not import scanned modules, run scanned code,
mutate ledger data, or enforce CI policy.
"""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

try:
    from scripts.circle1.observability_inventory import scan_observability
except ModuleNotFoundError:  # pragma: no cover - script execution fallback
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    sys.modules.pop("scripts", None)
    from scripts.circle1.observability_inventory import scan_observability

HARNESS_VERSION = "v0"
DEFAULT_INCLUDE_PATTERNS = ("scripts/**/*.py", "src/wea_cli/**/*.py")
TRACKING_STATUSES = ("new", "watched", "correlated", "retired", "inconclusive")

SIDE_EFFECT_WEIGHTS: dict[str, int] = {
    "stdout_cli_output": 1,
    "stderr_output": 1,
    "logging": 1,
    "file_artifact_write": 2,
    "unknown_ambiguous_side_effect": 2,
    "subprocess_launch": 3,
    "github_comment_side_effect_candidate": 3,
    "network_external_call": 3,
    "ledger_or_protocol_write_candidate": 4,
}

RISK_SEVERITY = {"critical": 4, "high": 3, "medium": 2, "low": 1}


@dataclass(frozen=True)
class FunctionRecord:
    path: str
    symbol: str
    start_line: int
    end_line: int
    complexity: int
    complexity_source: str


@dataclass(frozen=True)
class CoverageResult:
    state: str
    percent: float | None
    covered_lines: int | None
    measured_lines: int | None
    source: str
    reason: str


class CoverageIndex:
    def __init__(
        self,
        *,
        source_path: Path | None = None,
        files: dict[str, dict[int, int | bool]] | None = None,
        parse_errors: list[str] | None = None,
    ) -> None:
        self.source_path = source_path
        self.files = files or {}
        self.parse_errors = parse_errors or []

    @property
    def supplied(self) -> bool:
        return self.source_path is not None

    @classmethod
    def missing(cls) -> CoverageIndex:
        return cls()

    def coverage_for(self, function: FunctionRecord) -> CoverageResult:
        if not self.supplied:
            return CoverageResult(
                state="unknown",
                percent=None,
                covered_lines=None,
                measured_lines=None,
                source="none",
                reason="no explicit coverage artifact supplied",
            )

        lines = self.files.get(function.path)
        if lines is None:
            lines = self._suffix_match(function.path)
        if lines is None:
            return CoverageResult(
                state="unknown",
                percent=None,
                covered_lines=None,
                measured_lines=None,
                source=str(self.source_path),
                reason="coverage artifact supplied but file was not present",
            )

        measured = {
            line: covered
            for line, covered in lines.items()
            if function.start_line < line <= function.end_line
        }
        if not measured:
            return CoverageResult(
                state="not_applicable",
                percent=None,
                covered_lines=0,
                measured_lines=0,
                source=str(self.source_path),
                reason="coverage artifact has no measured executable lines in function",
            )

        covered_count = sum(1 for covered in measured.values() if covered)
        measured_count = len(measured)
        return CoverageResult(
            state="known",
            percent=round(covered_count / measured_count * 100, 2),
            covered_lines=covered_count,
            measured_lines=measured_count,
            source=str(self.source_path),
            reason="coverage artifact provided executable line evidence",
        )

    def _suffix_match(self, rel_path: str) -> dict[int, int | bool] | None:
        matches = [
            lines
            for path, lines in self.files.items()
            if path.endswith(f"/{rel_path}") or rel_path.endswith(f"/{path}")
        ]
        if len(matches) == 1:
            return matches[0]
        return None


def _repo_rel(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def _normalize_coverage_path(path_text: str, root: Path) -> str:
    path = Path(path_text)
    if path.is_absolute():
        try:
            return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
        except ValueError:
            return str(path).replace("\\", "/")
    normalized = path_text.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def load_coverage_index(
    coverage_path: Path | None,
    root: Path,
    coverage_format: str = "auto",
) -> CoverageIndex:
    if coverage_path is None:
        return CoverageIndex.missing()

    if coverage_format == "auto":
        suffix = coverage_path.suffix.lower()
        coverage_format = "xml" if suffix == ".xml" else "json"

    if coverage_format == "json":
        return _load_coverage_json(coverage_path, root)
    if coverage_format == "xml":
        return _load_coverage_xml(coverage_path, root)
    raise ValueError(f"unsupported coverage format: {coverage_format}")


def _load_coverage_json(path: Path, root: Path) -> CoverageIndex:
    data = json.loads(path.read_text(encoding="utf-8"))
    files: dict[str, dict[int, int | bool]] = {}
    parse_errors: list[str] = []

    for raw_path, entry in data.get("files", {}).items():
        rel_path = _normalize_coverage_path(raw_path, root)
        line_map: dict[int, int | bool] = {}
        for line in entry.get("executed_lines", []) or []:
            line_map[int(line)] = True
        for line in entry.get("missing_lines", []) or []:
            line_map.setdefault(int(line), False)

        # Newer coverage.py JSON may include function-level records. Keep using
        # lines as the shared denominator so the scanner works across versions.
        if line_map:
            files[rel_path] = line_map

    if not files:
        parse_errors.append("coverage JSON contained no per-file line data")
    return CoverageIndex(source_path=path, files=files, parse_errors=parse_errors)


def _load_coverage_xml(path: Path, root: Path) -> CoverageIndex:
    tree = ET.parse(path)
    files: dict[str, dict[int, int | bool]] = {}
    parse_errors: list[str] = []

    for class_node in tree.findall(".//class"):
        filename = class_node.attrib.get("filename")
        if not filename:
            continue
        rel_path = _normalize_coverage_path(filename, root)
        line_map: dict[int, int | bool] = {}
        for line_node in class_node.findall("./lines/line"):
            number = line_node.attrib.get("number")
            hits = line_node.attrib.get("hits")
            if number is None or hits is None:
                continue
            line_map[int(number)] = int(hits) > 0
        if line_map:
            files[rel_path] = line_map

    if not files:
        parse_errors.append("coverage XML contained no per-file line data")
    return CoverageIndex(source_path=path, files=files, parse_errors=parse_errors)


class ComplexityVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.score = 1

    def visit_If(self, node: ast.If) -> None:
        self.score += 1
        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:
        self.score += 1
        self.generic_visit(node)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self.score += 1
        self.generic_visit(node)

    def visit_While(self, node: ast.While) -> None:
        self.score += 1
        self.generic_visit(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        self.score += 1
        self.generic_visit(node)

    def visit_IfExp(self, node: ast.IfExp) -> None:
        self.score += 1
        self.generic_visit(node)

    def visit_BoolOp(self, node: ast.BoolOp) -> None:
        self.score += max(0, len(node.values) - 1)
        self.generic_visit(node)

    def visit_comprehension(self, node: ast.comprehension) -> None:
        self.score += 1 + len(node.ifs)
        self.generic_visit(node)

    def visit_Match(self, node: ast.Match) -> None:
        self.score += len(node.cases)
        self.generic_visit(node)

    def visit_Assert(self, node: ast.Assert) -> None:
        self.score += 1
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        return


def compute_complexity(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    visitor = ComplexityVisitor()
    for item in node.body:
        visitor.visit(item)
    return visitor.score


def discover_functions(
    path: Path, root: Path
) -> tuple[list[FunctionRecord], dict[str, Any] | None]:
    rel_path = _repo_rel(path, root)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return [], {"path": rel_path, "reason": f"read_error: {exc}"}

    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return [], {"path": rel_path, "reason": f"parse_error: {exc}"}

    records: list[FunctionRecord] = []

    def visit_body(body: list[ast.stmt], qual: list[str]) -> None:
        for node in body:
            if isinstance(node, ast.ClassDef):
                visit_body(node.body, [*qual, node.name])
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                symbol = ".".join([*qual, node.name])
                records.append(
                    FunctionRecord(
                        path=rel_path,
                        symbol=symbol,
                        start_line=node.lineno,
                        end_line=getattr(node, "end_lineno", node.lineno),
                        complexity=compute_complexity(node),
                        complexity_source=(
                            "ast_mccabe_like_v0: baseline 1 plus branch, "
                            "handler, boolean, comprehension, match, and assert points"
                        ),
                    )
                )
                visit_body(node.body, [*qual, node.name])

    visit_body(tree.body, [])
    return records, None


def discover_python_files(root: Path) -> tuple[list[Path], list[dict[str, str]]]:
    included: list[Path] = []
    skipped: list[dict[str, str]] = []
    seen: set[Path] = set()

    for pattern in DEFAULT_INCLUDE_PATTERNS:
        base = pattern.split("/", 1)[0]
        if not (root / base).is_dir():
            skipped.append({"path": base, "reason": "scope directory missing"})
            continue
        for path in sorted(root.glob(pattern)):
            if not path.is_file():
                continue
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            included.append(path)

    return included, skipped


def _observability_by_path(
    root: Path, scan_date: str | None
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    try:
        report = scan_observability(root, scan_date=scan_date, include_init=True)
    except Exception as exc:  # pragma: no cover - defensive degraded mode
        return {}, {"status": "unavailable", "reason": str(exc)}

    by_path: dict[str, list[dict[str, Any]]] = {
        entry["path"]: entry.get("channels", []) for entry in report.get("files", [])
    }
    return by_path, {
        "status": "available",
        "harness_version": report.get("harness_version"),
        "zone": report.get("zone"),
        "summary": report.get("summary", {}),
    }


def _channels_for_function(
    function: FunctionRecord,
    observability_by_path: dict[str, list[dict[str, Any]]],
) -> list[str]:
    channels: set[str] = set()
    for detection in observability_by_path.get(function.path, []):
        evidence = detection.get("evidence") or []
        if any(
            function.start_line <= int(item.get("line", 0)) <= function.end_line
            for item in evidence
        ):
            channels.add(detection["channel"])
    return sorted(channels)


def side_effect_weight(channels: list[str]) -> int:
    if not channels:
        return 0
    return max(SIDE_EFFECT_WEIGHTS.get(channel, 1) for channel in channels)


def compute_crap_score(complexity: int, coverage_percent: float) -> float:
    coverage = max(0.0, min(1.0, coverage_percent / 100.0))
    return round(complexity**2 * (1 - coverage) ** 3 + complexity, 2)


def classify_risk(
    *,
    complexity: int,
    coverage: CoverageResult,
    crap_score: float | None,
    weight: int,
) -> tuple[str, str]:
    if coverage.state == "known" and crap_score is not None:
        if crap_score >= 30 or (crap_score >= 15 and weight >= 3):
            return "critical", (
                f"known coverage; CRAP {crap_score} with side_effect_weight {weight}"
            )
        if crap_score >= 15 or (complexity >= 8 and weight >= 3):
            return "high", (
                f"known coverage; CRAP {crap_score} or complex side-effect surface"
            )
        if crap_score >= 8 or weight >= 2:
            return "medium", (
                f"known coverage; CRAP {crap_score} or observable side effects"
            )
        return "low", f"known coverage; CRAP {crap_score} and low side-effect weight"

    if coverage.state == "not_applicable":
        if complexity >= 8 or weight >= 3:
            return "medium", (
                "coverage not applicable; complexity or side effects still need review"
            )
        return "low", "coverage not applicable and low static complexity"

    if complexity >= 15 and weight >= 3:
        return "critical", (
            "coverage_unknown; very high complexity near high-impact side effects"
        )
    if complexity >= 10 or (complexity >= 6 and weight >= 3):
        return "high", "coverage_unknown; complex function or high-impact side effects"
    if complexity >= 4 or weight >= 2:
        return "medium", "coverage_unknown; moderate complexity or observable mutation"
    return "low", "coverage_unknown; low complexity and low side-effect weight"


def _tracking_id(function: FunctionRecord) -> str:
    return f"{function.path}:{function.symbol}:{function.start_line}"


def _review_priority(
    *, risk_band: str, crap_score: float | None, complexity: int, weight: int
) -> int:
    band_priority = RISK_SEVERITY[risk_band] * 1_000_000_000
    if crap_score is not None:
        return (
            band_priority
            + round(crap_score * 10_000_000)
            + complexity * 100
            + weight
        )
    return band_priority + complexity * 100 + weight


def _function_dict(
    function: FunctionRecord,
    coverage: CoverageResult,
    observability_channels: list[str],
) -> dict[str, Any]:
    weight = side_effect_weight(observability_channels)
    crap_score = (
        compute_crap_score(function.complexity, coverage.percent)
        if coverage.state == "known" and coverage.percent is not None
        else None
    )
    risk_band, risk_reason = classify_risk(
        complexity=function.complexity,
        coverage=coverage,
        crap_score=crap_score,
        weight=weight,
    )
    review_priority = _review_priority(
        risk_band=risk_band,
        crap_score=crap_score,
        complexity=function.complexity,
        weight=weight,
    )
    return {
        "path": function.path,
        "symbol": function.symbol,
        "start_line": function.start_line,
        "end_line": function.end_line,
        "complexity": function.complexity,
        "complexity_source": function.complexity_source,
        "coverage_state": coverage.state,
        "coverage_percent": coverage.percent,
        "coverage_source": coverage.source,
        "coverage_reason": coverage.reason,
        "covered_lines": coverage.covered_lines,
        "measured_lines": coverage.measured_lines,
        "crap_score": crap_score,
        "risk_band": risk_band,
        "risk_reason": risk_reason,
        "observability_channels": observability_channels,
        "side_effect_weight": weight,
        "review_priority": review_priority,
        "tracking_id": _tracking_id(function),
        "tracking_status": "new",
        "tracking_notes": "",
        "evidence_refs": [],
    }


def _git_sha(root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return result.stdout.strip() or "unknown"


def build_report(
    root: Path,
    *,
    coverage_path: Path | None = None,
    coverage_format: str = "auto",
    scan_date: str | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    scan_date = scan_date or date.today().isoformat()
    coverage = load_coverage_index(coverage_path, root, coverage_format)
    observability_by_path, observability_summary = _observability_by_path(
        root, scan_date
    )
    files, skipped_files = discover_python_files(root)

    functions: list[dict[str, Any]] = []
    for path in files:
        records, error = discover_functions(path, root)
        if error is not None:
            skipped_files.append(error)
            continue
        for record in records:
            coverage_result = coverage.coverage_for(record)
            channels = _channels_for_function(record, observability_by_path)
            functions.append(_function_dict(record, coverage_result, channels))

    functions.sort(
        key=lambda item: (
            -item["review_priority"],
            item["path"],
            item["start_line"],
            item["symbol"],
        )
    )
    return {
        "scan_date": scan_date,
        "repo_sha": _git_sha(root),
        "target": "wea",
        "harness_version": HARNESS_VERSION,
        "scope": {
            "include": list(DEFAULT_INCLUDE_PATTERNS),
            "default_exclusions": [],
            "skipped_files": skipped_files,
        },
        "coverage": {
            "artifact": str(coverage_path) if coverage_path else None,
            "format": coverage_format,
            "parse_errors": coverage.parse_errors,
            "honesty_rule": (
                "missing or non-matching coverage is coverage_unknown, never "
                "zero coverage or full coverage"
            ),
        },
        "observability": observability_summary,
        "side_effect_weights": SIDE_EFFECT_WEIGHTS,
        "risk_bands": {
            "known": (
                "CRAP-driven: critical >=30 or high-impact >=15; high >=15; "
                "medium >=8 or observable mutation; low otherwise"
            ),
            "unknown": (
                "fallback: critical complexity>=15 with high-impact side effects; "
                "high complexity>=10 or complexity>=6 with high-impact side effects; "
                "medium complexity>=4 or mutation; low otherwise"
            ),
        },
        "summary": _summary(functions, skipped_files),
        "functions": functions,
        "limitations": [
            "Complexity is AST McCabe-like static complexity, not runtime path proof.",
            (
                "Coverage is line evidence mapped to function bodies after "
                "the def line; branch coverage is not inferred."
            ),
            (
                "Coverage is only known when an explicit JSON/XML artifact is "
                "supplied and matches the scanned file."
            ),
            (
                "Observability annotations for scripts/ are joined by evidence "
                "line range and may miss wrapper side effects."
            ),
            (
                "The harness is a review prioritization aid, not a CI gate or "
                "automatic PR verdict."
            ),
        ],
        "tracking": {
            "status_values": list(TRACKING_STATUSES),
            "initial_status": "new",
            "future_sweep_rule": (
                "Agent0 may change tracking_status and evidence_refs when a watched "
                "function later correlates with review findings, bugs, redteam notes, "
                "test additions, or hardening tasks."
            ),
        },
    }


def _summary(
    functions: list[dict[str, Any]], skipped_files: list[dict[str, str]]
) -> dict[str, Any]:
    by_band = {band: 0 for band in RISK_SEVERITY}
    by_coverage_state = {"known": 0, "unknown": 0, "not_applicable": 0}
    channels: dict[str, int] = {channel: 0 for channel in SIDE_EFFECT_WEIGHTS}
    for function in functions:
        by_band[function["risk_band"]] += 1
        by_coverage_state[function["coverage_state"]] += 1
        for channel in function["observability_channels"]:
            channels[channel] = channels.get(channel, 0) + 1
    return {
        "functions_scanned": len(functions),
        "skipped_files": len(skipped_files),
        "by_risk_band": by_band,
        "by_coverage_state": by_coverage_state,
        "functions_with_observability_channels": sum(
            1 for function in functions if function["observability_channels"]
        ),
        "observability_channel_function_counts": channels,
    }


def compact_checkpoint(report: dict[str, Any], top_n: int = 20) -> dict[str, Any]:
    keep_fields = (
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
        "tracking_id",
        "tracking_status",
        "tracking_notes",
        "evidence_refs",
    )
    return {
        "scan_date": report["scan_date"],
        "repo_sha": report["repo_sha"],
        "target": report["target"],
        "harness_version": report["harness_version"],
        "scope": report["scope"],
        "coverage": report["coverage"],
        "summary": report["summary"],
        "tracking": report["tracking"],
        "top_risk": [
            {key: item[key] for key in keep_fields}
            for item in report["functions"][:top_n]
        ],
        "notes": [
            (
                "Compact pilot checkpoint stores top-risk functions only; "
                "rerun the harness for the full function inventory."
            ),
            (
                "Initial tracking_status is new until future Circle-1 sweeps "
                "attach evidence_refs or mark inconclusive."
            ),
        ],
    }


def render_markdown(report: dict[str, Any], max_items: int = 20) -> str:
    lines = [
        "# Circle-1 CRAP/Observability Risk Report",
        "",
        f"- scan_date: {report['scan_date']}",
        f"- repo_sha: {report['repo_sha']}",
        f"- harness_version: {report['harness_version']}",
        f"- functions_scanned: {report['summary']['functions_scanned']}",
        f"- coverage_unknown: {report['summary']['by_coverage_state']['unknown']}",
        f"- coverage_known: {report['summary']['by_coverage_state']['known']}",
        "",
        "## Top Risk Functions",
        "",
        (
            "| risk | path | symbol | lines | complexity | coverage | CRAP | "
            "channels | tracking |"
        ),
        "|---|---|---|---:|---:|---:|---:|---|---|",
    ]
    for item in report["functions"][:max_items]:
        coverage = (
            f"{item['coverage_percent']}%"
            if item["coverage_state"] == "known"
            else item["coverage_state"]
        )
        crap = "" if item["crap_score"] is None else str(item["crap_score"])
        channels = ", ".join(item["observability_channels"]) or "-"
        lines.append(
            "| {risk} | {path} | {symbol} | {start}-{end} | {complexity} | "
            "{coverage} | {crap} | {channels} | {tracking} |".format(
                risk=item["risk_band"],
                path=item["path"],
                symbol=item["symbol"],
                start=item["start_line"],
                end=item["end_line"],
                complexity=item["complexity"],
                coverage=coverage,
                crap=crap,
                channels=channels,
                tracking=item["tracking_status"],
            )
        )
    lines.extend(
        [
            "",
            "## Review Use",
            "",
            (
                "- Prioritize high-complexity functions where coverage is "
                "unknown and side-effect channels touch ledger, GitHub, "
                "subprocess, network, or file artifacts."
            ),
            (
                "- Treat missing coverage as unknown evidence, not as zero or "
                "full coverage."
            ),
            (
                "- Update tracking fields only when later review findings, "
                "bugs, redteam notes, test additions, or hardening tasks "
                "provide evidence."
            ),
            "",
            "## Limitations",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in report["limitations"])
    return "\n".join(lines) + "\n"


def _write_text(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        payload if payload.endswith("\n") else payload + "\n", encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Circle-1 CRAP/observability Python risk harness"
    )
    parser.add_argument("--root", default=".", help="Repository root")
    parser.add_argument(
        "--coverage", default=None, help="coverage.py JSON or XML artifact"
    )
    parser.add_argument(
        "--coverage-format",
        choices=("auto", "json", "xml"),
        default="auto",
        help="Coverage artifact format",
    )
    parser.add_argument("--scan-date", default=None, help="ISO date to embed")
    parser.add_argument("--json-output", default=None, help="Write full JSON report")
    parser.add_argument(
        "--markdown-output", default=None, help="Write markdown top-risk report"
    )
    parser.add_argument(
        "--checkpoint-output", default=None, help="Write compact checkpoint JSON"
    )
    parser.add_argument(
        "--max-top", type=int, default=20, help="Top risks in markdown/checkpoint"
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
            coverage_format=args.coverage_format,
            scan_date=args.scan_date,
        )
    except (OSError, ValueError, json.JSONDecodeError, ET.ParseError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    wrote = False
    if args.json_output:
        _write_text(
            Path(args.json_output), json.dumps(report, indent=2, sort_keys=True)
        )
        wrote = True
    if args.markdown_output:
        _write_text(Path(args.markdown_output), render_markdown(report, args.max_top))
        wrote = True
    if args.checkpoint_output:
        payload = compact_checkpoint(report, args.max_top)
        _write_text(
            Path(args.checkpoint_output),
            json.dumps(payload, indent=2, sort_keys=True),
        )
        wrote = True

    if not wrote:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
