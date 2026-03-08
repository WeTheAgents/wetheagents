#!/bin/bash
# Cloud Agent Setup — runs at session start, before Claude Code launches.
# Prepares worktrees, CLI tools, and agent identities for cloud-based agents.
#
# Required env vars (set in cloud session settings):
#   CLAUDE1_GITHUB_TOKEN  — fine-grained PAT for Claude-1 GitHub account
#   CODEX1_GITHUB_TOKEN   — fine-grained PAT for Codex-1 GitHub account
#
# Optional:
#   OPENAI_API_KEY        — for codex CLI (if using API mode)
#
# PAT permissions (fine-grained, repo: WeTheAgents/wetheagents):
#   Contents:     Read and write
#   Issues:       Read and write
#   Pull requests: Read and write
#   Metadata:     Read-only (auto-included)

set -euo pipefail

REPO=/home/user/wetheagents

echo "=== Cloud Agent Setup ==="

# ── 1. Install gh CLI ──────────────────────────────────────────────
if ! command -v gh &>/dev/null; then
  echo "[1/6] Installing gh CLI..."
  curl -sL "https://github.com/cli/cli/releases/download/v2.87.3/gh_2.87.3_linux_amd64.tar.gz" \
    | tar -xz -C /tmp
  cp /tmp/gh_2.87.3_linux_amd64/bin/gh /usr/local/bin/gh
else
  echo "[1/6] gh CLI already installed"
fi

# ── 2. Install wea CLI in .venv ────────────────────────────────────
echo "[2/6] Installing wea CLI..."
cd "$REPO"
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
. .venv/bin/activate
pip install -q -e .

# ── 3. Create agent worktrees ─────────────────────────────────────
echo "[3/6] Creating worktrees..."
for agent in claude-1 codex-1; do
  wt="/home/user/wetheagents-${agent}"
  if [ ! -d "$wt" ]; then
    git worktree add "$wt" -b "worktree/${agent}" HEAD
  else
    echo "  worktree ${agent} already exists"
  fi
done

# ── 4. Copy genomes ───────────────────────────────────────────────
echo "[4/6] Copying genomes..."
cp "$REPO/genomes/Claude-1@claude/AGENTS.local.md" /home/user/wetheagents-claude-1/AGENTS.local.md
cp "$REPO/genomes/Codex-1@codex/AGENTS.local.md" /home/user/wetheagents-codex-1/AGENTS.local.md

# ── 5. Configure push remotes ─────────────────────────────────────
echo "[5/6] Configuring push remotes..."

configure_push_remote() {
  local wt_path="$1" token="$2" label="$3"
  if [ -z "$token" ]; then
    echo "  ⚠ ${label}: no token, skipping push-origin"
    return
  fi
  # Remove existing push-origin if present, then add fresh
  git -C "$wt_path" remote remove push-origin 2>/dev/null || true
  git -C "$wt_path" remote add push-origin \
    "https://x-access-token:${token}@github.com/WeTheAgents/wetheagents.git"
  echo "  ✓ ${label}: push-origin configured"
}

configure_push_remote /home/user/wetheagents-claude-1 "${CLAUDE1_GITHUB_TOKEN:-}" "Claude-1"
configure_push_remote /home/user/wetheagents-codex-1 "${CODEX1_GITHUB_TOKEN:-}" "Codex-1"

# ── 6. Install codex CLI (optional) ───────────────────────────────
echo "[6/6] Codex CLI..."
if ! command -v codex &>/dev/null; then
  npm install -g @openai/codex 2>/dev/null && echo "  ✓ codex installed" || echo "  ⚠ codex install failed (non-fatal)"
else
  echo "  codex already installed"
fi

# ── Summary ────────────────────────────────────────────────────────
echo ""
echo "=== Setup Complete ==="
echo "Worktrees:"
git worktree list
echo ""
echo "Agent launch commands:"
echo "  Claude-1: GITHUB_TOKEN=\$CLAUDE1_GITHUB_TOKEN WEA_AGENT=Claude-1@claude claude -p '...'"
echo "  Codex-1:  GITHUB_TOKEN=\$CODEX1_GITHUB_TOKEN WEA_AGENT=Codex-1@codex codex '...'"
