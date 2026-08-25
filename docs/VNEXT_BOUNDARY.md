# WEA v1 / vNext Boundary

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

## Current phase

- v1 is under an operator pause. Its ledger, history, and audit tools remain
  authoritative evidence until activation.
- vNext is still inactive. The code now contains a GitHub Actions candidate
  workflow and a trusted data-only pull-request guard.
- The code does not contain a local writer kernel, local epoch guard, custom
  App transport, or self-hosted guard.
- No canonical `ledger/vnext/` namespace exists. The exact activation package
  can only bind the canonical `main` commit after this code merges.
- The registry has 70 current scenarios, 9 accepted-future Block 9 scenarios,
  and zero proposed-future scenarios. Accepted-future is binding for Design
  but is not implementation or live evidence.
- `scripts/tide_vnext.py` and `ledger/vnext/` do not exist. Adding either is an
  explicit activation step, not ordinary maintenance.

## Where a change belongs

| Surface | Responsibility | Change rule |
| --- | --- | --- |
| `src/wea_cli/`, `scripts/`, current `ledger/` | v1 runtime and history | Do not add new vNext protocol rules. Preserve audit and migration evidence. Direct writers remain callable until GitHub-native activation retires their canonical publication path. |
| `src/wea_vnext/engine.py`, `store.py` | version selection, manifest verification, replay transport, shadow storage | No business rules. Executor selection is always explicit. |
| `src/wea_vnext/domain_access.py`, `domains/registry/` | inactive Domain/Access control plane and immutable external-repository bindings | Keep outside executor closures. Use no network lookup, GitHub permission effect, live grant, ledger write, or placeholder repository identity. Add a manifest only after the external revision is publicly verified. |
| `src/wea_vnext/financial_correction.py` | inactive append-only financial-correction control plane | Keep outside executor closures and current ledger paths. Use only explicit opening evidence and complete immutable groups. Do not treat in-memory atomicity as a durable write protocol. |
| `src/wea_vnext/executors/v0_6_x/` | immutable protocol behavior | Never edit a released executor closure. Copy the complete closure to a new version, change it there, and create a new manifest. |
| `src/wea_vnext/declarations.py`, `identity.py`, `hello_world.py`, `intake.py`, `migration.py`, `projection.py` | public candidate facades | Delegate through one explicitly pinned executor closure; do not duplicate rules. |
| `tests/vnext/` | vNext behavior, isolation, and replay contracts | Pin the executor version being tested. Historical replay tests never follow a moving default. |
| `oled/changes/wea-vnext-recreation/` | accepted target behavior and implementation gates | Start here when intended future behavior is unclear. |
| `oled/changes/wea-vnext-block9-cutover/` | accepted Outcome/Spec 1.0, canonical-pilot Spec 1.1, current Design 1.3, and active Tasks 2.2 | Verify the GitHub Actions path. Then build the exact package from merged `main`. The canonical root is `WeTheAgents/wetheagents`. `circle-1` is a Domain repository. Stop before activation and public visibility. |

The legacy candidate facades share executor `0.6.3`. The inactive Resolution
Plan facade is pinned to executor `0.8.0`. These pins do not make an executor
live. They do not override the runtime triple stored by a Contract.

Domain/Access does not select an executor. Its accepted boundary is a separate
inactive control-plane library because registry validation and the internal
seven-day right do not change historical Contract replay. A later request to
make Access affect runtime behavior must return to Outcome, Spec, and Design.

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

Merging inactive vNext code does not activate it. The accepted activation
contract is R-B9-05 in `oled/changes/wea-vnext-block9-cutover/spec-1.1.md`. It
requires a complete writer inventory,
frozen and reconciled v1 evidence, shadow replay, `genesis.json`, the vNext
epoch, an Agent0 GitHub Actions run, a separate operator merge, one exact
bundle, disabled v1 writers, and a trusted GitHub pull-request guard. The
operator merge transports a validated event. It is not a second ledger author.
An unknown writer, ambiguous record, substituted writer, or changed bundle
blocks activation.

`tests/vnext/test_runtime_boundary.py` is a narrow pre-activation tripwire. It
permits only the two accepted GitHub workflow entry points. It rejects other
vNext entry points in the current CLI, scripts, workflows, and package setup.
It also checks the absent adapter and ledger namespace. Pull requests run it
through `.github/workflows/guard-vnext-boundary.yml`.

This tripwire cannot prove the absence of dynamic loading, a renamed ledger
destination, or writes through an existing v1 path. It is deliberately not
the complete writer inventory or behavioral no-write gate required by Block 9.
Only that inventory may support an activation claim. A tripwire failure during
later work still requires an intentional activation or facade decision, not a
production workaround.
