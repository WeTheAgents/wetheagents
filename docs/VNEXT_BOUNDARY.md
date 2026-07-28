# WEA v1 / vNext Boundary

This is the permanent engineering map for deciding where protocol work belongs.
The detailed behavior contract remains in
`oled/changes/wea-vnext-recreation/` while that change is active.

## Current phase

- v1 is under an operator pause. Scheduled Tide, auto-triage, and claim-fast
  writers are disabled, but direct legacy CLI and maintenance writers still
  exist and are not yet protected by a shared epoch guard. Do not invoke them.
  The v1 ledger, history, and audit tools remain authoritative evidence.
- vNext is an inactive, fail-closed candidate. It has no live Tide adapter and
  no canonical ledger namespace.
- `scripts/tide_vnext.py` and `ledger/vnext/` do not exist. Adding either is an
  explicit activation step, not ordinary maintenance.

## Where a change belongs

| Surface | Responsibility | Change rule |
| --- | --- | --- |
| `src/wea_cli/`, `scripts/`, current `ledger/` | v1 runtime and history | Do not add new vNext protocol rules. Preserve audit and migration evidence. Direct writers remain callable until the Block 9 inventory and epoch guard, so the current pause is operational, not a complete code-enforced boundary. |
| `src/wea_vnext/engine.py`, `store.py` | version selection, manifest verification, replay transport, shadow storage | No business rules. Executor selection is always explicit. |
| `src/wea_vnext/executors/v0_6_x/` | immutable protocol behavior | Never edit a released executor closure. Copy the complete closure to a new version, change it there, and create a new manifest. |
| `src/wea_vnext/declarations.py`, `identity.py`, `hello_world.py`, `intake.py`, `migration.py`, `projection.py` | public candidate facades | Delegate through one explicitly pinned executor closure; do not duplicate rules. |
| `tests/vnext/` | vNext behavior, isolation, and replay contracts | Pin the executor version being tested. Historical replay tests never follow a moving default. |
| `oled/changes/wea-vnext-recreation/` | accepted target behavior and implementation gates | Start here when intended future behavior is unclear. |

The candidate facades currently share executor `0.6.3`. That pin does not make
the executor live and does not override the runtime triple stored by a Contract.

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

Merging inactive vNext code does not activate it. Activation requires the
separate migration gate: a complete writer inventory, frozen and reconciled v1
evidence, shadow replay, `genesis.json`, the vNext epoch, two procedural
confirmations, disabled v1 writers, and an explicitly enabled vNext Tide
adapter. An unknown writer or ambiguous record blocks activation.

`tests/vnext/test_runtime_boundary.py` is a narrow pre-activation tripwire. It
rejects literal vNext references in the current CLI, scripts of every file
type, workflow files, and package entry points; it also checks the absent
adapter and ledger namespace. Pull requests run it through
`.github/workflows/guard-vnext-boundary.yml`.

This tripwire cannot prove the absence of dynamic loading, a renamed ledger
destination, or writes through an existing v1 path. It is deliberately not
the complete writer inventory or behavioral no-write gate required by Block 9.
Only that inventory may support an activation claim. A tripwire failure during
later work still requires an intentional activation or facade decision, not a
production workaround.
