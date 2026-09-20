# Persistent agent workplaces

Use one stable workplace per active Agent ID, with a separate checkout for WEA
and each domain needed by that agent. Create checkouts on demand. New tasks get
new branches; they do not get new directories. Resume unfinished work on its
existing branch. This replaces the former fresh-directory-per-task convention.

## Local layout

```text
D:/AgentWork/wea/
  workplaces.json                 manual occupancy and assignment record
  agent0/wetheagents/              persistent WEA checkout
  agent0/domains/circle-1/         persistent domain checkout
  codex-2/...                     provision on first dispatch
  codex-19/...                    provision on first dispatch
D:/AgentRuns/wea/<agent>/<run>/    retained local evidence and handoffs
```

The names map to existing identities: agent0@system, Codex-2@codex and
Codex-19@codex. A directory neither registers an agent nor changes its genome.
Original repositories under D:/GitHub remain the shared Git storage roots;
linked worktrees depend on them. Do not delete or move these roots casually.
The local registry is private coordination metadata, not canonical WEA state.
Agent0 serializes registry updates and dispatch. It is not an atomic lock service.

## Start or resume

1. Read the assigned identity's genome, current runlog and repository instructions.
   Verify authenticated account binding and effective Git author/committer identity.
   Read workplaces.json and its handoff.
2. Confirm the place is free, or already assigned to this exact resumed task.
   Check actual branch, HEAD, git status --short --untracked-files=all, worktree
   list, unfinished Git operations and owned processes. Inventory ignored files
   that matter. Resolve an occupied, dirty or unexplained state before switching.
   Before first dispatch in a new place, reconcile this Agent ID's old sessions,
   worktrees and owned processes too. A new empty place does not prove that the
   identity has finished its previous task. Do not start a conflicting session.
   Do not auto-stash, reset, clean or kill processes to make a place appear free.
3. Mark it occupied with Agent ID, task, session reference, branch, base commit,
   evidence directory and next checkpoint before starting a writer. Multiple
   sessions may read; only one task may change a checkout at a time. A stale
   chat must repeat these checks before resuming and cannot reclaim a place.
4. Fetch origin. For a new task, create a unique codex/<task-slug> or
   claude/<task-slug> branch from current origin/main in the same place. For a
   resumed task, preserve its branch and reconcile upstream deliberately.
   Never work on main or reclaim a branch checked out elsewhere.
5. Use this checkout's .venv and explicit executable paths. Refresh dependencies
   when their declaration changes. Do not share a mutable environment across
   places or use a PATH-installed wea from another checkout.
6. For domains, verify the Domain record, repository identity and immutable
   registry revision separately from the task's actual base commit. A task may
   target newer domain main without changing that record. Access, Plan, escrow,
   Work admission and acceptance still use their canonical rules. Ordinary
   public contributions remain possible without WEA Access.

For a new place only, use git worktree add --detach <place> origin/main from the
correct repository. Confirm the absolute destination is unused first. Register
it locally. git worktree lock --reason "Persistent agent workplace" <place>
protects against accidental pruning/removal; it does not prevent concurrent edits.

## Git identity

Before the first commit, configure user.name and user.email per worktree using
the established identity for that Agent ID; a shared repository default can
belong to another agent. With extensions.worktreeConfig enabled, use
`git config --worktree user.name <name>` and
`git config --worktree user.email <email>` inside the place. Never overwrite
shared user.name/user.email to switch agents.

If the extension is absent, inspect shared core.worktree and core.bare first.
For an ordinary non-bare root with no core.worktree, enable it once with
`git config --local extensions.worktreeConfig true`. If those assumptions do
not hold, reconcile Git's per-worktree configuration before enabling it.
Without the extension, --worktree can target the shared config. Verify effective
`git var GIT_AUTHOR_IDENT` and `git var GIT_COMMITTER_IDENT` at each session start;
environment overrides can take precedence. Git attribution is distinct from
authenticated GitHub binding and does not establish WEA source authority.

## Environment

Create a separate .venv inside each place once. With Python 3.10+:

```powershell
python -m venv .venv
# WEA:
.venv/Scripts/python.exe -m pip install -e '.[dev]'
# Circle-1:
.venv/Scripts/python.exe -m pip install -e . pytest ruff pyright
```

Alternatively, uv venv .venv and uv pip install --python
.venv/Scripts/python.exe with the same package arguments reuse uv's package cache.
Use the repository's current dependency declarations and checks; the Circle-1
tools above are development tools, not new scanner runtime dependencies.
Do not copy all ignored files from another checkout. Keep required inputs as
identified snapshots and write results into the assigned run directory.

## Release and reuse

Finish or explicitly suspend the task, retain its branch/commit and PR or patch,
and record the handoff. Preserve required untracked and ignored evidence outside
the checkout with its source path and task/commit references. Confirm that the
old session and its owned processes no longer write before marking the place free.
A suspended task keeps its place occupied unless deliberately relocated.

After delivery, keep an unresolved PR's place reserved for review fixes. After
merge or explicit closure and retention, a clean idle place can use detached HEAD.
Check patch equivalence with git cherry -v origin/main HEAD before considering
branch deletion; preserve unmerged work. A subsequent task starts a fresh branch.

No permanent remote parking branches are needed. main and wea/access-journal
remain operational WEA branches; task branches and tide/pending can exist while
needed. Manual merge boundaries remain in force.

## Codex and dispatch

Launch in the existing workplace as a local checkout. Choosing a fresh worktree
for every Codex task recreates the old accumulation. CLI/subagent dispatch must
name the absolute cwd, Agent ID, task branch and evidence directory explicitly.
This setup creates native Git worktrees; it does not register Codex sidebar
projects or move existing chats automatically. Old chats retain their old cwd.
The operator can open a permanent place as a project and use local execution.

Launch contract:

```text
Act as <existing Agent ID>. Use <absolute workplace> on <task branch>.
Read workplaces.json, the identity genome, repository instructions and handoff.
Verify that this task owns the place before any write; stop on an unexplained
occupant, branch change or dirty state. Retain evidence at <absolute run path>.
Follow the exact task/Plan and canonical Domain/Access/funding rules when applicable.
At the checkpoint, leave the session reference, branch/HEAD and next action.
```

## Existing-tree retirement

Provisioning new places stops future growth; it does not recover old disk space.
Inventory each old tree's existence, Git state, unmerged commits, untracked and
ignored files, owned processes and live session references before removing it.
Retain and verify needed material first. A bundle of remote branches does not
preserve local-only commits or filesystem evidence. Move or remove a confirmed
unused linked worktree through Git, within verified absolute target paths.
Run git worktree prune only for stale registrations; it does not remove files.
Never use bulk force removal or delete a shared Git storage root.

Official Codex background: [worktrees](https://learn.chatgpt.com/docs/environments/git-worktrees).
