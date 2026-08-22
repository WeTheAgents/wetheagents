# Spec: WEA vNext Block 9 Cutover

## Version log

| Version | Date | Status | Change |
| --- | --- | --- | --- |
| 1.0 | 2026-08-16 | proposed | Define the observable cutover gates from the accepted owner decisions. |

Spec version: `1.0`

Status: `proposed for operator review; not implemented; not live`

Implements outcome version: `1.0`

Preparation authority: the WEA operator requested Block 9 BDD on 2026-08-16.
Exact Outcome/Spec acceptance is pending.

Decision payload SHA-256: `100957844bcf3e9a1207ba95c2225acc74d3fb292a2684bd257a7ea7094a1c9e`.

Derived business-decision record:
`../wea-vnext-s13c-financial-correction/WEA_vNext_ACCEPTED_DECISIONS.txt`.
It is deterministic and source-bound, but it is not standalone authenticated
operator evidence. It does not approve the later S-71 through S-79 wording.

Proposed behavior scope: Block 9 Design and a later rehearsal and cutover.
The Design direction is authorized in principle, but Design against this exact
BDD waits for operator acceptance. The current v1 system remains authoritative.

Unchanged behavior: WEA vNext Spec 1.0, S13C Spec 1.1, and all 70 current
scenario IDs remain unchanged.

## ADDED Requirements

### Requirement R-B9-01: Complete writer boundary

The cutover gate MUST classify every v1 writer as `replace`, `disable`, or
`historical-read-only`. The inventory MUST bind to an independently derived,
frozen universe of write-capable entrypoints, workflows, maintenance scripts,
credentials, schedules, transaction helpers, and documented manual paths.

An unknown, ambiguous, omitted, or newly added writer MUST block cutover. A
writer that bypasses the shared epoch guard MUST block cutover.

#### Scenario S-71: An omitted or unsafe writer blocks cutover

- **GIVEN** a candidate writer inventory and an independently derived frozen
  writer universe.
- **WHEN** the system evaluates the cutover gate.
- **THEN** the gate rejects an unknown, ambiguous, omitted, late-added, or
  epoch-bypassing writer and creates no bootstrap or ledger record.
- **EVIDENCE** Planned `tests/vnext/test_block9_writer_gate.py` proves complete,
  unknown, omitted, late-added, bypass, and delayed-writer cases.

### Requirement R-B9-02: Complete v1 obligation reconciliation

Each unfinished v1 Issue MUST have exactly one outcome: `settle-v1`,
`stop/refund`, `convert-with-fresh-approval`, or `historical-close`.

`historical-close` MUST NOT hide an escrow, payment, refund, or other financial
obligation.

`convert-with-fresh-approval` MUST create only an immutable conversion intent
before cutover. The v1 task and escrow MUST close completely, with the required
refund or settlement, before genesis.

The intent MUST bind its deterministic ID, source Issue and exact source
revision/hash, v1 settlement or refund record/hash, author and payer as the
same exact Agent ID, that Agent's authenticated account and authority binding
ID/version/hash/effective interval, complete target Plan revision/hash and all
Plan fields, complete Plan bank, Triage revision, ruleset identity, runtime
triple, approval source/revision/hash, issue time, expiry time, and one
idempotency key. The approval MUST be an authenticated act by that Agent
through the bound account. A hash generated from public identity fields is not
approval evidence.

The intent state MUST be `pending`, `consumed`, `cancelled`, or `expired`. Only
`pending` can activate. Activation MUST occur inside the validity interval with
the exact authority binding still active. Consumption, cancellation, and expiry
are terminal.

After the vNext epoch starts, one idempotent activation MAY use the exact fresh
approval to debit the author-payer once and atomically create the program
escrow, Plan, Task, and first child Contract under the unchanged current Plan
activation contract. Genesis MUST NOT contain an active converted Plan, Task,
child Contract, or replacement program escrow. Stale approval, authority
rotation, expiry, insufficient funds, or a retry conflict MUST create none of
those effects. Insufficient funds MUST cancel the intent permanently. A later
balance increase MUST NOT revive it. One obligation MUST NOT have v1 escrow
and vNext program escrow at the same time.

The cutover gate MUST reject active escrow, a pending payment, an unexplained
amount, an unlinked task record, or an Issue with zero or multiple outcomes.

#### Scenario S-72: Every v1 obligation has one complete outcome

- **GIVEN** a reconciliation of Issues, task indexes, escrow, pending payments,
  ledger history, and idempotency keys.
- **WHEN** the system evaluates each unfinished Issue and each system record.
- **THEN** every record has one basis and every Issue has one outcome. For each
  funded obligation, deposited escrow equals payments plus refunds.
- **THEN** any missing basis, amount mismatch, active escrow, or pending payment
  rejects the candidate.
- **EVIDENCE** Planned `tests/vnext/test_block9_reconciliation.py` proves every
  outcome, conversion intent, refund then atomic Plan activation, retry, stale
  approval, and no dual escrow. It also proves payload mutation, expiry,
  authority rotation, author/payer mismatch, synthetic approval, direct-Contract
  rejection, insufficient-funds cancellation, later balance changes, and
  intent reuse.

