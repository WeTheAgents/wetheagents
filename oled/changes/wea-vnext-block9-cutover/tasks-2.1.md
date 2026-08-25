# Tasks delta: Block 9 lean pipeline through rehearsal

Task revision: `2.1`

Plan status: `proposed for exact operator acceptance`

Base Tasks: revision `2.0`, exact SHA-256
`e4d047d2bcf10ea6ed03296de869b2a9ea818f69df0208c307bf73da5e963c80`

Proposed Design: revision `1.1`, exact SHA-256
`ffd0ad44323e596b6c23f53aba6d50d214dbc20668f260cd8b37ba7a2ab77b1a`

Governing Outcome/Spec: Block 9 versions 1.0, unchanged.

Authority state: the operator authorized completion of the preparation needed
before Group 2 and requested the pipeline through the no-write rehearsal. This
does not convert an unseen environment diff or unseen v1 transaction manifest
into exact mutation approval. Tasks 2.0 remains current until this exact delta
and each required mutation package are accepted.

## What changes from Tasks 2.0

All Tasks 2.0 groups, dependencies, checks, and activation separation remain
unless this delta says otherwise.

### Group 1: complete the inspector honestly

- Add one read-only command that records target account presence, credential
  source names without values, active writer processes and scheduled writers,
  worktrees, workflow write permissions, the candidate remote ref, rulesets,
  Actions queues, and visible GitHub authority metadata.
- The command may write only its requested report file.
- An unavailable admin-only GitHub surface is recorded as unavailable. It is
  never guessed or reported as empty.
- Prove credential-value redaction, read-only behavior, and unavailable-surface
  handling in `tests/vnext/test_block9_writer_gate.py`.

### Group 2: provision only the ledger boundary

Group 2 remains split by one transparent checkpoint:

1. run the no-change inspection and publish the exact proposed diff;
2. obtain approval for those exact bytes;
3. only then create Windows identities and keys, install the ledger App, apply
   the two rulesets, and remove legacy canonical-ref authority;
4. prove ordinary ledger-App fast-forward and force/delete/other-principal
   rejection without enabling vNext.

The projection App is omitted from this initial environment diff. Its absence
is recorded as the exact `deferred` transport state. Do not grant Issues
permission to the ledger App and do not substitute a human credential.

### Group 5: support the explicit deferred state

- Add the exact `active | deferred` projection-transport value from Design 1.1.
- When `deferred`, build pending intents and `projection_degraded` status but
  perform no external mutation.
- Keep the existing projection App binding and retry code dormant for later
  activation of the projection transport.
- Extend `tests/vnext/test_block9_public_contract.py` and the cutover tests with
  the six Design 1.1 hooks.

### Groups 6 and 7: one delivery, still no activation

- After Groups 1 through 5 and Group 2 environment proof pass, produce the
  complete real-v1 dry-run action manifest.
- Obtain one exact operator acceptance for that manifest and the Group 7
  rehearsal procedure.
- Execute the accepted v1 closures under v1 authority, proving invariants after
  every transaction.
- Run one complete no-write rehearsal with projection transport `deferred`.
- The readiness report must show the exact pending projections and prove that
  no projection credential was used.
- Stop after the report. Do not publish sequence zero.

### Group 8: unchanged separate activation gate

Group 8 remains outside this pipeline authority. If later accepted, it may
publish through the ledger App while projection transport is `deferred`.
Tracked public files switch atomically; external comments and labels remain
visible as pending until a separately approved projection-App setup and retry.

## Human checkpoints

| Checkpoint | What the operator sees | What approval permits |
| --- | --- | --- |
| Current | Exact read-only inspection, lean Design 1.1, and Tasks 2.1 | Nothing external until exact acceptance. |
| Group 2 setup | One complete before/after diff for accounts, keys, ledger App, workflows, credentials, and two rulesets | Only that dormant environment mutation and its disposable proof. |
| Delivery 2 | One exact v1 action manifest plus no-write rehearsal procedure | Groups 6 and 7 only. No vNext activation. |
| Activation | Exact frozen candidate, hashes, and dual approval envelopes | Group 8 only. |

## Lean-cut rule

Delete or defer anything that supplies convenience only. Keep a component when
removing it would weaken money, single-writer authority, exact approval,
atomicity, replay, recovery, or proof that tested bytes equal published bytes.

Under this rule:

- keep the ledger App, two rulesets, shared lock, epoch guard, exact candidate,
  two shadow runs, and rehearsal/activation separation;
- defer the projection App, schedules, daemons, servers, queues, live migration,
  automatic rollback, and multi-host operation.

## Verification and stop condition

Before asking for Group 2 mutation approval, run the focused Block 9 tests,
complete `tests/vnext`, Ruff on every Block 9 changed Python file, Pyright, the
four repository guards, the three existing deterministic HTML checks, and the
new Group 2 review builder check.

Stop if the candidate repository, owner authority, App/ruleset visibility,
writer process state, credential inventory, or proposed recovery step is
unknown. The immediate next action is to obtain that named evidence, not to
guess or provision around it.
