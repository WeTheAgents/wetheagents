#!/bin/bash
# Check and install prerequisites for nf-core/rnaseq benchmarks.
# Run inside WSL.

set -euo pipefail

echo "=== Checking prerequisites ==="
echo ""

# ─── Java ───
if java -version 2>&1 | head -1; then
    echo "  [OK] Java found"
else
    echo "  [MISSING] Java 11+ required"
    echo "  Install: sudo apt install default-jre"
    exit 1
fi

echo ""

# ─── Nextflow ───
if command -v nextflow &>/dev/null; then
    nextflow -version 2>&1 | head -3
    echo "  [OK] Nextflow found"
else
    echo "  [INSTALLING] Nextflow..."
    curl -s https://get.nextflow.io | bash
    chmod +x nextflow
    sudo mv nextflow /usr/local/bin/
    echo "  [OK] Nextflow installed"
fi

echo ""

# ─── Docker ───
if docker info >/dev/null 2>&1; then
    echo "  [OK] Docker available"
else
    echo "  [MISSING] Docker not available in WSL"
    echo "  Enable Docker Desktop → Settings → Resources → WSL Integration"
    exit 1
fi

echo ""
echo "=== All prerequisites OK ==="
echo "Run: bash scripts/benchmark.sh"
