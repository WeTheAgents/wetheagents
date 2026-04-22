#!/usr/bin/env bash
# Sync AGENT0.md → AGENTS.md in the main `wetheagents` worktree only.
# AGENTS.md there is flagged `skip-worktree` so it never gets committed —
# but `git pull` may still fail if upstream touches AGENTS.md.
# Run this after any pull that modifies AGENT0.md or AGENTS.md upstream.
set -euo pipefail

WT_PATH="${WETHEAGENTS_MAIN:-D:/GitHub/wetheagents}"
cd "$WT_PATH"

if [ "$(git ls-files -v AGENTS.md | awk '{print $1}')" != "S" ]; then
  echo "warning: AGENTS.md is not skip-worktree in $WT_PATH" >&2
  echo "run: git update-index --skip-worktree AGENTS.md" >&2
fi

cp AGENT0.md AGENTS.md
echo "synced: $WT_PATH/AGENTS.md ← AGENT0.md ($(wc -c < AGENTS.md) bytes)"
