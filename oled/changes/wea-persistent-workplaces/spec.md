# Workplace operating contract

| Version | Date | Authority |
| --- | --- | --- |
| 1 | 2026-09-20 | Initial adoption; fresh-task-branch rule superseded. |
| 2 | 2026-09-21 | Operator correction: four WEA working branches, persistent across tasks, separate Agent0 instructions. |
| 3 | 2026-09-21 | Operator-approved neutral worker slots; bounded mixed CLI dispatch. |

Effective version 3, bound to outcome v3. This is an operating procedure with bounded local launch checks, not a repository-enforced allocator.

- PW-1: A new task reuses the assigned free workplace and persistent branch after reconciliation with fetched origin/main. Given two completed sequential tasks, branch name, path and environment remain the same; the next PR diff contains only the next task.
- PW-2: Dirty, occupied or suspended work blocks reuse. Given an unfinished PR or old session still writing, no unrelated task starts on that branch. Preserve it instead of resetting, cleaning or force-pushing. Reconcile old places for the same identity before first dispatch.
- PW-3: Completion retains commits, untracked/ignored evidence and session references. Given required evidence only in an old checkout, remote backup is insufficient for deletion. A closed unmerged PR requires explicit reconciliation, not treatment as merged.
- PW-4: Domain repository identity, immutable registry revision and task base remain distinct. A workplace gives no Access, Work, funding, acceptance, Release or GitHub authority.
- PW-5: Start checks compare occupancy, actual Git state, effective author/committer and authenticated binding. Manual checks apply even to resumed chats; no lock service is claimed.
- PW-6: Exactly four WEA writing slots are allocated: work/agent0 and work/slot-1 through work/slot-3. Worker slots accept registered Codex or Claude identities sequentially. A request for another concurrent writer waits or returns to the operator; it does not silently create a task branch. Service refs are excluded from this slot count.
- PW-7: Agent0 loads the coordinator AGENTS.md; the three workers load the worker AGENTS.md and their own genomes. Both retain shared repository rules. No role profile or copied local selector can replace verified identity or canonical authority.

- PW-8: Given a disagreement between the assignment, prompt, selector or actual cwd/branch, dispatch stops before process creation. Retain historical faulty receipts; correct future assignment data without rewriting past evidence. This local check does not replace manual prior-process reconciliation or canonical authority.

Existing Domain/Access and Tide scenarios are unchanged. No new wea command or canonical state transition is introduced.
