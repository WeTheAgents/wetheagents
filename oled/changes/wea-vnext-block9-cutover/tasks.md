# Tasks: WEA vNext Block 9 Cutover

Task revision: `2.0`

Plan status: `planned for operator review; implementation not started; activation blocked`

Implements outcome version: `1.0`, exact SHA-256
`e9cbdcc924c8e01cae3240885e272fc75a7595bae1dcab4ee4034e6d439d1f67`

Implements spec version: `1.0`, exact SHA-256
`25c65e999bb158d773fa7d46c5e566cd36f5a7eb4b8b8aff272274d8efe59dfa`

Implements design revision: `1.0`, exact SHA-256
`70026e7551acc7c5f1ae56b1d49962045dec3b70e0647aaf3b5040f36e856283`

Authority source: the operator accepted Block 9 Design in the current Codex
task on 2026-08-18. `WEA_vNext_BLOCK9_DESIGN_ACCEPTANCE.txt` binds that act to
the exact Design hash. The preparation-time `proposed` wording inside the
frozen Design stays unchanged.

## Plan shape

This plan has eight work groups. These groups form three accepted delivery
stages. A group is a dependency node, not a separate product approval.

- Delivery 1 is dormant implementation. It contains Groups 1 through 5.
- Group 1 supplies the code interfaces and transaction kernel.
- Groups 3, 4, and 5 can proceed in parallel after Group 1.
- Group 2 is the real dormant host and GitHub setup. It needs one explicit
  operator approval after its no-change inspection report.
- Delivery 2 contains Groups 6 and 7. One later exact operator acceptance covers
  the controlled v1 cleanup and the no-write rehearsal.
- Delivery 3 is Group 8. It needs new exact operator and Agent0 approvals.

Acceptance of Tasks 2.0 authorizes only code work in Groups 1, 3, 4, and 5. It
does not authorize Group 2 environment mutation, Group 6 v1 mutation, Group 7
rehearsal, or Group 8 activation.

## 1. Build the dormant transaction and writer kernel

- Covers accepted scenarios: S-71 and the transaction foundation of S-75.
- Status: planned.
- Depends on: accepted Block 9 Design 1.0 and accepted Tasks 2.0.
- Known entry points and affected areas: `src/wea_vnext/`, `src/wea_cli/`,
  `scripts/`, `.github/workflows/`, `.github/ISSUE_TEMPLATE/`, and canonical
  ledger schemas.
- What this gives: every protocol write uses one lock, one epoch guard, and one
  atomic Git transaction.
- Why this is needed: without this group, an old writer can create a second
  history after cutover.
- Simplification: keep locks, authority, storage, and remote comparison in one
  code group. They do not need separate approvals.

- [ ] Before the first implementation edit, require a clean worktree and write
  the exact `git rev-parse HEAD` value to
  `oled/changes/wea-vnext-block9-cutover/implementation-base.txt`. Group 7 uses
  this one base to derive the complete Block 9 changed-file manifest.
- [ ] Create `tests/vnext/test_block9_writer_gate.py` and the transaction
  foundation in `tests/vnext/test_block9_cutover.py`.
- [ ] Record the expected pre-change failures for omitted writers, guard
  bypass, wrong principals, ref drift, and non-atomic publication.
- [ ] Add two independent writer-universe builders and the three accepted
  inventories from D-B9-02.
- [ ] Add one transaction helper with the common-Git-directory lock, epoch
  guard, remote predecessor check, canonical JSON, and signed Git commit.
- [ ] Add append-only `ledger/vnext/` event storage and disposable derived
  state. Keep the live adapter disabled.
- [ ] Add the non-circular cutover-core, signed approval-envelope, sequence-zero,
  and final-tree validation path.
- [ ] Route each retained v1 mutation entry point through the shared guard.
  Disable every retired writer path.
- [ ] Add no-change inspection and provisioning tools for the accepted Windows
  identities, Apps, rulesets, keys, and permissions. Do not apply them here.
- [ ] Prove the code kernel with
  `python -m pytest -q tests/vnext/test_block9_writer_gate.py tests/vnext/test_block9_cutover.py`.

## 2. Prepare the dormant host and GitHub boundary

