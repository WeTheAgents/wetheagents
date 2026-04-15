#!/bin/bash
set -euo pipefail

# ============================================================
# I/O Bottleneck Test: samtools/sambamba thread scaling
# across storage tiers (Hetzner Volume vs local SSD vs tmpfs)
#
# Server: Hetzner CCX (16 physical cores, AMD EPYC-Genoa)
#   sdb = /mnt/data   (Hetzner Volume, network-attached, ~309 MB/s)
#   sda = /           (local SSD)
#   shm = /dev/shm    (tmpfs, RAM-backed, 16 GB)
#
# Tests 2 samples × 2 tools × 4 thread counts × 2 runs
# on local SSD, with iostat + mpstat monitoring.
# Existing sdb data is NOT re-run — compare after.
#
# ALL output files use "io_bench_" prefix.
# Existing results are NEVER touched.
# ============================================================

ulimit -n 65536

WORKDIR=/root/rnaseq-bench
VOLDIR=/mnt/data
RESULTS=$WORKDIR/results
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOG=$RESULTS/io_bench_${TIMESTAMP}.log
CSV=$RESULTS/io_bench_timings.csv
STATE=$RESULTS/io_bench_state.txt
FIO_OUT=$RESULTS/io_bench_fio.json

# Local SSD paths
SDA_BENCH=/tmp/io_bench
SDA_TMP=/tmp/io_bench_tmp
SHM_BENCH=/dev/shm/io_bench

mkdir -p $RESULTS $SDA_BENCH $SDA_TMP

exec > >(tee -a "$LOG") 2>&1

echo "============================================================"
echo "I/O Bottleneck Benchmark"
echo "============================================================"
echo "Started: $(date -Iseconds)"
echo "Host: $(hostname)"
echo "CPUs: $(nproc)"
echo "RAM: $(free -h | grep Mem | awk '{print $2}')"
echo "Swap: $(free -h | grep Swap | awk '{print $2, "used:", $3}')"
echo "samtools: $(samtools --version | head -1)"
echo "sambamba: $(sambamba --version 2>&1 | head -1 || echo 'not found')"
echo "fio: $(fio --version 2>/dev/null || echo 'not found')"
echo "ulimit -n: $(ulimit -n)"
echo ""
echo "CPU topology:"
lscpu | grep -E "Thread|Core|Socket|CPU\(s\)|Model"
echo ""
echo "Disk layout:"
lsblk -o NAME,SIZE,TYPE,MOUNTPOINT,ROTA
echo ""
echo "Disk usage:"
df -hT / /mnt/data /dev/shm
echo ""

# Disk monitor (every 5 min)
(
  while true; do
    echo "[disk $(date +%H:%M)] sda=$(df -h / | tail -1 | awk '{print $5, $4}') sdb=$(df -h /mnt/data | tail -1 | awk '{print $5, $4}') swap=$(free -h | grep Swap | awk '{print $3}')" >> "$RESULTS/io_bench_disk_monitor.log"
    sleep 300
  done
) &
DISK_MON_PID=$!
trap "kill $DISK_MON_PID 2>/dev/null || true; rm -rf $SDA_TMP $SHM_BENCH" EXIT

# ============================================================
# Phase 0: fio baselines
# ============================================================
echo "=== Phase 0: fio I/O baselines ==="
echo ""

