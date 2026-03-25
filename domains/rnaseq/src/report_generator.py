"""Generate markdown reports and charts from trace analysis."""

from __future__ import annotations

from pathlib import Path

from tabulate import tabulate

from src.models import ProcessSummary
from src.resource_analyzer import (
    detect_waste,
    find_bottleneck,
)
from src.trace_parser import aggregate_by_process, parse_trace


def _fmt_seconds(s: float) -> str:
    """Format seconds as human-readable duration."""
    if s < 1:
        return f"{s * 1000:.0f}ms"
    if s < 60:
        return f"{s:.1f}s"
    m = int(s // 60)
    sec = s % 60
    if m < 60:
        return f"{m}m {sec:.0f}s"
    h = m // 60
    m = m % 60
    return f"{h}h {m}m {sec:.0f}s"


def _fmt_gb(b: int) -> str:
    """Format bytes as GB."""
    return f"{b / 1024**3:.1f} GB"


def generate_profile_report(trace_path: Path) -> str:
    """Single-run resource profile with waste analysis."""
    records = parse_trace(trace_path)
    summaries = aggregate_by_process(records)
    waste_reports = detect_waste(summaries)
    bottleneck = find_bottleneck(summaries)

    lines = [
        f"# Resource Profile: {trace_path.name}",
        f"\nProcesses: {len(records)} tasks across {len(summaries)} process types",
        f"Bottleneck: **{bottleneck}**" if bottleneck else "",
        "",
        "## Time Breakdown",
        "",
    ]

    # Time table
    rows = []
    total_rt = sum(s.total_realtime_s for s in summaries.values())
    for name in sorted(summaries, key=lambda n: summaries[n].total_realtime_s, reverse=True):
        s = summaries[name]
        pct = (s.total_realtime_s / total_rt * 100) if total_rt > 0 else 0
        rows.append([
            name,
            s.count,
            _fmt_seconds(s.total_realtime_s),
            f"{pct:.0f}%",
            f"{s.avg_cpu_pct:.0f}%",
            _fmt_gb(s.max_peak_rss_bytes),
        ])

    lines.append(tabulate(
        rows,
        headers=["Process", "N", "Total realtime", "% of total", "Avg CPU%", "Peak RSS"],
        tablefmt="pipe",
    ))

    # Waste analysis
    if waste_reports:
        lines.extend(["", "", "## Resource Waste", ""])
        waste_rows = []
        for w in sorted(waste_reports, key=lambda r: r.wasted_ram_gb, reverse=True):
            waste_rows.append([
                w.process,
                f"{w.cpu_efficiency:.0%}",
                f"{w.ram_efficiency:.0%}",
                f"{w.wasted_cpus:.1f}",
                f"{w.wasted_ram_gb:.1f} GB",
                _fmt_seconds(w.queue_time_s),
            ])
        lines.append(tabulate(
            waste_rows,
            headers=["Process", "CPU eff", "RAM eff", "Wasted CPUs", "Wasted RAM", "Queue time"],
            tablefmt="pipe",
        ))

    lines.append("")
    return "\n".join(lines)


def generate_comparison_report(trace_a: Path, trace_b: Path) -> str:
    """Compare two benchmark runs."""
    records_a = parse_trace(trace_a)
    records_b = parse_trace(trace_b)
    sums_a = aggregate_by_process(records_a)
    sums_b = aggregate_by_process(records_b)

    label_a = trace_a.stem.replace("trace_", "")
    label_b = trace_b.stem.replace("trace_", "")

    all_procs = sorted(set(list(sums_a.keys()) + list(sums_b.keys())))

    lines = [
        f"# Comparison: {label_a} vs {label_b}",
        "",
    ]

    rows = []
    total_a = total_b = 0.0

    for proc in all_procs:
        sa = sums_a.get(proc)
        sb = sums_b.get(proc)
        rt_a = sa.total_realtime_s if sa else 0
        rt_b = sb.total_realtime_s if sb else 0
        total_a += rt_a
        total_b += rt_b

        if rt_a == 0 and rt_b == 0:
            continue

        diff = rt_b - rt_a
        diff_str = f"{diff:+.1f}s"
        if rt_a > 0:
            pct = diff / rt_a * 100
            diff_str = f"{diff:+.1f}s ({pct:+.0f}%)"

        rows.append([proc, _fmt_seconds(rt_a), _fmt_seconds(rt_b), diff_str])

    # Total row
    diff_total = total_b - total_a
    pct_total = (diff_total / total_a * 100) if total_a > 0 else 0
    rows.append(["**TOTAL**", _fmt_seconds(total_a), _fmt_seconds(total_b),
                 f"{diff_total:+.1f}s ({pct_total:+.0f}%)"])

    lines.append(tabulate(
        rows,
        headers=["Process", label_a, label_b, "Diff"],
        tablefmt="pipe",
    ))

    lines.append("")
    return "\n".join(lines)


def generate_markdup_report(results: list, comparison: dict) -> str:
    """Generate a focused markdup comparison report."""
    from src.markdup_analyzer import check_dup_equivalence

    lines = [
        "# Picard MarkDuplicates vs samtools markdup",
        "",
        "## Speed Comparison",
        "",
    ]

    rows = []
    for key in sorted(comparison.keys()):
        data = comparison[key]
        speedup = data["speedup_vs_picard"]
        speedup_str = "baseline" if key == "picard" else f"{speedup:.1f}x"
        rows.append([
            key,
            f"{data['avg_wall_time_s']:.1f}s",
            f"{data['avg_peak_rss_kb'] / 1024:.0f} MB",
            speedup_str,
        ])

    lines.append(tabulate(
        rows,
        headers=["Config", "Avg wall-time", "Avg Peak RSS", "Speedup"],
        tablefmt="pipe",
    ))

    # Per-sample dup equivalence
    lines.extend(["", "", "## Duplicate Count Equivalence", ""])

    # Group by sample
    from collections import defaultdict
    by_sample: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for r in results:
        by_sample[r.sample][r.tool].append(r)

    dup_rows = []
    all_equivalent = True
    for sample in sorted(by_sample.keys()):
        picard_dups = by_sample[sample].get("picard", [])
        samtools_dups = by_sample[sample].get("samtools", [])
        if picard_dups and samtools_dups:
            p_count = picard_dups[0].dup_count
            s_count = samtools_dups[0].dup_count  # threads=1
            equiv = check_dup_equivalence(p_count, s_count)
            if not equiv:
                all_equivalent = False
            dup_rows.append([
                sample,
                p_count,
                s_count,
                f"{abs(p_count - s_count)}",
                "yes" if equiv else "NO",
            ])

    lines.append(tabulate(
        dup_rows,
        headers=["Sample", "Picard dups", "samtools dups", "Diff", "Equivalent"],
        tablefmt="pipe",
    ))

    if all_equivalent:
        lines.append("\nAll samples within 1% tolerance.")
    else:
        lines.append("\n**WARNING**: Dup counts diverge on some samples. Investigate before proposing as alternative.")

    lines.append("")
    return "\n".join(lines)


def generate_chart(summaries: dict[str, ProcessSummary], output_path: Path) -> None:
    """Generate a horizontal bar chart of time breakdown by process."""
    import matplotlib.pyplot as plt

    sorted_procs = sorted(summaries.values(), key=lambda s: s.total_realtime_s)
    names = [s.name for s in sorted_procs]
    times = [s.total_realtime_s for s in sorted_procs]

    fig, ax = plt.subplots(figsize=(10, max(4, len(names) * 0.4)))
    ax.barh(names, times, color="#4C72B0")
    ax.set_xlabel("Total realtime (seconds)")
    ax.set_title("nf-core/rnaseq Process Time Breakdown")
    plt.tight_layout()
    plt.savefig(output_path, dpi=150)
    plt.close()