- Covers accepted scenarios: the environment and authority sides of S-71,
  S-74, S-75, and S-79.
- Status: blocked pending one explicit operator approval of the no-change
  inspection report.
- Depends on: Group 1 inspection and provisioning tools.
- Known entry points and affected areas: Windows local identities and ACLs,
  Agent0 dispatch, two GitHub Apps, two rulesets, workflow permissions, and
  legacy credentials.
- What this gives: Agent0, workers, shadow, ledger transport, and projections
  have separate enforceable permissions before vNext can start.
- Why this is needed: code cannot prevent a same-account worker or another
  GitHub credential from bypassing the ledger writer.
- Simplification: use one operator checkpoint for the complete dormant setup.
  Do not request one approval per account, App, key, or ruleset.

- [ ] Run the no-change inspection mode. Record current accounts, ACLs,
  credentials, workflows, Apps, rulesets, worktrees, and writer processes.
- [ ] Build the complete proposed environment diff and its recovery steps.
- [ ] Stop and obtain one explicit operator approval for that exact dormant
  setup. Tasks 2.0 acceptance does not supply this approval.
- [ ] After approval, create the Agent0, worker, and shadow identities. Apply
  the accepted ACL and token separation.
- [ ] Install the ledger App and no-Contents projection App. Apply both layered
  rulesets and remove legacy canonical-ref authority.
- [ ] Prove ledger-App fast-forward, force-push rejection, deletion rejection,
  projection-App ref rejection, worker secret denial, and shadow denial in a
  disposable repository and restricted accounts.
- [ ] Record exact public identities, permissions, fingerprints, rulesets, and
  rejection evidence. Do not enable the vNext adapter.

## 3. Build offline reconciliation and canonical genesis

- Covers accepted scenarios: S-72, S-73, S-76, and S-77.
- Status: planned.
- Depends on: Group 1 schemas and transaction interfaces. It does not depend on
  Groups 2, 4, or 5 for code work.
- Known entry points and affected areas: v1 ledger readers, GitHub boundary
  capture, `src/wea_vnext/`, retired command adapters, and genesis schemas.
- What this gives: every v1 obligation receives one outcome, and one replay
  creates the same opening vNext state.
- Why this is needed: without this group, money, tasks, or identities can be
  lost or counted twice during migration.
- Simplification: reconciliation, genesis, gauntlet retirement, and achievement
  retirement stay together because they use the same frozen input.

- [ ] Create `tests/vnext/test_block9_reconciliation.py`,
  `tests/vnext/test_block9_genesis.py`, and
  `tests/vnext/test_block9_legacy_retirement.py`.
- [ ] Record the expected pre-change failures for incomplete pagination,
  missing inverse links, unexplained money, duplicate outcomes, and unstable
  genesis bytes.
- [ ] Capture the complete offline GitHub and v1 input bundle from one exact
  test boundary. Keep the production capture path dormant.
- [ ] Implement the four accepted reconciliation outcomes and complete money
  equality.
- [ ] Implement the signed conversion-intent state machine. Do not create a
  converted Plan, Task, Contract, debit, or escrow in genesis.
- [ ] Build genesis from the frozen input. Rebuild it independently and require
  identical bytes and state hashes.
- [ ] Preserve gauntlet and achievement history as read-only evidence. Reject
  every new retired write.
- [ ] Prove reconciliation and genesis with
  `python -m pytest -q tests/vnext/test_block9_reconciliation.py tests/vnext/test_block9_genesis.py tests/vnext/test_block9_legacy_retirement.py`.

## 4. Make financial and non-financial recovery durable

- Covers accepted scenarios: S-78.
- Status: planned.
- Depends on: Group 1 transaction kernel. It can proceed in parallel with
  Groups 3 and 5.
- Known entry points and affected areas: `src/wea_vnext/financial_correction.py`,
  replay, event storage, authority loading, and transaction recovery.
- What this gives: a crash or replay defect cannot create two histories or
  force an automatic return to v1.
- Why this is needed: activation without recovery can preserve a bad state with
  no accepted way to repair it.
- Simplification: financial correction and `replay_repair` share one append
  kernel, but they keep separate authority and money rules.

- [ ] Create `tests/vnext/test_block9_recovery_prerequisites.py` and
  `tests/vnext/test_block9_recovery.py`.
