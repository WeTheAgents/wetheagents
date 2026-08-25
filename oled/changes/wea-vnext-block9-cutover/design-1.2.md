# Design delta: Block 9 staged public rollout

Status: `Proposed for exact operator acceptance. Not active.`

Revision: `1.2`

Date: `2026-08-23`

Accepted base Design 1.0 SHA-256:
`70026e7551acc7c5f1ae56b1d49962045dec3b70e0647aaf3b5040f36e856283`

Accepted lean Design 1.1 SHA-256:
`ffd0ad44323e596b6c23f53aba6d50d214dbc20668f260cd8b37ba7a2ab77b1a`

Accepted Outcome 1.0 and Spec 1.0 remain unchanged.

## Authority and purpose

The operator selected the public-root path with one condition. The canonical
repository stays private through the manual restart and the first tests. It
becomes public only after those tests produce acceptable evidence.

This delta defines that order. It does not approve a GitHub mutation, restart,
ledger write, rehearsal, or activation.

## Material decision

Keep every protection from Designs 1.0 and 1.1. Do not replace the dedicated
ledger App, the two different rulesets, the epoch guard, local locks, exact
hashes, replay, recovery, two-run shadow proof, or separate rehearsal and
activation gates.

Use a staged transition:

1. Prepare an exact private-stage environment package. Do not mutate GitHub.
2. Apply that package only after its own exact operator approval.
3. Perform the manual restart while the canonical repository is private.
4. Run the first private-stage tests. Keep vNext inactive.
5. Mark unavailable remote protection proofs as `DEFERRED`, never as `PASS`.
6. Audit the current tree and Git history before any public exposure.
7. Prove the App and both rulesets in a disposable public repository.
8. Prepare an exact canonical-public transition package.
9. Change visibility only after exact approval of that package.
10. Freeze every writer before the visibility change.
11. Make the canonical root public. Apply the proven App and rulesets at once.
12. Run post-public positive and negative proofs. Keep vNext inactive.

Activation remains a later, separate gate.

## Evidence states

Use only these states for each required proof:

- `PASS`: direct evidence proves the required behavior in the named context.
- `DEFERRED`: the current private plan cannot provide the remote proof.
- `FAIL`: evidence contradicts the required behavior.
- `NOT RUN`: the proof has not started.

A local fixture can prove local behavior. It cannot prove a live GitHub
ruleset. A disposable repository can prove the mechanism. It cannot prove that
the canonical repository has received the same settings.

## Private-stage boundary

The first test stage may complete with remote ruleset checks marked
`DEFERRED`. It may not claim Group 2 complete. It may not activate vNext.

The private stage must still prove what the laptop can prove:

- only the intended local Agent0 path can reach the dormant writer;
- the epoch guard rejects the wrong epoch;
- local locks prevent concurrent publication attempts;
- exact approval hashes, replay, and recovery behave as designed;
- the two-run shadow comparison is deterministic;
- no canonical ledger or public projection was written.

## Public-transition boundary

Before public visibility, the exposure audit must cover the current tree and
reachable Git history. Any unresolved credential, private data, license, or
identity finding blocks the transition.

The exact transition package must name the repository ID, current revision,
target visibility, ledger App installation and scope, both ruleset payloads,
expected before state, expected after state, verification commands, and stop
conditions. Approval of this Design is not approval of that package.

All queues and writers must be stopped before the visibility change. A short
writer-free interval is acceptable because the operator permits downtime and
controls every participant from one laptop.

## Recovery after public exposure

Public exposure cannot be treated as confidentially reversible. If App or
ruleset installation fails after the repository becomes public, keep vNext
inactive and keep every writer frozen. Resume the approved setup from the last
verified step or prepare a new exact repair package.

Do not report a visibility rollback as removal of already exposed data. A
private setting can limit later access. It cannot erase prior exposure.

## Verification hooks

The later Tasks 2.2 must require evidence for:

- no GitHub mutation before exact package approval;
- private restart and smoke tests with honest `DEFERRED` remote results;
- a clean tree-and-history exposure audit;
- disposable public proof of the ledger App and both rulesets;
- an exact canonical-public transition approval;
- writer freeze during the transition;
- canonical App and ruleset settings after the transition;
- rejection of a user token, workflow token, deploy key, wrong App, direct
  push, force push, deletion, and stale epoch;
- vNext remaining inactive after the public transition tests.

## Downstream status

Tasks 2.1 remains the accepted task contract until this exact Design 1.2 is
accepted. After acceptance, prepare Tasks 2.2. It must reconcile Group 2 with
this staged order. It must not authorize any environment mutation by itself.

