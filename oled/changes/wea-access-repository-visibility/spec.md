# Access repository visibility Spec 1.0

Binding: accepted Outcome 1.0 (2026-10-01). This delta supersedes only the private-only intake constraint in DA-01;
DA-06/08 retain their existing readback and installation requirements with both visibility cases.
The original Access 0.5 and all recorded package/grant evidence remain historical.

- **AV-01 / DA-01:** Given the exact canonical WEA repository ID and name, when authenticated Access intake runs with `private: true` or `private: false`, the visibility check MUST accept either Boolean. Missing, null, textual or numeric visibility, a foreign ID/name, or a PR instead of the configured Issue MUST fail closed. Visibility MUST NOT substitute for issuer authority, consent, registered identity/Domain, source integrity, scope or duration checks.
- **AV-02 / DA-06:** Given either visibility and a validated journal, CLI readback MUST retain the same pending/rejected/active/expired status, source and authority evidence, interval, commit and evaluation time. Public repository reading MUST NOT grant protocol participation or GitHub permissions. Fetch/replay failures MUST remain unavailable; synthetic time MUST remain identified.
- **AV-03 / DA-08, APT-01..06:** Existing journals MUST use the accepted append-only protocol transition after reviewed manual code merge. The exact operator source MUST bind predecessor, canonical code and package hashes. Installation alone MUST NOT authorize a mismatched writer. Genesis, grants, intervals, idempotency history, old snapshots and immutable executor closures MUST remain unchanged. A retry MUST return the same update without another grant or append.

Required evidence: both actual handler visibility branches in local fixtures; negative metadata and authorization tests;
both activation/transition branches, mixed historical replay, unchanged grants and real package-update readback.
No real public visibility, credential or permission change is authorized by this delta.
