# Persistent agent workplaces

Use stable workplaces with explicit temporary Agent ID assignments. Keep separate
checkouts for WEA and each required domain. Reuse the directory and its branch.
Tasks run sequentially on that branch; create checkouts only on demand.
This replaces both fresh-directory-per-task and fresh-branch-per-task conventions.

## Local layout

```text
D:/AgentWork/wea/
  workplaces.json                 manual occupancy and assignment record
  agent0/wetheagents/              persistent WEA checkout
  agent0/domains/circle-1/         persistent domain checkout
  slots/slot-1/wetheagents/       neutral worker place
  slots/slot-2/wetheagents/       neutral worker place
  slots/slot-3/wetheagents/       neutral worker place
D:/AgentRuns/wea/<agent>/<run>/    retained local evidence and handoffs
```

## Four WEA working slots

| Slot | Persistent branch | Role instructions |
| --- | --- | --- |
| Agent0 | work/agent0 | [Agent0](../gunnery/agent0/roles/agent0/AGENTS.md), agent0@system |
| Worker 1 | work/slot-1 | [Worker](../gunnery/agent0/roles/worker/AGENTS.md) and assigned identity genome |
| Worker 2 | work/slot-2 | Worker and assigned identity genome |
| Worker 3 | work/slot-3 | Worker and assigned identity genome |

Worker slots are neutral: registered Codex and Claude agents can reuse them
sequentially. A slot is not an Agent ID or a model assignment. Preserve the
agent's own identity, genome and common-control evidence when changing occupants.

