#!/bin/bash
set -euo pipefail

# ============================================================
# Phase 2-4: samtools markdup benchmark on Phase 1 BAMs
#
# Phase 1 (nf-core/rnaseq HISAT2+Picard) already completed.
# This script:
#   Phase 2: Extract Picard timings from execution trace
#   Phase 3: Run samtools markdup on pre-markdup BAMs (1/4/8 threads)
#   Phase 4: Summary CSV
#
# Picard standalone runs are SKIPPED — Phase 1 trace provides
# Picard data, and standalone Picard OOM'd on 5/8 samples in pipeline.
# ============================================================

WORKDIR=/root/rnaseq-bench
VOLDIR=/mnt/data
RESULTS=$WORKDIR/results_samtools_markdup
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOG=$RESULTS/benchmark_${TIMESTAMP}.log

mkdir -p "$RESULTS"

exec > >(tee -a "$LOG") 2>&1

echo "============================================================"
echo "Phase 2-4: samtools markdup Benchmark"
echo "============================================================"
echo "Started: $(date -Iseconds)"
echo "Host: $(hostname)"
echo "CPUs: $(nproc)"
echo "RAM: $(free -h | grep Mem | awk '{print $2}')"
echo "samtools: $(samtools --version | head -1)"
echo ""
echo "Disk:"
df -h / $VOLDIR
echo ""

# ============================================================
# Phase 2: Extract Picard timings from execution trace
# ============================================================
echo "=== Phase 2: Extract Picard MarkDuplicates timings ==="

TRACE=$(find $WORKDIR/results_hisat2_picard/pipeline_info -name "execution_trace_*" 2>/dev/null | sort | tail -1)
if [ -n "$TRACE" ]; then
  echo "Trace: $TRACE"
  echo ""
  echo "--- MarkDuplicates entries ---"
  head -1 "$TRACE"
  grep -i "markdup\|picard\|dedup" "$TRACE" || echo "(no markdup entries)"
  cp "$TRACE" "$RESULTS/hisat2_picard_trace.txt"
  echo ""
  echo "--- Full trace copied to results ---"
else
  echo "ERROR: No trace file found"
  exit 1
fi
echo ""

# ============================================================
# Phase 3: Run samtools markdup on pre-markdup BAMs
# ============================================================
echo "=== Phase 3: samtools markdup comparison ==="

# CSV header
echo "sample,tool,threads,run,time_sec,dup_count,total_reads,peak_rss_kb" > "$RESULTS/timings.csv"

# Find pre-markdup sorted BAMs (NOT markdup.sorted.bam)
mapfile -t BAMS < <(find $VOLDIR/work -name "*.sorted.bam" -not -name "*.markdup.*" -size +1M 2>/dev/null | sort)

echo "Found ${#BAMS[@]} pre-markdup BAMs:"
for bam in "${BAMS[@]}"; do
  echo "  $(du -h "$bam" | cut -f1)  $bam"
done
echo ""

PHASE3_START=$(date +%s)

for bam in "${BAMS[@]}"; do
  sample=$(basename "$bam" .sorted.bam)
  bamdir=$(dirname "$bam")
  size=$(du -h "$bam" | cut -f1)

  echo "====== Sample: $sample ($size) ======"

  for threads in 1 4 8; do
    for run in 1 2 3; do
      outbam="$bamdir/${sample}.st_t${threads}_r${run}.markdup.bam"
      statsfile="$bamdir/${sample}.st_t${threads}_r${run}.stats"
      timefile="$bamdir/${sample}.st_t${threads}_r${run}.time"

      echo "  samtools t=$threads run $run..."
      start_s=$(date +%s)

      /usr/bin/time -v bash -c "
        samtools sort -n -@ $threads '$bam' | \
        samtools fixmate -m -@ $threads - - | \
        samtools sort -@ $threads - | \
        samtools markdup -@ $threads -s \
          -f '$statsfile' \
          - '$outbam'
      " 2>"$timefile"

      end_s=$(date +%s)
      elapsed=$((end_s - start_s))
      peak_rss=$(grep "Maximum resident" "$timefile" | awk '{print $NF}' || echo "0")

      dup_count=$(samtools view -c -f 1024 "$outbam")
      total_count=$(samtools view -c "$outbam")

      echo "  samtools t=$threads r$run: ${elapsed}s, dups=$dup_count/$total_count, RSS=${peak_rss}KB"
      echo "${sample},samtools,${threads},${run},${elapsed},${dup_count},${total_count},${peak_rss}" >> "$RESULTS/timings.csv"

      # Clean up output BAM to save disk (keep stats + time)
      rm -f "$outbam"
    done
  done

  echo ""
  echo "Disk after $sample:"
  df -h $VOLDIR
  echo ""
done

PHASE3_END=$(date +%s)
PHASE3_DURATION=$((PHASE3_END - PHASE3_START))

# ============================================================
# Phase 4: Summary
# ============================================================
echo "============================================================"
echo "=== BENCHMARK RESULTS ==="
echo "============================================================"
echo ""
echo "Phase 3 duration: ${PHASE3_DURATION}s ($(( PHASE3_DURATION / 60 ))m)"
echo ""
echo "CSV data:"
cat "$RESULTS/timings.csv"
echo ""
echo "Disk usage final:"
df -h / $VOLDIR
echo ""
echo "============================================================"
echo "Benchmark complete: $(date -Iseconds)"
echo "Log: $LOG"
echo "CSV: $RESULTS/timings.csv"
echo "Trace: $RESULTS/hisat2_picard_trace.txt"
echo "============================================================"
