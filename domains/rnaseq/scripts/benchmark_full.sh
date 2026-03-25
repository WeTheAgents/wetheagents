#!/bin/bash
# W∃A × nf-core/rnaseq: Phase 1 — Full Human Genome Benchmark
#
# Runs test_full profile (GRCh37) with HISAT2 aligner (memory-efficient).
# HISAT2 uses ~8GB RAM vs STAR's ~38GB — avoids swap thrashing on 15GB machine.
# BAM format is identical for markdup comparison purposes.
#
# After pipeline: runs Picard vs samtools markdup on human-scale BAMs.
#
# Usage: wsl bash scripts/benchmark_full.sh

set -euo pipefail

WORKDIR="$HOME/rnaseq-full-work"
RESULTSDIR="$HOME/rnaseq-full-results"
MARKDUP_DIR="$RESULTSDIR/markdup"
VER="3.23.0"
WIN_OUTDIR="/mnt/d/GitHub/wetheagents/domains/rnaseq/benchmark_results/full_genome"

mkdir -p "$WORKDIR" "$RESULTSDIR" "$MARKDUP_DIR" "$WIN_OUTDIR"

echo "=== W∃A Phase 1: Full Human Genome Benchmark ==="
echo "Date: $(date -Iseconds)"
echo "Machine: $(nproc) threads, $(free -h | awk '/^Mem:/{print $2}') RAM, $(free -h | awk '/^Swap:/{print $2}') swap"
echo "Work dir: $WORKDIR (Linux FS, $(df -h / | tail -1 | awk '{print $4}') free)"
echo "Pipeline: nf-core/rnaseq v${VER}, test_full profile, HISAT2 aligner"
echo ""

# ─── Step 1: Run pipeline ───
echo "=== Step 1/3: Running nf-core/rnaseq test_full with HISAT2 ==="
echo "This will take 1-3 hours. HISAT2 needs ~8GB RAM (within our 15GB limit)."
echo ""

cd "$HOME"

nextflow run nf-core/rnaseq -r $VER \
  -profile test_full,docker \
  --aligner hisat2 \
  -w "$WORKDIR" \
  --outdir "$RESULTSDIR/pipeline_output" \
  -with-trace "$RESULTSDIR/trace_full.txt" \
  -with-timeline "$RESULTSDIR/timeline_full.html" \
  -with-report "$RESULTSDIR/report_full.html" \
  2>&1 | tee "$RESULTSDIR/log_full.txt"

echo ""
echo "=== Pipeline complete. Extracting BAMs for markdup benchmark... ==="
echo ""

# ─── Step 2: Find BAMs from Picard work dirs ───
echo "=== Step 2/3: Markdup Benchmark (Picard vs samtools) ==="

# Docker images
PICARD_IMG="community.wave.seqera.io/library/picard:3.4.0--e9963040df0a9bf6"
SAMTOOLS_IMG="quay.io/biocontainers/samtools:1.22.1--h96c455f_0"

# Pull images if not cached
docker pull "$PICARD_IMG" 2>/dev/null || true
docker pull "$SAMTOOLS_IMG" 2>/dev/null || true

TSV="$MARKDUP_DIR/markdup_full_results.tsv"
echo -e "sample\ttool\tthreads\twall_time_s\tpeak_rss_kb\tdup_count\ttotal_reads\tbam_size_mb" > "$TSV"

# Find sorted BAMs from Picard work directories
echo "Searching for BAMs in $WORKDIR..."
declare -A SAMPLE_BAMS
while IFS= read -r cmdsh; do
  dir=$(dirname "$cmdsh")
  bam=$(ls "$dir"/*.sorted.bam 2>/dev/null | grep -v markdup | head -1)
  if [ -n "$bam" ]; then
    sample=$(basename "$bam" .sorted.bam)
    if [ -z "${SAMPLE_BAMS[$sample]+x}" ]; then
      SAMPLE_BAMS[$sample]="$bam"
    fi
  fi
done < <(grep -rl 'MarkDuplicates' "$WORKDIR"/*/. --include='.command.sh' 2>/dev/null | head -20)

echo "Found ${#SAMPLE_BAMS[@]} samples:"
for s in "${!SAMPLE_BAMS[@]}"; do
  echo "  $s: $(du -h "${SAMPLE_BAMS[$s]}" | cut -f1)"
done
echo ""

