# Design delta: Block 9 lean projection transport

Decision status: `proposed for exact operator acceptance; not active`

Design revision: `1.1`

Date: `2026-08-23`

Base Design: revision `1.0`, exact SHA-256
`70026e7551acc7c5f1ae56b1d49962045dec3b70e0647aaf3b5040f36e856283`

Governing Outcome: Block 9 Outcome 1.0, unchanged.

Governing Spec: Block 9 Spec 1.0, unchanged.

Authority state: the operator accepted the lean direction in the current Codex
task. This exact delta still needs an exact acceptance after review. Until that
act, accepted Design 1.0 remains authoritative.

## One decision

Keep the dedicated ledger GitHub App and both layered branch rulesets as
activation prerequisites. Defer creation and installation of the separate
projection GitHub App until the first external comment or label projection is
actually requested.

This removes one credential and one GitHub installation from the initial
cutover. It does not combine ledger and projection permissions.

## Why this is the smallest safe cut

The ledger App enforces the important remote rule: only the authenticated
Agent0 transport may fast-forward the canonical ref. It remains required.

External comments and labels are not ledger state. Spec R-B9-09 already says a
projection failure leaves vNext authoritative, reports `projection_degraded`,
and retries later without repeating money. A deliberately deferred projection
transport can use that existing observable state.

Giving the ledger App Issues permission would be simpler only on paper. It
would let projection code hold canonical-ref write authority. A human PAT or
deploy key would also weaken the accepted Agent0 identity boundary. Both
alternatives remain rejected.

## Exact delta to Design 1.0

### D-B9-06 authority boundary

- Before activation, the dedicated ledger App remains installed only on the
  canonical repository with Metadata read and Contents write.
- The no-bypass safety ruleset and ledger-App-only writer-admission ruleset
  remain mandatory.
- The projection transport binding is an exact tagged value:
  - `active`: contains the pinned projection App and installation binding from
    Design 1.0; or
  - `deferred`: contains no App ID, installation ID, token, or credential.
- The cutover core binds that exact tagged value. Substitution between
  `active` and `deferred` invalidates the bundle.
- Ledger publication never uses a user PAT, deploy key, workflow token, or the
  projection App.

### D-B9-10 activation boundary

- Tracked root documentation, CLI help, Issue forms, and workflow guards still
  switch in the atomic activation tree.
- When projection transport is `deferred`, external comment and label intents
  start in `pending` state. Canonical operational status is immediately
  `projection_degraded` and lists each exact pending target.
- Missing projection transport does not block the ledger activation after all
  other accepted gates pass. It cannot change money or canonical files.

### D-B9-11 projection retry boundary

- The projector refuses to start while transport is `deferred`.
- Before the first retry, Group 2 provisioning is resumed for one narrow
  change: create the separate projection App with Metadata read and Issues
  write, prove it has no Contents or canonical-ref authority, and publish its
  exact versioned binding.
- That permission change requires an exact operator-approved environment diff.
- A later ledger transaction changes the transport tag from `deferred` to
  `active`. The projector then uses only the short-lived token for that pinned
  App and follows the unchanged idempotent reconciliation state machine.
- There is no fallback to the ledger App or a human credential.

## Unchanged protected boundaries

- One laptop, manual Agent0 cycles, unlimited downtime, no server, database,
  queue, daemon, scheduler, live migration, or dual write.
- Separate operator, Agent0, worker, and shadow Windows identities remain in
  the accepted Design. This delta does not weaken local key isolation.
- Money, exact approvals, append-only history, atomic Git publication, replay,
  recovery, writer inventories, shadow isolation, and retired-command rules
  are unchanged.
- Activation remains separate from rehearsal and still needs exact operator
  and Agent0 approvals.

## Verification hooks

The existing Block 9 tests must additionally prove:

1. a canonical `deferred` projection transport is accepted without an App
   binding;
2. a missing or forged tag, a tag/binding mismatch, or a credential fallback
   rejects;
3. activation with `deferred` transport publishes tracked public files and
   exact pending intents, then reports `projection_degraded`;
4. the projector performs no GitHub call while transport is `deferred`;
5. an exact later `active` binding permits the unchanged idempotent retry;
6. the projection App still cannot update the canonical ref.

## Ceiling and revisit trigger

This cut is valid while external comments and labels may remain pending for an
unbounded operator-approved interval. Return to Outcome/Spec/Design if public
projection convergence becomes an activation prerequisite, needs a deadline,
or must run automatically.

## Downstream status

- Design 1.0 remains accepted and current until this exact delta is accepted.
- Dormant code Groups 1, 3, and 4 are independent of this proposal.
- Group 5 projection code stays useful but needs the tagged transport delta.
- Groups 2, 7, and 8 need Tasks 2.1 after this delta is accepted.
- No account, key, App, ruleset, ledger, or GitHub state is changed by this
  document.
