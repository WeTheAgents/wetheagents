# Design 1.0

Binding: Outcome 1.0 and Spec 1.0. Reuse the existing Issue, Actions workflow, native Git reader, linear append-only journal and manual merge process. No new service or dependency.

Add one record format, `wea-access-protocol-1`, stored as `protocol-<comment-id>.json`. Retain its authenticated source, acceptance time, reviewed code SHA, full package manifest, provenance and a protocol-updated receipt. The exact source starts with `<!-- wea-access-protocol -->` and names schema, previous_protocol_hash, code_sha, protocol_hash and journal_ref.

Mixed replay validates each update against the preceding package and leaves DomainAccessState unchanged. Ordinary grant decisions retain their original format. Readers verify all journal bytes and sources; live readers verify installed bytes against the latest authorized manifest only after replay. Old packages fail closed on the new record rather than silently publishing under obsolete authority.

A workflow-dispatch-only transition command reads historical state without writer authority, captures the exact operator source, verifies the new package from current canonical main, validates full proposed replay and appends through the existing writer. It checks main again before publication. The existing workflow concurrency and non-forced ref update serialize publication; three readback attempts resolve a race or lost acknowledgement. It does not process grants until the update succeeds.

A changed nonempty Access snapshot is meaningful Tide evidence even without financial changes. The first installed snapshot and later journal appends produce one checkpoint; identical snapshots alone produce no repeated batch.

Keep source identity unique across decision and update records. An exact retry identifies the original introducing commit. A forward recovery update must name the then-current predecessor and newly reviewed main package; do not roll back by force or replace genesis. No generic migration framework or mutable package pointer is needed.

Expected scope: one small pure format module, Access replay/adapter/workflow integrations and focused tests, about 200-350 production lines. Revisit beyond 500 production lines, new dependencies or any financial/executor change.

Deployment order: review and tests; publish complete PR #1008; native review until clean; retain exact code/package hashes; perform the operator-authorized manual code-only installation exception to the old writer guard; publish exact operator update source; dispatch the trusted handler; verify journal and original trips; dispatch Tide and independently validate its canonical schema-3 candidate. The old guard's installation rejection remains visible, never spoofed. Future candidates use installed guard code.

| Material state | Authority / proof | Gap and next action |
| --- | --- | --- |
| Update authority and grant preservation | APT-01..04 accepted; regression hooks planned | Implement and test before installation |
| Tide/CLI historical read boundary | APT-05 accepted; admission suites exist | Add mixed-update coverage |
| Installation and manual merges | Explicit current operator confirmation | Review exact package, then install and retain live receipts |
| Recovery and bounded scope | Append forward; existing readback/native Git | Test race, lost acknowledgement and failure boundaries; revisit above stated scope |
