# Persistent workplaces

Authority: operator adoption on 2026-09-20, corrected explicitly on 2026-09-21 to persistent branches and four WEA working slots: three workers plus Agent0 with separate instructions.

| Version | Date | Decision |
| --- | --- | --- |
| 1 | 2026-09-20 | Reuse directories; fresh task branches. Superseded by v2. |
| 2 | 2026-09-21 | Reuse both directory and branch; four WEA slots and distinct Agent0 instructions. |

Current outcome v2: one persistent branch and place per assigned Agent ID and repository. Tasks run sequentially on that branch. The WEA roster is agent0@system, Codex-2@codex, Codex-19@codex and Codex-20@codex. main, wea/access-journal and Tide's temporary transport branch are not worker slots.

Preserve identity, canonical authority, work, ignored evidence and manual merges. A fifth simultaneous WEA writing slot needs an operator decision; ordinary analysis does not need a new branch. Domains use the same branch-reuse convention in their own repositories, provisioned only when needed.

Scope: revise PR #1011, retain current PR head until merge, reserve three worker branches locally, install Agent0's local role selector, document branch reuse and verification. Worker worktrees/environments remain on-demand after old-session reconciliation. No workers or loops are launched. Old-tree deletion remains a separate retention audit.

Success: two sequential deliveries can use the same branch and path, including after squash merge; only the next change appears in the next PR diff. Agent0 and workers load distinct role instructions plus shared rules. No financial, Domain/Access, permission or product BDD change.

Rollback preserves branches and evidence. No reset, force push, historical ledger rewrite or automatic merge is introduced.
