#!/usr/bin/env python3
"""Analyze Nextflow benchmark trace files.

Usage:
    python scripts/run_analysis.py trace_a.txt trace_b.txt    # comparison
    python scripts/run_analysis.py trace_a.txt                 # single-run profile
    python scripts/run_analysis.py --markdup markdup_results.tsv  # markdup comparison
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.report_generator import generate_chart, generate_comparison_report, generate_profile_report


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    # Markdup mode
    if sys.argv[1] == "--markdup":
        if len(sys.argv) < 3:
            print("Usage: python scripts/run_analysis.py --markdup markdup_results.tsv")
            sys.exit(1)
        tsv_path = Path(sys.argv[2])
        if not tsv_path.exists():
            print(f"Error: {tsv_path} not found")
            sys.exit(1)

        from src.markdup_analyzer import compare_markdup_tools, parse_markdup_results
        from src.report_generator import generate_markdup_report

        results = parse_markdup_results(tsv_path)
        comparison = compare_markdup_tools(results)
        report = generate_markdup_report(results, comparison)
        print(report)
        return

    # Trace analysis mode
    trace_a = Path(sys.argv[1])
    if not trace_a.exists():
        print(f"Error: {trace_a} not found")
        sys.exit(1)

    if len(sys.argv) >= 3:
        trace_b = Path(sys.argv[2])
        if not trace_b.exists():
            print(f"Error: {trace_b} not found")
            sys.exit(1)

        # Comparison mode
        report = generate_comparison_report(trace_a, trace_b)
        print(report)

        # Also generate individual profiles
        for t in (trace_a, trace_b):
            print()
            print(generate_profile_report(t))
    else:
        # Single-run profile mode
        report = generate_profile_report(trace_a)
        print(report)

    # Generate chart for first trace
    from src.trace_parser import aggregate_by_process, parse_trace

    records = parse_trace(trace_a)
    summaries = aggregate_by_process(records)
    chart_path = trace_a.parent / f"{trace_a.stem}_chart.png"
    try:
        generate_chart(summaries, chart_path)
        print(f"\nChart saved to: {chart_path}")
    except Exception as e:
        print(f"\nChart generation failed (non-critical): {e}")


if __name__ == "__main__":
    main()