run_fio() {
  local label=$1
  local dir=$2
  local direct_flag=$3   # "1" for block devices, "0" for tmpfs

  echo "--- fio: $label ($dir) ---"
  mkdir -p "$dir"

  # Sequential read
  fio --name=seq_read_${label} --rw=read --bs=1M --size=4G --numjobs=1 \
    --direct=$direct_flag --filename="$dir/fio_test" \
    --output-format=json --output="$dir/fio_seq_read.json" 2>/dev/null
  local sr=$(python3 -c "import json; d=json.load(open('$dir/fio_seq_read.json')); print(f\"{d['jobs'][0]['read']['bw']/1024:.0f} MB/s\")")
  echo "  seq read:  $sr"

  # Sequential write
  fio --name=seq_write_${label} --rw=write --bs=1M --size=4G --numjobs=1 \
    --direct=$direct_flag --filename="$dir/fio_test" \
    --output-format=json --output="$dir/fio_seq_write.json" 2>/dev/null
  local sw=$(python3 -c "import json; d=json.load(open('$dir/fio_seq_write.json')); print(f\"{d['jobs'][0]['write']['bw']/1024:.0f} MB/s\")")
  echo "  seq write: $sw"

  # Concurrent random R/W (8 jobs, simulates multithreaded markdup)
  fio --name=conc_rw_${label} --rw=randrw --bs=256K --size=2G --numjobs=8 \
    --direct=$direct_flag --filename="$dir/fio_test" \
    --output-format=json --output="$dir/fio_conc_rw.json" 2>/dev/null
  local cr=$(python3 -c "
import json
d=json.load(open('$dir/fio_conc_rw.json'))
r = sum(j['read']['bw'] for j in d['jobs'])/1024
w = sum(j['write']['bw'] for j in d['jobs'])/1024
print(f'read {r:.0f} MB/s + write {w:.0f} MB/s')
")
  echo "  conc rw:   $cr"

  rm -f "$dir/fio_test"
  echo ""
}

run_fio "sdb_volume" "/mnt/data/fio_bench" "1"
run_fio "sda_local"  "/tmp/fio_bench"      "1"
run_fio "shm_ram"    "/dev/shm/fio_bench"  "0"

# Collect fio summaries into one JSON
python3 -c "
import json, glob, os
result = {}
for tier in ['sdb_volume', 'sda_local', 'shm_ram']:
    dirs = {
        'sdb_volume': '/mnt/data/fio_bench',
        'sda_local':  '/tmp/fio_bench',
        'shm_ram':    '/dev/shm/fio_bench'
    }
    d = dirs[tier]
    entry = {}
    for test in ['seq_read', 'seq_write', 'conc_rw']:
        path = f'{d}/fio_{test}.json'
        if os.path.exists(path):
            data = json.load(open(path))
            entry[test] = data['jobs']
    result[tier] = entry
with open('$FIO_OUT', 'w') as f:
    json.dump(result, f, indent=2)
print('fio summary saved to $FIO_OUT')
"
echo ""

# Cleanup fio dirs
rm -rf /mnt/data/fio_bench /tmp/fio_bench /dev/shm/fio_bench

# ============================================================
# Phase 1: Copy BAMs to local SSD
# ============================================================
echo "=== Phase 1: Copy BAMs to local SSD (sda) ==="

# Find the specific BAMs
K562_REP1_BAM=$(find $VOLDIR/work -name "K562_REP1.sorted.bam" -not -name "*.markdup.*" -not -name "*.st_*" -not -name "*.sb_*" -size +1M 2>/dev/null | head -1)
MCF7_REP2_BAM=$(find $VOLDIR/work -name "MCF7_REP2.sorted.bam" -not -name "*.markdup.*" -not -name "*.st_*" -not -name "*.sb_*" -size +1M 2>/dev/null | head -1)

echo "K562_REP1: $K562_REP1_BAM ($(du -h "$K562_REP1_BAM" | cut -f1))"
echo "MCF7_REP2: $MCF7_REP2_BAM ($(du -h "$MCF7_REP2_BAM" | cut -f1))"

echo "Copying to $SDA_BENCH..."
cp -v "$K562_REP1_BAM" "$SDA_BENCH/K562_REP1.sorted.bam"
cp -v "$MCF7_REP2_BAM" "$SDA_BENCH/MCF7_REP2.sorted.bam"

echo "Local SSD copies:"
ls -lh $SDA_BENCH/
df -h /
echo ""

# ============================================================
# Phase 2: Benchmark on local SSD with I/O monitoring
# ============================================================
echo "=== Phase 2: Benchmark on local SSD (sda) ==="

BENCH_START=$(date +%s)

# CSV header (only if file doesn't exist — for resumability)
if [ ! -f "$CSV" ]; then
  echo "sample,tool,threads,run,time_sec,dup_count,total_reads,peak_rss_kb,storage_tier,swap_used_mb" > "$CSV"
fi

# State file for resumability
touch "$STATE"

SAMPLES=("K562_REP1" "MCF7_REP2")
TOOLS=("samtools" "sambamba")
THREADS=(8 16)
RUNS=(1 2)

for sample in "${SAMPLES[@]}"; do
  bam="$SDA_BENCH/${sample}.sorted.bam"

  for tool in "${TOOLS[@]}"; do
    echo "====== $sample ($(du -h "$bam" | cut -f1)) — $tool on sda ======"

    for threads in "${THREADS[@]}"; do
      for run in "${RUNS[@]}"; do
        run_key="${sample},${tool},sda,${threads},${run}"

        # Skip if already completed (resumability)
        if grep -qF "$run_key" "$STATE" 2>/dev/null; then
          echo "  SKIP (done): $tool t=$threads run $run"
          continue
        fi

        outbam="$SDA_BENCH/${sample}.${tool}_t${threads}_r${run}.markdup.bam"
        timefile="$SDA_BENCH/${sample}.${tool}_t${threads}_r${run}.time"
        iostat_log="$RESULTS/io_bench_${sample}_${tool}_t${threads}_r${run}_iostat.log"
        cpu_log="$RESULTS/io_bench_${sample}_${tool}_t${threads}_r${run}_cpu.log"

        # Drop caches before each run
        echo 3 > /proc/sys/vm/drop_caches
        sync

        # Record swap before
        swap_before=$(free -m | grep Swap | awk '{print $3}')

        # Start I/O and CPU monitoring
        iostat -dxt 5 /dev/sda /dev/sdb > "$iostat_log" 2>/dev/null &
        IOSTAT_PID=$!
        mpstat -P ALL 5 > "$cpu_log" 2>/dev/null &
        MPSTAT_PID=$!

        echo "  $tool t=$threads run $run..."
        start_s=$(date +%s)

        if [ "$tool" = "samtools" ]; then
          /usr/bin/time -v bash -c "
            samtools sort -n -@ $threads '$bam' | \
            samtools fixmate -m -@ $threads - - | \
            samtools sort -@ $threads - | \
            samtools markdup -@ $threads -s \
              -f '$SDA_BENCH/${sample}.st_t${threads}_r${run}.stats' \
              - '$outbam'
          " 2>"$timefile"
        else
          # sambamba with memory safeguards
          mkdir -p "$SDA_TMP"
          /usr/bin/time -v sambamba markdup \
            -t $threads \
            --sort-buffer-size=512 \
            --overflow-list-size=200000 \
            --hash-table-size=131072 \
            --tmpdir="$SDA_TMP" \
            "$bam" "$outbam" \
            2>"$timefile"
          # Clean tmpdir between runs
          rm -rf "$SDA_TMP"/*
        fi

        end_s=$(date +%s)
        elapsed=$((end_s - start_s))

        # Stop monitoring
        kill $IOSTAT_PID 2>/dev/null || true
        kill $MPSTAT_PID 2>/dev/null || true
        wait $IOSTAT_PID 2>/dev/null || true
        wait $MPSTAT_PID 2>/dev/null || true

        # Extract metrics
        peak_rss=$(grep "Maximum resident" "$timefile" | awk '{print $NF}' || echo "0")
        dup_count=$(samtools view -c -f 1024 "$outbam")
        total_count=$(samtools view -c "$outbam")

        # Record swap after
        swap_after=$(free -m | grep Swap | awk '{print $3}')
        swap_delta=$((swap_after - swap_before))

        echo "    ${elapsed}s, dups=$dup_count/$total_count, RSS=${peak_rss}KB, swap_delta=${swap_delta}MB"
        echo "${sample},${tool},${threads},${run},${elapsed},${dup_count},${total_count},${peak_rss},sda,${swap_delta}" >> "$CSV"

        # Mark as done (resumability)
        echo "$run_key" >> "$STATE"

        # Cleanup output
        rm -f "$outbam" "${outbam}.bai"
        rm -f "$SDA_BENCH/${sample}.st_t${threads}_r${run}.stats"
      done
    done
    df -h / | tail -1
    free -h | grep Swap
  done
done

P2_END=$(date +%s)
echo "Phase 2 done: $(( (P2_END - BENCH_START) / 60 ))m"
echo ""

# ============================================================
# Phase 3: /dev/shm ceiling test (sambamba only, K562_REP1)
# ============================================================
echo "=== Phase 3: /dev/shm ceiling test (sambamba, K562_REP1) ==="

K562_SIZE_MB=$(du -m "$SDA_BENCH/K562_REP1.sorted.bam" | cut -f1)
SHM_AVAIL_MB=$(df -m /dev/shm | tail -1 | awk '{print $4}')

echo "K562_REP1 size: ${K562_SIZE_MB}MB, /dev/shm available: ${SHM_AVAIL_MB}MB"

if [ "$K562_SIZE_MB" -lt "$((SHM_AVAIL_MB - 1024))" ]; then
  echo "Fits in /dev/shm (with 1GB margin). Proceeding..."
  mkdir -p "$SHM_BENCH"
  cp "$SDA_BENCH/K562_REP1.sorted.bam" "$SHM_BENCH/K562_REP1.sorted.bam"

  for threads in 8 16; do
    for run in 1 2; do
      run_key="K562_REP1,sambamba,shm,${threads},${run}"
      if grep -qF "$run_key" "$STATE" 2>/dev/null; then
        echo "  SKIP (done): sambamba t=$threads run $run"
        continue
      fi

      outbam="$SDA_BENCH/K562_REP1.shm_sb_t${threads}_r${run}.markdup.bam"
      timefile="$SDA_BENCH/K562_REP1.shm_sb_t${threads}_r${run}.time"

      echo 3 > /proc/sys/vm/drop_caches
      sync

      swap_before=$(free -m | grep Swap | awk '{print $3}')

      echo "  sambamba t=$threads run $run (input from /dev/shm, output to sda)..."
      start_s=$(date +%s)

      # tmpdir on sda, NOT on /dev/shm
      mkdir -p "$SDA_TMP"
      /usr/bin/time -v sambamba markdup \
        -t $threads \
        --sort-buffer-size=512 \
        --overflow-list-size=200000 \
        --hash-table-size=131072 \
        --tmpdir="$SDA_TMP" \
        "$SHM_BENCH/K562_REP1.sorted.bam" "$outbam" \
        2>"$timefile"

      end_s=$(date +%s)
      elapsed=$((end_s - start_s))
      peak_rss=$(grep "Maximum resident" "$timefile" | awk '{print $NF}' || echo "0")
      dup_count=$(samtools view -c -f 1024 "$outbam")
      total_count=$(samtools view -c "$outbam")
      swap_after=$(free -m | grep Swap | awk '{print $3}')
      swap_delta=$((swap_after - swap_before))

      echo "    ${elapsed}s, dups=$dup_count/$total_count, RSS=${peak_rss}KB, swap_delta=${swap_delta}MB"
      echo "K562_REP1,sambamba,${threads},${run},${elapsed},${dup_count},${total_count},${peak_rss},shm,${swap_delta}" >> "$CSV"
      echo "$run_key" >> "$STATE"

      rm -f "$outbam" "${outbam}.bai"
      rm -rf "$SDA_TMP"/*
    done
  done

  # Cleanup /dev/shm
  rm -rf "$SHM_BENCH"
else
  echo "SKIP: K562_REP1 too large for /dev/shm (need ${K562_SIZE_MB}MB + 1GB margin, have ${SHM_AVAIL_MB}MB)"
fi
echo ""

# ============================================================
# Phase 4: Correctness check
# ============================================================
echo "=== Correctness Check ==="

# Compare dup counts with existing sdb data
SAMTOOLS_CSV=$RESULTS/timings.csv
SAMBAMBA_CSV=$RESULTS/timings_sambamba.csv

for sample in K562_REP1 MCF7_REP2; do
  st_dups=$(grep "^${sample},samtools,1,1," "$SAMTOOLS_CSV" 2>/dev/null | cut -d, -f6 || echo "?")
  sb_dups=$(grep "^${sample},sambamba,1,1," "$SAMBAMBA_CSV" 2>/dev/null | cut -d, -f6 || echo "?")
  new_st=$(grep "^${sample},samtools,1,1," "$CSV" 2>/dev/null | cut -d, -f6 || echo "?")
  new_sb=$(grep "^${sample},sambamba,1,1," "$CSV" 2>/dev/null | cut -d, -f6 || echo "?")

  echo "  $sample:"
  echo "    sdb samtools=$st_dups  sdb sambamba=$sb_dups"
  echo "    sda samtools=$new_st   sda sambamba=$new_sb"
  if [ "$st_dups" = "$new_st" ] && [ "$sb_dups" = "$new_sb" ]; then
    echo "    MATCH"
  else
    echo "    DIFF — investigate!"
  fi
done
echo ""

# ============================================================
# Summary
# ============================================================

# Cleanup BAM copies from sda
rm -f "$SDA_BENCH/K562_REP1.sorted.bam" "$SDA_BENCH/MCF7_REP2.sorted.bam"
rm -rf "$SDA_TMP"

TOTAL_END=$(date +%s)
TOTAL=$((TOTAL_END - BENCH_START))
echo "============================================================"
echo "I/O Benchmark complete: $(date -Iseconds)"
echo "Total: ${TOTAL}s ($(( TOTAL / 3600 ))h $(( (TOTAL % 3600) / 60 ))m)"
echo "CSV: $CSV"
echo "fio: $FIO_OUT"
echo "iostat logs: $RESULTS/io_bench_*_iostat.log"
echo "CPU logs: $RESULTS/io_bench_*_cpu.log"
echo "============================================================"
echo ""
echo "Results:"
cat "$CSV"
