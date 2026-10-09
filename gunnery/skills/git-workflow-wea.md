---
name: git-workflow-wea
tags: [git, workflow]
origin: Claude-1@claude, Task #72
version: 3
---

# Git Workflow in WeTheAgents

Use the current [task worktree procedure](../../docs/WORKPLACES.md).
The operator's 2026-10-09 decision supersedes the persistent-slot/PR capacity rule.

- Assign an existing Agent ID explicitly; verify binding and Git identity.
- Fetch origin and use an isolated task worktree with a unique codex/ or claude/
  branch. Preserve all old work/* trees, branches, PRs and evidence.
- Hold an execution lease while running a native worker. Open PRs and stopped
  tasks retain artifacts but do not consume the default four running processes.
- Stage intended files only and `git commit -s`; never bypass hooks. If GPG
  signing fails, `git -c commit.gpgsign=false commit -s` is allowed.
- Hold the shared publication lock; verify the exact push-origin destination,
  account, task branch and commit, then `wea push` and `gh pr create --draft`
  with explicit repository/base/head and UTF-8 body file. One PR per task.
- Run self-review, relevant checks and native Codex review. Merges remain manual.
- Keep exact deliverable and verification references. Do not use Closes #N;
  Git publication is separate from canonical acceptance, Access and payment.

Dirty or unexplained state still blocks writing that checkout. Another isolated
assignment may proceed when process capacity is free. Never reset or force-push
old work to make capacity. Recovery must verify owner/child process identities.
