# Design delta: Block 9 GitHub-native canonical pilot

Decision status: `current`

Current design revision: `1.3`

Date: `2026-08-25`

Implements outcome version: `1.0`

Implements spec version: `1.1`

Accepted authority: the operator selected the real canonical ledger for the
private pilot. The operator required GitHub-native orchestration and removal of
local Apps and guards where possible.

## Revision history

| Revision | Implements spec | Status | Material decision |
| --- | --- | --- | --- |
| `1.0` | `1.0` | accepted historical base | Use a stopped universe, one laptop, a local lock, local approval keys, and dedicated Apps. |
| `1.1` | `1.0` | accepted historical delta | Defer the projection App. |
| `1.2` | `1.0` | superseded | Keep vNext inactive through private tests and add a separate public rehearsal. |
| `1.3` | `1.1` | current | Activate on the private canonical ledger and use GitHub Actions plus pull requests as the authority path. |

## Repository context

- Canonical root: `WeTheAgents/wetheagents`, repository ID `1171421025`.
- `WeTheAgents/circle-1` is a Domain repository. It is not the ledger root.
- The canonical root is private on GitHub Free during the pilot.
- Remote rulesets are unavailable in this state. This proof remains `DEFERRED`.
- All participants run manually and remain under operator control on one laptop.
- Unlimited downtime is acceptable.
- Existing v1 and dormant Block 9 code contains local locks, epoch guards,
  self-hosted workflows, and long-lived transport credentials.

GitHub documents that Actions are the smaller choice for repository event
automation. A custom App is useful when automation spans repositories, needs a
separate persistent actor, or needs permissions that `GITHUB_TOKEN` lacks.

## Material decisions

### D-B9-12. GitHub Actions is the execution plane

Use a GitHub-hosted Actions runner for canonical ledger preparation and proof.
Do not run the ledger workflow on the operator laptop or a self-hosted runner.

Local agents create Issues, comments, and work products. They do not edit or
push canonical ledger files. The operator manually starts one Agent0 workflow
for one accepted command.

The workflow:

1. reads the command and the current canonical `main` ref;
2. builds one deterministic ledger candidate;
3. runs replay, schema, idempotency, money, and supply checks;
4. pushes one candidate branch with the repository `GITHUB_TOKEN`;
5. reports the compare URL, candidate commit, predecessor, and proof hashes.

The operator opens the pull request. This manual step avoids hidden chaining
and the recursive workflow limits of `GITHUB_TOKEN`.

Rejected alternative: a local App or daemon adds a hidden runtime, local key
storage, lifecycle work, and another failure surface.

### D-B9-13. A trusted pull-request workflow is the canonical guard

Use one trusted `pull_request_target` workflow for every pull request that can
change protocol or ledger paths.

The workflow uses code from canonical `main`. It treats every candidate file
as untrusted data. It never checks out or runs code from the pull request.

For a ledger candidate, the guard rebuilds the expected transaction from the
bound command and predecessor. It requires byte equality, the next sequence,
one idempotency key, exact replay, valid money, and valid supply.

For a non-ledger pull request, the same check rejects any hidden protocol path
or workflow change that can weaken the ledger boundary.

After the repository becomes public, one branch ruleset targets `main`. It:

- requires a pull request;
- requires the trusted ledger check;
- requires linear history;
- blocks force pushes and deletion;
- grants no bypass actor, role, team, deploy key, workflow, or App.

This one ruleset replaces the previous App-only writer ruleset and separate
no-bypass safety ruleset.

### D-B9-14. GitHub evidence replaces local guards

Do not install or use the local shared lock, local epoch guard, dedicated
Windows writer accounts, local App keys, or local Git transport keys.

Before activation, disable every legacy write workflow and document every
legacy command as retired for canonical publication. After activation, the
trusted pull-request check rejects legacy ledger changes.

The project has one operator. The operator starts one ledger workflow at a
time. Each command remains in a GitHub Issue or comment, so a stopped or
replaced workflow run cannot lose the command.

The candidate binds the current predecessor. If `main` changes, the guard
rejects the stale candidate. The operator starts a new run against the new
predecessor.

This predecessor check and GitHub merge replace the local lock. Idempotency
replaces retry guessing. Canonical Git history replaces a local epoch file.

### D-B9-15. No custom GitHub App in the first pilot

The first pilot uses the built-in repository `GITHUB_TOKEN`. It does not create
or install a custom GitHub App.

