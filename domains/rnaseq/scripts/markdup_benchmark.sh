#!/bin/bash
# W∃A × nf-core/rnaseq: Picard vs samtools markdup comparison
#
# Uses sorted BAMs from pipeline benchmark run (~/rnaseq-work/).
# Runs both tools on same inputs, captures timing + dup counts.
#
# Prerequisites: Docker Desktop running, BAMs in ~/rnaseq-work/
# Usage: wsl bash scripts/markdup_benchmark.sh

set -euo pipefail

RESULTSDIR="$HOME/rnaseq-results/markdup"
WORKDIR="$HOME/rnaseq-work"
TSV="$RESULTSDIR/markdup_results.tsv"

# Docker images (already cached from pipeline run)
PICARD_IMG="community.wave.seqera.io/library/picard:3.4.0--e9963040df0a9bf6"
SAMTOOLS_IMG="quay.io/biocontainers/samtools:1.22.1--h96c455f_0"

mkdir -p "$RESULTSDIR"

echo "=== W∃A markdup Benchmark: Picard vs samtools ==="
echo "Date: $(date -Iseconds)"
echo ""

# Find one sorted BAM per sample from the trimgalore run (first 5 Picard work dirs)
# These are the exact inputs Picard used in the pipeline
PICARD_DIRS=$(grep -rl 'MarkDuplicates' "$WORKDIR"/*/. --include='.command.sh' 2>/dev/null | head -5)

declare -A SAMPLE_BAMS
for cmdsh in $PICARD_DIRS; do
  dir=$(dirname "$cmdsh")
  bam=$(ls "$dir"/*.sorted.bam 2>/dev/null | grep -v markdup | head -1)
  if [ -n "$bam" ]; then
    sample=$(basename "$bam" .sorted.bam)
    # Keep first occurrence per sample (avoid duplicates from fastp run)
    if [ -z "${SAMPLE_BAMS[$sample]+x}" ]; then
      SAMPLE_BAMS[$sample]="$bam"
    fi
  fi
done

echo "Found ${#SAMPLE_BAMS[@]} samples:"
for s in "${!SAMPLE_BAMS[@]}"; do
  echo "  $s: $(du -h "${SAMPLE_BAMS[$s]}" | cut -f1)"
done
echo ""

# TSV header
echo -e "sample\ttool\tthreads\twall_time_s\tpeak_rss_kb\tdup_count\ttotal_reads" > "$TSV"

run_picard() {
  local sample="$1"
  local bam="$2"
  local outdir="$RESULTSDIR/picard_${sample}"
  mkdir -p "$outdir"

  echo "  [picard] $sample..."

  # Copy BAM to outdir (Picard needs write access)
  cp "$bam" "$outdir/${sample}.sorted.bam"

  /usr/bin/time -v docker run --rm \
    -v "$outdir":/data \
    "$PICARD_IMG" \
    picard -Xmx12288M MarkDuplicates \
      --ASSUME_SORTED true \
      --REMOVE_DUPLICATES false \
      --VALIDATION_STRINGENCY LENIENT \
      --TMP_DIR /data/tmp \
      --INPUT "/data/${sample}.sorted.bam" \
      --OUTPUT "/data/${sample}.markdup.bam" \
      --METRICS_FILE "/data/${sample}.picard_metrics.txt" \
    2>"$outdir/time_picard.txt"

  # Extract timing
  local wall_time=$(grep "Elapsed (wall clock)" "$outdir/time_picard.txt" | sed 's/.*: //')
  local peak_rss=$(grep "Maximum resident" "$outdir/time_picard.txt" | sed 's/.*: //')

  # Convert wall time (h:mm:ss or m:ss.ss) to seconds
  local wall_s=$(echo "$wall_time" | awk -F: '{if (NF==3) print $1*3600+$2*60+$3; else print $1*60+$2}')

  # Get dup count via flagstat
  local dup_count=$(docker run --rm -v "$outdir":/data "$SAMTOOLS_IMG" \
    samtools flagstat "/data/${sample}.markdup.bam" | grep -m1 "duplicates" | awk '{print $1}')
  local total_reads=$(docker run --rm -v "$outdir":/data "$SAMTOOLS_IMG" \
    samtools flagstat "/data/${sample}.markdup.bam" | head -1 | awk '{print $1}')

  echo -e "${sample}\tpicard\t1\t${wall_s}\t${peak_rss}\t${dup_count}\t${total_reads}" >> "$TSV"
  echo "    wall=${wall_s}s rss=${peak_rss}KB dups=${dup_count}/${total_reads}"
}

run_samtools() {
  local sample="$1"
  local bam="$2"
  local threads="$3"
  local outdir="$RESULTSDIR/samtools_${sample}_t${threads}"
  mkdir -p "$outdir"

  echo "  [samtools -@ $threads] $sample..."

  # Copy BAM to outdir
  cp "$bam" "$outdir/${sample}.sorted.bam"

  # samtools markdup requires MC tags from fixmate.
  # Pipeline: sort-by-name → fixmate -m → sort-by-coord → markdup
  # We time the FULL pipeline (fixmate + sort + markdup) for fair comparison.
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

  # Extract timing
  local wall_time=$(grep "Elapsed (wall clock)" "$outdir/time_samtools.txt" | sed 's/.*: //')
  local peak_rss=$(grep "Maximum resident" "$outdir/time_samtools.txt" | sed 's/.*: //')
  local wall_s=$(echo "$wall_time" | awk -F: '{if (NF==3) print $1*3600+$2*60+$3; else print $1*60+$2}')

  # Get dup count
  local dup_count=$(docker run --rm -v "$outdir":/data "$SAMTOOLS_IMG" \
    samtools flagstat "/data/${sample}.markdup.bam" | grep -m1 "duplicates" | awk '{print $1}')
  local total_reads=$(docker run --rm -v "$outdir":/data "$SAMTOOLS_IMG" \
    samtools flagstat "/data/${sample}.markdup.bam" | head -1 | awk '{print $1}')

  echo -e "${sample}\tsamtools\t${threads}\t${wall_s}\t${peak_rss}\t${dup_count}\t${total_reads}" >> "$TSV"
  echo "    wall=${wall_s}s rss=${peak_rss}KB dups=${dup_count}/${total_reads}"
}

# ─── Run benchmarks ───
for sample in "${!SAMPLE_BAMS[@]}"; do
  bam="${SAMPLE_BAMS[$sample]}"
  echo ""
  echo "--- $sample ($(du -h "$bam" | cut -f1)) ---"

  run_picard "$sample" "$bam"
  run_samtools "$sample" "$bam" 1
  run_samtools "$sample" "$bam" 4
  run_samtools "$sample" "$bam" 6
done

# ─── Copy results to D: ───
WIN_OUTDIR="/mnt/d/GitHub/wetheagents/domains/rnaseq/benchmark_results"
mkdir -p "$WIN_OUTDIR"
cp -v "$TSV" "$WIN_OUTDIR/markdup_results.tsv"

echo ""
echo "=== Benchmark complete ==="
echo "Results: $TSV"
echo ""
echo "Next: uv run python scripts/run_analysis.py --markdup benchmark_results/markdup_results.tsv"
