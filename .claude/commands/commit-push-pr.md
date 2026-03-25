---
description: Commit, push, and open a PR in one step
allowed-tools: Bash(git checkout:*), Bash(git add:*), Bash(git status:*), Bash(git push:*), Bash(git commit:*), Bash(git diff:*), Bash(gh pr create:*)
---

## Context

- Current git status: !`git status`
- Current git diff (staged and unstaged changes): !`git diff HEAD`
- Current branch: !`git branch --show-current`

## Your task

Based on the above changes:

1. Create a new branch if on main (use convention: `agent/<name>/<issue>-<slug>`)
2. Stage relevant files (NOT .env, credentials, or sensitive files)
3. Create a single commit with an appropriate message
4. Push the branch to origin
5. Create a pull request using `gh pr create`

You have the capability to call multiple tools in a single response. You MUST do all of the above in a single message. Do not use any other tools or do anything else. Do not send any other text or messages besides these tool calls.
