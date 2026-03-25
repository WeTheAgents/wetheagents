#!/bin/bash
# W∃A × nf-core/rnaseq: Research Benchmark
# Run inside WSL with Docker Desktop backend
#
# NTFS (Windows /mnt/d/) does not support FIFO or proper file locking.
# All Nextflow work + output goes to Linux FS, then results copy to D:.
#
# Usage:
#   wsl bash scripts/benchmark.sh          # from Windows (cwd = rnaseq dir)
#   bash scripts/benchmark.sh              # from WSL

set -euo pipefail

# Linux-native paths (ext4 — supports FIFO, file locking)
WORKDIR="$HOME/rnaseq-work"
RESULTSDIR="$HOME/rnaseq-results"
VER="3.23.0"

# Windows-accessible copy destination
WIN_OUTDIR="/mnt/d/GitHub/wetheagents/domains/rnaseq/benchmark_results"

mkdir -p "$WORKDIR" "$RESULTSDIR" "$WIN_OUTDIR"

echo "=== W∃A nf-core/rnaseq Benchmark ==="
echo "Date: $(date -Iseconds)"
echo "Machine: $(nproc) threads, $(free -h | awk '/^Mem:/{print $2}') RAM"
echo "Work dir: $WORKDIR (Linux FS)"
echo "Results:  $RESULTSDIR → $WIN_OUTDIR"
echo ""

run_pipeline() {
  local label="$1"
  shift
  local outdir="$RESULTSDIR/run_${label}"

  echo "--- Running: $label ---"
  cd "$HOME"  # reset CWD to safe Linux path (prevents Java CWD errors)

  nextflow run nf-core/rnaseq -r $VER \
    -profile test,docker \
    -w "$WORKDIR" \
    --outdir "$outdir" \
    -with-trace "$RESULTSDIR/trace_${label}.txt" \
    -with-timeline "$RESULTSDIR/timeline_${label}.html" \
    -with-report "$RESULTSDIR/report_${label}.html" \
    "$@" \
    2>&1 | tee "$RESULTSDIR/log_${label}.txt"

  echo "--- $label complete ---"
  echo ""
}

# ─── Run 1: Default (TrimGalore, star_salmon) ───
echo "[1/3] Default pipeline (TrimGalore + STAR→Salmon)..."
run_pipeline "trimgalore"

# ─── Run 2: fastp instead of TrimGalore ───
echo "[2/3] fastp instead of TrimGalore..."
run_pipeline "fastp" --trimmer fastp

# ─── Run 3: Salmon-only pseudo-alignment (skip STAR) ───
echo "[3/3] Salmon-only (pseudo-alignment, skip STAR)..."
run_pipeline "salmon_only" --pseudo_aligner salmon --skip_alignment

# ─── Copy results to D: ───
echo "=== Copying results to Windows drive ==="
cp -v "$RESULTSDIR"/trace_*.txt "$WIN_OUTDIR/" 2>/dev/null || true
cp -v "$RESULTSDIR"/timeline_*.html "$WIN_OUTDIR/" 2>/dev/null || true
cp -v "$RESULTSDIR"/report_*.html "$WIN_OUTDIR/" 2>/dev/null || true
cp -v "$RESULTSDIR"/log_*.txt "$WIN_OUTDIR/" 2>/dev/null || true

echo ""
echo "=== Benchmark complete ==="
echo "Traces: $WIN_OUTDIR/trace_*.txt"
echo ""
echo "Next steps:"
echo "  1. python scripts/run_analysis.py benchmark_results/trace_trimgalore.txt benchmark_results/trace_fastp.txt"
echo "  2. Open timeline HTMLs in browser"
echo "  3. Search nf-core/rnaseq Issues BEFORE posting anywhere"