- [ ] Record the expected pre-change failures for missing durable adapters,
  crash points, duplicate retry, authority rotation, and money-changing repair.
- [ ] Adapt S13C 1.1 to the durable event transaction without weakening any
  financial, type, ordering, tamper, or idempotency rule.
- [ ] Add durable `replay_repair` for the accepted non-financial operation set.
  Reject every repair that changes a financial projection.
- [ ] Add correction checkpoints at the accepted 64-group boundary.
- [ ] Exercise failures before file replacement, commit creation, push, remote
  confirmation, and projection confirmation.
- [ ] Prove restart reconstruction, exact retry, tamper rejection, and no v1
  fallback with
  `python -m pytest -q tests/vnext/test_block9_recovery_prerequisites.py tests/vnext/test_block9_recovery.py`.

## 5. Build isolated shadow proof and public projections

- Covers accepted scenarios: S-74 and S-79.
- Status: planned.
- Depends on: Group 1 interfaces. Final integrated proof also needs Groups 2,
  3, and 4.
- Known entry points and affected areas: Windows setup tools, shadow harness,
  root docs, CLI help, Issue forms, workflow guards, labels, and comments.
- What this gives: the complete candidate runs twice without a live effect, and
  public GitHub state converges without repeating money.
- Why this is needed: unit tests cannot prove that the full runtime avoids
  credentials, network writes, or duplicate GitHub projections.
- Simplification: keep tracked public files in the activation tree. Use the
  projection worker only for labels and comments.

- [ ] Create `tests/vnext/test_block9_shadow.py` and
  `tests/vnext/test_block9_public_contract.py`.
- [ ] Record the expected pre-change failures for live-path access, available
  network, credential access, unstable replay, duplicate comments, and stale
  public status.
- [ ] Implement the restricted-account shadow harness with copied inputs,
  denied live paths, network-off proof, and bounded child processes.
- [ ] Run the complete candidate twice from fresh test inputs. Require identical
  report bytes and no host-state change.
- [ ] Make root docs, CLI help, Issue forms, and workflow guards epoch-aware in
  the dormant implementation.
- [ ] Add the projection state machine, hidden comment marker, full pagination,
  exact read-back, desired-state label update, and `projection_degraded` status.
- [ ] Bind projection work to the no-Contents projection App. Reject permission
  expansion or canonical-ref access.
- [ ] Prove the group with
  `python -m pytest -q tests/vnext/test_block9_shadow.py tests/vnext/test_block9_public_contract.py`.

## 6. Resolve every real v1 obligation under v1 authority

- Covers accepted scenarios: the real-project preparation side of S-72.
- Status: blocked pending a separate exact operator acceptance of Delivery 2.
- Depends on: Groups 1 through 5 complete and verified.
- Known entry points and affected areas: the canonical v1 ledger, task index,
  GitHub Issues, comments, escrows, pending payments, and conversion approvals.
- What this gives: every real v1 obligation is closed, refunded, converted by
  fresh approval, or proved historical before the final snapshot.
- Why this is needed: migration code alone does not settle the project data.
  Genesis cannot safely hide an open task or financial obligation.
- Simplification: one Delivery 2 approval covers this controlled cleanup and
  the following rehearsal. It does not authorize vNext activation.

- [ ] Stop every agent, writer, maintenance process, and writer workflow
  trigger. Keep the project frozen through Group 7.
- [ ] Prove that local writer processes and running or pending GitHub writer
  jobs are empty before the first operational capture.
- [ ] Capture the complete two-way Issue and v1 obligation universe.
- [ ] Assign exactly one accepted outcome to every real obligation.
- [ ] Build and hash a dry-run manifest for every planned v1 ledger action.
  Before each action, verify the exact escrow, available amount, idempotency
  key, expected predecessor, and expected result against the current ledger.
- [ ] Perform each authorized `settle-v1`, `stop/refund`, `historical-close`, or
  conversion closure/refund as one controlled Agent0 transaction through
  current v1 authority and idempotency rules.
- [ ] Immediately after each committed v1 transaction, run
  `python scripts/check_invariant.py`, `python scripts/check_ledger_schema.py`,
  and `python scripts/check_task_index_schema.py`. Classify any interruption as
  an exact retry, a conflict, or a partial failure. Resolve it before the next
  action. Never continue from an unverified ledger state.
