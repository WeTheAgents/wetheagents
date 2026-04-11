#!/bin/bash
# ============================================================
# Deploy & Run v3 — 3-way benchmark (Picard vs samtools vs sambamba)
# Usage: bash cloud_deploy_v3.sh <server-ip>
#
# Prerequisites:
#   - Hetzner Volume attached to the server
#   - SSH key configured for root@<server-ip>
# ============================================================

set -euo pipefail

SERVER=${1:?Usage: bash cloud_deploy_v3.sh <server-ip>}
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== Deploying v3 benchmark to $SERVER ==="

echo "Uploading scripts..."
scp -o StrictHostKeyChecking=no \
  "$SCRIPT_DIR/cloud_setup.sh" \
  "$SCRIPT_DIR/cloud_benchmark_v3.sh" \
  root@$SERVER:/root/

echo "Running setup..."
ssh root@$SERVER 'bash /root/cloud_setup.sh'

echo "Starting benchmark in tmux..."
ssh root@$SERVER 'apt-get install -y -qq tmux && tmux new-session -d -s bench "cd /root/rnaseq-bench && bash /root/cloud_benchmark_v3.sh; echo DONE; sleep 999999"'

echo ""
echo "=== Benchmark running in tmux session 'bench' ==="
echo "Monitor:   ssh root@$SERVER 'tmux attach -t bench'"
echo "Disk:      ssh root@$SERVER 'df -h / /mnt/data'"
echo "Check log: ssh root@$SERVER 'tail -50 /root/rnaseq-bench/results/benchmark_*.log'"
echo "Download:  scp root@$SERVER:/root/rnaseq-bench/results/* ./results/"