run_picard() {
  local sample="$1"
  local bam="$2"
  local outdir="$MARKDUP_DIR/picard_${sample}"
  mkdir -p "$outdir/tmp"

  echo "  [picard] $sample..."
  cp "$bam" "$outdir/${sample}.sorted.bam"

  /usr/bin/time -v docker run --rm \
    -v "$outdir":/data \
    "$PICARD_IMG" \
    picard -Xmx4096M MarkDuplicates \
      --ASSUME_SORTED true \
      --REMOVE_DUPLICATES false \
      --VALIDATION_STRINGENCY LENIENT \
      --TMP_DIR /data/tmp \
      --INPUT "/data/${sample}.sorted.bam" \
      --OUTPUT "/data/${sample}.markdup.bam" \
      --METRICS_FILE "/data/${sample}.picard_metrics.txt" \
    2>"$outdir/time_picard.txt"

  local wall_time=$(grep "Elapsed (wall clock)" "$outdir/time_picard.txt" | sed 's/.*: //')
  local peak_rss=$(grep "Maximum resident" "$outdir/time_picard.txt" | sed 's/.*: //')
  local wall_s=$(echo "$wall_time" | awk -F: '{if (NF==3) print $1*3600+$2*60+$3; else print $1*60+$2}')

  local dup_count=$(docker run --rm -v "$outdir":/data "$SAMTOOLS_IMG" \
    samtools flagstat "/data/${sample}.markdup.bam" | grep -m1 "duplicates" | awk '{print $1}')
  local total_reads=$(docker run --rm -v "$outdir":/data "$SAMTOOLS_IMG" \
    samtools flagstat "/data/${sample}.markdup.bam" | head -1 | awk '{print $1}')
  local bam_size=$(du -m "$bam" | cut -f1)

  echo -e "${sample}\tpicard\t1\t${wall_s}\t${peak_rss}\t${dup_count}\t${total_reads}\t${bam_size}" >> "$TSV"
  echo "    wall=${wall_s}s rss=${peak_rss}KB dups=${dup_count}/${total_reads} bam=${bam_size}MB"
}

run_samtools() {
  local sample="$1"
  local bam="$2"
  local threads="$3"
  local outdir="$MARKDUP_DIR/samtools_${sample}_t${threads}"
  mkdir -p "$outdir"

  echo "  [samtools -@ $threads] $sample..."
  cp "$bam" "$outdir/${sample}.sorted.bam"

  # Full pipeline: name-sort → fixmate → coord-sort → markdup
  /usr/bin/time -v docker run --rm \
    -v "$outdir":/data \
    "$SAMTOOLS_IMG" \
    bash -c "\
      samtools sort -n -@ $threads /data/${sample}.sorted.bam | \
      samtools fixmate -m -@ $threads - - | \
      samtools sort -@ $threads - | \
      samtools markdup -@ $threads -s -f /data/${sample}.samtools_stats.txt - /data/${sample}.markdup.bam && \
      samtools index /data/${sample}.markdup.bam \
    " \
    2>"$outdir/time_samtools.txt"

  local wall_time=$(grep "Elapsed (wall clock)" "$outdir/time_samtools.txt" | sed 's/.*: //')
  local peak_rss=$(grep "Maximum resident" "$outdir/time_samtools.txt" | sed 's/.*: //')
  local wall_s=$(echo "$wall_time" | awk -F: '{if (NF==3) print $1*3600+$2*60+$3; else print $1*60+$2}')

  local dup_count=$(docker run --rm -v "$outdir":/data "$SAMTOOLS_IMG" \
    samtools flagstat "/data/${sample}.markdup.bam" | grep -m1 "duplicates" | awk '{print $1}')
  local total_reads=$(docker run --rm -v "$outdir":/data "$SAMTOOLS_IMG" \
    samtools flagstat "/data/${sample}.markdup.bam" | head -1 | awk '{print $1}')
  local bam_size=$(du -m "$bam" | cut -f1)

  echo -e "${sample}\tsamtools\t${threads}\t${wall_s}\t${peak_rss}\t${dup_count}\t${total_reads}\t${bam_size}" >> "$TSV"
  echo "    wall=${wall_s}s rss=${peak_rss}KB dups=${dup_count}/${total_reads} bam=${bam_size}MB"
}

# Run benchmarks on each sample
for sample in "${!SAMPLE_BAMS[@]}"; do
  bam="${SAMPLE_BAMS[$sample]}"
  echo ""
  echo "--- $sample ($(du -h "$bam" | cut -f1)) ---"

  run_picard "$sample" "$bam"
  run_samtools "$sample" "$bam" 1
  run_samtools "$sample" "$bam" 4
  run_samtools "$sample" "$bam" 8
done

# ─── Step 3: Copy results ───
echo ""
echo "=== Step 3/3: Copying results to Windows ==="
cp -v "$RESULTSDIR"/trace_full.txt "$WIN_OUTDIR/" 2>/dev/null || true
cp -v "$RESULTSDIR"/timeline_full.html "$WIN_OUTDIR/" 2>/dev/null || true
cp -v "$RESULTSDIR"/report_full.html "$WIN_OUTDIR/" 2>/dev/null || true
cp -v "$RESULTSDIR"/log_full.txt "$WIN_OUTDIR/" 2>/dev/null || true
cp -v "$TSV" "$WIN_OUTDIR/" 2>/dev/null || true

# Copy Picard and samtools metrics for MultiQC comparison
for d in "$MARKDUP_DIR"/picard_*; do
  [ -d "$d" ] && cp "$d"/*.picard_metrics.txt "$WIN_OUTDIR/" 2>/dev/null || true
done
for d in "$MARKDUP_DIR"/samtools_*; do
  [ -d "$d" ] && cp "$d"/*.samtools_stats.txt "$WIN_OUTDIR/" 2>/dev/null || true
done

echo ""
echo "=== Phase 1 Complete ==="
echo "Pipeline trace: $WIN_OUTDIR/trace_full.txt"
echo "Markdup results: $WIN_OUTDIR/markdup_full_results.tsv"
echo ""
echo "Key files for nf-core contribution:"
echo "  Picard metrics: $WIN_OUTDIR/*.picard_metrics.txt"
echo "  samtools stats: $WIN_OUTDIR/*.samtools_stats.txt"
echo "  Pipeline trace: $WIN_OUTDIR/trace_full.txt"
