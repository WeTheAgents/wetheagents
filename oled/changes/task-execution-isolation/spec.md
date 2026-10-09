# Observable contract

- Register twenty tasks with unique immutable task/worktree/branch assignments;
  retaining their open PRs does not consume any execution capacity.
- No more than four foreground execution leases run by default. A completed
  process releases capacity and preserves its task, attempts and deliverables.
- Reject duplicate worktree or repository/branch allocations and simultaneous
  writers. Repeat registration is idempotent only for the exact assignment.
- Registry updates and publication are serialized by native advisory locks.
- Reconcile demonstrably dead owners/children using PID plus creation identity.
  Unknown liveness and interrupted child receipt fail closed; never kill a
  process, delete a worktree or reset Git during recovery.
- An execution holds its resource locks throughout foreground child lifetime.
  Detached descendants are unsupported and forbidden by launch instructions.
- Existing legacy registry is retained as historical evidence, not imported by
  destructive migration. Canonical funding and manual merge rules are unchanged.

Verification maps each scenario above to focused coordinator tests and checks
the documentation/launcher integration in independent review.
