"""Analyze markdup benchmark results: Picard vs samtools markdup."""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

from src.models import MarkdupResult


def parse_markdup_results(path: Path) -> list[MarkdupResult]:
    """Parse TSV produced by markdup_benchmark.sh."""
    results = []
    with open(path) as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            results.append(MarkdupResult(
                sample=row["sample"],
                tool=row["tool"],
                threads=int(row["threads"]),
                wall_time_s=float(row["wall_time_s"]),
                peak_rss_kb=int(row["peak_rss_kb"]),
                dup_count=int(row["dup_count"]),
                total_reads=int(row["total_reads"]),
            ))
    return results


def compare_markdup_tools(results: list[MarkdupResult]) -> dict[str, dict]:
    """Aggregate results by tool+threads, compute speedup vs Picard.

    Returns dict keyed by config label ("picard", "samtools_t1", etc.)
    with avg_wall_time_s, avg_peak_rss_kb, speedup_vs_picard.
    """
    groups: dict[str, list[MarkdupResult]] = defaultdict(list)
    for r in results:
        if r.tool == "picard":
            key = "picard"
        else:
            key = f"samtools_t{r.threads}"
        groups[key].append(r)

    comparison = {}
    for key, group in sorted(groups.items()):
        avg_wall = sum(r.wall_time_s for r in group) / len(group)
        avg_rss = sum(r.peak_rss_kb for r in group) / len(group)
        comparison[key] = {
            "avg_wall_time_s": avg_wall,
            "avg_peak_rss_kb": avg_rss,
            "count": len(group),
            "speedup_vs_picard": 0.0,
        }

    picard_avg = comparison.get("picard", {}).get("avg_wall_time_s", 0)
    if picard_avg > 0:
        for key, data in comparison.items():
            if key != "picard":
                data["speedup_vs_picard"] = picard_avg / data["avg_wall_time_s"]

    return comparison


def check_dup_equivalence(
    picard_count: int, samtools_count: int, tolerance: float = 0.01
) -> bool:
    """Check if duplicate counts are equivalent within tolerance (default 1%)."""
    if picard_count == 0 and samtools_count == 0:
        return True
    if picard_count == 0 or samtools_count == 0:
        return False
    diff_pct = abs(picard_count - samtools_count) / picard_count
    return diff_pct <= tolerance
