#!/bin/bash
set -euo pipefail

# ============================================================
# Full 3-way Benchmark: Picard vs samtools vs sambamba markdup
# on nf-core/rnaseq test_full (GRCh38 human genome)
#
# Server: Hetzner CPX62 (16 vCPU, 32GB RAM) + 1TB volume
# Aligner: HISAT2
#
# Phase 1: nf-core/rnaseq pipeline (HISAT2 + Picard default)
# Phase 2: Extract Picard timings from trace
# Phase 3: samtools markdup benchmark (1/4/8/16 threads × 3 runs)
# Phase 4: sambamba markdup benchmark (1/4/8/16 threads × 3 runs)
# Phase 5: Correctness comparison + summary
#
# ALL data lives on /mnt/data volume.
# ============================================================

WORKDIR=/root/rnaseq-bench
VOLDIR=/mnt/data
RESULTS=$WORKDIR/results
TMPDIR_SAMBAMBA=$VOLDIR/tmp/sambamba
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOG=$RESULTS/benchmark_${TIMESTAMP}.log

export NXF_WORK=$VOLDIR/work
export NXF_TEMP=$VOLDIR/tmp
export NXF_HOME=$WORKDIR/.nextflow

mkdir -p $RESULTS $NXF_WORK $NXF_TEMP $TMPDIR_SAMBAMBA

exec > >(tee -a "$LOG") 2>&1

echo "============================================================"
echo "3-way markdup Benchmark — Picard vs samtools vs sambamba"
echo "============================================================"
echo "Started: $(date -Iseconds)"
echo "Host: $(hostname)"
echo "CPUs: $(nproc)"
echo "RAM: $(free -h | grep Mem | awk '{print $2}')"
echo "Docker: $(docker --version)"
echo "Nextflow: $(nextflow -version 2>&1 | grep version | tail -1)"
echo "samtools: $(samtools --version | head -1)"
echo "sambamba: $(sambamba --version 2>&1 | head -1 || echo 'not installed')"
echo "NXF_WORK: $NXF_WORK"
echo ""
echo "Disk:"
df -h / $VOLDIR
echo ""

# Disk monitor — log every 5 minutes
(
  while true; do
    echo "[disk-monitor $(date +%H:%M)] root=$(df -h / | tail -1 | awk '{print $5}') vol=$(df -h $VOLDIR | tail -1 | awk '{print $5, $4}')" >> "$RESULTS/disk_monitor.log"
    sleep 300
  done
) &
DISK_MON_PID=$!
trap "kill $DISK_MON_PID 2>/dev/null || true; rm -rf $TMPDIR_SAMBAMBA" EXIT

BENCHMARK_START=$(date +%s)

# ============================================================
# Phase 1: nf-core/rnaseq with HISAT2 + Picard (default)
# ============================================================
echo "=== Phase 1: nf-core/rnaseq test_full — HISAT2 + Picard ==="
echo "Start: $(date -Iseconds)"

cd $WORKDIR
PHASE1_START=$(date +%s)

nextflow run nf-core/rnaseq -r 3.14.0 \
  -profile test_full,docker \
  --aligner hisat2 \
  --max_cpus $(nproc) \
  --max_memory '30.GB' \
  --outdir $WORKDIR/results_hisat2_picard \
  -w $NXF_WORK \
  2>&1

PHASE1_END=$(date +%s)
echo "Phase 1 duration: $(( (PHASE1_END - PHASE1_START) / 60 ))m"
echo ""
df -h / $VOLDIR
echo ""

# ============================================================
# Phase 2: Extract Picard timings from execution trace
# ============================================================
echo "=== Phase 2: Extract Picard MarkDuplicates timings ==="

TRACE=$(find $WORKDIR/results_hisat2_picard/pipeline_info -name "execution_trace_*" 2>/dev/null | sort | tail -1)
if [ -n "$TRACE" ]; then
  echo "Trace: $TRACE"
  head -1 "$TRACE"
  grep -i "markdup\|picard\|dedup" "$TRACE" || echo "(no markdup entries)"
  cp "$TRACE" "$RESULTS/hisat2_picard_trace.txt"
else
  echo "ERROR: No trace file found"
  exit 1
fi
echo ""

# ============================================================
# Find pre-markdup BAMs
# ============================================================
mapfile -t BAMS < <(find $NXF_WORK -name "*.sorted.bam" -not -name "*.markdup.*" -not -name "*.st_*" -not -name "*.sb_*" -size +1M 2>/dev/null | sort)

