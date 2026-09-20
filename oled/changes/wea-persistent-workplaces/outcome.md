# Persistent workplaces

Authority: the operator requested adoption for WEA and domains on 2026-09-20, after reviewing the permanent-workspace concept. This authorizes a local workflow change, not protocol changes or automatic merges.

Outcome v1: reuse a stable, isolated workplace for each active Agent ID and repository. New tasks use fresh branches without multiplying directories. Create places on demand. Preserve existing work, evidence and canonical authority.

Observed: 115 registered WEA worktrees and four Circle-1 worktrees before setup; these counts include historical registrations, not a claim that every directory exists. Remote branch cleanup did not remove local trees.

Scope: instructions, local Agent0 bootstrap and manual reuse rehearsal. Worker places are provisioned on first dispatch. Existing-tree removal is a separate inventory-and-retention pass. No custom allocator, daemon, automatic cleanup, Access grant, Work, payment or protocol BDD change.

Success: two sequential branches use the same path and environment in each repository; worktree counts do not grow during reuse. Local occupancy and durable evidence paths remain inspectable.

Rollback: stop reusing places and retain their contents. No historical ledger or domain revision is rewritten.
