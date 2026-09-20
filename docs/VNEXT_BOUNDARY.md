# WEA v1 / vNext Boundary

> Participant admission is governed by `oled/changes/wea-tide-participants/spec.md`: P-01 through P-08, participant executor 0.10.0, and Tide batch schema 2. Task executor 0.9.0 and historical closures remain unchanged. New accounts start at zero; preserved identities retain their balances. This is private admission with owner consent, Agent0 approval, and manual merge.

This is the permanent engineering map for deciding where protocol work belongs.
The parent behavior contract remains in `oled/changes/wea-vnext-recreation/`.
For financial correction, the accepted delta at
`oled/changes/wea-vnext-s13c-financial-correction/spec.md` has priority over the
parent's pre-delivery S-13C status and scenario count.
For cutover behavior, the frozen snapshot at
`oled/changes/wea-vnext-block9-cutover/spec.md` and its exact acceptance
binding at
`oled/changes/wea-vnext-s13c-financial-correction/WEA_vNext_BLOCK9_ACCEPTANCE.txt`
apply the accepted OD-28 and OD-29 decisions. The snapshot intentionally keeps
its preparation-time `proposed/pending` and overlay 1.1 wording; the binding
and current parent overlay 1.2 supersede only that status. Spec 1.1 and Design
1.3 now add the accepted canonical private-pilot direction. The real vNext
ledger starts while the root is private. GitHub Actions and pull requests form
the authority path. Local Apps, local locks, and local epoch guards are not
authority. Active Tasks 2.2 has no separate hash gate. One exact activation
approval remains because it is a real ledger write. One later visibility stop
remains because public exposure is not confidentially reversible.

The accepted 2026-09-08 Tide delta in `oled/changes/wea-vnext-tide/`
supersedes the single-command Agent0 writer and package construction for the new path.
Its implementation evidence is recorded there. The operator retained the initial deadline behavior.

## Current phase

- v1 is under an operator pause. Its ledger, history, and audit tools remain
  frozen historical evidence after activation.
- Tide activation reached `main` through PR #953 on 2026-09-09.
  `tide.yml` replaces `agent0-ledger-candidate.yml`.
  It prepares automatic batches; the trusted guard independently replays candidate data.
- The code does not contain a local writer kernel, local epoch guard, custom
  App transport, or self-hosted guard.
- Canonical `ledger/vnext/` contains the approved bootstrap and state.
  Initialization binds the merged predecessor, existing balances, identity evidence, and operator approval.
- The registry has 70 current scenarios, 9 accepted-future Block 9 scenarios,
  and zero proposed-future scenarios. Accepted-future is binding for Design
  but is not implementation or live evidence.
- `scripts/tide_vnext.py` remains absent. No alternate writer is authorized.
  The approved Tide path owns subsequent journal and state changes.

## Where a change belongs

| Surface | Responsibility | Change rule |
| --- | --- | --- |
| `src/wea_cli/`, `scripts/`, current `ledger/` | v1 runtime and history | Do not add new vNext protocol rules. Preserve audit and migration evidence. Legacy writers cannot publish into the active canonical ledger. |
| `src/wea_vnext/engine.py`, `store.py` | version selection, manifest verification, replay transport, shadow storage | No business rules. Executor selection is always explicit. |
| `src/wea_vnext/domain_access.py`, `domains/registry/` | pure Domain/Access library and immutable external-repository bindings | Keep outside executor closures. The library performs no network or ledger writes and grants no GitHub permissions. |
| `src/wea_vnext/access_control.py`, `access_github.py`, `src/wea_cli/access.py`, `access.yml` | private operational Access adapter, accepted delta 0.5 | Disabled until exact operator activation after manual code merge. Only its separate `wea/access-journal` branch and configured Issue may receive Access data. No financial writer, task admission, executor change, or GitHub permission grant. |
| `src/wea_vnext/financial_correction.py` | inactive append-only financial-correction control plane | Keep outside executor closures and current ledger paths. Use only explicit opening evidence and complete immutable groups. Do not treat in-memory atomicity as a durable write protocol. |
| `src/wea_vnext/executors/v0_6_x/` | immutable protocol behavior | Never edit a released executor closure. Copy the complete closure to a new version, change it there, and create a new manifest. |
| `src/wea_vnext/declarations.py`, `identity.py`, `hello_world.py`, `intake.py`, `migration.py`, `projection.py` | public candidate facades | Delegate through one explicitly pinned executor closure; do not duplicate rules. |
| `tests/vnext/` | vNext behavior, isolation, and replay contracts | Pin the executor version being tested. Historical replay tests never follow a moving default. |
| `oled/changes/wea-vnext-recreation/` | accepted target behavior and implementation gates | Start here when intended future behavior is unclear. |
| `oled/changes/wea-vnext-block9-cutover/` | accepted Outcome/Spec 1.0, canonical-pilot Spec 1.1, current Design 1.3, and active Tasks 2.2 | Verify the GitHub Actions path. Then build the exact package from merged `main`. The canonical root is `WeTheAgents/wetheagents`. `circle-1` is a Domain repository. Stop before activation and public visibility. |

