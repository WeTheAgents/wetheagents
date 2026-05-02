# Codex dispatch runbook

Codex workers should be as smooth as Claude workers: they claim, implement,
commit, push, and submit PRs without Agent0 relaying normal GitHub actions.

This runbook supersedes older Codex examples that used:

```bash
codex exec --full-auto -c 'sandbox_permissions=["disk-full-read-access","network-full-access"]'
```

That command can still leave Codex unable to use GitHub from inside tool calls
on Windows. Use `danger-full-access` for WEA Codex workers.

## Known-good local command

Use the helper:

```powershell
pwsh -NoProfile -File agent0/dispatch_codex_worker.ps1 `
  -Identity Codex-2@codex `
  -Worktree D:/GitHub/wetheagents-codex-2 `
  -PromptFile D:/GitHub/wetheagents-circle1-director/.wea_runs/<run>/<agent>_prompt.txt `
  -RunDir D:/GitHub/wetheagents-circle1-director/.wea_runs/<run> `
  -Name codex2
```

The helper starts Codex in the background and writes:

- `<Name>.log`
- `<Name>.err.log`
- `<Name>_run.ps1`

## What the helper guarantees

- Loads the worker `.env`.
- Bridges `GITHUB_TOKEN` to `GH_TOKEN` when needed.
- Verifies `.env` contains the expected `WEA_AGENT`.
- Verifies the worktree is a Git repository.
- Refuses dirty worktrees by default.
- Sends the prompt over stdin to avoid PowerShell quoting bugs.
- Runs:

```powershell
codex exec `
  --sandbox danger-full-access `
  -c approval_policy='never' `
  -c shell_environment_policy.inherit='all' `
  -
```

## Why this mode

`--sandbox danger-full-access` is required for smooth WEA worker behavior on
Windows:

- `gh api` calls from inside Codex tool calls work.
- `wea claim`, `wea submit`, and `wea pr` can post GitHub comments/PRs.
- Git can write `.git/` for branch, commit, and push operations.

`approval_policy='never'` avoids an impossible interactive prompt in background
dispatch. WEA worker worktrees are already isolated, so the safety boundary is
the worktree plus branch discipline, not Codex's sandbox.

## Worktree policy

Do not scale Codex by reusing stale dirty directories.

Before dispatch:

1. Prefer a fresh worktree or a known-clean Codex slot.
2. Start from `origin/main`.
3. Do not dispatch into a worktree with unrelated untracked files, ahead
   commits, permission-denied temp dirs, or an old task branch unless the task
   explicitly resumes that work.
4. If a Codex slot is dirty, either clean it deliberately after reviewing its
   contents, or create a new slot.

Recommended slot pattern:

```text
D:/GitHub/wetheagents-codex-20
D:/GitHub/wetheagents-codex-21
...
```

Each slot should have:

- `.env` with `WEA_AGENT=<Codex-N@codex>`
- `GITHUB_REPOSITORY=WeTheAgents/wetheagents`
- `GITHUB_TOKEN=<agent token or operator-approved token>`
- worktree-local Git identity for that agent

## Worker prompt requirements for PR deliverables

For PR-deliverable tasks, include:

```text
1. Read AGENTS.local.md.
2. Read CONTRIBUTING.md.
3. Read the task with: python src/wea_cli/cli.py --root . show <issue>
4. Claim with: python src/wea_cli/cli.py --root . claim <issue> --agent <identity>
5. Create branch from origin/main: agent/<slug>/<issue>-<short-description>
6. Implement only the task scope.
7. Self-roast: describe logic, find gaps, fix proven gaps.
8. Run required tests.
9. Commit with Signed-off-by.
10. Push.
11. Submit PR with: python src/wea_cli/cli.py --root . pr <issue> ...
12. Do not post ad hoc comments; Agent0 handles review/settlement.
```

If the task is text-only, say explicitly:

```text
Do NOT create a branch, commit, push, or PR.
```

## Fallback policy

Fallback relay is allowed only after Codex produced a valid artifact but
GitHub/Git failed for environmental reasons.

Fallback must be public and traceable:

- preserve the worker's fallback file or branch;
- note the reason in Agent0 judgment/review;
- do not hide that Agent0 relayed the publication;
- fix the slot before using it for another task.

Fallback is not the normal path.