- [ ] For each conversion, capture the exact verified v1 closure or refund
  record and hash. Then validate the exact fresh Agent approval and create the
  canonical immutable conversion-intent record in `pending` state. Bind that
  closure evidence, every field required by Spec 1.0 lines 66 through 72, the
  terminal-state rules, and one-shot idempotency key. Preserve the exact intent
  bytes, hash, and approval evidence for the final boundary and genesis input.
  Do not create vNext money or objects.
- [ ] Prove that active escrow, pending payments, duplicate outcomes,
  unexplained money, and unclassified obligations are absent. Keep writers
  stopped and capture a fresh final boundary for Group 7.

## 7. Build the exact candidate and run one no-write rehearsal

- Covers accepted scenarios: S-71 through S-79 together.
- Status: blocked pending the same separate exact operator acceptance as Group
  6 and successful completion of Group 6.
- Depends on: Groups 1 through 6 and the still-active stop-the-world boundary.
- Known entry points and affected areas: the complete Block 9 runtime, final
  frozen project input, disposable remote, and rehearsal evidence.
- What this gives: one exact report shows that the complete boundary-specific
  candidate can cut over without changing live v1 or the canonical ref.
- Why this is needed: separate tests do not prove that all modules, data,
  authorities, and activation files use the same snapshot.
- Simplification: run one rehearsal for the complete candidate. The shadow
  runtime still runs twice inside it to prove repeatability.

- [ ] Recheck that every writer trigger stays disabled and that local and
  GitHub writer queues remain empty before reading the final boundary.
- [ ] Capture and hash the final remote ref, v1 state, GitHub boundary,
  authority state, environment state, and runtime.
- [ ] Rebuild both writer universes, all inventories, reconciliation, genesis,
  recovery prerequisites, shadow reports, and public-surface expectations.
- [ ] Build the complete unsigned cutover core, exact bootstrap bytes,
  deterministic sequence-zero event blueprint, and closed activation path set.
- [ ] With non-authoritative rehearsal keys, exercise both approval envelopes,
  sequence zero, final-tree manifest, signed commit, and remote confirmation in
  a disposable repository. Do not create canonical sequence zero.
- [ ] Run every Block 9 focused proving target against this exact candidate.
- [ ] Run `python -m pytest -q tests/vnext`.
- [ ] From a clean final candidate, generate
  `evidence/vnext/block9-changed-python-files.txt`. Read the base from
  `oled/changes/wea-vnext-block9-cutover/implementation-base.txt`. The manifest
  includes every added, copied, modified, or renamed Python file anywhere in
  the repository; it excludes only deleted files. Use this exact PowerShell:
  `$base = (Get-Content -Raw oled/changes/wea-vnext-block9-cutover/implementation-base.txt).Trim(); if (git status --porcelain) { throw 'dirty candidate' }; $files = @(git diff --name-only --diff-filter=ACMR "${base}..HEAD" -- '*.py'); [Array]::Sort($files, [StringComparer]::Ordinal); if (-not $files) { throw 'empty Block 9 Python manifest' }; $files | Set-Content -Encoding utf8NoBOM evidence/vnext/block9-changed-python-files.txt`.
- [ ] In PowerShell, run
  `$files = @(Get-Content evidence/vnext/block9-changed-python-files.txt); if (-not $files) { throw 'empty Block 9 Python manifest' }; python -m ruff check -- $files`.
  Report the repository-wide Ruff baseline separately; unrelated legacy
  findings do not block this delivery.
- [ ] Run `python -m pyright` with the repository configuration.
- [ ] Run `python scripts/check_invariant.py`,
  `python scripts/check_ledger_schema.py`,
  `python scripts/check_task_index_schema.py`, and
  `python scripts/check_doc_sync.py`.
- [ ] Run
  `python oled/changes/wea-vnext-block9-cutover/build_tasks_review.py --check`,
  `python oled/changes/wea-vnext-s13c-financial-correction/build_sdd_review.py --check`,
  and `python oled/changes/wea-vnext-recreation/build_review_html.py --check`.
