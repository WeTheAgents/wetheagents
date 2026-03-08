#!/bin/bash
# Cloud Agent Setup — runs at session start, before Claude Code launches.
# Prepares worktrees, CLI tools, and agent identities for cloud-based agents.
#
# Required env vars (set in cloud session settings):
#   CLAUDE1_GITHUB_TOKEN  — fine-grained PAT for Claude-1 GitHub account
#   CODEX2_GITHUB_TOKEN   — fine-grained PAT for Codex-2 GitHub account
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
  echo "[1/7] Installing gh CLI..."
  curl -sL "https://github.com/cli/cli/releases/download/v2.87.3/gh_2.87.3_linux_amd64.tar.gz" \
    | tar -xz -C /tmp
  cp /tmp/gh_2.87.3_linux_amd64/bin/gh /usr/local/bin/gh
else
  echo "[1/7] gh CLI already installed"
fi

# ── 2. Install wea CLI in .venv ────────────────────────────────────
echo "[2/7] Installing wea CLI..."
cd "$REPO"
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
. .venv/bin/activate
pip install -q -e .

# ── 3. Fetch latest main ──────────────────────────────────────────
echo "[3/7] Fetching latest main..."
git fetch origin main 2>/dev/null || true

# ── 4. Create agent worktrees ─────────────────────────────────────
echo "[4/7] Creating worktrees..."

create_worktree() {
  local agent_slug="$1" branch_name="$2"
  local wt="/home/user/wetheagents-${agent_slug}"
  if [ -d "$wt" ]; then
    echo "  worktree ${agent_slug} already exists, syncing..."
    git -C "$wt" merge origin/main --no-edit 2>/dev/null || true
    return
  fi
  # Check if branch exists locally or on remote
  if git show-ref --verify --quiet "refs/heads/${branch_name}" 2>/dev/null; then
    git worktree add "$wt" "$branch_name"
  else
    git worktree add "$wt" -b "$branch_name" origin/main 2>/dev/null \
      || git worktree add "$wt" -b "$branch_name" HEAD
  fi
}

create_worktree "claude-1" "agent/Claude-1/work"
create_worktree "codex-2" "agent/Codex-2/work"

# ── 5. Configure git identity per worktree ─────────────────────────
echo "[5/7] Configuring git identity..."
git -C /home/user/wetheagents-claude-1 config --local user.name "Claude-1"
git -C /home/user/wetheagents-claude-1 config --local user.email "claude-1@claude"
git -C /home/user/wetheagents-codex-2 config --local user.name "Codex-2"
git -C /home/user/wetheagents-codex-2 config --local user.email "codex-2@codex"

# ── 6. Copy genomes ───────────────────────────────────────────────
echo "[6/7] Copying genomes..."
cp "$REPO/genomes/Claude-1@claude/AGENTS.local.md" /home/user/wetheagents-claude-1/AGENTS.local.md
cp "$REPO/genomes/Codex-2@codex/AGENTS.local.md" /home/user/wetheagents-codex-2/AGENTS.local.md

# ── 7. Configure push remotes ─────────────────────────────────────
echo "[7/7] Configuring push remotes..."

configure_push_remote() {
  local wt_path="$1" token="$2" label="$3"
  if [ -z "$token" ]; then
    echo "  warning: ${label}: no token, skipping push-origin"
    return
  fi
  git -C "$wt_path" remote remove push-origin 2>/dev/null || true
  git -C "$wt_path" remote add push-origin \
    "https://x-access-token:${token}@github.com/WeTheAgents/wetheagents.git"
  echo "  ok: ${label}: push-origin configured"
}

configure_push_remote /home/user/wetheagents-claude-1 "${CLAUDE1_GITHUB_TOKEN:-}" "Claude-1"
configure_push_remote /home/user/wetheagents-codex-2 "${CODEX2_GITHUB_TOKEN:-}" "Codex-2"

# ── Optional: Install codex CLI ────────────────────────────────────
if ! command -v codex &>/dev/null; then
  npm install -g @openai/codex 2>/dev/null && echo "codex CLI installed" \
    || echo "codex CLI install failed (non-fatal)"
fi

# ── Summary ────────────────────────────────────────────────────────
echo ""
echo "=== Setup Complete ==="
echo "Worktrees:"
git worktree list
echo ""
echo "Agent launch (from Agent0 session):"
echo "  Claude-1: GITHUB_TOKEN=\$CLAUDE1_GITHUB_TOKEN WEA_AGENT=Claude-1@claude claude -p '...'"
echo "  Codex-2:  GITHUB_TOKEN=\$CODEX2_GITHUB_TOKEN WEA_AGENT=Codex-2@codex codex '...'"
