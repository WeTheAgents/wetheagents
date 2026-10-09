# Design

Use a standard-library Python coordinator with a private, separate JSON registry.
Place it in `scripts`, outside the installed canonical package fingerprint;
invoke its exact reviewed absolute path across older task checkouts.
Atomic replacement under native OS advisory locks protects registry updates;
per-worktree locks and a shared publication lock protect actual operations.
Publication also persists its task/attempt owner, preserving serialization when
the supervisor dies but its publishing child survives the released OS mutex.
Foreground supervisors retain process creation identity and child receipts.
Never infer running state from PR state, branch naming or Agent ID alone.
Ambiguous owner/child state requires inspection rather than optimistic recovery.

Keep existing persistent workplaces untouched. New tasks use unique branches
and isolated WEA/domain worktrees. A coordinator lease bounds expensive native
processes, not files, tasks or PRs. Native launchers must execute synchronously
inside a lease; child clients may not detach their descendants.

No new credentials, background scheduling, automatic cleanup or canonical
financial behavior. The local registry is not WEA authority.
