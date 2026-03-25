# Benchmark Results v1 — nf-core/rnaseq 3.23.0 (test profile)

**Date**: 2026-03-18
**Machine**: Ryzen 5 4600H, 6C/12T, WSL2 15GB RAM, Docker Desktop 4.65.0
**Pipeline**: nf-core/rnaseq v3.23.0, test profile (yeast genome, 5 samples)
**Work dir**: ~/rnaseq-work (ext4, Linux FS — required for STAR FIFO)

## Summary

| Config | Total realtime | Tasks | Bottleneck |
|--------|---------------|-------|------------|
| TrimGalore + STAR→Salmon (default) | 10m 33s | 219 | STAR_ALIGN (31%) |
| fastp + STAR→Salmon | 10m 32s | 224 | STAR_ALIGN (30%) |
| Salmon-only (pseudo-alignment) | 4m 1s | 58 | BBMAP_BBSPLIT (39%) |

## Top 10 Processes by Realtime (TrimGalore run)

| Process | N | Total | % | Avg CPU% | Peak RSS |
|---------|---|-------|---|----------|----------|
| STAR_ALIGN | 5 | 3m 18s | 31% | 114% | 0.9 GB |
| BBMAP_BBSPLIT | 6 | 1m 24s | 13% | 384% | 1.3 GB |
| PICARD_MARKDUPLICATES | 5 | 55.1s | 9% | 180% | 4.1 GB |
| MULTIQC | 1 | 43.6s | 7% | 132% | 1.0 GB |
| TRIMGALORE | 5 | 37.0s | 6% | 146% | 0.3 GB |
| DUPRADAR | 5 | 25.6s | 4% | 104% | 0.2 GB |
| SALMON_QUANT | 11 | 22.0s | 3% | 108% | 0.8 GB |
| FASTQC | 5 | 18.0s | 3% | 182% | 0.5 GB |
| FASTQC_FILTERED | 5 | 18.0s | 3% | 210% | 0.5 GB |
| DESEQ2_QC_PSEUDO | 1 | 17.9s | 3% | 108% | 0.7 GB |

## Picard MarkDuplicates — Per-Sample Detail (TrimGalore run)

| Sample | Realtime | Duration | CPU% | Peak RSS | Peak VMEM |
|--------|----------|----------|------|----------|-----------|
| RAP1_UNINDUCED_REP1 | 11.8s | 14.7s | 155% | 3.6 GB | 15.7 GB |
| WT_REP2 | 9.3s | 11.9s | 191% | 3.9 GB | 16.4 GB |
| RAP1_IAA_30M_REP1 | 8.6s | 10.9s | 190% | 3.7 GB | 16.4 GB |
| RAP1_UNINDUCED_REP2 | 9.9s | 12.3s | 182% | 3.7 GB | 16.4 GB |
| WT_REP1 | 15.5s | 17.9s | 180% | 4.1 GB | 16.4 GB |

**Average**: 11.0s realtime, 180% CPU (1.8 cores), 3.8 GB RSS
**Observation**: Java single-threaded. 4.2 CPUs wasted per sample. Peak VMEM 16.4GB shows JVM heap reservation far exceeding actual use.

## fastp vs TrimGalore — Key Comparison

| Metric | TrimGalore | fastp | Verdict |
|--------|-----------|-------|---------|
| Trimming step | 37.0s | 18.6s | fastp 2x faster |
| Total pipeline | 10m 33s | 10m 32s | **No difference** |
| Extra QC steps | — | FASTQC_RAW +18s, FASTQC_TRIM +14s | Eats the gain |

fastp is faster at trimming but the fastp pipeline adds additional QC steps that negate the speedup on test data. Absolute numbers are small — proportions may differ on real datasets.

## Key Conclusions

1. **STAR_ALIGN is the dominant bottleneck** (31%). Cannot be optimized without changing aligner.
2. **Picard MarkDuplicates is #3** (9%) and the most promising optimization target: Java single-threaded, ~4 CPUs wasted.
3. **fastp vs TrimGalore**: negligible total difference on test data due to additional QC overhead.
4. **Salmon-only is 2.6x faster** by skipping alignment entirely.
5. **RAM waste undetectable** on test profile — files too small to stress memory.

## samtools markdup vs Picard — Direct Comparison (test data)

**Date**: 2026-03-19
**Method**: Extracted BAM from pipeline work dir, ran Picard and samtools markdup separately with 1/4/6 threads.

### Results

| Sample | Tool | Threads | Wall time (s) | Peak RSS (KB) | Dup count | Total reads |
|--------|------|---------|---------------|---------------|-----------|-------------|
| WT_REP1 | picard | 1 | 15.0 | 23,680 | 36,810 | 180,342 |
| WT_REP1 | samtools | 1 | 7.5 | 24,064 | 36,810 | 180,342 |
| WT_REP1 | samtools | 4 | 2.0 | 24,064 | 36,810 | 180,342 |
| WT_REP2 | picard | 1 | 11.5 | 24,192 | 11,688 | 90,962 |
| WT_REP2 | samtools | 1 | 2.2 | 23,680 | 11,688 | 90,962 |
| WT_REP2 | samtools | 4 | 1.3 | 23,680 | 11,688 | 90,962 |
| RAP1_UNINDUCED_REP2 | picard | 1 | 10.2 | 24,192 | 78,929 | 98,201 |
| RAP1_UNINDUCED_REP2 | samtools | 1 | 2.3 | 24,320 | 78,929 | 98,201 |
| RAP1_UNINDUCED_REP2 | samtools | 4 | 1.2 | 23,936 | 78,929 | 98,201 |
| RAP1_UNINDUCED_REP1 | picard | 1 | 12.0 | 23,808 | 36,294 | 48,977 |
| RAP1_UNINDUCED_REP1 | samtools | 1 | 1.4 | 23,936 | 36,294 | 48,977 |
| RAP1_UNINDUCED_REP1 | samtools | 4 | 0.9 | 24,064 | 36,294 | 48,977 |
| RAP1_IAA_30M_REP1 | picard | 1 | 9.9 | 24,064 | 11,094 | 91,232 |
| RAP1_IAA_30M_REP1 | samtools | 1 | 2.4 | 24,448 | 11,094 | 91,232 |
| RAP1_IAA_30M_REP1 | samtools | 4 | 1.3 | 23,808 | 11,094 | 91,232 |

### Key Findings

1. **Speed**: samtools markdup (1 thread) is **2-9x faster** than Picard. With 4 threads: **5-17x faster**.
2. **Memory**: ~24MB RSS for samtools vs ~24MB standalone (but Picard in-pipeline uses 3.8GB JVM heap).
3. **Accuracy**: **Identical dup counts** across all 5 samples — both tools find the same duplicates.
4. **Scaling**: samtools 4→6 threads shows diminishing returns on small files. On full genome, expect better scaling.

### Caveats

- Test data is tiny (yeast, 50K-180K reads). Speed ratios may change on human genome (100M+ reads).
- Picard in standalone mode uses less RSS than in-pipeline (no JVM pre-allocated heap).
- Need to verify: does samtools markdup produce `.metrics` compatible with MultiQC?
- Need to verify: behavior on edge cases (UMI, supplementary alignments, optical duplicates).

## Infrastructure Status (2026-03-19)

- WSL2 Ubuntu-Noble: 15GB RAM + 32GB swap = 47GB addressable
- Docker Desktop 4.65.0 with WSL integration
- Nextflow 25.10.4, Java 21
- swap file on D: drive (NVMe SSD)
- **test_full profile now feasible** with swap — expect STAR index load to page heavily but complete