- [ ] Run the disposable GitHub integration proof for both Apps and both
  rulesets. Do not target the canonical repository.
- [ ] Produce one readiness report with exact hashes and every remaining gap.
- [ ] If any result is ambiguous, incomplete, stale, or different between the
  two shadow runs, stop.
- [ ] After a clean report, stop. Do not publish canonical sequence zero or an
  activation commit.

## 8. Activate only under a new exact approval

- Covers accepted scenarios: S-75 and the post-cutover sides of S-78 and S-79.
- Status: blocked and outside the authority of Tasks 2.0.
- Depends on: a clean Group 7 report, a newly confirmed frozen boundary, an
  activation-specific Tasks revision, exact operator approval, and exact
  Agent0 approval.
- Known entry points and affected areas: the canonical ref, activation tree,
  local Agent0 writer, and external projections.
- What this gives: one atomic switch from the stopped v1 epoch to vNext.
- Why this is separate: this is the only group that changes the authoritative
  ledger epoch. A rehearsal cannot authorize this mutation.
- Simplification: use one activation gate and one fast-forward commit. Do not
  add a rolling migration, dual-write phase, automatic scheduler, or rollback
  to v1.

- [ ] Do not start this group from Tasks 2.0.
- [ ] After Group 7, create an activation-specific Tasks revision for the exact
  frozen boundary and candidate implementation.
- [ ] Reconfirm that the Group 7 boundary and every authority source remain
  unchanged. Rebuild the candidate if any bound input changed.
- [ ] Obtain the two accepted signed approval envelopes for that exact package.
- [ ] Publish one Agent0-signed fast-forward commit through the ledger App.
- [ ] Reconstruct from the remote ref, prove the invariant, and reconcile
  external projections through the projection App.
- [ ] If publication did not occur, discard or rebuild the candidate from the
  current boundary.
- [ ] If publication occurred, keep vNext authoritative and use forward repair.
  Never reactivate v1 automatically.

## Lean cut and simplification choices

| Choice | Result | Contract effect | Recommendation |
| --- | --- | --- | --- |
| Run Groups 3, 4, and 5 in parallel after Group 1 | Less calendar time and the same proof | No contract change | Use this cut. |
| Deliver Groups 1 through 5 as one dormant implementation package | One implementation review instead of five product approvals | If each focused proof stays visible, this cut does not change the contract. | Use this cut. |
| Use one approval for Groups 6 and 7 | One controlled v1 cleanup and one rehearsal delivery | Matches accepted Design | Use this cut. |
| Combine rehearsal and activation | Removes the last no-write proof before mutation | Changes accepted Design D-B9-10 | Do not use without a new Design acceptance. |
| Use one writer inventory | Cannot prove an omitted or late writer | Breaks R-B9-01 and S-71 | Do not use. |
| Use one Windows account for Agent0 and workers | Workers can reach Agent0 secrets | Breaks D-B9-06 authority isolation | Do not use without a new Design acceptance. |
| Use one GitHub App for ledger and projections | Projection code gains canonical-ref write permission | Breaks the accepted least-authority boundary | Do not use without a new Design acceptance. |
| Run shadow once | Does not prove repeatability | Breaks R-B9-04 and S-74 | Do not use. |
| Add recovery after activation | Leaves no accepted repair path at cutover | Breaks R-B9-08 and S-78 | Do not use. |

## Risk and recovery

- Dormant delivery authority: Tasks 2.0 acceptance authorizes only code Groups
  1, 3, 4, and 5. Group 2 needs one later exact environment approval.
- Rehearsal delivery authority: Groups 6 and 7 need one separate exact operator
  acceptance after dormant implementation evidence exists.
- Activation authority: Group 8 needs a later activation-specific Tasks
  revision and two exact signed approvals.
- Recovery-state boundary: Group 6 resolves real v1 obligations. Group 7 then
  captures the exact no-write rehearsal boundary while writers remain stopped.
- Mutation boundary: Group 6 can use current v1 authority only. Group 8 is the
  only group that can create the vNext epoch.
- Integrity proof: rebuild from the canonical remote ref and prove every
  financial, authority, history, and projection commitment.
- Recovery action: discard an unpublished candidate. Use forward correction or
  `replay_repair` after publication. Do not rewrite history.

