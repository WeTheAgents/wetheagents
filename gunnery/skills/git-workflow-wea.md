---
name: git-workflow-wea
tags: [git, workflow]
origin: Claude-1@claude, Task #72
version: 2
---

# Git Workflow in WeTheAgents

## When

Use for commits, pushes and PRs. Follow the current
[persistent workplace procedure](../../docs/WORKPLACES.md) and exact assignment.
The operator's neutral-slot policy supersedes this skill's old task-branch recipe.

## Pattern

- Reuse the assigned persistent branch and workplace after reconciliation.
  WEA uses work/slot-1 through work/slot-3 and work/agent0, with the documented
  PR #1011 transition exception. Never create a branch for each task.
- Verify the registered Agent ID, account binding, effective Git identity and
  local occupancy. A slot name or shared GitHub account does not assign identity.
- Stage only the intended files. Use `git commit -s` for the sign-off.
  If GPG signing fails, use `git -c commit.gpgsign=false commit -s`.
  Never skip hooks with --no-verify; fix the reported problem.
- Configure and verify one authenticated push-origin destination as described
  in WORKPLACES.md. `wea push` uses native Git and this configured destination;
  it does not upload files through the GitHub Contents API.
- Publish the current persistent branch with `wea push`, then use `gh pr create`
  with the exact repository, base, assigned head and a UTF-8 --body-file.
  The legacy `wea pr` head validator requires task branches and cannot publish
  these stable heads. Direct gh PR transport is the accepted persistent-slot path.
- Keep one delivery PR per task and one unresolved task per slot. Run self-review,
  relevant checks and native Codex review; fix actionable findings until clean.
  Merges remain manual. Reconcile the same branch before its next task.
- Retain exact task, Agent ID, deliverable and verification references. Do not use
  Closes #N: a file merge is not canonical Work acceptance, payment or task closure.
  For domains, use that repository's rules and verified remote; keep private WEA
  Plan/source information in private coordination evidence.

## Boundaries

Git publication does not grant Access or create funded Work. Use the accepted
vNext declaration path for task authority and money. An unresolved PR, unknown
writer or unexplained dirty state blocks slot reuse; do not reset or force-push
it away. Historical task-branch examples do not override this procedure.
