#!/bin/bash
set -euo pipefail

# ============================================================
# Cloud Server Setup for nf-core/rnaseq Benchmark
# Target: Hetzner CCX33 (8 vCPU, 32GB RAM, Ubuntu 24.04)
#
# IMPORTANT: Attach a Hetzner Volume BEFORE running this script.
# The volume will be auto-detected and mounted to /mnt/data.
# ALL Nextflow data (work, staging, tmp) goes on the volume.
# ============================================================

echo "=== nf-core/rnaseq Benchmark — Cloud Setup ==="
echo "Date: $(date -Iseconds)"
echo "Host: $(hostname)"
echo "CPUs: $(nproc)"
echo "RAM: $(free -h | grep Mem | awk '{print $2}')"
echo ""

# 1. Detect and mount volume
echo "--- Detecting Hetzner Volume ---"
# Hetzner volumes appear as /dev/sd[b-z] or /dev/disk/by-id/scsi-0HC_Volume_*
VOL_DEV=""
for dev in /dev/sdb /dev/sdc /dev/sdd; do
  if [ -b "$dev" ]; then
    VOL_DEV="$dev"
    break
  fi
done

if [ -z "$VOL_DEV" ]; then
  echo "ERROR: No Hetzner volume detected. Attach a volume first!"
  exit 1
fi

echo "Found volume: $VOL_DEV"

# Format if needed (only if no filesystem)
if ! blkid "$VOL_DEV" | grep -q TYPE; then
  echo "Formatting $VOL_DEV as ext4..."
  mkfs.ext4 -q "$VOL_DEV"
fi

# Mount
MOUNT=/mnt/data
mkdir -p $MOUNT
if ! mountpoint -q $MOUNT; then
  mount "$VOL_DEV" $MOUNT
  echo "Mounted $VOL_DEV → $MOUNT"
else
  echo "Already mounted: $MOUNT"
fi
echo "Volume size: $(df -h $MOUNT | tail -1 | awk '{print $2, "total,", $4, "free"}')"
echo ""

# 2. Create workspace — everything on volume
WORKDIR=/root/rnaseq-bench
mkdir -p $WORKDIR/results
mkdir -p $MOUNT/work
mkdir -p $MOUNT/tmp
mkdir -p $MOUNT/singularity

# Symlink work dir so Nextflow uses volume automatically
ln -sfn $MOUNT/work $WORKDIR/work
echo "Workspace: $WORKDIR"
echo "Work dir:  $MOUNT/work (symlinked)"
echo "Tmp dir:   $MOUNT/tmp"
echo ""

# 3. Install Docker
echo "--- Installing Docker ---"
if ! command -v docker &>/dev/null; then
  curl -fsSL https://get.docker.com | sh
  systemctl enable docker
  systemctl start docker
  echo "Docker installed: $(docker --version)"
else
  echo "Docker already installed: $(docker --version)"
fi

# Point Docker data to volume (prevents filling root disk with images/layers)
mkdir -p $MOUNT/docker
if [ ! -f /etc/docker/daemon.json ] || ! grep -q data-root /etc/docker/daemon.json 2>/dev/null; then
  cat > /etc/docker/daemon.json <<DEOF
{
  "data-root": "$MOUNT/docker"
}
DEOF
  systemctl restart docker
  echo "Docker data-root moved to $MOUNT/docker"
fi
echo ""

# 4. Install Java (needed for Nextflow)
echo "--- Installing Java ---"
if ! command -v java &>/dev/null; then
  apt-get update -qq
  apt-get install -y -qq openjdk-21-jre-headless
  echo "Java installed: $(java -version 2>&1 | head -1)"
else
  echo "Java already installed: $(java -version 2>&1 | head -1)"
fi

# 5. Install Nextflow
echo "--- Installing Nextflow ---"
if ! command -v nextflow &>/dev/null; then
  curl -s https://get.nextflow.io | bash
  mv nextflow /usr/local/bin/
  nextflow -version
else
  echo "Nextflow already installed: $(nextflow -version 2>&1 | grep version | tail -1)"
fi

# 6. Install samtools (standalone, for Phase 3 comparison)
echo "--- Installing samtools ---"
if ! command -v samtools &>/dev/null; then
  apt-get install -y -qq samtools
  echo "samtools installed: $(samtools --version | head -1)"
else
  echo "samtools already installed: $(samtools --version | head -1)"
fi

# 7. Install GNU time (for benchmarking)
echo "--- Installing GNU time ---"
apt-get install -y -qq time

# 8. Summary
echo ""
echo "=== Setup complete ==="
echo "Volume:    $VOL_DEV → $MOUNT ($(df -h $MOUNT | tail -1 | awk '{print $4}') free)"
echo "Work dir:  $MOUNT/work"
echo "Docker:    $MOUNT/docker"
echo "Tmp:       $MOUNT/tmp"
echo "Ready to benchmark!"
