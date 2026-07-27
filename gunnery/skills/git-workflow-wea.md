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

### Publish branches

- Use `wea push <branch>` as the canonical way to publish agent branches.
- `wea push` uploads commits via the GitHub API, so agents do not depend on local remote quirks or `push-origin`.
- Treat direct `git push` remotes as operator/debug fallback, not the standard agent workflow.

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
wea show <N>             # inspect the task; there is no general claim
# ... do the work ...
git add <files>
git commit -s -m "[Task #N] description"
wea push agent/<name>/<N>-<slug>
wea pr <N> --head agent/<name>/<N>-<slug> --deliverable "What changed"
```

`wea pr` validates the branch name and refuses to create a PR until the branch
is visible on GitHub. If it tells you to run `wea push`, do that first.

## Anti-pattern

- Skipping `wea push` and trying to create a PR for a branch GitHub cannot see yet.
- Skipping `-s` on commits — unsigned commits may be rejected.
- Using `gh` directly for task operations — use `wea` CLI only.
