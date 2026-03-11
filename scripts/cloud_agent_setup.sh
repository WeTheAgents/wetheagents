#!/bin/bash
# Cloud Agent Setup — runs at session start, before Claude Code launches.
# Prepares worktrees, CLI tools, and agent identities for cloud-based agents.
#
# Usage:
#   cloud_agent_setup.sh              — full setup (steps 1-7, deploys genomes)
#   cloud_agent_setup.sh --retrieve   — retrieve genomes from all worktrees
#   cloud_agent_setup.sh --retrieve --agent cursor-3  — retrieve one agent
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

# ── Agent registry ──────────────────────────────────────────
# Format: "slug|genome_id|agent_type|branch|display_name|email"
# agent_type: cli = AGENTS.local.md, ide = AGENTS.md (with YAML frontmatter)
AGENTS=(
  "claude-1|Claude-1@claude|cli|agent/Claude-1/work|Claude-1|claude-1@claude"
  "codex-2|Codex-2@codex|cli|agent/Codex-2/work|Codex-2|codex-2@codex"
  "cursor-3|Cursor-1@cursor|ide|agent/Cursor-3/work|Cursor-3|cursor-3@cursor"
  "antigravity-4|Antigravity-1@Google|ide|agent/Antigravity-4/work|Antigravity-4|antigravity-4@Google"
  "claude-5|Claude-5@claude|cli|agent/Claude-5/work|Claude-5|claude-5@claude"
  "claude-6|Claude-6@claude|cli|agent/Claude-6/work|Claude-6|claude-6@claude"
)

YAML_FRONTMATTER="---
description:
alwaysApply: true
---"

# ── Parse arguments ─────────────────────────────────────────
MODE="setup"
FILTER_AGENT=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --retrieve)  MODE="retrieve"; shift ;;
    --agent)     FILTER_AGENT="$2"; shift 2 ;;
    *)           echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

# ── Helper functions ────────────────────────────────────────

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

deploy_genome() {
  local slug="$1" genome_id="$2" agent_type="$3"
  local genome_src="$REPO/genomes/${genome_id}/AGENTS.local.md"
  local wt="/home/user/wetheagents-${slug}"

  if [ ! -f "$genome_src" ]; then
    echo "  WARN: genome not found: $genome_src"; return 0
  fi

  if [ "$agent_type" = "cli" ]; then
    cp "$genome_src" "${wt}/AGENTS.local.md"
    echo "  ${slug}: AGENTS.local.md (cli)"
  else
    # IDE agents read AGENTS.md, not AGENTS.local.md
    { printf '%s\n\n' "$YAML_FRONTMATTER"; cat "$genome_src"; } > "${wt}/AGENTS.md"
    # Hide from git status — AGENTS.md is tracked, prevent accidental commits
    git -C "$wt" update-index --assume-unchanged AGENTS.md 2>/dev/null || true
    echo "  ${slug}: AGENTS.md (ide, frontmatter added)"
  fi
}

retrieve_genome() {
  local slug="$1" genome_id="$2" agent_type="$3"
  local genome_dst="$REPO/genomes/${genome_id}/AGENTS.local.md"
  local wt="/home/user/wetheagents-${slug}"

  if [ "$agent_type" = "cli" ]; then
    local src="${wt}/AGENTS.local.md"
    if [ ! -f "$src" ]; then
      echo "  WARN: ${src} not found, skipping"; return 0
    fi
    cp "$src" "$genome_dst"
  else
    local src="${wt}/AGENTS.md"
    if [ ! -f "$src" ]; then
      echo "  WARN: ${src} not found, skipping"; return 0
    fi
    # Strip YAML frontmatter (--- ... ---) and blank line after it
    # Only activates if line 1 is exactly "---"; safe if no frontmatter
    awk '
      NR==1 && /^---$/ { in_fm=1; next }
      in_fm && !fm_done && /^---$/ { fm_done=1; next }
      fm_done && !blanked && /^$/ { blanked=1; next }
      !in_fm || fm_done { print }
    ' "$src" > "$genome_dst"
  fi
  echo "  ${slug}: genome retrieved -> genomes/${genome_id}/"
}

# ── Retrieve mode (early exit) ──────────────────────────────
if [ "$MODE" = "retrieve" ]; then
  echo "=== Genome Retrieve ==="
  for entry in "${AGENTS[@]}"; do
    IFS='|' read -r slug genome_id agent_type _branch _name _email <<< "$entry"
    [ -n "$FILTER_AGENT" ] && [ "$slug" != "$FILTER_AGENT" ] && continue
    retrieve_genome "$slug" "$genome_id" "$agent_type"
  done
  echo "=== Done ==="
  exit 0
fi

# ── Normal setup flow ───────────────────────────────────────
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
for entry in "${AGENTS[@]}"; do
  IFS='|' read -r slug _gid _type branch _name _email <<< "$entry"
  create_worktree "$slug" "$branch"
done

# ── 5. Configure git identity per worktree ─────────────────────────
echo "[5/7] Configuring git identity..."
for entry in "${AGENTS[@]}"; do
  IFS='|' read -r slug _gid _type _branch name email <<< "$entry"
  local_wt="/home/user/wetheagents-${slug}"
  git -C "$local_wt" config --local user.name "$name"
  git -C "$local_wt" config --local user.email "$email"
done

# ── 6. Deploy genomes ─────────────────────────────────────────────
echo "[6/7] Deploying genomes..."
for entry in "${AGENTS[@]}"; do
  IFS='|' read -r slug genome_id agent_type _branch _name _email <<< "$entry"
  deploy_genome "$slug" "$genome_id" "$agent_type"
done

# ── 7. Configure push remotes ─────────────────────────────────────
# NOTE: git remotes are stored in .git/config which is SHARED across all worktrees.
# Embedding per-agent tokens in the URL would cause the last-written token to win.
# Instead: use a credential helper that reads GITHUB_TOKEN from the environment.
# Each agent is launched with its own GITHUB_TOKEN set, so the right token is used.
echo "[7/7] Configuring push remotes..."

# Install credential helper (reads GITHUB_TOKEN from env at push time)
cat > /usr/local/bin/git-credential-github-token << 'CREDEOF'
#!/bin/bash
echo "username=x-access-token"
echo "password=${GITHUB_TOKEN}"
CREDEOF
chmod +x /usr/local/bin/git-credential-github-token

# Configure credential helper for github.com in the main repo (shared, that's fine)
git -C "$REPO" config credential.https://github.com.helper github-token

# Add a single push-origin remote (no embedded token — uses credential helper)
git -C "$REPO" remote remove push-origin 2>/dev/null || true
git -C "$REPO" remote add push-origin "https://github.com/WeTheAgents/wetheagents.git"
echo "  ok: push-origin configured (credential helper reads GITHUB_TOKEN from env)"

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
echo "  Claude-1:      GITHUB_TOKEN=\$CLAUDE1_GITHUB_TOKEN WEA_AGENT=Claude-1@claude claude -p '...'"
echo "  Codex-2:       GITHUB_TOKEN=\$CODEX2_GITHUB_TOKEN WEA_AGENT=Codex-2@codex codex '...'"
echo "  Cursor-3:      (IDE — reads AGENTS.md in worktree)"
echo "  Antigravity-4: (IDE — reads AGENTS.md in worktree)"
echo ""
echo "Genome retrieve:"
echo "  bash scripts/cloud_agent_setup.sh --retrieve"
echo "  bash scripts/cloud_agent_setup.sh --retrieve --agent cursor-3"
