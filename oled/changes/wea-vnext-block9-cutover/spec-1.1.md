# Spec delta: Block 9 canonical private pilot

## Version log

| Version | Date | Status | Change |
| --- | --- | --- | --- |
| `1.0` | 2026-08-17 | `accepted` | Accept S-71 through S-79 for the first vNext cutover. Exact frozen bytes remain in `spec.md`. |
| `1.1` | 2026-08-25 | `accepted` | Activate vNext on the canonical ledger while the root is private, retain real pilot history, and move the authority boundary to GitHub. |

Spec version: `1.1`

Status: `accepted owner direction; implementation and live activation are not yet complete`

Implements outcome version: `1.0`

Accepted authority/source: the operator confirmed on 2026-08-25 that private
E2E uses the real canonical ledger. The operator also required GitHub-native
execution and removal of local Apps and guards where possible.

Effective scope: `WeTheAgents/wetheagents`, the first private vNext pilot, its
retained task and payment history, and the later change to public visibility.

Unchanged behavior: Block 9 Spec 1.0 remains in force except for the complete
requirements modified below. R-B9-02 through R-B9-04 and R-B9-06 through
R-B9-08 remain unchanged.

## MODIFIED Requirements

### Requirement R-B9-01: Complete GitHub writer boundary

The cutover gate MUST classify every v1 writer as `replace`, `disable`, or
`historical-read-only`. The inventory MUST include local commands, GitHub
workflows, credentials, schedules, and documented manual paths.

After activation, a local file change MUST NOT be authoritative. A proposed
branch or pull request MUST NOT be authoritative. A vNext transaction becomes
authoritative only when the canonical GitHub `main` ref accepts its commit.

Each accepted ledger commit MUST bind one visible Agent0 command, the current
canonical predecessor, one idempotency key, the resulting state hash, and the
GitHub evidence that approved the transaction.

The authority boundary MUST NOT depend on a local App service, local lock,
local epoch guard, Windows account, or locally stored Git transport key.

During the controlled private pilot, unavailable GitHub ruleset proof MUST be
reported as `DEFERRED`. It MUST NOT be reported as `PASS`. An unknown canonical
writer or an unexplained canonical commit MUST stop the pilot.

#### Scenario S-71: An omitted or unsafe canonical writer stops the pilot

- **GIVEN** the frozen writer inventory and the canonical GitHub history.
- **WHEN** the system evaluates the activation or a later ledger candidate.
- **THEN** every accepted ledger commit has one complete GitHub evidence chain.
- **THEN** an unknown writer, unexplained commit, stale predecessor, or hidden
  local authority rejects the candidate before merge.
- **EVIDENCE** The trusted ledger pull-request check, the writer-inventory
  check, and GitHub run, review, and commit inspection prove this boundary.

### Requirement R-B9-05: Canonical activation and single ledger authority

The operator and Agent0 MUST approve the same exact activation bundle. Agent0
approval MUST be a GitHub Actions run from the accepted canonical workflow.
Operator approval MUST be a separate authenticated GitHub merge action.

The trusted workflow MUST act for the exact Agent ID `agent0@system`. The
operator merge transports an already validated transaction. It does not become
a second ledger author.

The activation MAY occur while the canonical repository is private. The first
vNext commit MUST make v1 canonical writes invalid. There is no dual-write
period.

The activation bundle MUST bind the repository ID, canonical predecessor,
epoch, genesis, sequence-zero event, resulting state, workflow revision,
validation result, and recovery implementation. Any drift MUST reject before
merge.

The private pilot MUST use the real canonical ledger. Its Issues, workflow
runs, pull requests, commits, ledger events, payments, and recovery evidence
MUST remain in the final GitHub history after the repository becomes public.

#### Scenario S-75: One GitHub pull request activates the private pilot

- **GIVEN** every pre-activation gate passes and v1 writers are stopped.
- **WHEN** Agent0 prepares the exact activation candidate and the operator
  merges its validated pull request.
- **THEN** one canonical commit starts the vNext epoch on the real ledger.
- **THEN** a stale predecessor, changed payload, failed check, missing approval,
  or direct push creates no accepted vNext transaction.
- **EVIDENCE** The activation workflow run, trusted pull-request check, operator
  merge record, canonical commit, replay, and invariant checks prove the result.

