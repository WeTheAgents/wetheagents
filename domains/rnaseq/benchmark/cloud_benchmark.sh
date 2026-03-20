#!/bin/bash
set -euo pipefail

# ============================================================
# Full Benchmark: Picard MarkDuplicates vs samtools markdup
# on nf-core/rnaseq test_full (GRCh37 human genome)
#
# Server: Hetzner CCX33 (8 vCPU AMD, 32 GB RAM)
# Aligner: HISAT2 (needs ~8GB, fits in 32GB)
#
# ALL data lives on /mnt/data volume.
# ============================================================

WORKDIR=/root/rnaseq-bench
VOLDIR=/mnt/data
RESULTS=$WORKDIR/results
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOG=$RESULTS/benchmark_${TIMESTAMP}.log

# Nextflow environment — everything on volume
export NXF_WORK=$VOLDIR/work
export NXF_TEMP=$VOLDIR/tmp
export NXF_HOME=$WORKDIR/.nextflow

mkdir -p $RESULTS $NXF_WORK $NXF_TEMP

exec > >(tee -a "$LOG") 2>&1

echo "============================================================"
echo "nf-core/rnaseq Benchmark — Human Genome (GRCh37)"
echo "============================================================"
echo "Started: $(date -Iseconds)"
echo "Host: $(hostname)"
echo "CPUs: $(nproc)"
echo "RAM: $(free -h | grep Mem | awk '{print $2}')"
echo "Docker: $(docker --version)"
echo "Nextflow: $(nextflow -version 2>&1 | grep version | tail -1)"
echo "NXF_WORK: $NXF_WORK"
echo "NXF_TEMP: $NXF_TEMP"
echo ""
echo "Disk:"
df -h / $VOLDIR
echo ""

# Disk monitor — log disk usage every 5 minutes in background
(
  while true; do
    echo "[disk-monitor $(date +%H:%M)] root=$(df -h / | tail -1 | awk '{print $5}') vol=$(df -h $VOLDIR | tail -1 | awk '{print $5, $4}')" >> "$RESULTS/disk_monitor.log"
    sleep 300
  done
) &
DISK_MON_PID=$!
trap "kill $DISK_MON_PID 2>/dev/null || true" EXIT

# ============================================================
# Phase 1: Run nf-core/rnaseq with HISAT2 + Picard (default markdup)
# ============================================================
echo "=== Phase 1: nf-core/rnaseq test_full — HISAT2 + Picard ==="
echo "Start: $(date -Iseconds)"

cd $WORKDIR
PHASE1_START=$(date +%s)

nextflow run nf-core/rnaseq -r 3.14.0 \
  -profile test_full,docker \
  --aligner hisat2 \
  --max_cpus 8 \
  --max_memory '30.GB' \
  --outdir $WORKDIR/results_hisat2_picard \
  -w $NXF_WORK \
  2>&1

PHASE1_END=$(date +%s)
PHASE1_DURATION=$((PHASE1_END - PHASE1_START))
echo "Phase 1 duration: ${PHASE1_DURATION}s ($(( PHASE1_DURATION / 60 ))m)"
echo ""

echo "Disk after Phase 1:"
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
  echo "--- All processes ---"
  cat "$TRACE"
  echo ""
  echo "--- MarkDuplicates entries ---"
  head -1 "$TRACE"
  grep -i "markdup\|picard\|dedup" "$TRACE" || echo "(no markdup entries)"
  cp "$TRACE" "$RESULTS/hisat2_picard_trace.txt"
else
  echo "No trace file found"
fi
echo ""

# ============================================================
# Phase 3: Run samtools markdup on same BAMs (the key comparison)
# ============================================================
echo "=== Phase 3: samtools markdup comparison ==="

# Initialize CSV
echo "sample,tool,threads,run,time_sec,dup_count,total_reads,peak_rss_kb" > "$RESULTS/timings.csv"

# Find pre-markdup BAMs in work directory
# HISAT2 produces .sorted.bam files before Picard marks them
SORTED_BAMS=$(find $NXF_WORK -name "*.sorted.bam" -size +1M 2>/dev/null | grep -v markdup | grep -v ".picard" | grep -v ".st_" || true)

if [ -z "$SORTED_BAMS" ]; then
  echo "No pre-markdup BAMs found in work dir. Trying output dir..."
  SORTED_BAMS=$(find $WORKDIR/results_hisat2_picard -name "*.markdup.sorted.bam" -size +1M 2>/dev/null || true)
fi

echo "Found BAMs:"
echo "$SORTED_BAMS" | while read f; do echo "  $(du -h "$f" | cut -f1) $f"; done
echo ""

