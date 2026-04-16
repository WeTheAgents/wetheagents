# markdup-wea — Development Log: Session 1

**Date:** 2026-04-15
**Duration:** ~5 hours
**Repo:** `peachgabba22/markdup-wea` (public)
**Fork:** `WeTheAgents/markdup-wea-eval` (private, synced)

---

## What was built

A complete Rust duplicate marker for BAM files — drop-in Picard MarkDuplicates replacement. From zero to validated on human genome in one session.

### Architecture

Two-pass design over coordinate-sorted BAM:

- **Pass 1 (scan):** Read every record sequentially, assign record_id (0..N). Classify each record (unmapped/secondary/supplementary/paired/single-end). Build duplicate groups by grouping identical alignment positions. For paired reads, use QNAME hashing (64-bit FxHash + 32-bit check_hash) to track pending mates. When both mates are seen, form PairedEndKey from their unclipped 5' positions and add to GroupTracker. Incremental resolution via BTreeMap — as the stream advances past a position, all groups anchored at or below that position are resolved. Resolution: highest quality_sum wins, rest → mark record_ids in BitVec.

- **Pass 2 (write):** Re-read BAM from beginning with same record_id counter. If `dup_bits[id]` is set → set FLAG 0x400. If `--remove-duplicates` → skip entirely. Clear any pre-existing 0x400 flags. Convert bam::Record → RecordBuf for flag modification (noodles Records are immutable).

### Key implementation decisions

| Decision | Choice | Why |
|----------|--------|-----|
| BAM library | **noodles 0.96** (pure Rust) | rust-htslib failed on Windows — hts-sys requires OpenSSL/curl/perl, .sh scripts fail with "not a valid Win32 application". noodles = zero C deps, compiles everywhere |
| Dupset | **BitVec** (0.125 bytes/read) | 25MB for 200M reads. FxHashSet also implemented behind DupSet trait for benchmarking |
| Mate tracking | **FxHashMap<u64, Vec<PendingMate>>** | 64-bit QNAME hash → O(1) lookup. Vec handles rare hash collisions. 52 bytes/entry. Peak ~2-10M entries for RNA-seq |
| Group resolution | **Incremental via BTreeMap** | Resolve groups as stream advances past their max_pos. Keeps active group count small (~100K). Full resolve at chromosome boundary and EOF |
| Tie-breaking | **Highest score, then lowest record_id** | Matches Picard's deterministic behavior |
| Flag modification | **RecordBuf + flags_mut()** | noodles bam::Record is immutable. RecordBuf conversion required for write path |
| Metrics format | **Exact Picard header format** | MultiQC parses by header line. Must match `htsjdk.samtools.metrics.StringHeader` exactly |

### Source code

| File | Lines | Purpose |
|------|-------|---------|
| `src/scan.rs` | 254 | Pass 1 orchestrator — classification, grouping, resolution |
| `src/groups.rs` | 508 | PairedEndKey, SingleEndKey, GroupTracker, incremental resolution |
| `src/metrics.rs` | 278 | Picard-format DuplicationMetrics, Lander-Waterman, histogram |
| `src/pending_mates.rs` | 191 | QNAME hash mate buffer, collision detection |
| `src/dupset.rs` | 153 | BitVecDupSet + HashDupSet behind DupSet trait |
| `src/position.rs` | 117 | unclipped_5prime() — handles all CIGAR edge cases |
| `src/markdup.rs` | 94 | Two-pass orchestrator, flag modification, writer |
| `src/io.rs` | 112 | BAM reader/writer, sort validation, stdin→tempfile |
| `src/main.rs` | 63 | CLI (clap) |
| `src/scoring.rs` | 55 | quality_sum() — sum bases >= Q15 |
| **Total** | **1,825** | |

### Test suite: 45 tests passing

- `position.rs`: 11 tests (forward/reverse, soft/hard clips, empty CIGAR, edge cases)
- `scoring.rs`: 7 tests (threshold, mixed, edge cases)
- `dupset.rs`: 4 tests (BitVec, HashSet, consistency)
- `groups.rs`: 6 tests (paired groups, single-end, tie-breaking, incremental resolution)
- `pending_mates.rs`: 5 tests (insert/remove, collision, drain)
- `metrics.rs`: 7 tests (percent_duplication, library_size, format, histogram)
- `io.rs`: 3 tests (sort validation)
- Additional integration tests in groups.rs

### Specification

- `docs/SPEC.md` — Approved architectural spec (v3), designated "Spec is law"
- `openspec/` — Full OpenSpec pipeline: config.yaml, proposal.md, design.md (8 decisions), tasks.md (65 tasks, 5 gates), 7 delta specs with WHEN/THEN scenarios

---

## Human genome validation results

