# Design v1

Binding: outcome v1, spec v1. Use native linked Git worktrees, one stable home per Agent ID and a separate checkout per repository. WEA and domain Git databases remain distinct. Create only Agent0's WEA and Circle-1 places now; Codex-2 and Codex-19 follow the same recipe when dispatched.

D:/AgentWork/wea/<agent-slug>/wetheagents and domains/<domain-id> hold code. D:/AgentRuns/wea/<agent-slug>/<run-id> holds durable local evidence. Each checkout has its own .venv. A shared package cache may reduce downloads; mutable environments and outputs are not shared.

The local D:/AgentWork/wea/workplaces.json records places, exact Agent IDs, state and assignment. One coordinator updates it before dispatch. It is a manual handoff registry, not an atomic scheduler, OS mutex or WEA authority. Git worktree lock protects against accidental removal/pruning, not concurrent writes. Idle places use detached HEAD; they do not need published parking branches.

Use fresh branches from current origin/main for new work. Preserve an unfinished branch on resume. Domain registry revision remains immutable even when a task deliberately uses newer domain main. Record both.

Choose this over a shared writable checkout (concurrent state collisions), per-task directories (unbounded accumulation), and a new allocator/CLI (unnecessary for current manual dispatch). If manual occupancy collisions recur, propose a separate guarded launcher before adding runtime behavior.

Old worktrees and shared Git parent repositories stay in place until a dedicated retention audit. A clean Git status alone is insufficient: ignored files, session references, processes and non-pushed commits must also be accounted for.
