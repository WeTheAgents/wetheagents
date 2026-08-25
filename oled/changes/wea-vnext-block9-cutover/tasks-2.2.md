# Tasks: Block 9 GitHub-native private pilot

Task revision: `2.2`

Plan status: `steps 1 through 3 locally verified. Step 4 waits for code merge`

Implements outcome version: `1.0`

Implements spec version: `1.1`

Implements design revision: `1.3`

Authority: the operator selected the real canonical ledger and required
GitHub-native orchestration on 2026-08-25. This runbook needs no separate hash
acceptance.

## Five steps before the SDD consistency check

### 1. Reconcile the accepted contract

- Covers: S-71, S-75, S-79, S-80, and S-81.
- Status: `complete`.
- Depends on: none.

- [x] Record the canonical-private-pilot decision.
- [x] Add Spec 1.1 and Design 1.3 without changing frozen accepted files.
- [x] Remove the separate Tasks 2.2 hash gate.
- [x] Rebuild the simple Russian HTML review artifact.
- [x] Make every durable handoff point to Spec 1.1 and Design 1.3.

### 2. Build the GitHub Actions ledger path

- Covers: S-71 and the preparation side of S-75.
- Status: `implemented and locally verified`.
- Depends on: step 1.
- Known areas: `.github/workflows/`, the deterministic Block 9 transaction
  builder, and trusted candidate-data validation.

- [x] Add one manually started GitHub-hosted workflow that builds a candidate
  from one GitHub command and the current canonical predecessor.
- [x] Make the workflow run replay, idempotency, money, supply, and schema
  checks before it pushes a candidate branch.
- [x] Make the workflow report a compare URL. The operator opens the pull
  request manually.
- [x] Add one trusted `pull_request_target` guard. Use only base-branch code.
- [x] Treat every pull-request file as data. Never execute candidate code.
- [x] Reject stale predecessors, changed commands, non-next sequences, repeated
  idempotency keys, replay drift, money drift, supply drift, and hidden protocol
  path changes.
- [x] Prove these cases with focused tests and workflow fixture inspection.

### 3. Retire local and legacy authority

- Covers: S-71 and the no-dual-write side of S-75.
- Status: `implemented and locally verified`.
- Depends on: step 2.
- Known areas: `src/wea_epoch/`, protocol guard scripts, v1 mutation entry
  points, self-hosted write workflows, and long-lived write credentials.

- [x] Remove the local lock and epoch guard from the canonical authority path.
- [x] Remove local App transport and dedicated Windows writer accounts from the
  activation package.
- [x] Disable or convert every legacy workflow that can write canonical state.
- [x] Make the trusted GitHub guard reject legacy ledger changes after vNext
  activation.
- [x] Preserve historical v1 readers and immutable history.
- [x] Update obsolete tests to the accepted GitHub-native behavior.
- [x] Prove that no active local command, self-hosted workflow, PAT, deploy key,
  or custom App is required for a vNext canonical transaction.

### 4. Rehearse and activate the private canonical ledger

- Covers: S-75 and S-79.
- Status: `blocked on the implementation merge`.
- Depends on: steps 2 and 3.

- [ ] Run one no-write rehearsal from the exact private predecessor.
- [ ] Build one exact activation package. Bind repository ID `1171421025`,
  predecessor, epoch, genesis, sequence zero, state, workflow revisions, proof
  results, and recovery revisions.
- [ ] Show the exact activation package to the operator.
- [ ] Stop before the live pull request until the operator approves those exact
  bytes. This is the only remaining ledger-mutation approval.
- [ ] After approval, run Agent0 Actions, open the generated pull request, and
  merge only after the trusted guard passes.
- [ ] Read canonical `main`, replay every vNext byte, and run all financial
  invariants.
- [ ] Record unavailable private ruleset evidence as `DEFERRED`, not `PASS`.

### 5. Complete the retained private E2E pilot

- Covers: S-80.
- Status: `blocked on step 4`.
- Depends on: step 4.

- [ ] Complete at least two real tasks with controlled local agents.
- [ ] Collectively prove create, escrow, claim, delivery, acceptance, payment,
  idempotent retry, replay, and recovery.
- [ ] Bring each pilot task to a terminal state.
- [ ] Prove zero pilot escrow and zero pending pilot payment.
- [ ] Prove money, supply, history, and exact replay invariants.
- [ ] Retain every Issue, workflow run, pull request, commit, ledger event, and
  payment record.

