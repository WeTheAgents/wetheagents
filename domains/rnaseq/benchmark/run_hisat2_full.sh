#!/bin/bash
set -euo pipefail

# nf-core/rnaseq benchmark: HISAT2 + test_full (GRCh37 human genome)
# HISAT2 needs ~8GB RAM (vs STAR ~38GB), fits in 16GB laptop

WORKDIR=/home/peach/rnaseq-bench
RESULTS=$WORKDIR/results
LOG=$WORKDIR/hisat2_benchmark.log
mkdir -p $RESULTS

exec > >(tee -a "$LOG") 2>&1

echo "=== nf-core/rnaseq HISAT2 Full Human Genome Benchmark ==="
echo "Started: $(date -Iseconds)"
echo "Memory: $(free -h | grep Mem | awk '{print $2}')"
echo "Swap: $(free -h | grep Swap | awk '{print $2}')"
echo ""

# Phase 1: Run pipeline with HISAT2 aligner (uses Picard MarkDuplicates by default)
echo "=== Phase 1: nf-core/rnaseq test_full + HISAT2 + Picard MarkDuplicates ==="
cd $WORKDIR

nextflow run nf-core/rnaseq -r 3.14.0 \
  -profile test_full,docker \
  --aligner hisat2 \
  --outdir $WORKDIR/results_hisat2_picard \
  -resume \
  2>&1

echo ""
echo "=== Phase 1 complete: $(date -Iseconds) ==="

# Phase 2: Extract Picard timing from execution trace
echo ""
echo "=== Phase 2: Picard MarkDuplicates timing ==="
TRACE=$(find $WORKDIR/results_hisat2_picard/pipeline_info -name "execution_trace_*" 2>/dev/null | sort | tail -1)
if [ -n "$TRACE" ]; then
  echo "Trace file: $TRACE"
  echo "--- MarkDuplicates entries ---"
  head -1 "$TRACE"
  grep -i "markdup\|picard\|dedup" "$TRACE" || echo "No markdup entries found"
  echo ""
  echo "--- Full trace (for reference) ---"
  cat "$TRACE"
fi

# Phase 3: Run samtools markdup on the same BAMs
echo ""
echo "=== Phase 3: samtools markdup comparison ==="

# Find sorted BAMs from HISAT2 alignment (before Picard markdup)
# These are in the Nextflow work directory
BAMS=$(find $WORKDIR/work -name "*.bam" -path "*hisat2*" -size +1M 2>/dev/null | head -10)
if [ -z "$BAMS" ]; then
  # Try broader search
  BAMS=$(find $WORKDIR/work -name "*.sorted.bam" -size +1M 2>/dev/null | head -10)
fi
if [ -z "$BAMS" ]; then
  BAMS=$(find $WORKDIR/work -name "*.bam" -size +1M 2>/dev/null | grep -v "markdup\|dedup" | head -10)
fi

echo "Found BAMs:"
echo "$BAMS"
echo ""

for bam in $BAMS; do
  sample=$(basename "$bam" .bam)
  bamdir=$(dirname "$bam")
  bamfile=$(basename "$bam")
  size=$(du -h "$bam" | cut -f1)

  echo "Processing: $sample ($size)"

  # Run samtools markdup (name-sort -> fixmate -> coord-sort -> markdup)
  echo "  Running samtools fixmate + markdup pipeline..."
  start_ns=$(date +%s%N)

  docker run --rm -v "$bamdir:/data" \
    community.wave.seqera.io/library/samtools:1.21--585e5e8bffd1e8ce \
    bash -c "
      samtools sort -n -@ 4 /data/$bamfile | \
      samtools fixmate -m -@ 4 - - | \
      samtools sort -@ 4 - | \
      samtools markdup -@ 4 -s - /data/${sample}.samtools_markdup.bam \
      2>/data/${sample}.samtools_markdup.stats
    "

  end_ns=$(date +%s%N)
  elapsed_ms=$(( (end_ns - start_ns) / 1000000 ))
  echo "  samtools markdup: ${elapsed_ms}ms (${sample})"

  # Get flagstat comparison
  echo "  Flagstats:"
  docker run --rm -v "$bamdir:/data" \
    community.wave.seqera.io/library/samtools:1.21--585e5e8bffd1e8ce \
    bash -c "
      echo '  Original:'
      samtools flagstat /data/$bamfile
      echo '  samtools markdup:'
      samtools flagstat /data/${sample}.samtools_markdup.bam
    "

  # Print markdup stats
  if [ -f "$bamdir/${sample}.samtools_markdup.stats" ]; then
    echo "  Markdup stats:"
    cat "$bamdir/${sample}.samtools_markdup.stats"
  fi

  echo ""
done

echo "=== Benchmark complete: $(date -Iseconds) ==="
echo ""
echo "=== Summary ==="
echo "Log: $LOG"
echo "Picard results: $WORKDIR/results_hisat2_picard/"
echo "Execution trace: $TRACE"
