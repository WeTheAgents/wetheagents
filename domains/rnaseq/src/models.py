"""Pydantic models for Nextflow trace data."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel


class TraceRecord(BaseModel):
    """One row from a Nextflow trace file."""

    task_id: str = ""
    hash: str = ""
    name: str = ""
    status: str = ""
    exit_code: str = ""
    duration: str = ""
    realtime: str = ""
    cpu_pct: str = ""
    peak_rss: str = ""
    peak_vmem: str = ""
    cpus: str = "1"
    memory: str = "0"

    @property
    def base_process(self) -> str:
        """Extract base process name (strip sample info in parentheses/after colon)."""
        name = self.name
        if "(" in name:
            name = name.split("(")[0].strip()
        if ":" in name:
            name = name.split(":")[-1].strip()
        return name


class ProcessSummary(BaseModel):
    """Aggregated stats for one process type across all invocations."""

    name: str
    count: int = 0
    total_realtime_s: float = 0.0
    avg_realtime_s: float = 0.0
    max_peak_rss_bytes: int = 0
    avg_cpu_pct: float = 0.0
    allocated_cpus: int = 1
    allocated_memory_bytes: int = 0
    total_duration_s: float = 0.0


class BenchmarkRun(BaseModel):
    """Metadata for a single benchmark execution."""

    label: str
    trace_path: Path
    config: dict[str, str] = {}


class ComparisonResult(BaseModel):
    """Diff between two runs for one process."""

    process: str
    realtime_a_s: float = 0.0
    realtime_b_s: float = 0.0
    diff_s: float = 0.0
    diff_pct: float = 0.0
    peak_rss_a_bytes: int = 0
    peak_rss_b_bytes: int = 0


class WasteReport(BaseModel):
    """Resource waste for one process."""

    process: str
    cpu_efficiency: float = 0.0  # 0-1 ratio
    ram_efficiency: float = 0.0  # 0-1 ratio
    wasted_cpus: float = 0.0
    wasted_ram_gb: float = 0.0
    queue_time_s: float = 0.0  # duration - realtime


class MarkdupResult(BaseModel):
    """One row from the markdup benchmark TSV."""

    sample: str
    tool: str  # "picard" | "samtools"
    threads: int = 1
    wall_time_s: float = 0.0
    peak_rss_kb: int = 0
    dup_count: int = 0
    total_reads: int = 0

    @property
    def dup_rate(self) -> float:
        return self.dup_count / self.total_reads if self.total_reads > 0 else 0.0
