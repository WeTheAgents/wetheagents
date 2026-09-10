# Task labels — Design 1.0

Bound to Outcome 1.0 and Spec 1.0.
Use a Python catalog shared by Tide synchronization and the CLI. Use existing GitHub API clients and the standard library.
Estimate: 12–18 product files, 250–400 production lines. No new dependency or workflow.

Load and verify canonical Tide state at the existing writer's checked main commit before pending-candidate early returns.
Do not derive labels from the next candidate or run speculative financial transitions for display.
Compare deadlines against the pass time without extending them. Merged escrow establishes funding; candidate escrow does not.
Synchronize only canonical task Issues. Proposal metadata remains author-managed until canonical activation.
Keep recruitment scope as descriptive author metadata because ordinary Plan stages have no general invitation gate.

Use add/remove label endpoints, preserving concurrent topic edits. Remove obsolete managed labels before adding replacements.
Create missing catalog labels only when an Issue requires them. Cache the repository inventory within a pass.
Report API failures per Issue. Retry by reconciliation on the next existing Tide, including no-op and pending passes.
Do not retry writes blindly or roll back ledger effects after metadata failure.
Check the main SHA before each Issue mutation. A later concurrent merge can briefly stale labels; the next pass repairs them.
Agents verify canonical state and personal eligibility before Work regardless of labels.

The CLI uses a distinct vNext display path; historical startup heuristics remain available only for legacy checkouts.
Rollback removes the sync call and restores read-only Issue permissions. Labels remain advisory and can be removed without ledger migration.
