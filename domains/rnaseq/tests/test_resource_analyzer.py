"""Tests for resource waste analysis."""

import pytest

from src.models import ProcessSummary
from src.resource_analyzer import compute_cpu_efficiency, compute_ram_efficiency, detect_waste


class TestCpuEfficiency:
    def test_full_utilization(self):
        """12 CPUs allocated, 1200% CPU used = 100% efficiency."""
        s = ProcessSummary(name="X", allocated_cpus=12, avg_cpu_pct=1200.0)
        assert compute_cpu_efficiency(s) == pytest.approx(1.0)

    def test_partial_utilization(self):
        """12 CPUs allocated, 180% CPU used = 15% efficiency."""
        s = ProcessSummary(name="X", allocated_cpus=12, avg_cpu_pct=180.0)
        assert compute_cpu_efficiency(s) == pytest.approx(0.15)

    def test_single_cpu(self):
        """1 CPU allocated, 95% used = 95% efficiency."""
        s = ProcessSummary(name="X", allocated_cpus=1, avg_cpu_pct=95.0)
        assert compute_cpu_efficiency(s) == pytest.approx(0.95)

    def test_zero_cpus(self):
        s = ProcessSummary(name="X", allocated_cpus=0, avg_cpu_pct=100.0)
        assert compute_cpu_efficiency(s) == 0.0


class TestRamEfficiency:
    def test_half_utilization(self):
        """72 GB allocated, 36 GB peak = 50% efficiency."""
        alloc = 72 * 1024**3
        peak = 36 * 1024**3
        s = ProcessSummary(name="X", allocated_memory_bytes=alloc, max_peak_rss_bytes=peak)
        assert compute_ram_efficiency(s) == pytest.approx(0.5)

    def test_low_utilization(self):
        """72 GB allocated, 2 GB peak = ~2.8% efficiency."""
        alloc = 72 * 1024**3
        peak = 2 * 1024**3
        s = ProcessSummary(name="X", allocated_memory_bytes=alloc, max_peak_rss_bytes=peak)
        assert compute_ram_efficiency(s) == pytest.approx(2 / 72)

    def test_zero_allocated(self):
        s = ProcessSummary(name="X", allocated_memory_bytes=0, max_peak_rss_bytes=100)
        assert compute_ram_efficiency(s) == 0.0


class TestDetectWaste:
    def test_wasteful_process_flagged(self):
        """TrimGalore-like: 12 CPUs allocated, 180% used, 72GB alloc, 2GB peak."""
        summaries = {
            "TRIMGALORE": ProcessSummary(
                name="TRIMGALORE",
                count=2,
                allocated_cpus=12,
                avg_cpu_pct=180.0,
                allocated_memory_bytes=72 * 1024**3,
                max_peak_rss_bytes=2 * 1024**3,
                total_duration_s=600,
                total_realtime_s=580,
            ),
        }
        reports = detect_waste(summaries)
        assert len(reports) == 1
        assert reports[0].process == "TRIMGALORE"
        assert reports[0].cpu_efficiency < 0.5
        assert reports[0].ram_efficiency < 0.25

    def test_efficient_process_not_flagged(self):
        """STAR-like: 12 CPUs, 850% CPU, 72GB alloc, 28GB peak."""
        summaries = {
            "STAR_ALIGN": ProcessSummary(
                name="STAR_ALIGN",
                count=1,
                allocated_cpus=12,
                avg_cpu_pct=850.0,
                allocated_memory_bytes=72 * 1024**3,
                max_peak_rss_bytes=28 * 1024**3,
                total_duration_s=920,
                total_realtime_s=895,
            ),
        }
        reports = detect_waste(summaries)
        assert len(reports) == 0

    def test_queue_time_reported(self):
        """Duration 600s, realtime 580s → 20s queue overhead."""
        summaries = {
            "SLOW": ProcessSummary(
                name="SLOW",
                count=1,
                allocated_cpus=1,
                avg_cpu_pct=10.0,  # Very low → flagged
                allocated_memory_bytes=1 * 1024**3,
                max_peak_rss_bytes=100 * 1024**2,  # 100 MB / 1 GB = 10%
                total_duration_s=600,
                total_realtime_s=580,
            ),
        }
        reports = detect_waste(summaries)
        assert len(reports) >= 1
        assert reports[0].queue_time_s == pytest.approx(20.0)
