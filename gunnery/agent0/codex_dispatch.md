# Native Codex task dispatch

Follow [task worktree and execution coordination](../../docs/WORKPLACES.md).
The operator's 2026-10-09 policy supersedes historical persistent-slot recipes.
Do not restart external Agent0 schedules or copy credentials between checkouts.

Use `gunnery/agent0/dispatch_codex_worker.ps1` with explicit Identity, TaskId,
RegistryRoot (one shared absolute directory), Worktree, Branch, PythonExecutable,
CodexExecutable (native codex.exe), PromptFile, stable TaskEvidenceDir, new RunDir
and Name. This WEA launcher validates the canonical origin repository. GenomeRoot
may name the assigned WEA checkout. Set WEA_AGENT in the existing session or
existing task-local environment; no launcher creates credentials or identity.
Resource accepts extra JSON [repository, branch, absolute worktree] bindings.
All mutable WEA/domain checkouts must be included in the assignment.
The launcher passes registered domain resources as Codex `--add-dir` arguments
in workspace-write mode; read-only preparation keeps resources read-only.

Default Sandbox is workspace-write; read-only preparation uses read-only.
The launcher has no danger-full-access mode or automatic permission escalation.
The operator's authorization, funding/Access checks and agreed checkpoint must
already be satisfied; registration or branch reservation alone is insufficient.

The launcher verifies the Git root/branch, identity and genome; rejects dirty
or inaccessible paths unless AllowDirty is explicitly selected; rejects reused
evidence directories; and registers immutable assignment before dispatch.
Its fixed supervisor loads JSON, opens the prompt as stdin and executes the
native Codex binary directly inside the coordinator's foreground lease. It
retains launch.json, events.jsonl, stderr.log, result.md and exit.json. Read the
actual task attempt receipt for child PID/creation identity and capacity state.
The outer PowerShell PID alone does not prove a model client started or finished.

Pass explicit shared instructions, role, genome, task/Plan, input paths and
checkpoint in the prompt. Do not detach workers or background descendants.
After interruption, reconcile proven-dead processes and inspect ambiguous
launches. Native session/model/result evidence is necessary alongside exit code.
Old runbook examples remain available through Git history; they are not launch
instructions. A persistent Agent ID can receive multiple isolated task assignments.
