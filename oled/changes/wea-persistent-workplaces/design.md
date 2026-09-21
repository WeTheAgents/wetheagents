# Design v3

Binding: outcome/spec v3. Supersedes v1's per-task branches and idle detached-HEAD policy. Use native linked Git worktrees and stable branches: work/agent0, work/slot-1, work/slot-2, work/slot-3. Each name is scoped to its repository. WEA has four allocated writing slots. Worker worktrees and domain checkouts remain on-demand.

Keep D:/AgentWork/wea/agent0/wetheagents, slots/slot-N/wetheagents and separately assigned domain places, individual .venv environments, external evidence under D:/AgentRuns/wea, and the manual workplaces.json registry. Git worktree lock prevents accidental removal, not concurrent writes. No scheduler or authority service is added.

After a delivery is merged and all writers are stopped, fetch origin and merge origin/main into the same clean branch. A fast-forward is preferable; an ordinary merge also connects squash/rebase merge history without rewriting it. Verify a zero tree diff against origin/main before starting the next task. Stop on conflicts, unmerged prior work or unexplained differences. Retain head/PR/source evidence. No reset --hard or force push is part of normal reuse. A closed unmerged PR requires a separate explicit reconciliation decision; the slot stays occupied meanwhile.

PR #1011 keeps codex/persistent-workplaces-20260920 until its manual merge. It occupies Agent0's slot, not a fifth slot. Once clean and synchronized, rename that local branch to work/agent0, publish it and remove only the obsolete transition ref after confirming no open PR uses it. Remote worker branches are published when needed; local reservations are not proof of dispatch. main and wea/access-journal remain service refs; tide/pending may exist for a pending batch.

Tracked role sources are agent0/roles/agent0/AGENTS.md and agent0/roles/worker/AGENTS.md. A short ignored root AGENTS.override.md explicitly reads shared AGENTS.md and the assigned role source. It does not modify tracked AGENTS.md per branch or carry copied mutable policy. For a domain, also read that repository's AGENTS.md and the WEA role source through an explicit WEA checkout path. Validate identity/role against the local registry at every start, especially after copying a checkout. Never infer authority from the selector.

Git attribution is configured per worktree. Worker setup sets WEA_AGENT for the assigned session and verifies the authenticated binding separately. Reassignment updates the selector and effective Git identity without changing the registered Agent ID. Ordinary task dispatch waits for reviewed role sources on main; the explicitly requested read-only preparation cycle can use exact local role sources before merge.

The bounded local runner retains native output and rejects assignment/prompt/cwd/branch/selector inconsistencies before launch. It is an external session tool, not a WEA command or background service. Preserve the original Claude-5 mismatch and actual slot-3 receipt; corrected assignment evidence is separate. Manual registry ownership and prior-process reconciliation remain required.

Rejected: extra task branches (operator rejected accumulation), divergent tracked AGENTS.md per branch (leaks role edits into PRs), shared writable checkout (collisions), destructive reset (risks evidence). A general allocator or atomic lease service remains outside this change. Existing-tree removal remains outside this change.
