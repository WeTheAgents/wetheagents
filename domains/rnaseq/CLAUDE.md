# RNA-seq Pipeline Optimization

Profiling and optimizing the nf-core/rnaseq pipeline — the most widely used RNA-seq workflow (1200+ stars, 6800+ commits, maintained by Seqera Labs).

**Mission:** Contribute a data-driven optimization back to the community. We come with benchmarks, not opinions.

## Current Focus: samtools markdup as alternative to Picard MarkDuplicates

Picard MarkDuplicates is the 3rd most time-consuming step (~9% of total runtime). It's Java-based, single-threaded, and allocates 3.8GB JVM heap while wasting 5 of 6 allocated CPUs.

**samtools markdup** is a C-based, multi-threaded drop-in alternative. Our test-profile benchmark shows:
- **2-9x faster** (1 thread), **5-17x faster** (4 threads)
- **Identical duplicate counts** across all samples
- ~24MB RSS vs 3.8GB JVM heap
- Ready-made `BAM_MARKDUPLICATES_SAMTOOLS` subworkflow already exists in nf-core/modules

**Status:** Running full human genome (GRCh37) benchmark on Hetzner CCX33 cloud server.

## Repository Structure

```
domains/rnaseq/
├── CLAUDE.md              # this file
├── benchmark/             # cloud benchmark scripts
│   ├── cloud_setup.sh     # server provisioning (Docker, Java, Nextflow)
│   ├── cloud_benchmark.sh # full benchmark: HISAT2 + Picard vs samtools markdup
│   └── cloud_deploy.sh    # one-command deploy to cloud server
├── benchmark_results/     # raw trace files, logs, charts (gitignored)
├── knowledge/             # accumulated research findings
│   ├── research_plan.md   # 5 hypotheses, prioritized approach
│   ├── benchmark_results_v1.md  # test profile results + samtools comparison
│   ├── code_findings.md   # pipeline code analysis (6 findings)
│   ├── nfcore_issue_audit.md    # GitHub Issues research
│   └── plan_markdup_verification.md  # 5-phase verification plan
├── scripts/               # local benchmark scripts (WSL)
│   ├── benchmark.sh       # 3-config local benchmark
│   ├── markdup_benchmark.sh # Picard vs samtools comparison
│   └── run_analysis.py    # trace analysis entry point
├── src/                   # Python analysis toolkit
│   ├── trace_parser.py    # Nextflow trace TSV parser
│   ├── resource_analyzer.py # CPU/RAM waste detection
│   ├── markdup_analyzer.py  # markdup comparison analysis
│   └── report_generator.py  # markdown report generation
└── tests/                 # pytest test suite
```

## Running

```bash
# Local analysis of existing traces
cd domains/rnaseq
uv sync
uv run python scripts/run_analysis.py benchmark_results/trace_trimgalore.txt

# Cloud benchmark (requires server)
bash benchmark/cloud_deploy.sh <server-ip>

# Monitor cloud benchmark
ssh root@<server-ip> 'tmux attach -t bench'
ssh root@<server-ip> 'tail -50 /root/rnaseq-bench/results/benchmark_*.log'
```

## Key Research Findings

1. **STAR_ALIGN is the #1 bottleneck** (31% of runtime) — cannot be optimized without changing aligner
2. **Picard MarkDuplicates is #3** (9%) — most promising target: Java, single-threaded, 5 CPUs wasted
3. **fastp vs TrimGalore**: negligible difference on test data (extra QC steps negate trimming speedup)
4. **samtools markdup**: nobody has proposed it in nf-core/rnaseq Issues — novel contribution
5. **BAM_MARKDUPLICATES_SAMTOOLS subworkflow already exists** in nf-core/modules — minimal PR needed

## PR Strategy

Add `--markdup_tool samtools` as an **option** (Picard stays default):

1. New parameter: `params.markdup_tool = 'picard'` (default)
2. Conditional routing in `workflows/rnaseq/main.nf`
3. Import existing `BAM_MARKDUPLICATES_SAMTOOLS` + add SAMTOOLS_INDEX + BAM_STATS_SAMTOOLS
4. MultiQC integration for samtools markdup stats
5. Documentation with benchmark data
6. CI test with `--markdup_tool samtools`

## Approach: Data First

- Open Issue with benchmark data before submitting PR
- Present proportions, not claims
- Ask maintainers if direction is welcome
- Respect 10-year project history — "here's what we measured" not "here's what's wrong"
