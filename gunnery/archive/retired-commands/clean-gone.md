# Retired command recipe

Historical, non-effective material. Do not execute the branch/worktree deletion recipe below. [WORKPLACES](../../../docs/WORKPLACES.md) supersedes it and requires preserving assigned workplaces and unexplained work.

---
description: Clean up local git branches that have been deleted on the remote (marked as [gone])
allowed-tools: Bash(git branch:*), Bash(git worktree:*), Bash(git fetch:*)
---

## Your Task

Clean up stale local branches that have been deleted from the remote repository.

1. First, fetch and prune remote tracking info: `git fetch --prune`
2. List branches to identify any with [gone] status: `git branch -v`
3. Identify worktrees that may need removal: `git worktree list`
4. For each [gone] branch:
   - If it has an associated worktree, remove the worktree first: `git worktree remove <path>`
   - Then delete the branch: `git branch -D <branch>`
5. Report what was cleaned up
