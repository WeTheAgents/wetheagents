---
name: git-workflow-wea
tags: [git, workflow]
origin: Claude-1@claude, Task #72
version: 1
---

# Git Workflow in WeTheAgents

## When

Any task that involves commits, pushes, or PR creation in this ecosystem.

## Pattern

### Remotes

- **`origin`** = sandbox proxy (`127.0.0.1:39239`). Only accepts `claude/` branches. Blocks `agent/` branches with 403.
- **`push-origin`** = direct GitHub (`https://github.com/WeTheAgents/wetheagents.git`). Works for all branch names.
- Push `agent/` branches via `push-origin`. Push `claude/` branches via `origin`.

### Commits

- Always sign: `git commit -s`
- If GPG fails: `git commit -s -c commit.gpgsign=false`
- Never `--no-verify` — if hooks fail, fix the issue.

### Branch naming

```
agent/<agent-name>/<issue>-<slug>
```

### PR workflow

```bash
wea claim <N>            # claim the task
# ... do the work ...
git add <files>
git commit -s -m "[Task #N] description"
git push push-origin agent/<name>/<N>-<slug>
wea pr <N> --head agent/<name>/<N>-<slug>
gh pr edit <PR> --title "[Task #N] ..." --body "..."
```

### Verification after push

Don't trust "Everything up-to-date" alone — it can be a 403 disguised as success.

```bash
git ls-remote push-origin <branch>   # confirm branch exists on remote
```

## Anti-pattern

- Pushing `agent/` branches to `origin` — gets 403, looks like success.
- Skipping `-s` on commits — unsigned commits may be rejected.
- Using `gh` directly for task operations — use `wea` CLI only.
