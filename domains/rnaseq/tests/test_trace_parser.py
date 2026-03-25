"""Tests for Nextflow trace parsing — TDD: written before implementation."""

import textwrap

import pytest

from src.trace_parser import aggregate_by_process, dur_to_seconds, parse_memory, parse_trace

# ── Duration parsing edge cases ──


class TestDurToSeconds:
    """Nextflow duration formats: '1h 23m 45s', '5m 30.2s', '45.1s', '234ms', '1d 2h', '-', '0'."""

    def test_hours_minutes_seconds(self):
        assert dur_to_seconds("1h 23m 45s") == pytest.approx(5025.0)

    def test_minutes_seconds(self):
        assert dur_to_seconds("5m 30.2s") == pytest.approx(330.2)

    def test_seconds_only(self):
        assert dur_to_seconds("45.1s") == pytest.approx(45.1)

    def test_milliseconds(self):
        assert dur_to_seconds("234ms") == pytest.approx(0.234)

    def test_days_hours(self):
        assert dur_to_seconds("1d 2h") == pytest.approx(93600.0)

    def test_dash_returns_zero(self):
        assert dur_to_seconds("-") == 0.0

    def test_zero_string(self):
        assert dur_to_seconds("0") == 0.0

    def test_empty_string(self):
        assert dur_to_seconds("") == 0.0

    def test_plain_float(self):
        assert dur_to_seconds("123.45") == pytest.approx(123.45)

    def test_seconds_no_decimal(self):
        assert dur_to_seconds("10s") == pytest.approx(10.0)

    def test_hours_only(self):
        assert dur_to_seconds("2h") == pytest.approx(7200.0)

    def test_whitespace_tolerance(self):
        assert dur_to_seconds("  5m 30s  ") == pytest.approx(330.0)


# ── Memory parsing ──


class TestParseMemory:
    """Nextflow memory formats: '6 GB', '512 MB', '1024 KB', raw bytes, '6.GB'."""

    def test_gigabytes_space(self):
        assert parse_memory("6 GB") == 6 * 1024**3

    def test_megabytes_space(self):
        assert parse_memory("512 MB") == 512 * 1024**2

    def test_kilobytes_space(self):
        assert parse_memory("1024 KB") == 1024 * 1024

    def test_raw_bytes(self):
        assert parse_memory("1073741824") == 1073741824

    def test_gigabytes_dot(self):
        """Nextflow DSL sometimes uses '6.GB' format."""
        assert parse_memory("6.GB") == 6 * 1024**3

    def test_dash_returns_zero(self):
        assert parse_memory("-") == 0

    def test_zero(self):
        assert parse_memory("0") == 0

    def test_empty(self):
        assert parse_memory("") == 0

    def test_fractional_gb(self):
        assert parse_memory("1.5 GB") == int(1.5 * 1024**3)


# ── Trace file parsing ──


SAMPLE_TRACE = textwrap.dedent("""\
    task_id\thash\tname\tstatus\texit\tduration\trealtime\t%cpu\tpeak_rss\tpeak_vmem\tcpus\tmemory
    1\tab/123456\tNFCORE_RNASEQ:RNASEQ:FASTQ_QC:TRIMGALORE (sample_1)\tCOMPLETED\t0\t5m 30s\t5m 12s\t180.5%\t2.1 GB\t4.5 GB\t12\t72 GB
    2\tcd/789012\tNFCORE_RNASEQ:RNASEQ:FASTQ_QC:TRIMGALORE (sample_2)\tCOMPLETED\t0\t4m 50s\t4m 35s\t175.2%\t2.0 GB\t4.3 GB\t12\t72 GB
    3\tef/345678\tNFCORE_RNASEQ:RNASEQ:ALIGN:STAR_ALIGN (sample_1)\tCOMPLETED\t0\t15m 20s\t14m 55s\t850.0%\t28.5 GB\t35.2 GB\t12\t72 GB
    4\tgh/901234\tNFCORE_RNASEQ:RNASEQ:QUANTIFY:SALMON_QUANT (sample_1)\tCOMPLETED\t0\t2m 10s\t2m 5s\t320.0%\t1.8 GB\t3.1 GB\t6\t36 GB
""")


class TestParseTrace:
    def test_parse_returns_records(self, tmp_path):
        trace_file = tmp_path / "trace.txt"
        trace_file.write_text(SAMPLE_TRACE)
        records = parse_trace(trace_file)
        assert len(records) == 4

    def test_record_fields(self, tmp_path):
        trace_file = tmp_path / "trace.txt"
        trace_file.write_text(SAMPLE_TRACE)
        records = parse_trace(trace_file)
        r = records[0]
        assert "TRIMGALORE" in r.name
        assert r.status == "COMPLETED"
        assert r.cpus == "12"
        assert r.memory == "72 GB"

    def test_base_process_extraction(self, tmp_path):
        trace_file = tmp_path / "trace.txt"
        trace_file.write_text(SAMPLE_TRACE)
        records = parse_trace(trace_file)
        bases = [r.base_process for r in records]
        assert bases[0] == "TRIMGALORE"
        assert bases[2] == "STAR_ALIGN"
        assert bases[3] == "SALMON_QUANT"


# ── Aggregation ──


class TestAggregateByProcess:
    def test_groups_by_base_process(self, tmp_path):
        trace_file = tmp_path / "trace.txt"
        trace_file.write_text(SAMPLE_TRACE)
        records = parse_trace(trace_file)
        summaries = aggregate_by_process(records)
        assert "TRIMGALORE" in summaries
        assert summaries["TRIMGALORE"].count == 2

    def test_total_realtime(self, tmp_path):
        trace_file = tmp_path / "trace.txt"
        trace_file.write_text(SAMPLE_TRACE)
        records = parse_trace(trace_file)
        summaries = aggregate_by_process(records)
        # 5m12s + 4m35s = 312 + 275 = 587s
        assert summaries["TRIMGALORE"].total_realtime_s == pytest.approx(587.0)

    def test_allocated_resources(self, tmp_path):
        trace_file = tmp_path / "trace.txt"
        trace_file.write_text(SAMPLE_TRACE)
        records = parse_trace(trace_file)
        summaries = aggregate_by_process(records)
        assert summaries["TRIMGALORE"].allocated_cpus == 12
        assert summaries["TRIMGALORE"].allocated_memory_bytes == 72 * 1024**3
