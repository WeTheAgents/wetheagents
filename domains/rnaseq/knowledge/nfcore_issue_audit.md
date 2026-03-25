# nf-core/rnaseq Issue Audit

Findings from searching nf-core/rnaseq Issues. Updated: 2026-03-18.

## fastp

| Issue | Status | Finding |
|-------|--------|---------|
| #1200 | Open | fastp breaks UMI processing for Smart3-seq data. TrimGalore works correctly. This is a concrete reason fastp CANNOT be default — less tested in edge cases |

## Picard MarkDuplicates

| Issue | Status | Finding |
|-------|--------|---------|
| #82 | Closed | Picard crashes with "No space left on device" due to Java tmpdir. Known problem |
| #293 | Closed | Memory >8GB breaks Groovy parsing. Fixed, but shows fragility of Java dependency |
| #891 | Closed | Proposal to skip MarkDuplicates with UMI — accepted |

## samtools markdup

**No issues found.** Nobody has proposed samtools markdup as an alternative to Picard. Potentially novel contribution.

## Performance profiling

**No public trace profiles found.** No issues with "benchmark" or "performance profile" tags yielding timing data. Our trace data could be genuinely useful.

## Still to check

- Closed issues tagged "performance", "enhancement"
- CHANGELOG.md: when and why fastp was added
- nf-core Slack archive for same queries
