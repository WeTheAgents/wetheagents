"""Parse Nextflow trace TSV files into structured data."""

from __future__ import annotations

import contextlib
import csv
import re
from collections import defaultdict
from pathlib import Path

from src.models import ProcessSummary, TraceRecord


def dur_to_seconds(dur_str: str) -> float:
    """Convert Nextflow duration string to seconds.

    Handles: '1h 23m 45s', '5m 30.2s', '234ms', '1d 2h', '-', '0', plain float.
    """
    if not dur_str or dur_str.strip() in ("-", "0"):
        return 0.0

    dur_str = dur_str.strip()
    total = 0.0
    found = False

    for part in dur_str.split():
        if part.endswith("ms"):
            total += float(part[:-2]) / 1000
            found = True
        elif part.endswith("d"):
            total += float(part[:-1]) * 86400
            found = True
        elif part.endswith("h"):
            total += float(part[:-1]) * 3600
            found = True
        elif part.endswith("m"):
            total += float(part[:-1]) * 60
            found = True
        elif part.endswith("s"):
            total += float(part[:-1])
            found = True

    if not found:
        with contextlib.suppress(ValueError):
            total = float(dur_str)

    return total


def parse_memory(mem_str: str) -> int:
    """Convert Nextflow memory string to bytes.

    Handles: '6 GB', '512 MB', '1024 KB', '6.GB', raw bytes, '-', '0'.
    """
    if not mem_str or mem_str.strip() in ("-", "0"):
        return 0

    mem_str = mem_str.strip()

    # Normalize '6.GB' → '6 GB' (Nextflow DSL format)
    mem_str = re.sub(r"(\d)\.([GMKT]B)", r"\1 \2", mem_str)

    multipliers = {
        "GB": 1024**3,
        "MB": 1024**2,
        "KB": 1024,
        "B": 1,
    }

    for suffix, mult in multipliers.items():
        if mem_str.upper().endswith(suffix):
            num_str = mem_str[: -len(suffix)].strip()
            try:
                return int(float(num_str) * mult)
            except ValueError:
                return 0

    try:
        return int(float(mem_str))
    except ValueError:
        return 0


def parse_trace(path: Path) -> list[TraceRecord]:
    """Parse a Nextflow trace TSV file into TraceRecord objects."""
    records = []
    with open(path) as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            record = TraceRecord(
                task_id=row.get("task_id", ""),
                hash=row.get("hash", ""),
                name=row.get("name", row.get("process", "")),
                status=row.get("status", ""),
                exit_code=row.get("exit", ""),
                duration=row.get("duration", "0"),
                realtime=row.get("realtime", row.get("duration", "0")),
                cpu_pct=row.get("%cpu", "0"),
                peak_rss=row.get("peak_rss", row.get("rss", "0")),
                peak_vmem=row.get("peak_vmem", row.get("vmem", "0")),
                cpus=row.get("cpus", "1"),
                memory=row.get("memory", "0"),
            )
            records.append(record)
    return records


def _parse_cpu_pct(s: str) -> float:
    """Parse CPU percentage string like '180.5%' to float 180.5."""
    s = s.strip().rstrip("%")
    try:
        return float(s)
    except ValueError:
        return 0.0


def aggregate_by_process(records: list[TraceRecord]) -> dict[str, ProcessSummary]:
    """Group trace records by base process name and compute aggregates."""
    groups: dict[str, list[TraceRecord]] = defaultdict(list)
    for r in records:
        groups[r.base_process].append(r)

    summaries = {}
    for name, recs in groups.items():
        total_rt = sum(dur_to_seconds(r.realtime) for r in recs)
        total_dur = sum(dur_to_seconds(r.duration) for r in recs)
        cpu_pcts = [_parse_cpu_pct(r.cpu_pct) for r in recs]
        peak_rsses = [parse_memory(r.peak_rss) for r in recs]

        # Use first record's allocation (same process type = same label)
        first = recs[0]
        alloc_cpus = int(first.cpus) if first.cpus else 1
        alloc_mem = parse_memory(first.memory)

        summaries[name] = ProcessSummary(
            name=name,
            count=len(recs),
            total_realtime_s=total_rt,
            avg_realtime_s=total_rt / len(recs),
            max_peak_rss_bytes=max(peak_rsses) if peak_rsses else 0,
            avg_cpu_pct=sum(cpu_pcts) / len(cpu_pcts) if cpu_pcts else 0.0,
            allocated_cpus=alloc_cpus,
            allocated_memory_bytes=alloc_mem,
            total_duration_s=total_dur,
        )

    return summaries
