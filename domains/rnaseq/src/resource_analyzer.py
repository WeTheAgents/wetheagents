"""Resource efficiency analysis for Nextflow trace data."""

from __future__ import annotations

from src.models import ProcessSummary, WasteReport


def compute_cpu_efficiency(summary: ProcessSummary) -> float:
    """Ratio of actual CPU usage to allocated CPUs.

    avg_cpu_pct is in Nextflow format: 180% means 1.8 cores used.
    Returns 0-1 ratio.
    """
    if summary.allocated_cpus <= 0:
        return 0.0
    max_pct = summary.allocated_cpus * 100.0
    return summary.avg_cpu_pct / max_pct


def compute_ram_efficiency(summary: ProcessSummary) -> float:
    """Ratio of peak RSS to allocated memory. Returns 0-1 ratio."""
    if summary.allocated_memory_bytes <= 0:
        return 0.0
    return summary.max_peak_rss_bytes / summary.allocated_memory_bytes


def detect_waste(
    summaries: dict[str, ProcessSummary],
    cpu_threshold: float = 0.5,
    ram_threshold: float = 0.25,
) -> list[WasteReport]:
    """Flag processes where CPU efficiency < threshold OR RAM efficiency < threshold."""
    reports = []
    for name, s in summaries.items():
        cpu_eff = compute_cpu_efficiency(s)
        ram_eff = compute_ram_efficiency(s)
        queue_time = s.total_duration_s - s.total_realtime_s

        if cpu_eff < cpu_threshold or ram_eff < ram_threshold:
            wasted_cpus = s.allocated_cpus * (1 - cpu_eff)
            wasted_ram_gb = (
                s.allocated_memory_bytes * (1 - ram_eff) / (1024**3)
            )
            reports.append(
                WasteReport(
                    process=name,
                    cpu_efficiency=cpu_eff,
                    ram_efficiency=ram_eff,
                    wasted_cpus=wasted_cpus,
                    wasted_ram_gb=wasted_ram_gb,
                    queue_time_s=queue_time,
                )
            )

    return reports


def find_bottleneck(summaries: dict[str, ProcessSummary]) -> str | None:
    """Return the process name that accounts for the largest share of total wall-time."""
    if not summaries:
        return None
    return max(summaries, key=lambda n: summaries[n].total_realtime_s)
