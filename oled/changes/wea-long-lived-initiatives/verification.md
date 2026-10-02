# Long-lived initiatives: Verification

Bindings: Outcome 0.2, Spec 1.0, Design 1.0. Candidate implementation; no production installation or activation.

## Actual checks

- Full scoped run: 219 passed in 544.89 seconds. Exit 0.
- Modules: test_initiatives, test_access_runtime, test_access_protocol_transition, test_tide_domain_admission, test_tide_replay, test_tide_ledger.
- The same run includes scenario registry, runtime boundary, and Domain registry checks.
- Repository-reference completion receives a separate focused run, retained in references-tests.log.
- Ruff and doc-sync pass. Canonical Tide 22 replay passes: opening supply 19025, escrow 0, balances plus escrow 19025.
- Evidence directory: D:/AgentRuns/wea/agent0/20261002-long-lived-initiatives-implementation/.

| Scenario | Actual test hooks | Result |
| --- | --- | --- |
| LRI-01 | default_steward_activation; invalid_source; readonly_cli; new_draft_requires_active_registered_steward | PASS |
| LRI-02 | evidence_and_task_link_are_metadata; manual corpus below | PASS for record and review boundaries |
| LRI-03 | exact_handoff_consent_and_previous_steward; operator_resolution_still_needs_new_consent | PASS |
| LRI-04 | registry_revisions_rename; repository_id_read_failure_and_locator_reuse; missing_context_revision; reference_revision | PASS; focused reference result retained separately |
| LRI-05 | lifecycle_has_no_repository_or_obligation_effect; vacancy_blocks_new_participation; old_funded_work_and_acceptance_survive_archive; new_draft | PASS |
| LRI-06 | binding_a_never_authorizes_binding_b; delayed_legacy_body_and_global_cross_domain_overlap | PASS |
| LRI-07 | exact_retry_conflict; metadata_does_not_create_tide_batch; activation_gate; lost_response_readonly_failure; concurrent_winner | PASS |

Historical mapping: R-11/S-11A gain immutable registry revisions and exact binding scope after activation.
S-11B and DA-04/06 retain seven-day intervals and global overlap. DA-01/08 retain authenticated authority and protected effects.
APT-02/05/06 retain exact package transitions, complete prefixes, and readonly recovery. Metadata filtering is the explicit future APT-05 delta.
DWA-01/02/03/05 gain binding checks outside released executors. DWA-04/06 and financial contracts remain unchanged.
Current 70 scenario IDs remain unchanged. LRI-01..07 join the exact accepted-future registry and match the accepted Spec headings.

## LRI-02 manual evidence review

The review inspects reports/circle1-access-wta/result.md and the synthetic EVIDENCE record in test_initiatives.py.
The retained result identifies scanner revision 36a71440840351aa462e61a8ad5955881f55ecb0, funded base, method, exact source notes, and limitations.
Its before/after parser observation informs an actual installed correction through Task #997 and PR #1001.
This is downstream use of that historical result. It does not prove adoption of a future LRI initiative or Task #1016 proposals.
The zero-file counterexample is synthetic fixture evidence. It is not a new live scanner measurement.
The fixture names its input, method, result, limits, and references. Its empty downstream_use list asserts no adoption.
Separate sessions and submissions under the shared account do not establish independent ownership or replication.
The negative forms are activity counts alone, a result without a method, and independence without common-control evidence.
The review identifies their missing support. None creates useful-progress proof, funding, acceptance, or payment authority.
Scientific usefulness remains a participant judgment. The runtime preserves structured evidence and creates no automatic numerical incentive.

## Delivery gates

Self-review checks source authority, exact predecessors, repository ID and pinned commit, immutable grants, historical scope, and global interval admission.
The implementation adds no dependency, service, authoritative journal, financial writer, credential, repository permission, or background worker.
The operator-appointed Circle-1 Domain Steward remains unchanged. Initiative succession creates only coordination responsibility in its explicit scope.
Installation, exact package transition, policy activation, public opening, and repository creation require separate decisions.
The protected-package guard remains enforced. A draft installation CI rejection is not waived by this implementation approval.
Draft publication, native review, and CI results remain pending at this pre-publication checkpoint.