## Verification map

| Accepted scenario or boundary | Adequate proving surface | Planned command or locator | Evidence gap and owner |
| --- | --- | --- | --- |
| S-71 | Writer universe, guard, ruleset, and credential rejection | `python -m pytest -q tests/vnext/test_block9_writer_gate.py` | Test is absent. Group 1 creates it. Group 2 supplies environment proof. |
| S-72 | Complete obligation and conversion-intent behavior | `python -m pytest -q tests/vnext/test_block9_reconciliation.py` | Test is absent. Group 3 creates it. Group 6 supplies real-project evidence. |
| S-73 | Exact genesis and replay | `python -m pytest -q tests/vnext/test_block9_genesis.py` | Test is absent. Group 3 creates it. |
| S-74 | Two isolated full-runtime shadow runs | `python -m pytest -q tests/vnext/test_block9_shadow.py` plus the restricted-account evidence locator | Test and environment proof are absent. Groups 2 and 5 create them. |
| S-75 | Signed atomic cutover in local bare Git and a disposable GitHub repository | `python -m pytest -q tests/vnext/test_block9_cutover.py` plus the disposable-repository evidence locator | Test and external proof are absent. Groups 1, 2, and 7 create them. |
| S-76 and S-77 | Historical readability and retired-write rejection | `python -m pytest -q tests/vnext/test_block9_legacy_retirement.py` | Test is absent. Group 3 creates it. |
| S-78 | Durable correction, repair, crash, and restart | `python -m pytest -q tests/vnext/test_block9_recovery_prerequisites.py tests/vnext/test_block9_recovery.py` | Tests are absent. Group 4 creates them. |
| S-79 | Tracked surface activation and idempotent external projection | `python -m pytest -q tests/vnext/test_block9_public_contract.py` | Test is absent. Groups 2 and 5 create it. |
| Money | Existing and new financial invariant proofs | `python scripts/check_invariant.py` plus Block 9 focused tests | New Block 9 proof is absent. Groups 3, 4, and 6 create it. |
| Current runtime stays inactive | Runtime boundary tripwire | `python -m pytest -q tests/vnext/test_runtime_boundary.py` | No gap for the current boundary. |
| Broader vNext regression | Complete vNext suite | `python -m pytest -q tests/vnext` | Run after each integrated dormant package and in Group 7. |
| Repository quality | Exact Group 7 Ruff, Pyright, four guard, and three artifact commands | Commands are listed in Group 7 | Run during Execute and Verify. Do not claim results here. |

## Resume handoff

| Lane or group | Status | Dependency or blocker | Exact next action | Proof or evidence gap |
| --- | --- | --- | --- | --- |
| Accepted contract | complete | none | Preserve exact Outcome, Spec, and Design hashes. | None for planning. |
| Group 1 code kernel | planned | Tasks 2.0 acceptance | Start with the two absent focused test modules and no-change inspection tools. | S-71 and S-75 code proof is absent. |
| Group 2 environment | blocked | Group 1 inspection plus exact operator approval | Produce the no-change inspection and proposed environment diff. | Host and GitHub enforcement proof is absent. |
| Group 3 state migration | planned | Group 1 interfaces | Build frozen-input and reconciliation tests. | S-72, S-73, S-76, and S-77 proof is absent. |
| Group 4 recovery | planned | Group 1 transaction kernel | Build durable recovery prerequisite tests. | S-78 proof is absent. |
| Group 5 shadow and public state | planned | Group 1 interfaces | Build shadow and public-contract tests. | S-74 and S-79 proof is absent. |
| Group 6 v1 resolution | blocked | Groups 1–5 plus separate Delivery 2 acceptance | Classify and resolve every real obligation under v1 authority. | Real-project reconciliation evidence is absent. |
| Group 7 rehearsal | blocked | Group 6 and the same Delivery 2 acceptance | Build one exact candidate and no-write report. | Integrated candidate proof is absent. |
| Group 8 activation | blocked | clean rehearsal and new exact dual approval | Do not start. Create an exact activation plan after readiness. | Activation authority and evidence are absent. |

Next authorized action: operator review of Tasks 2.0 and its lean cut. No
implementation or environment mutation starts before that review.
