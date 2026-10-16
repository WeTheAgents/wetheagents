# Task worktrees and execution capacity

The operator's 2026-10-09 decision replaces the four persistent writing-slot
policy. Agent identity, task, checkout, branch, native process and PR are separate.
Ten to twenty tasks and open PRs may coexist. The default limit is **four actual
running executions**, configurable explicitly by the coordinator, not four PRs.
This is private local coordination; canonical WEA authority is unchanged.

## Preserve existing work

Keep the existing `D:/AgentWork/wea/workplaces.json`, persistent `work/*` branches,
worktrees, PRs and evidence intact. They are retained historical assignments.
An open or closed unmerged PR does not reserve compute. It still owns its branch
and artifacts: never reset, force-push, auto-stash, delete or repurpose its tree.
A stopped task retains its checkout for later review/resumption. Cleanup requires
separate inspection of commits, ignored/untracked evidence and owned processes.
Shared repositories under `D:/GitHub` remain Git storage roots; do not remove them.

## New task assignment

1. Read shared instructions, the assigned registered identity genome, role and
   task/handoff. Verify the session's authenticated account binding and effective
   Git author/committer. An Agent ID is not inferred from a branch or GitHub login.
2. Fetch origin, inspect `git worktree list`, and create a unique task branch from
   current `origin/main`: `codex/<task-slug>` or `claude/<task-slug>`. Never use main
   as an agent working branch or reclaim another task's branch. Use a dedicated
   isolated worktree for this task in WEA and each required domain repository.
3. Verify unused absolute destination paths, repository identity, branch/base,
   actual Git status, unfinished operations and relevant ignored files. Never
   make a checkout appear free by killing, cleaning, resetting or stashing.
4. Record task ID, existing Agent ID, WEA/domain resources, evidence directory and
   checkpoint in a **new separate** execution registry. Registering an exact
   assignment again is idempotent; changing it or sharing another task's branch
   or worktree is rejected. Identity may appear in several retained tasks; this
   does not create another identity or authorize conflicting active assignments.
5. Acquire an execution lease before a native worker starts. One writer per
   checkout, default at most four actual foreground executions across the shared
   registry. Every launcher must use the same absolute registry; separate files
   do not enforce a shared limit. Stale chats must recheck task and lease ownership.
6. Use a task-local mutable environment. Identified read-only inputs may be shared;
   never copy arbitrary ignored files or credentials. Domain Access, approved Plan,
   escrow, admission and acceptance are checked independently before funded work.

Use `git worktree lock --reason "Retained task deliverable" <path>` to protect
against pruning; this is distinct from the coordinator's writer lock.

## Coordinator and native launch

`python -m scripts.task_execution` is a standard-library local coordinator, with
native advisory file locks, atomic registry replacement and execution receipts.
Its command help defines register, run, reconcile and publication operations.
Use an explicit Python executable and module checkout, not an unrelated PATH
installation. The maintained native Codex launcher requires an explicit task,
registry and assignment; the old compatibility path forwards to it.
The launcher invokes the absolute reviewed script path so another task's older
checkout cannot shadow the selected coordinator. This helper stays outside the
fingerprinted installed `wea_cli`/`wea_vnext` packages and canonical writer boundary.

An execution supervisor retains its own PID/creation identity and direct child
PID/creation identity. It holds the worktree lease through child completion.
Actual exit releases compute while task history, branch, PR and files persist.
Do not detach native clients or background descendants from the supervised child.
A client that needs such behavior requires a separately reviewed supervisor.

After interruption, reconcile only when the owner and any recorded child are
provably dead, comparing PID **and creation identity** to detect PID reuse.
Inaccessible liveness and a crash before a child receipt remain blocked for
inspection. Never assume a timeout or unlocked file proves an orphan child died.
Reconciliation does not kill processes or alter Git. Retain old attempts and
new receipts; record session ID, model, timestamps, exit and useful result.

## Publication

Hold the shared publication lock during publication bookkeeping/push/PR creation.
The API requires `publication_lock(lease)`; CLI `publish TASK -- COMMAND` takes
both the task execution lease and global publication lock. A persistent task/
attempt marker retains orphan publication ownership after its supervisor dies;
another publisher waits until that attempt is provably finished or abandoned.
Before acting, verify the exact task, lease, registered identity, account binding,
repository, branch and commit. Configure per-worktree `remote.push-origin.pushurl`
with one verified canonical URL and check a dry run of the exact head. Use
`wea push` and `gh pr create --repo <exact-repository> --base main --head <task-branch>
--draft --title "[Task #N] <description>" --body-file <utf8-file>` for paid task
artifacts. Keep one delivery PR per task; several PRs can remain open concurrently.
Operator-assigned unpaid maintenance uses a descriptive title and explicitly
states its scope without inventing a paid task/Work.

Inspect the resulting PR repository/base/head/body and retain its exact commit.
Run self-review, relevant checks and native Codex review, fixing actionable
findings. Merges remain manual. Never use `Closes #N`: file merge is separate
from canonical Work acceptance/payment/task closure. A stopped worker's PR
requires review, not a reserved compute slot.

## Identity, roles and environment

Configure Git attribution per worktree with `extensions.worktreeConfig` and
`git config --worktree user.name/user.email`; inspect shared `core.worktree` and
`core.bare` before enabling the extension. Verify `git var GIT_AUTHOR_IDENT` and
`git var GIT_COMMITTER_IDENT`; environment overrides may take precedence.
Do not change shared identity configuration to switch agents.

Ignored `AGENTS.override.md` selectors must explicitly retain shared instructions
and name the role and genome through exact paths. Roles are at
`gunnery/agent0/roles/{agent0,worker}/AGENTS.md`. Verify selectors against the task
assignment; a selector grants no authority. Domain selectors first read that
repository's instructions and explicitly name their WEA role source. Preserve
local exclude contents and verify the selector is ignored before staging.

Dot hosts the sole Agent0 coordinator and assigns its local executor. External
Agent0 schedules stay paused; this change adds no automation or credentials.
Agent0 may coordinate multiple isolated tasks; Agent0 does not compete for worker
rewards. Local branches, registrations and locks do not create Work or Access.
Use canonical `wea report`/Tide replay for money, never local registry or PR labels.
Historical inbox/branch-entropy helpers do not establish task ownership or cleanup.