if [ ${#BAMS[@]} -eq 0 ]; then
  echo "ERROR: No pre-markdup BAMs found"
  exit 1
fi

echo "Found ${#BAMS[@]} pre-markdup BAMs:"
for bam in "${BAMS[@]}"; do
  echo "  $(du -h "$bam" | cut -f1)  $bam"
done
echo ""

# CSV header
echo "sample,tool,threads,run,time_sec,dup_count,total_reads,peak_rss_kb" > "$RESULTS/timings.csv"

# ============================================================
# Phase 3: samtools markdup
# ============================================================
echo "=== Phase 3: samtools markdup ==="
PHASE3_START=$(date +%s)

for bam in "${BAMS[@]}"; do
  sample=$(basename "$bam" .sorted.bam)
  bamdir=$(dirname "$bam")
  echo "====== $sample ($(du -h "$bam" | cut -f1)) — samtools ======"

  for threads in 1 4 8 16; do
    for run in 1 2 3; do
      outbam="$bamdir/${sample}.st_t${threads}_r${run}.markdup.bam"
      timefile="$bamdir/${sample}.st_t${threads}_r${run}.time"

      echo "  samtools t=$threads run $run..."
      start_s=$(date +%s)

      /usr/bin/time -v bash -c "
        samtools sort -n -@ $threads '$bam' | \
        samtools fixmate -m -@ $threads - - | \
        samtools sort -@ $threads - | \
        samtools markdup -@ $threads -s \
          -f '$bamdir/${sample}.st_t${threads}_r${run}.stats' \
          - '$outbam'
      " 2>"$timefile"

      end_s=$(date +%s)
      elapsed=$((end_s - start_s))
      peak_rss=$(grep "Maximum resident" "$timefile" | awk '{print $NF}' || echo "0")
      dup_count=$(samtools view -c -f 1024 "$outbam")
      total_count=$(samtools view -c "$outbam")

      echo "    ${elapsed}s, dups=$dup_count/$total_count, RSS=${peak_rss}KB"
      echo "${sample},samtools,${threads},${run},${elapsed},${dup_count},${total_count},${peak_rss}" >> "$RESULTS/timings.csv"

      rm -f "$outbam"
    done
  done
  df -h $VOLDIR | tail -1
done

PHASE3_END=$(date +%s)
echo "Phase 3 duration: $(( (PHASE3_END - PHASE3_START) / 60 ))m"
echo ""

# ============================================================
# Phase 4: sambamba markdup
# ============================================================
echo "=== Phase 4: sambamba markdup ==="
PHASE4_START=$(date +%s)

for bam in "${BAMS[@]}"; do
  sample=$(basename "$bam" .sorted.bam)
  bamdir=$(dirname "$bam")
  echo "====== $sample ($(du -h "$bam" | cut -f1)) — sambamba ======"

  for threads in 1 4 8 16; do
    for run in 1 2 3; do
      outbam="$bamdir/${sample}.sb_t${threads}_r${run}.markdup.bam"
      timefile="$bamdir/${sample}.sb_t${threads}_r${run}.time"

      echo "  sambamba t=$threads run $run..."
      start_s=$(date +%s)

      /usr/bin/time -v sambamba markdup \
        -t $threads \
        --tmpdir="$TMPDIR_SAMBAMBA" \
        "$bam" "$outbam" \
        2>"$timefile"

      end_s=$(date +%s)
      elapsed=$((end_s - start_s))
      peak_rss=$(grep "Maximum resident" "$timefile" | awk '{print $NF}' || echo "0")
      dup_count=$(samtools view -c -f 1024 "$outbam")
      total_count=$(samtools view -c "$outbam")

      echo "    ${elapsed}s, dups=$dup_count/$total_count, RSS=${peak_rss}KB"
      echo "${sample},sambamba,${threads},${run},${elapsed},${dup_count},${total_count},${peak_rss}" >> "$RESULTS/timings.csv"

      rm -f "$outbam" "${outbam}.bai"
    done
  done
  df -h $VOLDIR | tail -1
done

PHASE4_END=$(date +%s)
echo "Phase 4 duration: $(( (PHASE4_END - PHASE4_START) / 60 ))m"
echo ""

# ============================================================
# Phase 5: Correctness comparison + Summary
# ============================================================
echo "============================================================"
echo "=== Phase 5: CORRECTNESS CHECK ==="
echo "============================================================"

for bam in "${BAMS[@]}"; do
  sample=$(basename "$bam" .sorted.bam)
  st_dups=$(grep "^${sample},samtools,1,1," "$RESULTS/timings.csv" | cut -d, -f6)
  sb_dups=$(grep "^${sample},sambamba,1,1," "$RESULTS/timings.csv" | cut -d, -f6)

  if [ "$st_dups" = "$sb_dups" ]; then
    echo "  $sample: MATCH — samtools=$st_dups, sambamba=$sb_dups"
  else
    delta=$((sb_dups - st_dups))
    echo "  $sample: DIFF — samtools=$st_dups, sambamba=$sb_dups (delta=$delta)"
  fi
done
echo ""

echo "============================================================"
echo "=== FULL RESULTS ==="
echo "============================================================"
echo ""
cat "$RESULTS/timings.csv"
echo ""
echo "Disk final:"
df -h / $VOLDIR
echo ""

BENCHMARK_END=$(date +%s)
TOTAL=$((BENCHMARK_END - BENCHMARK_START))
echo "============================================================"
echo "Benchmark complete: $(date -Iseconds)"
echo "Total duration: ${TOTAL}s ($(( TOTAL / 3600 ))h $(( (TOTAL % 3600) / 60 ))m)"
echo "Log: $LOG"
echo "CSV: $RESULTS/timings.csv"
echo "============================================================"