## Required check after step 5

After steps 1 through 5 pass, compare the implementation and evidence with the
current accepted SDD/OLED rules.

The check must answer:

1. Does each accepted requirement have a concrete scenario and proof?
2. Does Design add a mechanism that no current requirement needs?
3. Does Tasks contain a gate that protects neither money nor an irreversible
   action?
4. Can a fresh session distinguish accepted, superseded, deferred, failed, and
   not-run state without chat history?
5. Do code, workflows, tests, HTML, and handoffs bind Spec 1.1 and Design 1.3?

Remove an unnecessary mechanism or gate before the public transition. Do not
weaken money, idempotency, replay, recovery, history, or untrusted-code
isolation.

## Public transition after the SDD check

### 6. Audit exposure and enable public enforcement

- Covers: S-79 and S-81.
- Status: `blocked on step 5 and the SDD consistency check`.

- [ ] Audit the current tracked tree and every reachable Git object for
  secrets, private data, license conflicts, and identity exposure.
- [ ] Resolve every blocking finding. Do not rewrite history without explicit
  destructive-change approval.
- [ ] Show the final exposure report and exact visibility change to the
  operator. This is the only remaining irreversible-action stop.
- [ ] Make `WeTheAgents/wetheagents` public after approval.
- [ ] Apply one `main` branch ruleset with required pull request, trusted ledger
  check, linear history, blocked force push, blocked deletion, and no bypass.
- [ ] Prove rejection of direct push, force push, deletion, stale ledger
  candidate, invalid ledger candidate, and a pull request that changes both the
  guard and ledger data.
- [ ] Change remote protection evidence from `DEFERRED` to `PASS` only after
  direct GitHub readback and negative proof.
- [ ] Keep external participation closed until every required remote check is
  `PASS`.

## GitHub App revisit task

Do not create a custom GitHub App now.

Create a new Design task only when one trigger occurs:

- automatic read access from root to a private Domain is required.
- automatic Domain-to-root dispatch is required.
- manual pull-request creation or merge blocks useful throughput.
- the public GitHub rule cannot identify the built-in Actions path safely.

If a trigger occurs, first use an App token inside GitHub Actions. Add a hosted
App service only when a real external webhook requires it.

## Risk and recovery

- Before activation: discard an unmerged candidate and start from current
  `main`.
- After activation: keep vNext active and use append-only forward repair.
- Private rules unavailable: keep the result `DEFERRED` and restrict the pilot
  to controlled local agents.
- Failed public setup: close external participation and complete the protection
  setup. Do not claim that returning to private removes prior exposure.

## Verification map

| Accepted scenario or boundary | Adequate proving surface | Evidence gap or owner |
| --- | --- | --- |
| S-71 | Trusted PR guard, writer inventory, workflow and commit inspection | Local proof passes. Live GitHub proof starts after the code-only merge. |
| S-75 | No-write rehearsal, exact activation package, workflow run, merge, replay, invariants | Exact activation bytes require later operator approval. |
| S-79 | Canonical status and GitHub settings readback | Private ruleset proof remains `DEFERRED`. |
| S-80 | At least two terminal real tasks and the retained pilot report | Live private activation must occur first. |
| S-81 | Exposure audit, pre/post ref hashes, ruleset readback, negative probes | Public visibility requires explicit operator approval. |
| Untrusted pull-request code | Trusted workflow fixture and source inspection | The workflow must not execute candidate code. |
| Recovery | Crash/restart tests plus one retained pilot recovery result | Live pilot evidence is missing. |

## Resume handoff

| Lane | Status | Exact next action | Stop point |
| --- | --- | --- | --- |
| Contract | complete | Preserve the accepted versions and current HTML. | none |
| GitHub Actions path | locally verified | Merge the implementation without ledger data. | code review must pass |
| Local authority retirement | locally verified | Read the merged workflow and writer boundary from `main`. | code review must pass |
| Private activation | blocked | Build the exact package from the merged `main` predecessor. | operator approval of exact ledger bytes |
| Private E2E | blocked | Run after canonical activation. | stop on invariant or replay failure |
| SDD consistency | blocked | Run after the five steps pass. | resolve every blocking inconsistency |
| Public transition | blocked | Audit exposure and prepare the visibility change. | operator approval before public exposure |
| External participation | blocked | Open only after public enforcement is `PASS`. | remote proof |
