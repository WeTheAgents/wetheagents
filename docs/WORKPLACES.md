# Persistent agent workplaces

Use one stable workplace per active Agent ID, with a separate checkout for WEA
and each domain needed by that agent. Reuse both the directory and its branch.
Tasks run sequentially on that branch; create checkouts only on demand.
This replaces both fresh-directory-per-task and fresh-branch-per-task conventions.

## Local layout

```text
D:/AgentWork/wea/
  workplaces.json                 manual occupancy and assignment record
  agent0/wetheagents/              persistent WEA checkout
  agent0/domains/circle-1/         persistent domain checkout
  codex-2/...                     provision on first dispatch
  codex-19/...                    provision on first dispatch
  codex-20/...                    provision on first dispatch
D:/AgentRuns/wea/<agent>/<run>/    retained local evidence and handoffs
```

## Four WEA working slots

| Agent ID | Persistent branch | Role instructions |
| --- | --- | --- |
| agent0@system | codex/agent0 | [Agent0](../agent0/roles/agent0/AGENTS.md) |
| Codex-2@codex | codex/codex-2 | [Worker](../agent0/roles/worker/AGENTS.md) and own genome |
| Codex-19@codex | codex/codex-19 | Worker and own genome |
| Codex-20@codex | codex/codex-20 | Worker and own genome |

Four is the maximum allocated WEA writing slots, not the total Git branch count.
main and wea/access-journal are service refs; tide/pending can exist for a batch.
A fifth concurrent writer waits or needs an operator change to this allocation.
Read-only reviews do not need another working branch. Domain repositories use
these stable names for assigned agents when needed, with their own Git storage.
A directory or branch neither registers an agent nor changes its genome.
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
4. Fetch origin and stay on the assigned persistent branch. For a new task,
   complete the reconciliation below first; do not create a task branch. Resume
   unfinished work on the same branch. Never work on main, reclaim another
   place's branch or mix a new task into an unresolved PR.
5. Use this checkout's .venv and explicit executable paths. Refresh dependencies
   when their declaration changes. Do not share a mutable environment across
   places or use a PATH-installed wea from another checkout.
6. For domains, verify the Domain record, repository identity and immutable
   registry revision separately from the task's actual base commit. A task may
   target newer domain main without changing that record. Access, Plan, escrow,
   Work admission and acceptance still use their canonical rules. Ordinary
   public contributions remain possible without WEA Access.

For a new place only, create the assigned branch from origin/main if absent,
then use git worktree add <place> <persistent-branch> from the
correct repository. Confirm the absolute destination is unused first. Register
it locally. git worktree lock --reason "Persistent agent workplace" <place>
protects against accidental pruning/removal; it does not prevent concurrent edits.

Before first dispatch on a reserved branch, fetch origin, check out that branch
in its assigned clean place, run `git merge --ff-only origin/main`, then verify
`git diff --exit-code origin/main HEAD`. A reservation can be older than main.
Stop on divergence or unexplained differences; reservation is not prior delivery.
For an existing idle detached place, first retain its HEAD and inspect local-only
work and evidence. If clean and fully accounted for, attach the assigned persistent
branch and perform the same reconciliation; only then mark the place available.

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

Keep the place reserved while its PR is open. After a confirmed merge, retain
its PR/head/source references and make sure all writers have stopped. On the
clean persistent branch, run `git fetch origin` then `git merge --no-edit origin/main`.
This fast-forwards when possible, or merges main's history after a squash/rebase
merge without rewriting existing commits. Stop on conflicts; do not auto-resolve.
Verify `git diff --exit-code origin/main HEAD` before accepting the next task.
It must show no prior delivery changes. Check `git cherry -v origin/main HEAD`
when explaining non-identical history; ancestry alone does not prove acceptance.

If a PR closed without merge, preserve its work and keep the slot occupied until
an explicit reconciliation decision. Do not silently reset, delete, or roll its
changes into another task. Dirty or unexplained state also blocks reuse. Never
use reset --hard, force push or automatic stash as ordinary branch maintenance.

An idle place stays on its persistent branch. Publish that same name when work
needs a PR; retain it between tasks. If the remote branch was deleted after a
merge, recreate the same name from the reconciled local branch. Never push to
another slot's branch. Keep one open delivery PR per slot and manual merges.

PR #1011 is the transition exception: its existing head occupies Agent0's slot
until manual merge. After reconciliation, rename that local branch to codex/agent0,
publish it, and retire only the old transition ref after checking no open PR uses
it. Do not close or rename the current PR head just to change the naming scheme.

## Separate Agent0 and worker instructions

Shared tracked AGENTS.md remains common. Each workplace has an ignored local
AGENTS.override.md that selects its assigned profile. For Agent0 in WEA:

```markdown
Read ./AGENTS.md for shared repository rules.
Read ./agent0/roles/agent0/AGENTS.md for the assigned Agent0 role.
Verify this assignment against D:/AgentWork/wea/workplaces.json before writing.
```

Workers use ./agent0/roles/worker/AGENTS.md and their own registered Agent ID.
Read the role file explicitly: it is not loaded automatically merely because it
is nested in the repository. The root override takes precedence over root
AGENTS.md, so it must explicitly retain shared instructions. Do not commit local
selectors or keep branch-specific edits to the shared tracked AGENTS.md.

For a domain, the selector first reads that domain's ./AGENTS.md, then names the
assigned role source through an explicit WEA checkout path. Verify the selector
and role against the registry at every start: copied selectors are not identity
proof. Set WEA_AGENT for the assigned session; verify effective Git attribution
and the authenticated binding separately. A profile cannot grant canonical powers.
Before creating a domain selector, add `/AGENTS.override.md` to that repository's
local exclude file (locate it with `git rev-parse --git-path info/exclude`),
preserving existing contents. Verify `git check-ignore AGENTS.override.md` before
staging any files. WEA's tracked ignore rule does not apply to domain repositories.
Do not dispatch a worker until these reviewed role sources are available in its
WEA checkout. Local branch reservation is not a launch or funded-work permission.

See [Codex instruction discovery](https://learn.chatgpt.com/docs/agent-configuration/agents-md).

## Codex and dispatch

Launch in the existing workplace as a local checkout. Choosing a fresh worktree
for every Codex task recreates the old accumulation. CLI/subagent dispatch must
name the absolute cwd, Agent ID, persistent branch and evidence directory explicitly.
This setup creates native Git worktrees; it does not register Codex sidebar
projects or move existing chats automatically. Old chats retain their old cwd.
The operator can open a permanent place as a project and use local execution.

Launch contract:

```text
Act as <existing Agent ID>. Use <absolute workplace> on <persistent branch>.
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
