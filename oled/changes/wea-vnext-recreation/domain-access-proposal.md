# WEA vNext: Domain and Access decision record

Status: `approved with architecture correction on 2026-08-15`.

The operator approved the Domain registry, internal Access, fixed expiry, and
external Circle-1 decisions. The operator rejected a narrow successor
reference runtime. The accepted contract is now in `outcome.md`, `spec.md`, and
`design.md`. Those files are authoritative.

## Accepted decisions

1. The first Domain is a real public external Circle-1 repository.
2. WEA binds a Domain to a permanent repository ID, an audit locator, and one
   full commit SHA in a canonical immutable manifest.
3. Access is an internal WEA right. It does not grant, revoke, or inspect a
   GitHub permission.
4. Only an operator or Agent0 source can grant Access.
5. Access lasts exactly seven days in a half-open interval.
6. One Agent ID cannot hold overlapping Access across any Domains.
7. This cut has no early revoke, renewal, extension, suspension, or transfer.
8. Circle-1 owns portable scanner code and canon. WEA retains target profiles,
   checkpoints, director operations, task-index work, and ledger work.
9. The Domain registry and Access state are an inactive control-plane module
   outside all immutable executor closures.
10. The existing ruleset `0.8`, Tide interface `0.8`, executor `v0_8_0`, and
    all 67 current Spec `0.9` scenario proofs remain byte-for-byte unchanged.
11. S-13C financial correction is a separate OLED change and a separate PR.

## Rejected proposal

The earlier draft proposed one combined ruleset `0.9` / executor `v0_9_0`
closure for S-11A, S-11B, and S-13C. That proposal is rejected. It would copy a
large immutable runtime without a runtime behavior dependency and would couple
Access to a protected money-write boundary.

No successor runtime, ruleset, facade, financial correction module, or live
writer belongs in this delivery.

## BDD impact

- Baseline: 67 current scenarios and three accepted-future scenarios.
- The external Circle-1 repository exists, its public default-branch revision
  is pinned, the WEA registry manifest verifies, and the focused Access
  evidence passes.
- S-11A and S-11B are current control-plane scenarios.
- S-13C is the only accepted-future scenario.

## Current execution state

- The public Circle-1 repository is committed at
  `36a71440840351aa462e61a8ad5955881f55ecb0`.
- Its permanent repository ID is `R_kgDOT4-F-Q`.
- The external suite passes: 215 passed and 9 explicit WEA integration skips.
- The WEA black-box scan, Ruff, and Pyright pass.
- `domains/registry/v1.json` binds the exact public ID, locator, revision,
  record hash, and registry hash.
- The WEA registry validator and Access state machine pass their focused tests.
- S-11A and S-11B are effective in the inactive control plane. No live writer,
  GitHub permission effect, ledger write, bootstrap, or cutover exists.

## Publication state

The external prerequisite and implementation are complete. Fresh full checks,
independent review, and the WEA PR remain the publication gates. S-13C starts
only as a separate OLED change after the Domain/Access PR merges.
