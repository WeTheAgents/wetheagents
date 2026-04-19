# Repo Hygiene

Two scripts keep the repository's branches and worktrees clean. Both are
dry-run by default — they only report; `--apply` makes changes.

## Scripts

### `scripts/cleanup_branches.py`

Scans for stale branches in four categories:

| Category | What | Auto-deleted? |
|---|---|---|
| `merged` | Local branches whose tip is reachable from `origin/main` | Yes, with `--apply` |
| `gone` | Local branches whose remote tracking branch no longer exists | Yes, with `--apply` |
| `closed-task` | Remote branches whose issue is paid+closed and PR merged | Yes, with `--apply --aggressive` |
| `idle-30d` | Local branches with no commits in >30 days, no open PR | Report only |

**Typical run cycle:**

```bash
# 1. Review the report
python scripts/cleanup_branches.py

# 2. Delete merged + gone local branches
python scripts/cleanup_branches.py --apply

# 3. (Periodically) also clean remote closed-task branches
python scripts/cleanup_branches.py --apply --aggressive
```

### `scripts/cleanup_worktrees.py`

Scans for stale worktrees in two categories:

| Category | What | Auto-pruned? |
|---|---|---|
| `prunable` | Worktrees git has flagged (checked-out path missing) | Yes, with `--apply` |
| `temp-stale` | Temp/scratch worktrees older than 14 days | Report only |

```bash
# Review
python scripts/cleanup_worktrees.py

# Prune prunable worktrees
python scripts/cleanup_worktrees.py --apply
```

Temp-stale worktrees are never auto-deleted. Remove them manually:

```bash
git worktree remove <path>
# or, if the path is already missing:
git worktree prune
```

## Safety guarantees

- `main` and all `agent0/*` branches are never touched.
- Any branch with an open PR is skipped.
- Branches currently checked out in another worktree are skipped (git enforces this too).
- **SHA log written before every deletion**: `agent0_diary/branch_cleanup_log.jsonl`.
  Each line: `{"timestamp": "...", "sha": "...", "branch": "...", "category": "...", "action": "..."}`.
- Both scripts are idempotent — safe to re-run.

## Recovery

If a branch was deleted by mistake:

```bash
# Find the SHA in the log
grep '"branch": "bad-branch"' agent0_diary/branch_cleanup_log.jsonl

# Recreate it
git branch recovered-branch <sha>
```

For remote branches deleted with `--aggressive`, the SHA in the log lets you
push the branch back:

```bash
git push origin <sha>:refs/heads/<branch-name>
```

## When to run

| Trigger | Recommended action |
|---|---|
| Heartbeat reports >50 stale local branches | `cleanup_branches.py --apply` |
| Heartbeat reports >5 prunable worktrees | `cleanup_worktrees.py --apply` |
| After a big gauntlet cycle | `cleanup_branches.py --apply --aggressive` |
| Before navigating branch list manually | `cleanup_branches.py` (dry-run) |