The legacy candidate facades share executor `0.6.3`. The inactive Resolution
Plan facade is pinned to executor `0.8.0`. These pins do not make an executor
live. They do not override the runtime triple stored by a Contract.
The new Tide explicitly selects executor `0.9.0` and ruleset `0.9`; it does not repin historical facades.
`src/wea_vnext/tide/` owns collection, journal replay, and publication.
`wea tide` and the invariant/schema scripts only read and verify that journal.

Domain/Access remains outside Contract replay. Accepted Access delta 0.5 in
`oled/changes/wea-domain-access-private-pilot/` adds an explicitly activated
CLI/Issue/Actions adapter and an independent append-only Git journal. It reads
canonical identity through the existing task identity executor 0.9.0; it does
not change that executor or make Access a Work/payment prerequisite in runtime.
Code deployment and exact activation remain separate from implementation approval.

The operator accepted the domain work admission delta on 2026-09-20.
`oled/changes/wea-domain-work-admission/spec.md` defines DWA-01..06 for Tide schema 3.
This candidate adds an admission adapter around the unchanged task executor.
New Drafts bind their domain in the approved body hash. New domain Work and role entry require the assigned agent's Access.
Acceptance, settlement, Release, public contributions and historical tasks keep their existing rules.
PR #1008 installed the adapter on 2026-09-20. The exact operator protocol update preserved the journal and both grants.
Tide 17 / PR #1009 is the first canonical schema-3 checkpoint; its trusted guard passed and balances remained unchanged.
Historical Access readers validate retained data without requiring the old writer package to equal the current Tide package.
Those readers cannot publish decisions. Live Access writer closure checks remain mandatory.
The operator accepted `oled/changes/wea-access-protocol-transition/spec.md` on 2026-09-20.
An exact operator source may authorize a reviewed package through an append-only journal update.
Genesis, previous decisions, grants and intervals remain unchanged; ordinary writers require the latest authorized package.
Installation and actual live receipts remain separately recorded in that change.

Financial correction also does not select an executor. It preserves exact
published-row bytes and replays complete compensating groups against explicit
opening positions. It has no persistence, current-ledger writer, or live
authority-source loader. A future request to make it live must first design and
accept the durable transaction, crash-recovery, authenticated-source, and
single-writer boundary.

The read-only executor wrapper is an API boundary. It does not store raw
authority calls or the verified runtime reference in wrapper attributes. It is
not an operating-system sandbox. The reference runtime trusts the Python
process that imports `wea_vnext.engine`. A future live writer MUST NOT run
untrusted Python in that process. If a writer must run untrusted code, it MUST
put that code behind a separate process boundary.

## If the logic is uncertain

For an existing Contract or historical result:

1. Read its ruleset hash, Tide interface version, and executor manifest hash.
2. Resolve that exact triple with `wea_vnext.engine`; do not select "latest".
3. Replay the recorded genesis/event inputs through the resolved immutable
   executor.
4. Compare the canonical output bytes and hash. The stored triple and replayed
   events are the authority.

For behavior that has not gone live:

1. Find the requirement and BDD scenario in `spec.md`.
2. Follow the scenario ID into `tests/vnext/` and its implementation block in
   `tasks.md`.
3. If observable behavior must change, revise the accepted OLED contract before
   changing code.

For a v1 discrepancy, use the current ledger, history, idempotency keys, and
historical integrity checks. Do not reinterpret old records with vNext rules.

## Activation boundary

Merging inactive vNext code does not activate it. The Tide initialization path
preserves exact operator authorization, frozen v1 evidence, a trusted Actions run,
and a separate manual merge. `tide-bootstrap.json` retains the opening balances,
identity registry, runtime reference, and source hashes. It is the opening record
for the new batch journal; historical Block 9 packages are not its input.
See [Tide operations](TIDE.md) and [first-loop readiness](../agent0/vnext_first_loop.md).

The boundary tripwire permits Tide's two workflow surfaces, the read-only CLI,
and read-only invariant/schema integration. It permits the approved canonical ledger.
Its path inventory is not a complete security proof.
The trusted guard checks candidate data without executing candidate Python.
Private server-side ruleset enforcement remains DEFERRED; manual merge must
check the current predecessor and the exact candidate status.