for bam in $SORTED_BAMS; do
  sample=$(basename "$bam" | sed 's/\.sorted.*//; s/\.Aligned.*//')
  bamdir=$(dirname "$bam")
  bamfile=$(basename "$bam")
  size=$(du -h "$bam" | cut -f1)

  echo "====== Sample: $sample ($size) ======"
  echo "BAM: $bam"

  # --- Picard standalone (3 runs for variance) ---
  for run in 1 2 3; do
    echo "  Picard run $run..."
    start_s=$(date +%s)

    /usr/bin/time -v docker run --rm \
      -v "$bamdir:/data" \
      quay.io/biocontainers/picard:3.4.0--hdfd78af_0 \
      picard MarkDuplicates \
        I=/data/$bamfile \
        O=/data/${sample}.picard_r${run}.markdup.bam \
        M=/data/${sample}.picard_r${run}.metrics \
        VALIDATION_STRINGENCY=LENIENT \
        REMOVE_DUPLICATES=false \
        2>"$bamdir/${sample}.picard_r${run}.time"

    end_s=$(date +%s)
    elapsed=$((end_s - start_s))
    peak_rss=$(grep "Maximum resident" "$bamdir/${sample}.picard_r${run}.time" | awk '{print $NF}' || echo "0")

    if [ -f "$bamdir/${sample}.picard_r${run}.markdup.bam" ]; then
      dup_count=$(samtools view -c -f 1024 "$bamdir/${sample}.picard_r${run}.markdup.bam")
      total_count=$(samtools view -c "$bamdir/${sample}.picard_r${run}.markdup.bam")
    else
      dup_count=0; total_count=0
    fi

    echo "  Picard r$run: ${elapsed}s, dups=$dup_count/$total_count, RSS=${peak_rss}KB"
    echo "${sample},picard,1,${run},${elapsed},${dup_count},${total_count},${peak_rss}" >> "$RESULTS/timings.csv"

    # Clean up BAM to save disk (keep metrics)
    rm -f "$bamdir/${sample}.picard_r${run}.markdup.bam"
  done

  # --- samtools markdup (1, 4, 8 threads, 3 runs each) ---
  for threads in 1 4 8; do
    for run in 1 2 3; do
      echo "  samtools t=$threads run $run..."
      start_s=$(date +%s)

      /usr/bin/time -v bash -c "
        samtools sort -n -@ $threads '$bam' | \
        samtools fixmate -m -@ $threads - - | \
        samtools sort -@ $threads - | \
        samtools markdup -@ $threads -s \
          -f '$bamdir/${sample}.st_t${threads}_r${run}.stats' \
          - '$bamdir/${sample}.st_t${threads}_r${run}.markdup.bam'
      " 2>"$bamdir/${sample}.st_t${threads}_r${run}.time"

      end_s=$(date +%s)
      elapsed=$((end_s - start_s))
      peak_rss=$(grep "Maximum resident" "$bamdir/${sample}.st_t${threads}_r${run}.time" | awk '{print $NF}' || echo "0")

      dup_count=$(samtools view -c -f 1024 "$bamdir/${sample}.st_t${threads}_r${run}.markdup.bam")
      total_count=$(samtools view -c "$bamdir/${sample}.st_t${threads}_r${run}.markdup.bam")

      echo "  samtools t=$threads r$run: ${elapsed}s, dups=$dup_count/$total_count, RSS=${peak_rss}KB"
      echo "${sample},samtools,${threads},${run},${elapsed},${dup_count},${total_count},${peak_rss}" >> "$RESULTS/timings.csv"

      # Clean up BAM to save disk (keep stats)
      rm -f "$bamdir/${sample}.st_t${threads}_r${run}.markdup.bam"
    done
  done

  # --- Correctness check: compare dup counts ---
  echo ""
  echo "  Correctness check:"
  picard_dups=$(grep "^${sample},picard,1,1," "$RESULTS/timings.csv" | cut -d, -f6)
  samtools_dups=$(grep "^${sample},samtools,1,1," "$RESULTS/timings.csv" | cut -d, -f6)
  if [ "$picard_dups" = "$samtools_dups" ]; then
    echo "  PASS: Picard=$picard_dups, samtools=$samtools_dups (identical)"
  else
    echo "  DIFF: Picard=$picard_dups, samtools=$samtools_dups"
  fi
  echo ""
done

# ============================================================
# Phase 4: Summary
# ============================================================
echo "============================================================"
echo "=== BENCHMARK RESULTS ==="
echo "============================================================"
echo ""
echo "CSV data:"
cat "$RESULTS/timings.csv"

echo ""
echo "Disk usage final:"
df -h / $VOLDIR

echo ""
echo "============================================================"
echo "Benchmark complete: $(date -Iseconds)"
echo "Total duration: $(($(date +%s) - PHASE1_START))s"
echo "Log: $LOG"
echo "CSV: $RESULTS/timings.csv"
echo "Trace: $RESULTS/hisat2_picard_trace.txt"
echo "============================================================"
