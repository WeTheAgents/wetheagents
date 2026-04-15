# markdup-wea — Handoff for Next Session

**Written:** 2026-04-15 09:10 UTC+3
**Server:** Hetzner CPX62 at 204.168.253.225 (16 vCPU AMD, 32GB RAM)

---

## Immediate action: Check benchmark results

The 8-sample human genome benchmark is running via nohup on the server. When you start:

```bash
ssh root@204.168.253.225 'cat /root/markdup-test/results.txt'
```

**Expected output format per sample:**
```
SAMPLE | wall=MM:SS.ss | RSS=XXXKB | pair_dups=N | flagged=N*2
```

**Compare `flagged` to Picard ground truth:**

| Sample | Picard flagged (ground truth) |
|--------|-------------------------------|
| GM12878_REP1 | 125,959,040 |
| GM12878_REP2 | 126,547,312 |
| H1_REP1 | 111,561,954 |
| H1_REP2 | 97,362,862 |
| K562_REP1 | 133,311,874 |
| K562_REP2 | 160,964,674 |
| MCF7_REP1 | 80,424,932 |
| MCF7_REP2 | 98,159,156 |

**Already confirmed EXACT MATCH:** K562_REP1, GM12878_REP1, GM12878_REP2 (3/8).

**NOTE:** The script computes `flagged = pair_dups * 2`. This only counts paired-read duplicates. The Picard ground truth (`samtools view -c -f 1024`) counts ALL reads with 0x400 flag (paired + unpaired). If there's a small delta, check unpaired_read_duplicates in the metrics file:
```bash
ssh root@204.168.253.225 'cat /tmp/SAMPLE.wea_metrics.txt'
```
The correct comparison is: `(pair_dups * 2) + unpaired_dups == picard_flagged_count`.

---

## If ALL 8 match: proceed to Phase 4

### Fix 1: BGZF compressed output

The noodles `bam::io::Writer` wraps raw `std::io::Write`. For BGZF output, wrap the file in `bgzf::Writer` before passing to `bam::io::Writer`:

```rust
// In src/markdup.rs, replace:
let f = std::fs::File::create(p)?;
bam::io::Writer::from(Box::new(BufWriter::new(f)))

// With:
let f = std::fs::File::create(p)?;
let bgzf_writer = noodles::bgzf::Writer::new(BufWriter::new(f));
bam::io::Writer::from(Box::new(bgzf_writer))
```

Check that this also writes the BGZF EOF marker on drop/flush. If not, manually write the 28-byte EOF block.

### Fix 2: Multi-threaded BGZF

noodles bgzf supports multi-threaded compression. Check `bgzf::Writer::builder()` for thread pool options. For reading, check `bgzf::Reader::builder()`.

This is the `-@ N` CLI flag. Wire it through.

### Fix 3: Pre-sized allocations

In `scan.rs`, estimate read count from BAM file size:
```rust
let estimated_reads = file_size / 150; // ~150 bytes/record average for RNA-seq
pending.reserve(estimated_reads / 5);  // ~20% of reads pending at any time
```

---

## If any sample DOESN'T match: debug checklist

1. **Check the delta:** Is it off by exactly `unpaired_read_duplicates`? Then the script's comparison formula is wrong, not the tool.

2. **Compare metrics files:**
   ```bash
   # Our metrics
   cat /tmp/SAMPLE.wea_metrics.txt
   # Picard metrics (from nf-core run)
   find /mnt/HC_Volume_105344878/work -name "SAMPLE.markdup.sorted.bam.metrics" -exec cat {} \;
   ```

3. **Check for supplementary flagging:** Picard flags supplementary alignments of duplicate reads. We don't (by design, documented in SPEC.md). This could cause a count delta if Picard's count includes supplementaries with 0x400.

4. **Check for cross-chromosome pair handling:** These resolve at EOF. If the count is low by a small number, cross-chrom pairs may not be resolving correctly.

5. **QNAME hash collisions:** With 200M reads, expect ~0 collisions from 64-bit hash. But verify: add temporary logging for check_hash mismatches.

---

## Repo locations

| Path | What |
|------|------|
| `D:\GitHub\markdup-wea\` | Main repo (peachgabba22/markdup-wea) |
| `D:\GitHub\wetheagents\domains\rnaseq\` | Analysis + benchmark scripts |
| Server: `/root/markdup-test/` | Benchmark workspace |
| Server: `/root/markdup-test/markdup-wea/` | Cloned repo with release binary |
| Server: `/root/markdup-test/data/` | Symlinks to BAM files on volume |
| Server: `/root/markdup-test/run_all.sh` | Batch benchmark script |
| Server: `/root/markdup-test/results.txt` | Benchmark output |
| Server: `/tmp/SAMPLE.wea_metrics.txt` | Per-sample metrics files |
| Server: `/tmp/SAMPLE.time.txt` | /usr/bin/time output (RSS, wall) |

---

## Server access

```bash
ssh root@204.168.253.225
# Volume: /mnt/HC_Volume_105344878
# nf-core output (Picard BAMs): /mnt/HC_Volume_105344878/work/
# Rust toolchain installed: ~/.cargo/env
```

The server has:
- Rust toolchain (for recompiling)
- samtools, sambamba (for verification)
- Docker, Nextflow (for nf-core runs)
- BAM files from nf-core/rnaseq run (HISAT2 aligner, GRCh37 genome)

---

## Plan phases remaining

| Phase | Status | Description |
|-------|--------|-------------|
| Phase 1 | **DONE** | Skeleton + core primitives |
| Phase 2 | **DONE** | Paired-end duplicate detection (45 tests) |
| Phase 3 | **DONE** | Picard-compatible metrics |
| Phase 4 | **TODO** | BGZF compression, threading, optimization |
| Phase 5a | **TODO** | Yeast validation + dupset benchmark |
| Phase 5b | **IN PROGRESS** | Human genome validation (3/8 confirmed) |

**Gate:** Phase 5b completion (all 8 human samples exact match) is the gate for calling the MVP "validated". After that:
1. Fix BGZF output + threading (Phase 4)
2. Build full benchmark comparison table
3. Open Issue on nf-core/rnaseq with data
4. Submit PR

---

## Spec files

- `docs/SPEC.md` — Architectural spec (v3), "Spec is law". All implementation decisions traceable to this doc.
- `openspec/config.yaml` — OpenSpec config
- `openspec/changes/` — 7 delta specs with WHEN/THEN scenarios

---

## Key technical details to remember

1. **noodles, not rust-htslib.** Pure Rust BAM library. No C deps. API is poorly documented — read source code when in doubt.

2. **RecordBuf for writes.** noodles `bam::Record` is immutable. Must convert to `RecordBuf` via `try_from_alignment_record()`, then use `flags_mut()` to modify, then `write_alignment_record()` to write.

3. **BitVecDupSet is the production choice.** FxHashSet also exists behind the trait for benchmarking. Switch in `scan.rs` constructor.

4. **Incremental group resolution.** `PairedGroupTracker` uses `BTreeMap<(i32, i64), Vec<PairedEndKey>>` keyed by (ref_id, max_pos) to know when groups are safe to resolve. This keeps memory bounded.

5. **Library index.** Read groups → library mapping built from `@RG` headers. Each record's `RG` aux tag maps to a library_idx (u8). Used in all grouping keys.

6. **The io_benchmark.sh** in `domains/rnaseq/benchmark/` is a separate storage I/O benchmark (samtools/sambamba across SSD/volume/tmpfs). Not related to markdup-wea directly, but provides baseline I/O numbers for the server.
