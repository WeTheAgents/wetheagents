# Persistent workplaces

Authority: operator adoption on 2026-09-20, corrected explicitly on 2026-09-21 to persistent branches and four WEA working slots: three workers plus Agent0 with separate instructions.

| Version | Date | Decision |
| --- | --- | --- |
| 1 | 2026-09-20 | Reuse directories; fresh task branches. Superseded by v2. |
| 2 | 2026-09-21 | Reuse both directory and branch; four WEA slots and distinct Agent0 instructions. |
| 3 | 2026-09-21 | Neutral worker slots for registered Codex or Claude identities; first bounded mixed cycle. |

Current outcome v3: one persistent branch and place per slot and repository. Tasks run sequentially on that branch. WEA has work/agent0 and three neutral slots work/slot-1, work/slot-2 and work/slot-3. Registered Codex and Claude identities can occupy worker slots sequentially; occupancy does not change their identity. main, wea/access-journal and Tide's temporary transport branch are not worker slots.

Preserve identity, canonical authority, work, ignored evidence and manual merges. A fifth simultaneous WEA writing slot needs an operator decision; ordinary analysis does not need a new branch. Domains use the same branch-reuse convention in their own repositories, provisioned only when needed.

Scope: revise PR #1011, retain its current head until merge, provision the three neutral worker places, and document role selection and branch reuse. Execute the explicitly requested first cycle as four local unpaid explorations followed by Agent0 review. Preserve native receipts and correct demonstrated dispatch inconsistencies. No recurring loop is started. Old-tree deletion remains a separate retention audit.

Success: two sequential deliveries can use the same branch and path, including after squash merge; only the next change appears in the next PR diff. Agent0 and workers load distinct role instructions plus shared rules. No financial, Domain/Access, permission or product BDD change.

Rollback preserves branches and evidence. No reset, force push, historical ledger rewrite or automatic merge is introduced.