### Requirement R-B9-03: Canonical genesis

Genesis MUST preserve the exact Agent IDs, balances, genomes, identity
bindings, used Hello World keys, historical references, and calculated opening
supply from the frozen cutover state. It MUST preserve pending conversion
intents as non-financial records. It MUST NOT create converted Plans, Tasks,
child Contracts, or replacement program escrow.

Genesis MUST treat historical v1 mint as audit metadata. It MUST NOT add that
mint to the calculated opening supply again.

#### Scenario S-73: Genesis and replay recreate one state

- **GIVEN** a frozen and reconciled v1 state with its exact evidence hashes.
- **WHEN** the system builds genesis and replays genesis plus all vNext events.
- **THEN** both runs produce the same canonical bytes, IDs, balances, and
  derived state.
- **THEN** a stale historical checkpoint or changed source hash rejects the
  candidate.
- **EVIDENCE** Planned `tests/vnext/test_block9_genesis.py` proves exact rebuild,
  source binding, opening supply, and stale-snapshot rejection.

### Requirement R-B9-04: Read-only shadow proof

Shadow replay MUST create no ledger, GitHub, credential, or protocol-state
write. Each report MUST bind the input boundary, rule hash, input hash, and
output hash.

#### Scenario S-74: Shadow replay is repeatable and has no live effect

- **GIVEN** one frozen input boundary and one verified runtime reference.
- **WHEN** the system runs the shadow replay twice.
- **THEN** both reports have the same canonical output and the live state stays
  byte-identical.
- **THEN** any output mismatch or incomplete input blocks cutover.
- **EVIDENCE** Planned `tests/vnext/test_block9_shadow.py` proves repeatability,
  no-write behavior, and mismatch rejection.

### Requirement R-B9-05: Atomic single-writer cutover

The operator and Agent0 MUST approve the same exact cutover bundle. Each
approval MUST come from separate authenticated immutable source evidence. It
MUST bind an exact source identity, source revision, and active authority
binding. A caller-supplied role label is not approval evidence.

The bundle MUST bind the frozen v1 state, inventories, reconciliation, genesis,
shadow proof, runtime reference, and GitHub boundary. It MUST also bind the
exact canonical bootstrap bytes/hash, target epoch ID, expected ledger
predecessor, expected post-transition state hash, and the sole vNext writer,
whose Agent ID MUST be exactly `agent0@system`.

The writer binding MUST include the exact `agent0@system` Agent ID,
authenticated identity, credential binding ID/version/hash, and effective
interval. Any other writer Agent ID MUST reject. The bundle MUST bind the
version and hash of each durable recovery implementation required by R-B9-08.

The cutover MUST create all authoritative epoch and ledger bootstrap effects or
none. External projections follow R-B9-09 and are not part of this transaction.
The first vNext ledger record MUST make every v1 writer ineffective. A
dual-write period is forbidden.

The bootstrap transaction MUST byte-match the approved bootstrap payload and
all expected transition fields. Writer substitution, credential or authority
rotation, epoch substitution, predecessor drift, state-hash drift, or bootstrap
payload drift MUST reject before any effect.

#### Scenario S-75: One approved boundary switches the writer epoch

- **GIVEN** all gates pass, no v1 write job is active, and both roles approve
  the same bundle hash.
- **WHEN** the system applies the cutover transition.
- **THEN** one bootstrap record establishes the vNext epoch and exactly one
  writer: `agent0@system` through the approved active credential binding.
- **THEN** a missing approval, changed boundary, stale process, or partial
  effect rejects without two active writers.
- **EVIDENCE** Planned `tests/vnext/test_block9_cutover.py` proves atomicity,
  exact authority, retry, stale-process rejection, and no dual write. It also
  proves non-Agent0 and writer-binding substitution, authority rotation, epoch
  substitution, predecessor drift, state-hash drift, and bootstrap-payload
  drift.

### Requirement R-B9-06: Gauntlet mint is historical only

The first vNext cutover MUST NOT import gauntlet mint as an active mechanism.
Historical gauntlet and trajectory-mint records MUST remain readable and
immutable.

#### Scenario S-76: Gauntlet cannot create WEA after cutover

- **GIVEN** v1 history contains gauntlet or trajectory-mint records.
- **WHEN** genesis is built or a caller requests a gauntlet mint after cutover.
- **THEN** genesis retains the history without a second mint, and the new mint
  request rejects without changing money.
- **EVIDENCE** Planned `tests/vnext/test_block9_legacy_retirement.py` proves
  history retention, no double mint, command rejection, and invariant stability.

### Requirement R-B9-07: Achievements are historical only

The first vNext cutover MUST NOT import achievements, `award`, `revoke`, or
`transform` as active state or active commands.

Historical records MUST NOT change genome, Release, eligibility, authority, or
money. A future ikigai or identity mechanism requires a separate accepted
Outcome and Spec.

Genesis MUST preserve the separately reconciled current genome snapshot. It
MUST NOT derive or modify that snapshot by replaying achievement history.

#### Scenario S-77: Achievement history has no active effect

