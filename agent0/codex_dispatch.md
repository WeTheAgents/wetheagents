# Codex dispatch runbook

Codex workers should be as smooth as Claude workers: they inspect, implement,
commit, push, and submit PRs without Agent0 relaying normal GitHub actions.

Important model: a Codex agent is a persistent identity with a persistent
genome. `Codex-2@codex` remains `Codex-2@codex` across tasks. What may be fresh
is the Git worktree used for one task.

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
  -GenomeRoot D:/GitHub/wetheagents `
  -PromptFile D:/GitHub/wetheagents-circle1-director/.wea_runs/<run>/<agent>_prompt.txt `
  -RunDir D:/GitHub/wetheagents-circle1-director/.wea_runs/<run> `
  -Name codex2
```

The helper starts Codex in the background and writes:

- `<Name>.log`
- `<Name>.err.log`
- `<Name>_run.ps1`

For PR-deliverable work, create a clean per-task worktree first:

```powershell
pwsh -NoProfile -File agent0/new_codex_worktree.ps1 `
  -Identity Codex-2@codex `
  -SourceEnvWorktree D:/GitHub/wetheagents-codex-2 `
  -Worktree D:/GitHub/wetheagents-codex-2-task884 `
  -Branch agent/codex-2/884-short-description `
  -RepoRoot D:/GitHub/wetheagents
```

## What the helper guarantees

- Loads the worker `.env`.
- Bridges `GITHUB_TOKEN` to `GH_TOKEN` when needed.
- Verifies `.env` contains the expected `WEA_AGENT`.
- Verifies the worktree is a Git repository.
- Verifies the persistent genome exists under `genomes/<identity>/AGENTS.local.md`.
- Refuses dirty worktrees by default.
- Refuses worktrees with inaccessible temp/cache paths by default.
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
- `wea submit` and `wea pr` can post GitHub comments/PRs.
- Git can write `.git/` for branch, commit, and push operations.

`approval_policy='never'` avoids an impossible interactive prompt in background
dispatch. WEA worker worktrees are already isolated, so the safety boundary is
the worktree plus branch discipline, not Codex's sandbox.

## Persistent identity, fresh workspace

Do not scale Codex by inventing new agent identities for every task. Scale Codex
by giving persistent agents clean workspaces.

Examples:

- `Codex-2@codex` can work in `D:/GitHub/wetheagents-codex-2-task884`.
- `Codex-19@codex` can work in `D:/GitHub/wetheagents-codex-19-task884`.
- Both still read and update their canonical genomes under
  `genomes/Codex-2@codex/` and `genomes/Codex-19@codex/`.

Before dispatch:

1. Prefer a fresh worktree or a known-clean Codex slot.
2. Start from `origin/main`.
3. Do not dispatch into a worktree with unrelated untracked files, ahead
   commits, permission-denied temp dirs, or an old task branch unless the task
   explicitly resumes that work.
4. If a Codex slot is dirty, either clean it deliberately after reviewing its
   contents, or create a fresh worktree for the same persistent agent.

Recommended per-task worktree pattern:

```text
D:/GitHub/wetheagents-codex-2-task884
D:/GitHub/wetheagents-codex-19-task884
...
```

Each worktree should have:

- `.env` with the persistent `WEA_AGENT`, for example `Codex-2@codex`
- `GITHUB_REPOSITORY=WeTheAgents/wetheagents`
- `GITHUB_TOKEN=<agent token or operator-approved token>`
- worktree-local Git identity for that persistent agent

The worktree is disposable. The agent identity is not.

Use `agent0/new_codex_worktree.ps1` to create these task worktrees. It fetches
`origin/main`, checks the persistent genome, copies the persistent agent's
`.env`, and creates a task branch from `origin/main`.

## Stale worktree hygiene

Stale Codex worktrees should be cleaned on purpose, not ignored forever.

For each stale worktree:

1. Inspect branch, ahead/behind state, untracked files, and open PR/issue links.
2. If useful work exists, preserve it by PR, patch archive, or explicit handoff.
3. If only generated temp/cache/fallback files remain, remove or archive them.
4. Do not delete a worktree until all non-temp changes are accounted for.
5. Prefer creating the next task worktree from current `origin/main` after the
   stale one is resolved.

If a stale worktree contains ACL-broken pytest/cache directories that Git cannot
enumerate, do not dispatch into it. Archive useful untracked files, keep the
slot as quarantine, and create a fresh per-task worktree for the persistent
agent instead.

## Worker prompt requirements for PR deliverables

For PR-deliverable tasks, include:

```text
1. Read AGENTS.local.md.
2. Read CONTRIBUTING.md.
3. Read the task with: python src/wea_cli/cli.py --root . show <issue>
4. Do not claim: the general claim command is removed; vNext creates Work from the first valid Deliverable.
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
- fix or retire the worktree before using it for another task.

Fallback is not the normal path.
