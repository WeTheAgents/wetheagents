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
- This delivery can promote S-11A and S-11B only after the external Circle-1
  repository exists, its public default-branch revision is pinned, the WEA
  registry manifest verifies, and the focused Access evidence passes.
- S-13C remains the only accepted-future scenario after that promotion.
- Until the external prerequisite passes, the scenario registry remains at
  67 current and three accepted-future scenarios.

## Current execution state

- The extracted Circle-1 repository is locally committed at
  `c538fba593d9aae06c3f60b9721b821118d8dafb`.
- The external suite passes: 215 passed and 9 explicit WEA integration skips.
- The WEA black-box scan, Ruff, and Pyright pass.
- Both configured GitHub identities can read `WeTheAgents`, but neither token
  can create `WeTheAgents/circle-1`. The public repository, permanent
  repository ID, and remote commit are therefore unavailable.
- The WEA registry validator and Access state machine pass 20 focused tests.
- `domains/registry/v1.json` is intentionally absent. No placeholder identity
  or unverified revision is accepted.
- S-11A and S-11B remain non-effective until the external gate passes.

## Exact unblock action

An organization owner must create the empty public repository
`WeTheAgents/circle-1` or grant repository-create permission to the configured
publishing identity. The prepared local repository can then push `main`.

After the push, execution must read the permanent repository node ID and the
full default-branch commit SHA from GitHub, generate the canonical WEA registry
manifest, run the complete gates, and only then promote S-11A and S-11B.