**Server:** Hetzner CPX62 (16 vCPU AMD, 32GB RAM)
**Binary:** cross-compiled release, 2.0MB static

### Completed samples (as of session end)

| Sample | Wall time | Peak RSS | Our flagged | Picard flagged | Match? |
|--------|-----------|----------|-------------|----------------|--------|
| K562_REP1 | ~30min* | ~34MB | 133,311,874 | 133,311,874 | **EXACT** |
| GM12878_REP1 | **9:16** | **199MB** | 125,959,040 | 125,959,040 | **EXACT** |
| GM12878_REP2 | **9:37** | **367MB** | 126,547,312 | 126,547,312 | **EXACT** |
| H1_REP1 | (running) | 297MB | — | 111,561,954 | TBD |
| H1_REP2 | — | — | — | 97,362,862 | TBD |
| K562_REP2 | — | — | — | 160,964,674 | TBD |
| MCF7_REP1 | — | — | — | 80,424,932 | TBD |
| MCF7_REP2 | — | — | — | 98,159,156 | TBD |

*K562_REP1 was first manual test, not timed precisely in the batch run.

### Performance comparison (preliminary)

| Metric | Picard | markdup-wea | Factor |
|--------|--------|-------------|--------|
| Wall time (GM12878_REP1) | ~30min (estimated from trace) | 9:16 | **~3x faster** |
| Peak RSS | 21.5GB JVM heap | 199-367MB | **58-109x less memory** |
| Binary size | ~300MB JVM + Picard JAR | 2.0MB static | **150x smaller** |
| Configuration | JVM heap tuning, GC flags | None | **Zero config** |

---

## Technical challenges encountered and solved

### 1. rust-htslib Windows build failure
**Problem:** hts-sys requires OpenSSL, curl, and executes .sh scripts directly. On Windows: "Error 193: not a valid Win32 application" from version.sh.
**Fix:** Abandoned rust-htslib entirely. Switched to noodles — pure Rust BAM library, zero C dependencies.

### 2. noodles API discovery (18 mismatches)
**Problem:** noodles API is poorly documented. 18 separate API mismatches discovered during implementation:
- No `sort_order()` method → use `other_fields().get(&SORT_ORDER)`
- No `library()` on read groups → use `other_fields().get(&LIBRARY)`
- bam::Record is immutable → need RecordBuf + `flags_mut()`
- Quality scores have non-trivial lifetime → `.as_ref().to_vec()`
- CIGAR ops return `io::Result<Op>`, must iterate with error handling
- Writer::from not Writer::new for dynamic dispatch
**Fix:** Iterative discovery through compile errors. Each fix documented.

### 3. SSH connection drops killing server jobs
**Problem:** Long-running SSH sessions to Hetzner server dropped with "Connection reset by peer", killing the benchmark.
**Fix:** Switched to `nohup ./run_all.sh &` pattern with output redirected to file. Process survives SSH disconnect.

### 4. Uncompressed output BAM
**Problem:** Output BAM is 40GB (uncompressed) vs 8.7GB input (BGZF compressed). noodles Writer to /dev/null doesn't trigger BGZF compression.
**Status:** Known issue. Does not affect correctness validation (which uses /dev/null output). Fix scheduled for Phase 4.

### 5. Missing EOF marker
**Problem:** samtools warns "EOF marker is absent" on output BAM.
**Status:** Needs proper writer finalization (flush + BGZF EOF block). Fix in Phase 4.

---

## What's NOT done yet

### Phase 4: Threading + Optimization
- BGZF compression for output (currently uncompressed)
- EOF marker in output BAM
- Multi-threaded I/O (BGZF decompression/compression)
- Pre-sized HashMap allocation

### Phase 5a: Yeast validation + dupset benchmark
- 5 yeast samples correctness check
- BitVec vs FxHashSet memory/speed comparison
- MultiQC metrics validation

### Phase 5b: Human genome validation (partially done)
- 3 of 8 samples confirmed exact match (K562_REP1, GM12878_REP1, GM12878_REP2)
- Remaining 5 samples running on server
- Full benchmark comparison table (Picard vs samtools vs markdup-wea)
- Wall time with t>1 threads

### PR to nf-core/rnaseq
- Issue with benchmark data
- Conditional routing in workflows/rnaseq/main.nf
- Integration with existing BAM_MARKDUPLICATES subworkflow pattern

---

## Commits

| Hash | Message |
|------|---------|
| `fe0d180` | Initial commit |
| `e216a0c` | spec: add MVP specification (v3, approved) |
| `ac520e5` | openspec: full MVP specification (proposal, specs, design, tasks) |
| `dad81a9` | fix: align SPEC.md and OpenSpec after cross-audit |
| `35fa7c1` | feat: Phase 1+2 implementation — core markdup engine with 45 passing tests |