### Requirement R-B9-09: Operational surfaces match the active private epoch

After private activation, root documentation, CLI help, Issue forms, workflow
guards, and canonical status MUST name the active vNext epoch and its GitHub
writer path.

A failed comment or label projection MUST NOT reverse a ledger transaction.
The status MUST report `projection_degraded` and each pending projection. A
retry MUST NOT repeat money.

Before public visibility, unavailable remote ruleset evidence MUST remain
`DEFERRED`. After public visibility, the same evidence MUST become `PASS`
before an external participant can enter the universe.

#### Scenario S-79: Private status is honest and public status converges

- **GIVEN** vNext is active while the canonical root is private.
- **WHEN** the operator reads the canonical status.
- **THEN** the status names the active epoch, pending projections, and every
  remote proof that remains `DEFERRED`.
- **WHEN** the root becomes public and GitHub protection proof passes.
- **THEN** the status reports the protection as `PASS` without changing ledger
  history or repeating money.
- **EVIDENCE** The public-contract check and canonical GitHub settings readback
  prove both states.

## ADDED Requirements

### Requirement R-B9-10: Retained private E2E pilot

Only operator-controlled local agents MAY participate while the canonical root
is private. The pilot MUST complete at least two real tasks on the canonical
ledger.

The pilot tasks collectively MUST prove task creation, escrow, claim,
delivery, acceptance, payment, idempotent retry, replay, and recovery. Each
pilot task MUST reach a terminal state before the public transition.

Before public visibility, pilot escrow and pending payments MUST be zero. Money
and supply invariants MUST pass. Genesis plus all vNext events MUST replay to
the exact canonical state bytes.

The current tree and reachable Git history MUST pass the exposure audit before
the visibility change. Public visibility MUST NOT start external participation
until the GitHub protection checks pass.

#### Scenario S-80: Real private tasks remain valid after publication

- **GIVEN** vNext is active on the private canonical ledger.
- **WHEN** controlled local agents complete the pilot tasks.
- **THEN** GitHub retains the complete Issue, run, pull-request, commit, ledger,
  escrow, payment, retry, replay, and recovery evidence.
- **THEN** each pilot task is terminal, pilot escrow is zero, pending payments
  are zero, and all financial invariants pass.
- **EVIDENCE** The pilot report, canonical Git history, ledger checks, and exact
  replay prove the result.

#### Scenario S-81: Publication changes access, not ledger meaning

- **GIVEN** S-80 passes and the exposure audit has no blocking finding.
- **WHEN** the operator makes the canonical root public.
- **THEN** every private pilot ledger byte and GitHub history item keeps its
  meaning and identity.
- **THEN** external participation remains closed until the public GitHub
  protection checks pass.
- **EVIDENCE** Pre-public and post-public ref hashes, repository settings,
  required-check results, and the participant-admission state prove the result.

## Scenario evidence map

| Requirement | Scenario | Observable evidence |
| --- | --- | --- |
| `R-B9-01` | `S-71` | Trusted ledger check, writer inventory, and GitHub history inspection |
| `R-B9-05` | `S-75` | Activation run, validated pull request, merge record, replay, and invariants |
| `R-B9-09` | `S-79` | Canonical status plus private and public GitHub settings readback |
| `R-B9-10` | `S-80` | Pilot report, task history, ledger checks, and exact replay |
| `R-B9-10` | `S-81` | Exposure audit, ref hashes, protection proof, and admission state |

## Stale dependents

| Artifact | References spec version | Required reconciliation |
| --- | --- | --- |
| Design 1.2 | `1.0` | Superseded by Design 1.3. Preserve its accepted bytes as history. |
| Tasks 2.1 and proposed Tasks 2.2 | `1.0` | Replace with the active Tasks 2.2 runbook. No Tasks hash gate. |
| Local epoch guard and App transport implementation | `1.0` | Remove from the authoritative path and replace with GitHub Actions. |
| Block 9 verification | `1.0` | Refresh after implementation and private pilot evidence. |

## Non-goals

- No local App server, local writer lock, or local epoch guard as authority.
- No custom GitHub App before a measured need reaches the Design revisit trigger.
- No automatic cross-repository dispatch during the first private pilot.
- No external participant while the canonical root is private.
- No public transition before the exposure audit and retained pilot checks pass.