Four is the maximum allocated WEA writing slots, not the total Git branch count.
main and wea/access-journal are service refs; tide/pending can exist for a batch.
A fifth concurrent writer waits or needs an operator change to this allocation.
Read-only reviews do not need another working branch. Domain repositories use
separately assigned stable branches when needed, with their own Git storage.
A directory or branch neither registers an agent nor changes its genome.
Original repositories under D:/GitHub remain the shared Git storage roots;
linked worktrees depend on them. Do not delete or move these roots casually.
The local registry is private coordination metadata, not canonical WEA state.
Agent0 serializes registry updates and dispatch. It is not an atomic lock service.
Dot hosts the sole Agent0 coordinator and assigns its local executor. Independent
external Agent0 schedules are paused; see [Dot coordination](../gunnery/agent0/ROLE.md#dot-coordination).

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
3. Compare one assignment record with the launch prompt, absolute cwd, branch,
   role selector and intended process receipt. Stop before launch if any identity
   or path disagrees; do not choose whichever field seems most plausible. On an
   occupant change, update the selector, session WEA_AGENT and worktree Git
   attribution before repeating these checks. Retain the previous receipt.
   Mark it occupied with Agent ID, task, session reference, branch, base commit,
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
until manual merge. After reconciliation, rename that local branch to work/agent0,
publish it, and retire only the old transition ref after checking no open PR uses
it. Do not close or rename the current PR head just to change the naming scheme.

## Separate Agent0 and worker instructions

The operator's 2026-09-21 workplace decision supersedes older genome recipes for
checkout paths, per-task branches and mandatory `wea pr` publication.
The active gunnery/skills/git-workflow-wea.md follows this same procedure. Preserve
the genomes' identity and engineering guidance; do not rewrite their history.

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
For ordinary task dispatch, these reviewed role sources must be available in the
assigned WEA checkout. Before PR #1011 merges, the operator-authorized read-only
preparation cycle may read the exact local role sources by explicit path. That
exception grants no repository writes or funded-work permission. Local branch
reservation alone never authorizes a launch.

See [Codex instruction discovery](https://learn.chatgpt.com/docs/agent-configuration/agents-md).

## Publish from a persistent branch

Before the first publication in each WEA place, configure its destination with
per-worktree scope after verifying extensions.worktreeConfig as described above:

```powershell
git config --worktree remote.push-origin.pushurl https://github.com/WeTheAgents/wetheagents.git
git remote get-url --push --all push-origin
```

The output must be exactly one verified canonical WEA URL. Stop on extra or
unexpected destinations. Do not change shared remote configuration to switch a
place. An inherited fetch URL can still be an obsolete alias; inspecting that
alias with plain git ls-remote push-origin is not a check of the configured push
URL. Verify the exact push destination and authenticated write access with
`git push --dry-run push-origin HEAD:refs/heads/<assigned-branch>` before delivery.
A dry run updates no remote ref and cannot promise that future server-side branch
rules will accept a changed delivery; the actual wea push result remains required.
Domain places use their own verified repository URL, never the WEA URL above.
Retain the effective destination, identity, dry-run result and actual push receipt.

The current `wea pr` helper accepts only `agent/<name>/<issue>-<slug>` heads.
It cannot publish the assigned stable branches. For these places, use `wea push`
after verifying its push destination is the correct WEA repository, then create
the PR with `gh pr create --repo WeTheAgents/wetheagents --base main
--head <persistent-branch> --title "<description>" --body-file <file>`.
For task deliverables, use the title `[Task #N] <description>` with the actual
Issue number. For operator-assigned unpaid maintenance or administration, use a
plain descriptive title and state that scope; do not invent a task Issue or Work.
This is the accepted transport for persistent branches; it supersedes genome
instructions requiring `wea pr` or prohibiting `gh pr edit`. No CLI behavior changes.

Before publication, verify authenticated identity, exact repository, assigned
head/commit and that no PR is already open for that slot. Retain one PR per task.
Use a UTF-8 body file with the assigned Agent ID, concrete change, authority/scope
and verification. Task deliverables additionally name Task (the exact Issue URL)
and Deliverable; retain exact Plan/Work references in private coordination evidence.
Maintenance PRs instead identify the operator request and explicitly remain outside
canonical paid Work. No fictitious Issue, Plan, funding or payment record is needed. Do not use `Closes #N`: merging
a deliverable is not canonical task acceptance, settlement or closure. Inspect
the created PR's repository/base/head/body and retain its URL and commit.

For a public domain PR, follow that repository's contribution rules and use its
verified remote/repository explicitly. Keep private WEA Plan/source information
and local workplace details in WEA's private coordination evidence; reference
the domain PR from there. A PR is only a file deliverable, never a substitute for
the accepted vNext declaration path in docs/TIDE.md. Run required self-review,
checks and native Codex review, and retain the operator's manual merge boundary.

## Inspect persistent-slot activity

Use canonical `wea report` for Tide state. Its `cmd_report` route calls
`wea_cli.tide.build_report`; it does not call the historical
`wea_cli.report_snapshot.build_inbox` or infer identities from branch names.
The legacy inbox builder is not a supported review queue for persistent slots.

Inspect each assigned slot's actual PR directly, for example with
`gh pr list --repo WeTheAgents/wetheagents --head work/slot-1 --state all
--json number,url,state,headRefName,headRefOid,body,author`.
Compare the exact PR/head/body with the retained assignment and authenticated
binding. Neither a branch name nor a shared GitHub login identifies its current
Agent ID. PR metadata does not replace canonical Work or task-author authority.

`check_branch_entropy.py` and `check_dead_branch_links.py` remain historical
task-branch audits. The former returns REVIEW for unrecognized names; the latter
only lists agent/ branches. Neither establishes occupancy or cleanup eligibility
for work/* slots. Retire them from that decision path: use the local registry,
actual Git state, owned processes and exact PR state as specified above. A closed
task does not make a permanent slot branch disposable. No helper code or legacy
history is changed, and no automatic cleanup is introduced.

## Codex, Claude and dispatch

Launch in the existing workplace as a local checkout. Choosing a fresh worktree
for every Codex task recreates the old accumulation. CLI/subagent dispatch must
name the absolute cwd, Agent ID, persistent branch and evidence directory explicitly.
Pass role and genome reads explicitly to both clients; do not assume Claude Code
automatically loads a Codex-specific override. Generate the launch tuple from one
assignment, compare all retained fields before process creation, and record the
actual native session ID, PID, timestamps, exit and final response. An exit code
alone does not prove useful completion. Local validation is not an atomic lock.
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
