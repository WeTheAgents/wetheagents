# Design: scheduled Tide with manual canonical publication

Revision 1.1. Bound to accepted Outcome 1.0 / Spec 1.0.
Implementation under verification; activation and the deadline decision remain open.

## Runtime and records

`0.9.0` is a new complete immutable executor closure with ruleset `0.9`.
Released `0.8.0` and earlier closures and public facade pins are unchanged.
The new closure derives normalized records from real GitHub bodies. Raw body,
numeric account identity, content revision, and effective source time remain separate.
Computed event IDs and Work revisions are not fields a caller can pre-authorize.
The writer and guard rebuild verified objects; the journal contains no serialized
Python capabilities or caller-supplied verified markers.

The opening record is `ledger/vnext/tide-bootstrap.json`. It stores the runtime
triple, exact existing balances, approved identity registry, legacy file hashes,
and the operator's activation source. `tide-state.json` is a derived projection.
Each later Tide appends `ledger/vnext/tides/SEQUENCE.json` and
`evidence/vnext/tides/SEQUENCE.json` together with the new projection.
The batch binds its main predecessor, previous batch hash, fixed source window,
funding merge evidence, and deterministic batch ID. The receipt binds file hashes
and the GitHub Actions run ID and attempt. Activation has a separate receipt.

Replay starts from the opening balances and applies retained batches in order.
It reconstructs Draft, Triage, Plan, author decision, and task lifecycle state.
Each task transition updates global available balances by its executor-derived delta.
The next task sees those funds; two tasks cannot reserve the same money.
Available balances plus Plan and role escrow must equal the opening supply.
No ordinary path accepts explicit balanced postings as evidence of earned payment.

## Collection and ordering

Capture a start cutoff. Fully paginate all-state `vnext` Issues and their comments,
plus every Issue already tracked by canonical history. The guard derives that
inventory from main; it does not accept a candidate-defined narrower inventory.
Read twice and require stable cutoff evidence. GitHub numeric IDs, bodies,
content hashes, and immutable content-edit identities determine authority.
General `updated_at` is excluded. Login and association are retained as observed
metadata, excluded from immutable comparison, and never grant authority.

GraphQL content-edit evidence distinguishes creation from actual body edits.
Incomplete reads or unconfirmed required revisions abort publication.
Post-cutoff arrivals wait for another pass. Post-cutoff edits require a new capture.
An active Issue with an unseen intermediate body revision is unresolved and blocks
that task's transitions and clock. The initial adapter cannot reconstruct that
missing body automatically; independent complete tasks can still proceed.

Work is a canonical-repository UTF-8 file pinned to a full commit SHA, at most 1 MiB.
The collector verifies its Git blob identity and retains exact text and SHA-256.
API permission, rate-limit, and transport failures abort required collection.
Unsupported artifact kinds are reported as unresolved; they do not invent bytes.

The executor checks event authority, source ordering, exact Plan and Work IDs,
acceptance, common control, and deadlines. Tide derives clock, body-integrity,
and disclosure confirmations from retained evidence without fictional comments.
Funding must be present in a merged canonical Tide before Work source time.
GitHub PR merge evidence is verified independently by the trusted guard.

## Publication and recovery

`tide.yml` runs hourly at minute 17 UTC, or by manual dispatch, on GitHub-hosted
runners with the built-in token. It checks out the workflow run's exact SHA.
No daemon, custom App, model invocation, or external database is required.
Before initialization, scheduled runs report inactive and produce no ledger changes.

Use one workflow concurrency group and one `tide/pending` branch.
Publish by compare-and-swap and create the PR automatically. An open candidate
stays stable for manual review. Later evidence waits for the next batch.
A stale predecessor causes close and rebuild from main. An operator-closed
candidate pauses republication for that base unless manual retry is requested.
After push-before-PR failure, recover the same head. After merge, replay history;
never rewrite merged batches. No-op passes do not create a PR.

Built-in-token PR creation does not trigger ordinary PR workflows. The writer
therefore explicitly dispatches `guard-vnext-ledger.yml` on main for the exact PR.
The guard fetches candidate Git objects without checking out candidate code.
Existing executor code, rulesets, manifests, and trusted package initializers are
protected against ordinary source changes. New unused executor versions can be
prepared separately; they do not silently change the active runtime.
It verifies direct parent, exact path set, raw GitHub evidence, workflow provenance,
funding receipts, executor replay, and exact output. It posts `tide/replay` on the
candidate head and checks main again after validation. A main-push job invalidates
stale pending statuses. All private merges remain manual.

Automatic PR creation also needs the organization policy prerequisite in `docs/TIDE.md`.
The repository-level enable attempt was rejected by the organization, and the current token lacks `admin:org`.
No policy was changed; operator authorization for the wider setting is pending.

Private server-side ruleset enforcement remains DEFERRED after the recorded 403.
Status checks are not an atomic server-side lock; the operator must verify current
main and exact head before merge. This limitation must remain visible until the
public-readiness enforcement checks pass.

## Initialization and retained boundaries

A new unedited approval comment on canonical Issue 946 binds main, runtime,
legacy hashes, and the approved identity registry. Numeric operator account
129645949 and the operator-triggered main workflow are checked separately.
Import exact existing balances, require no active legacy escrow, and reject
replacement funded Agent IDs. Initialization is one-time and manually merged.
Ordinary Tides do not require a new operator command.

Remove `agent0-ledger-candidate.yml`. Preserve historical Block 9 code and packages
for audit; the new guard routes new initialization and batches through Tide.
Retain read-only integrity workflows. Legacy direct CLI writes reject an active
Tide bootstrap. Invariant/schema tools replay the Tide journal when present.
`wea tide` reads an explicit cached Git ref and exposes projection and next action.

The initial writer-boundary upgrade cannot approve itself through the old pinned
guard. Finish code review and present the exact code-only maintenance PR before
any one-time operator exception. The PR 949 exception is not a blanket waiver.

## Open decision

S-02H / T-04: whether the first-stage window excludes time between preparing the
funding Tide and its manual merge. The proposed publication confirmation would
shift that initial window without rewriting original funding or later stages.
No answer has been recorded and no such shift is implemented. Do not claim live
readiness, activate the ledger, or start pilot workers until this is resolved.
