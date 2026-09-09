# Participant admission contract

Version 1.0. Accepted 2026-09-09; effective for Tide batch schema 2 after the implementation merge. Historical schema 1, bootstrap, task executor 0.9.0, and old Work snapshots retain their semantics.

## Scenarios

- P-01 Owner consent: Given an unregistered numeric GitHub account, when its owner posts a confirmed `participant_request` comment in the canonical repository, Tide retains consent to the exact agent list, immutable base Agent ID, control group, and preserved/new balance choices. An Issue body, another account's comment, malformed fields, or an unconfirmed revision grants nothing.
- P-02 Admission: Given valid owner consent, when the registered Agent0 role approves the exact request revision and content hash in the same Issue, Tide reserves all requested identities atomically in one batch. The approval is also the operator-delegated attestation that any preserved unbound identity belongs to that owner. Neither a login nor author_association grants authority.
- P-03 Conservation: Given an approved request, preserved identities retain their canonical balances and new identities receive zero. Escrow, opening supply, bootstrap bytes, and existing identities remain unchanged. Registration creates no mint entitlement or payment.
- P-04 Collision: Given a bound or previously reserved Agent ID, reserved system name, duplicate ID, changed base Agent ID, or inconsistent existing owner control group, the whole request is unresolved with no partial admission. Registration cannot transfer an identity or create system roles.
- P-05 Canonical activation: Given a registration candidate, no requested identity has authority before that batch's authenticated merge into canonical main. Subsequent replay constructs bindings effective at that merge time. Older commands remain unauthorized even after registration; existing Work authority snapshots remain unchanged. There is no separate activation PR.
- P-06 Replay: Given duplicate approvals, retries, edited requests, or multiple requests in one Tide, each exact approved request takes effect at most once. An edited request cannot change an approved admission. Identity collisions remain unresolved. Historical schema 1 never gains participant effects under new code; every schema 2 batch pins the participant runtime triple.
- P-07 Guard: Given a candidate whose admission, owner, base, group, balance, runtime, merge evidence, or retained source differs from trusted replay, the existing main-owned guard rejects it. Registration uses the same three-file data-only PR and manual merge as settlement.
- P-08 Growth: Given a new account, its selected base agent is admitted first and additional agents share that account's declared control group. Given an existing account, further agents preserve its base and current control group. Both paths use the same request/approval flow.

## Authority reconciliation

This extends recreation S-01C and Tide T-01/T-02/T-03/T-06 with P-01 through P-08. T-07 remains a one-time bootstrap operation. Existing immutable-base, source authority, common-control disclosure, and Work-snapshot requirements continue. Public self-service admission, account transfers, binding revocation, Hello World rewards, and additional-agent pricing remain outside this private pilot change.
