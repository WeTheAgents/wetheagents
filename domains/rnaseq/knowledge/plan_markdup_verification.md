# Plan: samtools markdup vs Picard — Full Verification

**Status**: Draft v1, 2026-03-19
**Goal**: Produce data-driven evidence for adding `--markdup_tool samtools` option to nf-core/rnaseq

---

## What we already have (test profile, yeast)

- samtools markdup is **2-9x faster** (1 thread) and **5-17x faster** (4 threads) than Picard
- **Identical duplicate counts** across all 5 samples
- samtools uses ~24MB RSS vs Picard's 3.8GB JVM heap in-pipeline
- nf-core/modules has production-ready `samtools/markdup` module
- MultiQC has dedicated samtools markdup module (JSON + text output)

## What we need to prove on full human genome

### Phase 1: Correctness verification (critical path)

**Question**: Do Picard and samtools markdup produce identical results on human RNA-seq data?

**Method**:
1. Run nf-core/rnaseq with `test_full` profile (GRCh37, Salmon pseudo-aligner)
   - This avoids STAR's 38GB RAM requirement
   - Pipeline will still run Picard MarkDuplicates on genome-aligned BAMs
2. Extract the coordinate-sorted BAMs from pipeline work directory
3. Run samtools markdup on same BAMs with varying thread counts (1, 4, 6, 12)
4. Compare:
   - **Dup counts**: must be identical or documented why different
   - **Flagged read positions**: `samtools view -f 1024` on both outputs, diff the read names
   - **Metrics output**: verify samtools stats are parseable by MultiQC

**Expected duration**: 2-4 hours (Salmon mode, no STAR bottleneck)
**Infrastructure**: 15GB RAM + 32GB swap is sufficient for test_full with Salmon

### Phase 2: Performance benchmark (full genome)

**Question**: How much faster is samtools markdup on real-size human BAMs?

**Method**:
1. Use BAMs from Phase 1 (human genome, realistic file sizes)
2. Benchmark both tools:
   ```bash
   # Picard
   /usr/bin/time -v picard MarkDuplicates I=input.bam O=picard_out.bam M=picard_metrics.txt

   # samtools (requires fixmate first)
   /usr/bin/time -v samtools fixmate -m input.bam - | samtools sort - | samtools markdup -s -f stats.txt - samtools_out.bam

   # samtools with threads
   /usr/bin/time -v samtools markdup -s -f stats.txt --threads 4 input_fixmate.bam samtools_out.bam
   ```
3. Measure: wall time, peak RSS, CPU utilization
4. Multiple runs for statistical significance (3 runs each)

**Expected outcome**: On 100M+ read human BAMs, expect:
- Picard: 10-30 minutes, 4-8GB RSS, 1 CPU
- samtools (4t): 2-5 minutes, <1GB RSS, 4 CPUs utilized
- Speedup: 5-15x

### Phase 3: Edge case testing

**Question**: Are there RNA-seq-specific scenarios where results differ?

**Tests**:
1. **Optical duplicates**: Run with `-d 100` (HiSeq) and `-d 2500` (NovaSeq), compare with Picard
2. **Supplementary alignments**: Check `-S` flag behavior for chimeric reads (common in RNA-seq)
3. **MultiQC compatibility**: Feed samtools stats to MultiQC, verify report generation
4. **Metrics parity**: Map Picard metrics fields to samtools markdup stats fields

### Phase 4: Integration design (for PR)

**Approach**: Add as option, NOT replace default

```groovy
// nextflow.config addition
markdup_tool = 'picard'  // default stays Picard (safe, established)
// User can set: --markdup_tool samtools
```

**What the PR would include**:
1. New subworkflow: `bam_markduplicates_samtools` (mirror structure of `bam_markduplicates_picard`)
2. Config parameter: `--markdup_tool` with validation
3. Conditional routing in main workflow
4. Updated MultiQC config to collect samtools markdup stats
5. Documentation: when to use which tool, benchmark data
6. Tests: CI test with `--markdup_tool samtools`

**What the PR would NOT do**:
- Change the default (Picard stays default)
- Remove Picard support
- Claim samtools is "better" — present data, let users decide

### Phase 5: Community engagement

**Before coding**:
1. Open Issue in nf-core/rnaseq presenting benchmark data
2. Ask maintainers if this direction is welcome
3. Reference existing samtools/markdup module in nf-core/modules
4. Reference MultiQC samtools markdup support

**Message template**:
```
Title: [Feature request] Add samtools markdup as alternative to Picard MarkDuplicates

Hi! I've been profiling nf-core/rnaseq and noticed that Picard MarkDuplicates
is the 3rd most time-consuming step (~9% of total runtime). I benchmarked
samtools markdup as an alternative:

[test profile results table]
[test_full results table]

Key findings:
- samtools markdup is Xx faster with Y threads
- Duplicate counts are identical on all tested samples
- samtools/markdup module already exists in nf-core/modules
- MultiQC has a dedicated samtools markdup module

I'd like to propose adding --markdup_tool samtools as an option (keeping Picard
as default). Would this be welcome? Any concerns I should address first?

Benchmark data and scripts: [link to repo/gist]
```

---

## Risks and mitigations

| Risk | Mitigation |
|------|------------|
| Heng Li doesn't recommend samtools markdup for precision dedup | Frame as "option for speed-sensitive workflows", not replacement |
| Different dup counts on some edge cases | Document differences, provide guidance on when Picard is preferred |
| Maintainers say "not needed" | Respect decision; publish benchmark data as Issue anyway |
| samtools markdup requires fixmate preprocessing | Handle in subworkflow; check if STAR output already has mate info |
| MultiQC report looks different | Test thoroughly, ensure equivalent information |

## Decision: run Phase 1 next

Infrastructure is ready (15GB + 32GB swap). test_full with Salmon doesn't need STAR.
Next step: run the pipeline, extract BAMs, benchmark both tools on real human data.
