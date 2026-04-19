# Repo Hygiene

Two maintenance scripts help keep local branches and worktrees tidy without making destructive changes by default.

## Branch cleanup

Run `python scripts/cleanup_branches.py` to classify stale local branches in four buckets:

- `merged into main`
- `gone-remote`
- `closed-task-pr-merged`
- `idle-30d`

The script is dry-run by default. `--apply` force-deletes only branches that pass its safety gates:

- never delete `main`
- never delete `agent0/*` or `agent/agent0/*`
- never delete branches currently checked out in a worktree
- never delete branches with open PRs

Before each deletion it appends a JSONL record to `agent0_diary/branch_cleanup_log.jsonl` with the branch name and SHA.

## Worktree cleanup

Run `python scripts/cleanup_worktrees.py` to:

- execute `git worktree prune --dry-run --verbose`
- flag worktrees under the system temp directory that are older than 14 days

Use `--apply` to run `git worktree prune --verbose` for real. The script only reports old temp worktrees; it does not delete active worktree directories.

## Heartbeat use

Heartbeat can run both scripts in dry-run mode and summarize:

- stale branch counts by category
- branches protected by open PRs or active worktrees
- `git worktree prune` output
- temp-dir worktrees older than 14 days
