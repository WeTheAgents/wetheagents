# Handoff: RNA-seq Benchmark v2 — Fresh Server

**Date**: 2026-03-20
**Status**: Ready to deploy on new server

## What happened

Benchmark v1 (test profile, yeast) — completed successfully. Results in `knowledge/benchmark_results_v1.md`.

Benchmark v2 (full human genome GRCh37) — **failed 5 times** on server 89.167.21.112:
1. Disk 100% — S3 staging (~150GB FASTQ) filled 226GB root disk
2. Added 300GB volume, moved work dir via symlink — partial fix
3. Multiple restarts corrupted LevelDB cache (NullPointerException)
4. `genome.fa` staging race condition — file not ready when GETCHROMSIZES runs
5. Final state: Nextflow dead, work dir corrupted, server useless

**Root cause**: S3 staging, Docker images, and work all competed for 226GB root disk. Volume was added too late and symlinked in, but Nextflow's internal staging didn't follow symlinks properly.

## What's fixed in v2 scripts

Three rewritten scripts in `benchmark/`:

1. **cloud_setup.sh** — auto-detects Hetzner volume, mounts to `/mnt/data`, moves Docker data-root there
2. **cloud_benchmark.sh** — `NXF_WORK=/mnt/data/work`, `NXF_TEMP=/mnt/data/tmp`, explicit `-w` flag, disk monitor every 5min
3. **cloud_deploy.sh** — single command: `bash cloud_deploy.sh <ip>`

Everything on volume from minute zero. Root disk only has OS + binaries.

## New server

- **Name**: ubuntu-32gb-rna
- **Specs**: CCX33 (8 vCPU AMD, 32GB RAM) — same as before
- **Volume**: 500GB (was 300GB, not enough for multiple Nextflow restarts)
- **IP**: TBD — operator will provide

## Deploy steps

```bash
# 1. Get the IP from Hetzner console
# 2. Deploy (from local machine, WSL or Git Bash):
cd domains/rnaseq/benchmark
bash cloud_deploy.sh <new-ip>

# 3. Monitor:
ssh root@<new-ip> 'tmux attach -t bench'
ssh root@<new-ip> 'df -h / /mnt/data'
ssh root@<new-ip> 'tail -20 /root/rnaseq-bench/results/disk_monitor.log'

# 4. When done — download results:
mkdir -p results
scp root@<new-ip>:/root/rnaseq-bench/results/* ./results/

# 5. DELETE SERVER to stop billing
```

## Expected timeline

- Phase 1 (nf-core/rnaseq test_full HISAT2): ~4-8 hours (S3 download + alignment + Picard)
- Phase 2 (extract trace): seconds
- Phase 3 (samtools comparison): ~2-4 hours (3 runs × 4 configs × 8 samples)
- Total: ~6-12 hours

## After benchmark

1. Download `results/timings.csv` + `results/hisat2_picard_trace.txt`
2. Save analysis to `knowledge/benchmark_results_v2.md`
3. Update `CLAUDE.md` with final numbers
4. Delete Hetzner server
5. Draft nf-core/rnaseq Issue with benchmark data
6. Prepare PR code

## Key files

| File | Purpose |
|------|---------|
| `knowledge/benchmark_results_v1.md` | Test profile results (yeast, 5 samples) |
| `knowledge/code_findings.md` | Pipeline code analysis |
| `knowledge/plan_markdup_verification.md` | 5-phase plan |
| `benchmark/cloud_*.sh` | v2 deploy scripts (just committed) |
