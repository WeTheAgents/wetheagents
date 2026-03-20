#!/bin/bash
# ============================================================
# Deploy & Run — one command from your local machine
# Usage: bash cloud_deploy.sh <server-ip>
#
# Prerequisites:
#   - Hetzner Volume attached to the server
#   - SSH key configured for root@<server-ip>
# ============================================================

set -euo pipefail

SERVER=${1:?Usage: bash cloud_deploy.sh <server-ip>}
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== Deploying to $SERVER ==="

# 1. Upload scripts
echo "Uploading scripts..."
scp -o StrictHostKeyChecking=no \
  "$SCRIPT_DIR/cloud_setup.sh" \
  "$SCRIPT_DIR/cloud_benchmark.sh" \
  root@$SERVER:/root/

# 2. Run setup (installs deps, mounts volume, creates dirs)
echo "Running setup..."
ssh root@$SERVER 'bash /root/cloud_setup.sh'

# 3. Start benchmark in tmux (survives SSH disconnect)
echo "Starting benchmark in tmux..."
ssh root@$SERVER 'apt-get install -y -qq tmux && tmux new-session -d -s bench "cd /root/rnaseq-bench && bash /root/cloud_benchmark.sh; echo DONE; sleep 999999"'

echo ""
echo "=== Benchmark running in tmux session 'bench' ==="
echo "Monitor:   ssh root@$SERVER 'tmux attach -t bench'"
echo "Disk:      ssh root@$SERVER 'df -h / /mnt/data'"
echo "Check log: ssh root@$SERVER 'tail -50 /root/rnaseq-bench/results/benchmark_*.log'"
echo "Download:  scp root@$SERVER:/root/rnaseq-bench/results/* ./results/"
