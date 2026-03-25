"""Tests for markdup benchmark analyzer."""

import textwrap
from io import StringIO
from pathlib import Path

import pytest

from src.markdup_analyzer import (
    check_dup_equivalence,
    compare_markdup_tools,
    parse_markdup_results,
)
from src.models import MarkdupResult


# ─── Fixtures ───

SAMPLE_TSV = textwrap.dedent("""\
    sample\ttool\tthreads\twall_time_s\tpeak_rss_kb\tdup_count\ttotal_reads
    SAMPLE_A\tpicard\t1\t11.8\t3600000\t1200\t50000
    SAMPLE_A\tsamtools\t1\t5.2\t800000\t1198\t50000
    SAMPLE_A\tsamtools\t4\t2.1\t900000\t1198\t50000
    SAMPLE_A\tsamtools\t6\t1.9\t950000\t1198\t50000
    SAMPLE_B\tpicard\t1\t9.3\t3900000\t800\t40000
    SAMPLE_B\tsamtools\t1\t4.1\t750000\t802\t40000
    SAMPLE_B\tsamtools\t4\t1.8\t800000\t802\t40000
    SAMPLE_B\tsamtools\t6\t1.6\t820000\t802\t40000
""")


# ─── parse_markdup_results ───

class TestParseMarkdupResults:

    def test_parses_all_rows(self, tmp_path):
        tsv = tmp_path / "results.tsv"
        tsv.write_text(SAMPLE_TSV)
        results = parse_markdup_results(tsv)
        assert len(results) == 8

    def test_fields_correct(self, tmp_path):
        tsv = tmp_path / "results.tsv"
        tsv.write_text(SAMPLE_TSV)
        results = parse_markdup_results(tsv)
        picard_a = results[0]
        assert picard_a.sample == "SAMPLE_A"
        assert picard_a.tool == "picard"
        assert picard_a.threads == 1
        assert picard_a.wall_time_s == 11.8
        assert picard_a.peak_rss_kb == 3600000
        assert picard_a.dup_count == 1200
        assert picard_a.total_reads == 50000

    def test_dup_rate_property(self):
        r = MarkdupResult(sample="X", tool="picard", dup_count=100, total_reads=1000)
        assert r.dup_rate == pytest.approx(0.1)

    def test_dup_rate_zero_reads(self):
        r = MarkdupResult(sample="X", tool="picard", dup_count=0, total_reads=0)
        assert r.dup_rate == 0.0


# ─── compare_markdup_tools ───

class TestCompareMarkdupTools:

    def test_speedup_calculated(self, tmp_path):
        tsv = tmp_path / "results.tsv"
        tsv.write_text(SAMPLE_TSV)
        results = parse_markdup_results(tsv)
        comparison = compare_markdup_tools(results)

        # picard avg: (11.8 + 9.3) / 2 = 10.55
        # samtools t1 avg: (5.2 + 4.1) / 2 = 4.65
        # samtools t4 avg: (2.1 + 1.8) / 2 = 1.95
        # samtools t6 avg: (1.9 + 1.6) / 2 = 1.75
        assert comparison["picard"]["avg_wall_time_s"] == pytest.approx(10.55)
        assert comparison["samtools_t1"]["avg_wall_time_s"] == pytest.approx(4.65)
        assert comparison["samtools_t4"]["avg_wall_time_s"] == pytest.approx(1.95)

    def test_speedup_vs_picard(self, tmp_path):
        tsv = tmp_path / "results.tsv"
        tsv.write_text(SAMPLE_TSV)
        results = parse_markdup_results(tsv)
        comparison = compare_markdup_tools(results)

        # samtools t1 speedup: 10.55 / 4.65 ≈ 2.27x
        assert comparison["samtools_t1"]["speedup_vs_picard"] == pytest.approx(10.55 / 4.65, rel=0.01)
        # samtools t4 speedup: 10.55 / 1.95 ≈ 5.41x
        assert comparison["samtools_t4"]["speedup_vs_picard"] == pytest.approx(10.55 / 1.95, rel=0.01)

    def test_memory_comparison(self, tmp_path):
        tsv = tmp_path / "results.tsv"
        tsv.write_text(SAMPLE_TSV)
        results = parse_markdup_results(tsv)
        comparison = compare_markdup_tools(results)

        # picard avg RSS: (3600000 + 3900000) / 2 = 3750000
        assert comparison["picard"]["avg_peak_rss_kb"] == pytest.approx(3750000)
        # samtools t1 avg RSS: (800000 + 750000) / 2 = 775000
        assert comparison["samtools_t1"]["avg_peak_rss_kb"] == pytest.approx(775000)


# ─── check_dup_equivalence ───

class TestCheckDupEquivalence:

    def test_exact_match(self):
        assert check_dup_equivalence(1200, 1200) is True

    def test_within_tolerance(self):
        # 1198 vs 1200 = 0.17% diff, within 1% default
        assert check_dup_equivalence(1200, 1198) is True

    def test_outside_tolerance(self):
        # 1000 vs 1200 = 20% diff
        assert check_dup_equivalence(1200, 1000) is False

    def test_custom_tolerance(self):
        assert check_dup_equivalence(1200, 1150, tolerance=0.05) is True
        assert check_dup_equivalence(1200, 1100, tolerance=0.05) is False

    def test_zero_counts(self):
        assert check_dup_equivalence(0, 0) is True
