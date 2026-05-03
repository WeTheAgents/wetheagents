"""Circle-1 CRAP-style risk harness for Python functions/methods.

Scope (issue #888):
  - include: scripts/**/*.py and src/wea_cli/**/*.py
  - exclude: __init__.py at any depth, reported in `skipped_files`

Honesty rules:
  - cyclomatic complexity is statically computed and the formula is documented;
  - coverage is ingested only from an explicit artifact (--coverage); without
    it the harness reports `coverage_state: unknown` per function and refuses
    to compute `crap_score`;
  - observability annotation for scripts/ is sourced from
    `scripts.circle1.observability_inventory.scan_observability`. src/wea_cli
    files emit `observability_state: not_applicable` because no inventory
    exists for that tree yet;
  - tracking_status defaults to `new`; the harness never auto-correlates.

Output is structured JSON suitable for checkpoint diffs, plus a concise
markdown top-risk report. The markdown opens with an unknown-coverage banner
when no coverage artifact was supplied.

Stability:
  - all collections are sorted before emission;
  - floats are rounded to 4 decimal places;
  - `harness_version` is bumped on any breaking schema change.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Iterable

try:
    from scripts.circle1.observability_inventory import (
        CHANNEL_NAMES,
        scan_observability,
    )
except Exception:  # pragma: no cover - defensive: harness still useful
    CHANNEL_NAMES = ()  # type: ignore[assignment]
    scan_observability = None  # type: ignore[assignment]

HARNESS_VERSION = "v1"

DEFAULT_INCLUDE = ("scripts", "src/wea_cli")

# Side-effect weight is bucketed deterministically from observability channels.
# Higher weight = more reviewer attention warranted for the same complexity.
# Channels not listed below contribute 0.
_CHANNEL_WEIGHT: dict[str, int] = {
    "ledger_or_protocol_write_candidate": 4,
    "github_comment_side_effect_candidate": 4,
    "subprocess_launch": 3,
    "network_external_call": 3,
    "file_artifact_write": 2,
    "unknown_ambiguous_side_effect": 2,
    "logging": 1,
    "stdout_cli_output": 1,
    "stderr_output": 1,
}

# Risk band thresholds. CRAP thresholds match the original Alberg/Crapsy
# guidance (CRAP > 30 is a long-standing "very risky" line). The complexity
# fallback thresholds are deliberately conservative because complexity alone
# is not risk; the side-effect weight modulates them.
_CRAP_HIGH = 30.0
_CRAP_MEDIUM = 5.0
_COMPLEXITY_HIGH = 10
_COMPLEXITY_MEDIUM = 5

# Known-coverage escalation: a side_effect_weight >= 3 function (ledger,
# GitHub, subprocess, network) sitting near the next CRAP threshold gets
# bumped one band so it is prioritized over a pure formatter at the same
# CRAP score. "Near" is the upper portion of the current band.
_SIDE_EFFECT_ESCALATION_WEIGHT = 3
_ESCALATE_NEAR_HIGH = 0.6 * _CRAP_HIGH      # 18.0; medium -> high
_ESCALATE_NEAR_MEDIUM = 0.6 * _CRAP_MEDIUM  # 3.0;  low    -> medium

_RISK_TIER_ORDER = (
    "high",
    "unknown_high",
    "medium",
    "unknown_medium",
    "low",
    "unknown_low",
)
_RISK_TIER_RANK = {name: idx for idx, name in enumerate(_RISK_TIER_ORDER)}


@dataclass
class FunctionRecord:
    path: str
    symbol: str
    start_line: int
    end_line: int
    complexity: int
    complexity_source: str
    coverage_state: str
    coverage_percent: float | None
    crap_score: float | None
    risk_band: str
    risk_reason: str
    observability_channels: list[str]
    observability_state: str
    side_effect_weight: int
    tracking_id: str
    tracking_status: str
    tracking_notes: str
    evidence_refs: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "symbol": self.symbol,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "complexity": self.complexity,
            "complexity_source": self.complexity_source,
            "coverage_state": self.coverage_state,
            "coverage_percent": (
                None if self.coverage_percent is None
                else round(self.coverage_percent, 4)
            ),
            "crap_score": (
                None if self.crap_score is None else round(self.crap_score, 4)
            ),
            "risk_band": self.risk_band,
            "risk_reason": self.risk_reason,
            "observability_channels": sorted(self.observability_channels),
            "observability_state": self.observability_state,
            "side_effect_weight": self.side_effect_weight,
            "tracking_id": self.tracking_id,
            "tracking_status": self.tracking_status,
            "tracking_notes": self.tracking_notes,
            "evidence_refs": list(self.evidence_refs),
            "notes": list(self.notes),
        }


# --------------------------------------------------------------------------- #
# Complexity
# --------------------------------------------------------------------------- #

COMPLEXITY_SOURCE = (
    "ast_mccabe_v1: base 1; +1 per If, For, AsyncFor, While, ExceptHandler, "
    "IfExp, assert, comprehension if-clause; +1 per match case after the "
    "first; +(len(values)-1) per BoolOp. Decorators not counted."
)


def _compute_complexity(node: ast.AST) -> int:
    """Compute cyclomatic complexity for a function body.

    Counted nodes are documented in COMPLEXITY_SOURCE. The function node
    itself is not counted; we walk its descendants but stop at nested
    function/class definitions so each function is scored independently.
    """
    score = 1
    stack: list[ast.AST] = list(_iter_body(node))
    while stack:
        current = stack.pop()
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue  # nested defs are scored separately
        score += _node_complexity_contribution(current)
        stack.extend(ast.iter_child_nodes(current))
    return score


def _iter_body(node: ast.AST) -> Iterable[ast.AST]:
    body = getattr(node, "body", None)
    if body is None:
        return ()
    return list(body)


def _node_complexity_contribution(node: ast.AST) -> int:
    if isinstance(
        node,
        (
            ast.If,
            ast.For,
            ast.AsyncFor,
            ast.While,
            ast.ExceptHandler,
            ast.IfExp,
            ast.Assert,
        ),
    ):
        return 1
    if isinstance(node, ast.BoolOp):
        return max(0, len(node.values) - 1)
    if hasattr(ast, "Match") and isinstance(node, ast.Match):
        return max(0, len(node.cases) - 1)
    if isinstance(node, comprehension_types()):
        # comprehension generators carry `ifs`; each `if` adds a branch.
        ifs = getattr(node, "ifs", ())
        return len(ifs)
    return 0


def comprehension_types() -> tuple[type, ...]:
    types: list[type] = [ast.comprehension]
    return tuple(types)


# --------------------------------------------------------------------------- #
# Function discovery
# --------------------------------------------------------------------------- #


@dataclass
class _FuncInfo:
    qualname: str
    start_line: int
    end_line: int
    node: ast.AST


def _collect_functions(tree: ast.Module) -> list[_FuncInfo]:
    out: list[_FuncInfo] = []

    def visit(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qualname = f"{prefix}.{child.name}" if prefix else child.name
                end_line = getattr(child, "end_lineno", None) or child.lineno
                out.append(
                    _FuncInfo(
                        qualname=qualname,
                        start_line=child.lineno,
                        end_line=end_line,
                        node=child,
                    )
                )
                visit(child, qualname)
            elif isinstance(child, ast.ClassDef):
                inner_prefix = (
                    f"{prefix}.{child.name}" if prefix else child.name
                )
                visit(child, inner_prefix)
            else:
                visit(child, prefix)

    visit(tree, "")
    return out


# --------------------------------------------------------------------------- #
# Coverage
# --------------------------------------------------------------------------- #


def _normalize_path(text: str, root: Path | None = None) -> str:
    """Normalize a path string to repo-relative POSIX form.

    - Backslashes are converted to forward slashes.
    - Absolute paths are made relative to ``root`` when possible; otherwise
      they are returned in POSIX form so the caller can detect mismatches.
    - Leading ``./`` segments are stripped iteratively (NOT via ``lstrip("./")``,
      which would also strip parts of names that happen to start with ``.``).
    """
    if not text:
        return text
    text = text.replace("\\", "/")
    p = Path(text)
    if p.is_absolute():
        if root is not None:
            try:
                return p.resolve().relative_to(root.resolve()).as_posix()
            except ValueError:
                return p.as_posix()
        return p.as_posix()
    while text.startswith("./"):
        text = text[2:]
    return text


def _load_coverage(
    coverage_path: Path | None, root: Path | None = None
) -> dict[str, dict[str, Any]] | None:
    """Return coverage.py-shaped per-file maps, or None when unavailable."""
    if coverage_path is None:
        return None
    text = coverage_path.read_text(encoding="utf-8")
    payload = json.loads(text)
    files = payload.get("files")
    if not isinstance(files, dict):
        raise ValueError(
            "coverage artifact missing 'files' object; expected coverage.py JSON"
        )
    result: dict[str, dict[str, Any]] = {}
    for raw_path, data in files.items():
        rel = _normalize_path(str(raw_path), root=root)
        executed = set(data.get("executed_lines", []) or [])
        missing = set(data.get("missing_lines", []) or [])
        result[rel] = {"executed": executed, "missing": missing}
    return result


def _coverage_for_function(
    coverage_map: dict[str, dict[str, Any]] | None,
    rel_path: str,
    start: int,
    end: int,
) -> tuple[str, float | None]:
    """Return (coverage_state, coverage_percent)."""
    if coverage_map is None:
        return "unknown", None
    file_entry = coverage_map.get(rel_path)
    if file_entry is None:
        return "unknown", None
    executable = file_entry["executed"] | file_entry["missing"]
    in_range = {
        line for line in executable if start <= line <= end
    }
    if not in_range:
        return "not_applicable", None
    executed_in_range = in_range & file_entry["executed"]
    return "known", len(executed_in_range) / len(in_range)


def _crap_score(complexity: int, coverage_percent: float | None) -> float | None:
    if coverage_percent is None:
        return None
    coverage_clamped = max(0.0, min(1.0, coverage_percent))
    miss = 1.0 - coverage_clamped
    return complexity * complexity * (miss ** 3) + complexity


# --------------------------------------------------------------------------- #
# Observability annotation
# --------------------------------------------------------------------------- #


def _build_observability_index(
    inventory: dict[str, Any] | None,
) -> dict[str, list[dict[str, Any]]]:
    """Map relative path -> list of detection dicts with channel + evidence.

    Each detection retains its ``evidence`` entries so callers can intersect
    evidence line numbers against function ranges. Detections missing a
    channel name are dropped.
    """
    if not inventory:
        return {}
    out: dict[str, list[dict[str, Any]]] = {}
    for entry in inventory.get("files", []):
        path = entry.get("path")
        channels = entry.get("channels") or []
        if not path:
            continue
        kept: list[dict[str, Any]] = []
        for det in channels:
            name = det.get("channel")
            if not name:
                continue
            evidence = det.get("evidence") or []
            kept.append({"channel": name, "evidence": list(evidence)})
        out[_normalize_path(path)] = kept
    return out


def _channels_in_range(
    detections: list[dict[str, Any]],
    start: int,
    end: int,
) -> list[str]:
    """Return sorted unique channel names whose evidence falls in [start, end].

    Detections without evidence line numbers are skipped: without a line we
    cannot bind a side-effect channel to a specific function, so the safe
    default is to NOT inherit it onto pure helpers in the same file.
    """
    matched: set[str] = set()
    for det in detections:
        channel = det.get("channel")
        if not channel:
            continue
        for ev in det.get("evidence") or []:
            line = ev.get("line")
            if isinstance(line, int) and start <= line <= end:
                matched.add(channel)
                break
    return sorted(matched)


def _side_effect_weight(channels: Iterable[str]) -> int:
    weights = [_CHANNEL_WEIGHT.get(c, 0) for c in channels]
    return max(weights) if weights else 0


# --------------------------------------------------------------------------- #
# Risk banding
# --------------------------------------------------------------------------- #


def _risk(
    coverage_state: str,
    complexity: int,
    crap: float | None,
    side_effect_weight: int,
) -> tuple[str, str]:
    """Return (risk_band, risk_reason).

    Known coverage uses CRAP thresholds. A high side-effect weight
    (ledger / GitHub / subprocess / network) bumps the band by one tier when
    CRAP is in the upper portion of the current band, so a covered
    ledger-writer near the next threshold outranks a pure formatter at the
    same CRAP score. Unknown coverage falls back to complexity bands with an
    analogous side-effect escalation.
    """
    if coverage_state == "known" and crap is not None:
        if crap >= _CRAP_HIGH:
            return "high", f"crap={crap:.2f} >= {_CRAP_HIGH}"
        if crap >= _CRAP_MEDIUM:
            if (
                side_effect_weight >= _SIDE_EFFECT_ESCALATION_WEIGHT
                and crap >= _ESCALATE_NEAR_HIGH
            ):
                return (
                    "high",
                    f"crap={crap:.2f} in [{_ESCALATE_NEAR_HIGH}, {_CRAP_HIGH}); "
                    f"escalated by side_effect_weight={side_effect_weight}",
                )
            return "medium", f"crap={crap:.2f} in [{_CRAP_MEDIUM}, {_CRAP_HIGH})"
        if (
            side_effect_weight >= _SIDE_EFFECT_ESCALATION_WEIGHT
            and crap >= _ESCALATE_NEAR_MEDIUM
        ):
            return (
                "medium",
                f"crap={crap:.2f} in [{_ESCALATE_NEAR_MEDIUM}, {_CRAP_MEDIUM}); "
                f"escalated by side_effect_weight={side_effect_weight}",
            )
        return "low", f"crap={crap:.2f} < {_CRAP_MEDIUM}"

    # not_applicable behaves like unknown for ranking purposes but reasons differ.
    base: str
    reason: str
    if complexity >= _COMPLEXITY_HIGH:
        base, reason = "unknown_high", f"complexity={complexity} >= {_COMPLEXITY_HIGH}"
    elif complexity >= _COMPLEXITY_MEDIUM:
        base = "unknown_medium"
        reason = f"complexity={complexity} in [{_COMPLEXITY_MEDIUM}, {_COMPLEXITY_HIGH})"
    else:
        base, reason = "unknown_low", f"complexity={complexity} < {_COMPLEXITY_MEDIUM}"

    high_weight = side_effect_weight >= _SIDE_EFFECT_ESCALATION_WEIGHT
    if high_weight and base == "unknown_medium":
        return (
            "unknown_high",
            reason + f"; escalated by side_effect_weight={side_effect_weight}",
        )
    if high_weight and base == "unknown_low" and complexity >= 3:
        return (
            "unknown_medium",
            reason + f"; escalated by side_effect_weight={side_effect_weight}",
        )
    if coverage_state == "not_applicable":
        reason = "coverage_state=not_applicable; " + reason
    return base, reason


# --------------------------------------------------------------------------- #
# Per-file scan
# --------------------------------------------------------------------------- #


def _gather_python_files(root: Path, includes: Iterable[str]) -> tuple[list[Path], list[dict[str, str]]]:
    files: list[Path] = []
    skipped: list[dict[str, str]] = []
    for include in includes:
        base = root / include
        if not base.is_dir():
            skipped.append(
                {
                    "path": include,
                    "reason": "include root not present in this checkout",
                }
            )
            continue
        for p in sorted(base.rglob("*.py")):
            if p.name == "__init__.py":
                skipped.append(
                    {
                        "path": str(p.relative_to(root)).replace("\\", "/"),
                        "reason": "__init__.py excluded by default",
                    }
                )
                continue
            files.append(p)
    return files, skipped


def inspect_file(
    path: Path,
    root: Path,
    coverage_map: dict[str, dict[str, Any]] | None,
    observability_index: dict[str, list[dict[str, Any]]],
    observability_zone: str,
) -> tuple[list[FunctionRecord], dict[str, Any] | None]:
    rel_path = str(path.relative_to(root)).replace("\\", "/")
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return [], {"path": rel_path, "status": "read_error", "detail": str(exc)}

    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return [], {"path": rel_path, "status": "parse_error", "detail": str(exc)}

    funcs = _collect_functions(tree)
    if not funcs:
        return [], {"path": rel_path, "status": "no_functions"}

    # Observability is per-function: we intersect detection evidence line
    # numbers against each function's [start_line, end_line] so a pure
    # helper does not inherit a neighbor's side-effect channels.
    file_in_inventory = (
        observability_zone == "scripts" and rel_path in observability_index
    )
    file_detections = (
        observability_index.get(rel_path, []) if file_in_inventory else []
    )
    if observability_zone == "scripts":
        observability_state = "joined" if file_in_inventory else "missing"
    else:
        observability_state = "not_applicable"

    records: list[FunctionRecord] = []
    for info in funcs:
        complexity = _compute_complexity(info.node)
        coverage_state, coverage_percent = _coverage_for_function(
            coverage_map, rel_path, info.start_line, info.end_line
        )
        crap = (
            _crap_score(complexity, coverage_percent)
            if coverage_state == "known"
            else None
        )
        if file_in_inventory:
            channels = _channels_in_range(
                file_detections, info.start_line, info.end_line
            )
        else:
            channels = []
        weight = _side_effect_weight(channels) if channels else 0
        band, reason = _risk(coverage_state, complexity, crap, weight)
        records.append(
            FunctionRecord(
                path=rel_path,
                symbol=info.qualname,
                start_line=info.start_line,
                end_line=info.end_line,
                complexity=complexity,
                complexity_source=COMPLEXITY_SOURCE,
                coverage_state=coverage_state,
                coverage_percent=coverage_percent,
                crap_score=crap,
                risk_band=band,
                risk_reason=reason,
                observability_channels=list(channels),
                observability_state=observability_state,
                side_effect_weight=weight,
                tracking_id=f"{rel_path}::{info.qualname}::{info.start_line}",
                tracking_status="new",
                tracking_notes="",
            )
        )
    return records, None


# --------------------------------------------------------------------------- #
# Top-level scan
# --------------------------------------------------------------------------- #


def _zone_for(rel_path: str) -> str:
    if rel_path.startswith("scripts/"):
        return "scripts"
    if rel_path.startswith("src/wea_cli/"):
        return "src_wea_cli"
    return "other"


def scan_crap(
    root: Path,
    includes: Iterable[str] = DEFAULT_INCLUDE,
    coverage_path: Path | None = None,
    observability_inventory: dict[str, Any] | None = None,
    scan_date: str | None = None,
) -> dict[str, Any]:
    """Scan includes, ingest coverage if provided, return structured report."""
    root = root.resolve()
    files, skipped_files = _gather_python_files(root, includes)
    coverage_map = (
        _load_coverage(coverage_path, root=root) if coverage_path else None
    )

    if observability_inventory is None and scan_observability is not None:
        try:
            observability_inventory = scan_observability(
                root, scan_date=scan_date or date.today().isoformat()
            )
        except Exception as exc:  # pragma: no cover - defensive
            observability_inventory = {"error": str(exc), "files": []}
    observability_index = _build_observability_index(observability_inventory)

    records: list[FunctionRecord] = []
    file_problems: list[dict[str, Any]] = []
    for path in files:
        rel_path = str(path.relative_to(root)).replace("\\", "/")
        zone = _zone_for(rel_path)
        recs, problem = inspect_file(
            path, root, coverage_map, observability_index, zone
        )
        if problem is not None:
            file_problems.append(problem)
        records.extend(recs)

    records.sort(key=lambda r: (r.path, r.start_line, r.symbol))

    summary = _summarize(records, skipped_files, file_problems, coverage_map is not None)
    payload: dict[str, Any] = {
        "harness_version": HARNESS_VERSION,
        "scan_date": scan_date or date.today().isoformat(),
        "scope": {
            "include": list(includes),
            "default_exclusions": ["__init__.py"],
        },
        "coverage_artifact": (
            None if coverage_path is None else str(coverage_path)
        ),
        "coverage_artifact_format": (
            None if coverage_path is None else "coverage.py-json"
        ),
        "complexity_source": COMPLEXITY_SOURCE,
        "observability_zone_supported": ["scripts"],
        "channel_weights": dict(sorted(_CHANNEL_WEIGHT.items())),
        "risk_thresholds": {
            "crap_high": _CRAP_HIGH,
            "crap_medium": _CRAP_MEDIUM,
            "complexity_high": _COMPLEXITY_HIGH,
            "complexity_medium": _COMPLEXITY_MEDIUM,
            "side_effect_escalation_weight": _SIDE_EFFECT_ESCALATION_WEIGHT,
            "escalate_near_high": _ESCALATE_NEAR_HIGH,
            "escalate_near_medium": _ESCALATE_NEAR_MEDIUM,
        },
        "limitations": [
            "coverage.py marks a function's def-line as executable, which is "
            "trivially executed on import; this can inflate coverage_percent "
            "for short pure functions. Future versions may exclude def lines.",
            "observability_state=joined means the file was scanned by the "
            "observability inventory; it does NOT guarantee every detection "
            "carries an evidence line. Detections without evidence are "
            "ignored when binding channels to functions.",
        ],
        "summary": summary,
        "skipped_files": sorted(
            skipped_files, key=lambda d: (d.get("path", ""), d.get("reason", ""))
        ),
        "file_problems": sorted(
            file_problems, key=lambda d: d.get("path", "")
        ),
        "functions": [r.as_dict() for r in records],
    }
    return payload


def _summarize(
    records: list[FunctionRecord],
    skipped_files: list[dict[str, str]],
    file_problems: list[dict[str, Any]],
    has_coverage: bool,
) -> dict[str, Any]:
    by_band: dict[str, int] = {tier: 0 for tier in _RISK_TIER_ORDER}
    by_zone: dict[str, dict[str, int]] = {}
    for r in records:
        by_band[r.risk_band] = by_band.get(r.risk_band, 0) + 1
        zone = _zone_for(r.path)
        zone_entry = by_zone.setdefault(zone, {"functions": 0, "files": 0})
        zone_entry["functions"] += 1
    seen_paths: dict[str, set[str]] = {}
    for r in records:
        seen_paths.setdefault(_zone_for(r.path), set()).add(r.path)
    for zone, paths in seen_paths.items():
        by_zone.setdefault(zone, {"functions": 0, "files": 0})["files"] = len(paths)
    return {
        "function_count": len(records),
        "by_risk_band": by_band,
        "by_zone": by_zone,
        "skipped_file_count": len(skipped_files),
        "file_problem_count": len(file_problems),
        "coverage_artifact_supplied": has_coverage,
    }


# --------------------------------------------------------------------------- #
# Top-risk / markdown
# --------------------------------------------------------------------------- #


_RANKING_UNKNOWN_CRAP = -1.0  # ranking-only; never written to JSON


def _rank_key(r: dict[str, Any]) -> tuple:
    band_rank = _RISK_TIER_RANK.get(r["risk_band"], len(_RISK_TIER_ORDER))
    crap = r["crap_score"] if r["crap_score"] is not None else _RANKING_UNKNOWN_CRAP
    return (
        band_rank,
        -r["side_effect_weight"],
        -crap,
        -r["complexity"],
        r["path"],
        r["start_line"],
    )


def top_risk(records: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    return sorted(records, key=_rank_key)[: max(0, limit)]


def render_markdown(report: dict[str, Any], limit: int = 25) -> str:
    coverage_supplied = report["summary"]["coverage_artifact_supplied"]
    lines: list[str] = []
    lines.append("# Circle-1 CRAP risk inventory")
    lines.append("")
    lines.append(f"- harness_version: {report['harness_version']}")
    lines.append(f"- scan_date: {report['scan_date']}")
    lines.append(f"- function_count: {report['summary']['function_count']}")
    if not coverage_supplied:
        lines.append("")
        lines.append(
            "> **No coverage artifact supplied.** CRAP scores were NOT computed; "
            "risk bands fall back to complexity + side-effect weight. "
            "Pass `--coverage <coverage.py-json>` for true CRAP scoring."
        )
    lines.append("")
    lines.append("## Risk band counts")
    lines.append("")
    lines.append("| band | count |")
    lines.append("|---|---:|")
    for tier in _RISK_TIER_ORDER:
        lines.append(f"| {tier} | {report['summary']['by_risk_band'].get(tier, 0)} |")
    lines.append("")
    lines.append(f"## Top {limit} risk functions")
    lines.append("")
    if not report["functions"]:
        lines.append("(no functions found)")
    else:
        lines.append(
            "| rank | path:line | symbol | complexity | coverage | crap | band | weight | channels |"
        )
        lines.append("|---:|---|---|---:|---|---:|---|---:|---|")
        for idx, r in enumerate(top_risk(report["functions"], limit), start=1):
            cov = (
                "unknown" if r["coverage_state"] == "unknown"
                else "n/a" if r["coverage_state"] == "not_applicable"
                else f"{(r['coverage_percent'] or 0)*100:.0f}%"
            )
            crap = "—" if r["crap_score"] is None else f"{r['crap_score']:.1f}"
            chans = ",".join(r["observability_channels"]) or "—"
            lines.append(
                f"| {idx} | {r['path']}:{r['start_line']} | `{r['symbol']}` | "
                f"{r['complexity']} | {cov} | {crap} | {r['risk_band']} | "
                f"{r['side_effect_weight']} | {chans} |"
            )
    lines.append("")
    lines.append("## Tracking semantics")
    lines.append("")
    lines.append(
        "Every function in this report ships with `tracking_status=new`. "
        "Future Circle-1 sweeps update tracking_status only with explicit "
        "evidence (review finding, redteam note, bug fix, or hardening task)."
    )
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# Checkpoint
# --------------------------------------------------------------------------- #


def build_checkpoint(report: dict[str, Any], top_n: int = 30) -> dict[str, Any]:
    """Return a compact checkpoint for committing to circle-1/checkpoints/.

    The full per-function list is intentionally omitted to keep diffs small.
    Reviewers can regenerate the full report from source.
    """
    items = top_risk(report["functions"], top_n)
    return {
        "harness_version": report["harness_version"],
        "scan_date": report["scan_date"],
        "scope": report["scope"],
        "coverage_artifact_supplied": report["summary"]["coverage_artifact_supplied"],
        "coverage_artifact_format": report["coverage_artifact_format"],
        "summary": report["summary"],
        "top_n": top_n,
        "items": items,
        "tracking_protocol": {
            "default_status": "new",
            "valid_statuses": [
                "new",
                "watched",
                "correlated",
                "retired",
                "inconclusive",
            ],
            "promotion_rule": (
                "tracking_status only changes with explicit evidence in "
                "evidence_refs (PR number, redteam note path, bug fix commit, "
                "or hardening issue)"
            ),
        },
    }


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def _serialize_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Circle-1 CRAP risk harness for Python functions."
    )
    parser.add_argument("--root", default=".", help="Repo root directory")
    parser.add_argument(
        "--include",
        action="append",
        default=None,
        help=(
            "Include root (relative to repo). Repeatable. "
            f"Default: {' and '.join(DEFAULT_INCLUDE)}"
        ),
    )
    parser.add_argument(
        "--coverage",
        default=None,
        help="Optional path to coverage.py-shaped JSON artifact.",
    )
    parser.add_argument(
        "--scan-date",
        default=None,
        help="ISO date (YYYY-MM-DD) for reproducible reports.",
    )
    parser.add_argument(
        "--format",
        choices=("json", "markdown", "checkpoint"),
        default="json",
        help="Output format.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Optional output path.",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=25,
        help="Top-N functions for markdown / checkpoint.",
    )
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"ERROR: not a directory: {root}", file=sys.stderr)
        return 1
    includes = tuple(args.include) if args.include else DEFAULT_INCLUDE

    coverage_path = Path(args.coverage).resolve() if args.coverage else None
    if coverage_path is not None and not coverage_path.is_file():
        print(f"ERROR: coverage artifact not found: {coverage_path}", file=sys.stderr)
        return 1

    report = scan_crap(
        root,
        includes=includes,
        coverage_path=coverage_path,
        scan_date=args.scan_date,
    )

    if args.format == "json":
        payload = _serialize_json(report)
    elif args.format == "markdown":
        payload = render_markdown(report, limit=args.top)
    else:  # checkpoint
        payload = _serialize_json(build_checkpoint(report, top_n=args.top))

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            payload + ("" if payload.endswith("\n") else "\n"), encoding="utf-8"
        )
        print(f"Saved: {out_path}", file=sys.stderr)
    else:
        sys.stdout.write(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
