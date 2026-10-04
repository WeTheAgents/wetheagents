# Repo Hygiene

Two maintenance scripts help keep local branches and worktrees tidy without making destructive changes by default.

## Branch cleanup

Run `python scripts/cleanup_branches.py` to classify stale local branches in four buckets:

- `merged into main`
- `gone-remote`
- `closed-task-pr-merged`
- `idle-30d`

The script is dry-run by default. Explicit `--apply` conditionally deletes only local branch refs that pass its safety gates:

- never delete `main`
- never delete the exact local persistent names `work/agent0`, `work/slot-1`, `work/slot-2` or `work/slot-3`, even without an attached worktree or open PR
- never delete `agent0/*` or `agent/agent0/*`
- never delete branches currently checked out in a worktree
- never delete branches with open PRs

Before each deletion it appends a JSONL record to `agent0_diary/branch_cleanup_log.jsonl` with the branch name and SHA.
If the open-PR query is unavailable or fails, `--apply` is blocked.

Deletion validates the full `refs/heads/<name>` identity and captured nonzero full SHA, refuses symbolic, missing or changed refs, and uses `git update-ref --no-deref -d <full-ref> <expected-sha>`. The comparison and deletion are atomic for that ref. Tags and remote refs with matching short names are not deletion targets. A changed tip is never silently reclassified.

After writing the `pre_delete` receipt, the tool refreshes worktree membership, including branches held by detached rebase or bisect operations and secondary branches scheduled by `rebase --update-refs`. Malformed or unreadable operation metadata blocks deletion. Inspection or logging errors prevent deletion. Refusals and conditional-update failures appear in `Delete failures` and produce exit code 2. Early identity/SHA refusals have no receipt; later failures retain their attempt receipt. A `pre_delete` receipt is recovery evidence, not proof of success.

Worktree inspection and ref deletion are separate operations. Concurrent attachment after the final inspection is not atomically excluded, just as the previous native `git branch -D` path did not establish a shared worktree-creation lock. PR protection uses the classification-time query. Keep other local writers stopped during an authorized cleanup; this tool does not acquire a repository-wide lock. Conditional ref deletion does not remove leftover `branch.*` configuration.

The exact-name guard enforces [persistent workplaces](WORKPLACES.md): a closed task does not make a permanent local branch disposable. It does not exempt all `work/*` names, recreate remote branches or authorize cleanup execution.

## Worktree cleanup

Run `python scripts/cleanup_worktrees.py` to:

- execute `git worktree prune --dry-run --verbose`
- flag worktrees under the system temp directory that are older than 14 days

Use `--apply` to run `git worktree prune --verbose` for real. The script only reports old temp worktrees; it does not delete active worktree directories.

## Bounded coordination

[Dot's project context](../gunnery/agent0/ROLE.md#dot-coordination) is the sole Agent0 coordinator. Independent external Agent0 heartbeats and schedules remain paused. An explicitly assigned bounded maintenance session can run both scripts in dry-run mode and summarize:

- stale branch counts by category
- branches protected by open PRs or active worktrees
- `git worktree prune` output
- temp-dir worktrees older than 14 days

Dry-run results do not authorize branch deletion, worktree retirement, another coordinator or a background cleanup loop.
