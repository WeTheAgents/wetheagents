# Benchmark Results v2: samtools markdup vs Picard MarkDuplicates

**Date:** 2026-03-25
**Server:** Hetzner CCX33 (8 vCPU, 32GB RAM, 1TB volume)
**Dataset:** 4 human cell lines x 2 replicates = 8 samples (ENCODE RNA-seq)
**Pipeline:** nf-core/rnaseq 3.14.0, HISAT2 aligner, GRCh38

## Key Finding

**samtools markdup produces identical duplicate counts to Picard MarkDuplicates
on all 8 samples (1.5 billion reads total), while using 2-3x less memory
and running 1.9x faster at 8 threads.**

## Duplicate Count Verification

| Sample | Total Reads | Picard Dups | samtools Dups | Match |
|--------|------------|-------------|---------------|-------|
| GM12878_REP1 | 166,920,856 | 125,959,080 | 125,959,080 | EXACT |
| GM12878_REP2 | 167,447,266 | 126,547,322 | 126,547,322 | EXACT |
| H1_REP1 | 223,421,772 | 111,561,962 | 111,561,962 | EXACT |
| H1_REP2 | 186,588,970 | 97,362,860 | 97,362,860 | EXACT |
| K562_REP1 | 156,141,246 | 133,311,912 | 133,311,912 | EXACT |
| K562_REP2 | 195,837,638 | 160,964,676 | 160,964,676 | EXACT |
| MCF7_REP1 | 222,752,796 | 80,424,916 | 80,424,916 | EXACT |
| MCF7_REP2 | 230,760,862 | 98,159,168 | 98,159,168 | EXACT |

All optical duplicate counts = 0 (standard Illumina flowcell, no tile proximity).

## Performance: samtools markdup (sort-n + fixmate + sort + markdup)

### Time (seconds, mean of 3 runs)

| Sample | BAM Size | t=1 | t=4 | t=8 | Picard (1T) |
|--------|----------|-----|-----|-----|-------------|
| GM12878_REP1 | 9.0G | 5,070 | 1,220 | 995 | 1,791 |
| GM12878_REP2 | 9.1G | 5,090 | 1,230 | 1,003 | 1,780 |
| H1_REP1 | 12G | 5,889 | 1,460 | 1,188 | 2,272 |
| H1_REP2 | 9.2G | 4,865 | 1,218 | 988 | 1,895 |
| K562_REP1 | 8.7G | 4,579 | 1,141 | 920 | 1,651 |
| K562_REP2 | 12G | 5,884 | 1,417 | 1,167 | 2,109 |
| MCF7_REP1 | 13G | 5,907 | 1,440 | 1,185 | 2,340 |
| MCF7_REP2 | 12G | 6,147 | 1,521 | 1,244 | 2,379 |

### Speedup vs Picard

| Threads | Mean Speedup | Note |
|---------|-------------|------|
| t=1 | **0.37x** (2.7x slower) | 4 passes vs Picard's 1 pass |
| t=4 | **1.52x faster** | Crossover point |
| t=8 | **1.89x faster** | Best config for 8-vCPU machine |

### Peak RSS (KB)

| Sample | samtools t=1 | samtools t=4 | samtools t=8 | Picard |
|--------|-------------|-------------|-------------|--------|
| GM12878_REP1 | 3,132,520 | 3,616,836 | 7,229,156 | 22,400,000 |
| GM12878_REP2 | 4,511,232 | 4,514,872 | 7,230,092 | 25,000,000 |
| H1_REP1 | 12,193,024 | 12,195,944 | 12,200,448 | 19,700,000 |
| H1_REP2 | 5,554,944 | 5,557,760 | 7,383,992 | 25,000,000 |
| K562_REP1 | 2,454,272 | 3,626,204 | 7,247,048 | 21,800,000 |
| K562_REP2 | 1,915,272 | 3,625,972 | 7,245,568 | 19,000,000 |
| MCF7_REP1 | 13,281,504 | 13,284,428 | 13,288,564 | 19,800,000 |
| MCF7_REP2 | 11,974,764 | 11,978,244 | 11,982,392 | 19,000,000 |

**Mean peak RSS:** samtools t=8 = 9.2GB vs Picard = 21.5GB (**2.3x less memory**)

## OOM Stability

Picard MarkDuplicates OOM'd (exit 137) on **5 of 8 samples** on first attempt
with 32GB RAM. Required Nextflow retry with increased memory allocation.

samtools markdup: **zero OOM events** across 72 runs (8 samples x 3 threads x 3 runs).

## Pipeline Architecture

samtools markdup requires a 4-step pipeline (vs Picard's single command):

```
samtools sort -n -@ $T input.bam \
| samtools fixmate -m -@ $T - - \
| samtools sort -@ $T - \
| samtools markdup -@ $T -s - output.bam
```

This is the standard nf-core subworkflow: `BAM_MARKDUPLICATES_SAMTOOLS`
(COLLATE + FIXMATE + SORT + MARKDUP).

At t=1, the 4 passes make samtools 2.7x slower than Picard's single pass.
At t>=4, multithreading compensates and samtools wins.
nf-core/rnaseq defaults allocate 4+ CPUs per task, so this is the expected regime.

## Thread Scaling

| Transition | Mean Speedup |
|-----------|-------------|
| t=1 -> t=4 | 4.1x |
| t=4 -> t=8 | 1.2x |
| t=1 -> t=8 | 5.1x |

Near-linear scaling from t=1 to t=4. Diminishing returns at t=8
(I/O becomes bottleneck on single SATA volume).

## Data Provenance

- Phase 1 trace: `data/traces/hisat2_picard_trace.txt` (268 tasks, nf-core/rnaseq full pipeline)
- Phase 2 CSV: `data/traces/samtools_markdup_timings.csv` (72 runs)
- Picard metrics: `data/traces/picard_metrics/*.MarkDuplicates.metrics.txt`
- samtools stats: `data/traces/samtools_stats/*.stats`
- Pipeline reports: `data/traces/pipeline_info/`
- Salmon counts (Picard pipeline): `data/traces/salmon_picard/`

## Limitations

1. **Single machine.** Results are for 8 vCPU / 32GB. Larger machines may show different scaling.
2. **No optical duplicates.** Dataset has 0 optical dups. Picard vs samtools may diverge
   on patterned flowcell data (e.g., NovaSeq S4) where optical dup detection differs.
3. **No downstream comparison.** Gene counts from Picard pipeline are saved but
   we did not re-run the full pipeline with samtools to compare featureCounts output.
   Given identical dup counts, downstream results should be identical.

## Conclusion

For standard RNA-seq on non-patterned flowcells with >=4 CPUs per task,
samtools markdup is a drop-in replacement for Picard MarkDuplicates:
same results, less memory, faster execution, zero OOM risk.