A custom App would add:

- a stable machine identity that rulesets can name;
- short-lived tokens across selected repositories;
- automatic cross-repository Domain-to-root access;
- automatic pull-request chaining or merge without the operator step.

The first pilot does not need these properties. The operator controls every
participant and accepts manual starts, pull requests, and merges.

Without a custom App, the first pilot loses automatic Domain-to-root dispatch,
automatic merge, and a separate App actor in the audit log. It does not lose
ledger correctness, replay, idempotency, money checks, or Git history.

Revisit this decision when one of these events occurs:

1. the root workflow must read a private Domain repository automatically;
2. an external participant requires automatic Domain-to-root dispatch;
3. manual pull-request creation or merge becomes a measured bottleneck;
4. a required GitHub rule cannot identify the built-in Actions path safely.

At that time, use the smallest App. Prefer an App token inside Actions. Do not
add a separate App server unless an external webhook needs it.

### D-B9-16. Private canonical pilot precedes public enforcement

Activation occurs while the root is private. The activation pull request is a
real canonical ledger mutation. The operator must approve its exact bundle.

Remote rule enforcement remains `DEFERRED` during the private pilot. This is an
accepted temporary trust reduction because every participant and push
credential remains under operator control.

Complete at least two real E2E tasks. Retain every Issue, workflow run, pull
request, commit, escrow, payment, retry, replay, and recovery record.

Before public visibility:

- every pilot task is terminal;
- pilot escrow and pending payments are zero;
- ledger, money, and supply checks pass;
- exact replay matches canonical state;
- the current tree and reachable history pass the exposure audit.

Then make the root public and apply the single branch ruleset. External
participation remains closed until positive and negative remote checks pass.

## Protected boundaries

- GitHub `main` is the only canonical ledger location.
- Only an exact validated transaction can enter canonical history.
- Pull-request code never executes inside the trusted ledger guard.
- v1 and vNext are never authoritative at the same time.
- A retry never repeats money.
- A post-activation failure uses append-only forward repair.
- Private ruleset absence stays visible as `DEFERRED`.
- Public participation stays closed until remote enforcement is `PASS`.

## Ceiling and observable revisit trigger

Ceiling: one operator, manually started local agents, manual workflow dispatch,
manual pull-request creation, and manual merge for one canonical root.

Revisit when the first private Domain needs automatic source verification, an
external participant enters, or manual GitHub steps block useful throughput.

## Migration and recovery

- Rollout: replace local authority hooks with GitHub workflows, rehearse without
  a ledger write, approve one exact activation pull request, run the private
  pilot, audit exposure, then enable public enforcement.
- Replay and idempotence: every command has one immutable GitHub source and one
  idempotency key. Rebuild every derived byte before merge.
- Chosen recovery: before activation, discard the candidate. After activation,
  create an append-only repair through the same GitHub pull-request path.
- Recovery-mode evidence: Spec 1.0 R-B9-08 already selects forward recovery
  after sequence zero. The private canonical pilot does not change that rule.
- Partial failure: an unmerged branch has no canonical effect. A merged ledger
  event stays immutable. A failed projection remains pending and cannot repeat
  money.

## Verification hooks

- Unit tests prove candidate determinism, stale-predecessor rejection,
  idempotency, replay, money, supply, and forward repair.
- A workflow fixture proves that the trusted guard uses base code and treats
  pull-request files as data.
- A no-write rehearsal proves the exact activation candidate and workflow
  inputs before the operator approves the live pull request.
- GitHub run, pull-request, review, and commit records prove each canonical
  pilot transaction.
- The pilot report proves S-80.
- The exposure audit and public settings readback prove S-81.

## Downstream state

- Tasks: replace the proposed Tasks 2.2 with an active runbook bound to Design
  1.3. Do not add a Tasks approval gate.
- Implementation and tests: local guard and App assumptions are stale. Replace
  them before activation.
- Verification: prior dormant results remain historical evidence. They do not
  prove Spec 1.1 or the live private pilot.

## Unknowns and blockers

- Exact activation bytes do not exist. This blocks only the first canonical
  ledger merge.
- The trusted GitHub workflows do not exist. This blocks activation.
- Legacy write workflows still have canonical write credentials. This blocks
  activation.
- The exposure audit is not complete. This blocks public visibility, not the
  private pilot.
- Public ruleset proof is unavailable while the root is private. Record it as
  `DEFERRED`. It blocks external participation, not the private pilot.