- **GIVEN** v1 contains achievement, award, revoke, or transform records.
- **WHEN** genesis is built or a caller requests one of these writes after
  cutover.
- **THEN** the records remain readable history, the write rejects, and active
  vNext state does not change.
- **EVIDENCE** Planned `tests/vnext/test_block9_legacy_retirement.py` proves
  history retention, write rejection, and no effect on genome, Release,
  eligibility, authority, or money.

### Requirement R-B9-08: Recovery follows the cutover boundary

A failure before the first vNext ledger record MUST create no cutover. A new
attempt MUST use a new snapshot when v1 state changes.

A failure after the first vNext ledger record MUST NOT reactivate v1. Financial
errors use append-only correction. Non-financial replay errors use
`replay_repair`.

Before cutover, a durable financial-correction path MUST exist. It MUST use
authenticated approvals, one crash-safe append transaction, restart
reconstruction, and idempotent duplicate handling.

The durable path MUST implement or strictly extend S13C Spec 1.1. It MUST
preserve immutable prior-row bytes, complete-group atomicity, pre/post financial
invariants, a nonnegative resulting signed supply, canonical opening and group
chain commitments, full reconstruction, exact replay, and tamper rejection.
Its exact implementation version/hash and crash/restart evidence MUST be part
of the cutover bundle.

Before cutover, durable `replay_repair` MUST exist for non-financial derived
state. The cutover gate MUST reject if either recovery path is absent,
unversioned, or not covered by crash and restart evidence. The current inactive
S13C library does not satisfy this prerequisite.

#### Scenario S-78: Recovery never creates two histories

- **GIVEN** a failure before or after the first vNext ledger record.
- **WHEN** the operator starts recovery.
- **THEN** a pre-record failure leaves no vNext epoch and requires fresh
  evidence after any v1 change.
- **THEN** a post-record failure keeps the vNext epoch and uses forward repair.
- **EVIDENCE** Planned `tests/vnext/test_block9_recovery_prerequisites.py` proves
  durable correction, retained S13C 1.1 semantics, implementation binding, and
  replay-repair eligibility. Planned
  `tests/vnext/test_block9_recovery.py` proves crash points, restart
  reconstruction, duplicate recovery, authority rotation, money/non-money
  separation, exact retry, and no automatic v1 fallback.

### Requirement R-B9-09: Public state matches the active epoch

The cutover MUST publish one current operational contract. Root documentation,
CLI help, Issue forms, workflow guards, and projected labels MUST name the
active vNext epoch and the permitted writer.

A projection failure MUST NOT reverse a ledger transition. The canonical
operational status MUST report `projection_degraded`, list every pending
projection, and continue to reject retired writers. A later idempotent retry
MUST restore the expected public state without repeating money.

#### Scenario S-79: Projection failure is visible and retry converges

- **GIVEN** an accepted cutover with one failed external projection.
- **WHEN** an operator reads the canonical operational status before retry.
- **THEN** vNext remains authoritative, retired writers reject, and the status
  reports the exact pending projection without a second money transition.
- **WHEN** the operator runs the idempotent projection retry.
- **THEN** each public surface converges on the active vNext epoch. The retry
  changes only projections and never repeats a ledger transition.
- **EVIDENCE** Planned `tests/vnext/test_block9_public_contract.py` and doc-sync
  inspection prove current status, retired paths, and projection-only retry.

## Stale dependents

| Artifact | References spec version | Required reconciliation |
| --- | --- | --- |
| Block 9 Design | none | Create an accepted design before implementation. |
| Parent `migration.md` and `delta.md` | Decision overlay 1.1 | Current for gauntlet and achievement retirement. |
| Parent `design.md` and `schema.md` | Domain/Access Design 1.1 | Add technical cutover mechanics only during Block 9 Design. |
| Block 9 implementation and tests | none | Remain blocked until Design and tasks are current. |
| Readiness evidence | none | Add after design and implementation evidence exist. |

## Scenario evidence map

| Requirement | Scenario | Observable evidence |
| --- | --- | --- |
| R-B9-01 | S-71 | Planned `test_block9_writer_gate.py` |
| R-B9-02 | S-72 | Planned `test_block9_reconciliation.py` |
| R-B9-03 | S-73 | Planned `test_block9_genesis.py` |
| R-B9-04 | S-74 | Planned `test_block9_shadow.py` |
| R-B9-05 | S-75 | Planned `test_block9_cutover.py` |
| R-B9-06 | S-76 | Planned `test_block9_legacy_retirement.py` |
| R-B9-07 | S-77 | Planned `test_block9_legacy_retirement.py` |
| R-B9-08 | S-78 | Planned `test_block9_recovery_prerequisites.py` and `test_block9_recovery.py` |
| R-B9-09 | S-79 | Planned `test_block9_public_contract.py` and doc-sync inspection |

## Non-goals

- No production writer, live bootstrap, or cutover execution.
- No credential, permission, Issue, label, or ledger mutation.
- No gauntlet replacement.
- No achievement, ikigai, or identity-discovery implementation.
- No implementation mechanics before an accepted Design.
