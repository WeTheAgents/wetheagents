# External repository observation: Spec 1.0

Bound to Outcome 1.0; implementation refinement of IR-04/LRI-04 and IR-06/LRI-07 in wea-long-lived-initiatives. No pure replay rule, journal schema, financial scenario or released executor changes.

| Requirement | Observable evidence |
| --- | --- |
| ER-01: external reads use a distinct bounded reader; canonical writes remain restricted | Real transport exact GET/fixed GraphQL and canonical external-path refusal tests |
| ER-02: locators, permanent identity aliases and context commits remain bound | Input attacks make zero requests; invalid metadata/node/object/SHA fail; retained LRI alias/reuse cases |
| ER-03: failed required read prevents append and exposes no secret | 401/403/404, redirect, timeout, excessive/invalid JSON groups; process head/writes unchanged |
| ER-04: preflight and exact retry preserve existing source semantics | Unauthorized source zero external reads; exact retry no new observation or append |
| ER-05: a separate read-only preflight can prove visibility before source publication | Same identity/commit methods, exact execution SHA and nonsecret credential-source label; no writer/journal/receipt call; CLI rejects write modes |
| ER-06: credential selection never replaces canonical writer credentials | Optional WEA_DOMAIN_READ_TOKEN goes only to reader; absent secret uses existing GITHUB_TOKEN; preflight and run separation tests |
| ER-07: history/installation remain protected | No pure replay, guard or executor edits; existing Access/initiative/APT regression and independent review |

Canonical HTTPS GitHub locator and full 40-hex revision validation reuse DomainRecord. The reader does not create permission or substitute local evidence for failed authoritative reads. Preflight rejects incomplete or mixed write inputs before network, and its workflow job has only contents-read permissions. Normal reconciliation excludes any preflight input.
