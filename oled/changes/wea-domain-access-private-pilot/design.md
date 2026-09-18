# Accepted Design: CLI and GitHub Access journal

Revision 0.5, accepted 2026-09-18; bound to accepted Outcome 0.5 and Spec 0.5.
CLI, retained GitHub, no per-Access PR, and two trips before the funded WTA task are the operator's selected direction.
The operator authorized implementation with the simplifications below. Activation remains separate.

## Two kinds of change

Code changes retain review and manual merge.
The existing trusted-main writer guard intentionally rejects introduction of
`access.yml`; it cannot authorize its own expanded writer universe. Use the
existing one-time, exact-code maintenance procedure documented in
`oled/changes/wea-vnext-tide/design.md`. Finish review and present the exact PR
for the operator's installation decision. Do not falsify its failed status,
weaken the guard, or treat earlier infrastructure exceptions as authorization.
Routine Access uses CLI, a GitHub Issue, and a dedicated trusted Actions handler.
The handler appends Access decisions directly to a private Git journal branch, without PRs.
Tide financial batches retain their existing publication, schema, and manual merge path.

This is a new Access publication surface, accepted with delta 0.5.
Implementation explicitly updates that boundary and its tests; deployment still requires manual merge and exact activation.
It must not add a financial ledger writer or change a released executor closure.

## Proposed path

Accepted commands implemented by this change:

```text
wea access grant --agent Codex-19@codex --domain circle-1
wea access show --agent Codex-19@codex
```

1. CLI resolves the configured private root, account, registry, and explicit authority context.
2. It retains a request ID before submitting a structured Issue comment through GitHub authentication.
3. The trusted handler reads that source, canonical identity evidence, the pinned registry, and the complete Access journal.
4. It validates authority, registration, idempotency, and overlap, then records acceptance and the seven-day interval.
5. It appends the decision by a fast-forward ref update against the captured predecessor.
6. It posts an Issue receipt linking the commit. CLI reads the journal before reporting success.

A pending comment is a request, not a grant. The receipt is a readable view of the committed decision.
No further human approval is required for a valid request already issued by the operator or Agent0.
CLI waits for a bounded interval and then returns pending with the request ID if processing is unfinished.
A later read resolves that same operation.

## GitHub evidence and recovery source

Use one configured private WEA Issue for this pilot's requests and receipts.
A dedicated `wea-access` marker separates intake from task declarations and funded Draft lookup.
Use a `wea/access-journal` branch containing only fixed-format control-plane records.
The branch and Issue ID become activation configuration. No journal has been activated; existing private Issue #997 is the pilot intake candidate.
Do not merge this data branch into main during ordinary operation.

Retain exact source bytes/hashes, numeric author, source IDs, creation/update times, and authority snapshots.
Each decision retains request ID, Domain bytes/hash, recipient, disposition, accepted interval, and protocol reference. Git ancestry supplies ordering; there is no additional record hash chain.
Publication evidence links the Actions run, trusted code SHA, canonical identity-state SHA, and journal parent.
Pin the installed Access and imported vNext code by content in genesis, with its reviewed code SHA. A different closure fails closed. There is one record format and no migration/version dispatcher.
Fresh processes rebuild from genesis and ordered records; projections and local caches are disposable.

Issues make the history readable. Git commits retain captured evidence after a comment edit or deletion.
The pilot trusts the operator's repository administration, as the existing private deployment does.
Git object verification, linear ancestry, and append-only tree validation detect inconsistent retained data; they cannot prevent administrator deletion or complete history replacement.
Verify runtime write restrictions and recovery from a separate clone before activation; this proposal does not establish those checks.

## Trusted handler and authority

Execute reviewed default-branch code only, never code supplied through comments, PRs, forks, or journal records.
Accept only the configured root repository and Issue; reject PR comments and foreign repositories.
An `issue_comment` trigger requests processing. Explicit manual dispatch provides recovery without a new periodic loop.
Bot receipts never re-enter intake. Every run reconciles pending retained requests; events are only wake-up hints.
Do not treat workflow concurrency as a durable queue or FIFO ordering guarantee.

Resolve the numeric source account against canonical identity evidence.
Operator sources match canonical operator approval; Agent0 sources name the exact active role binding and subject.
Authority must hold at declaration and acceptance. The recipient must be registered at acceptance.
The declared subject needs a valid role binding; `WEA_AGENT` alone is not evidence of that binding.
Only then construct `VerifiedAccessAuthority`.

GitHub authentication proves account control, not the originating local agent session.
This private pilot trusts all holders of the operator credentials to select roles canonically bound to that account.
Another such session can select `pilot-agent0-role-v1`; the proposed checks cannot distinguish it from the assigned Agent0 session.
Retain numeric authenticated account and declared agent attribution as separate fields; do not label attribution as independently verified session identity.
Separate credentials or a verified session capability are a later scope if independent session enforcement becomes required.

The library requires globally unique binding IDs and an exact retained authority for every historical grant.
Derive a per-declaration witness ID from the canonical role binding ID/version, evidence hash, and source revision.
Use this witness ID as the library binding ID and retain the canonical binding separately.
Keep all earlier witnesses so successive grants under one role preserve valid history.

## Clock and acknowledgement

Take `accepted_at` from the trusted Actions runtime UTC clock immediately before preparing publication.
Retain that time as replay input. Reject caller start, duration, expiry, and backdating fields.
Authority and overlap checks use that exact time; `ends_at = accepted_at + 604800 seconds`.
The grant becomes usable only after the atomic journal ref update succeeds.
A small publication delay consumes part of the interval; there is no human review queue in that interval.

If the predecessor changes, discard the unpublished candidate and revalidate with a fresh acceptance time.
If publication has an uncertain outcome, read the remote journal before recomputing anything.
An already committed decision retains its original timestamp, including after retries.
A late observation reports expired and never resets the interval.

## Serialization, retry, and failures

Use one journal across all domains because overlap is global per agent.
Each candidate has exactly one parent: the head used for validation.
A non-forced fast-forward ref update serializes competing appends; a loser must revalidate against the winner.
Never merge divergent candidates or force-push journal history. Local locks and run ordering are not authority.

Scope idempotency to root repository, authenticated author, and CLI-generated request ID.
An identical retry reuses the decision. A conflicting payload under that key is rejected.
Resolve uncertain comment creation by reading back the key before retrying.
Duplicate comments retain their source references but produce at most one logical effect.
Reject sources edited before capture. Accepted source bytes survive later edits or deletion.

Before commit failure: no grant exists; resume from the retained request.
After commit but before receipt: the grant exists; repair only its Issue receipt.
After response loss: read the result by request key.
On integrity failure: stop new grants and expose the error, preserving the last valid history.
Recovery never rewrites an accepted interval, financial history, or task state.

## Expiry and observations

Fresh readback derives status from `[starts_at, ends_at)` and derives expiry at the original endpoint.
No scheduler, append, PR, receipt, or human action is needed to make Access expire.
A later observation receipt records its actual query time separately from `ends_at`.
An outdated Issue label cannot extend Access. Historical evaluation is labeled and does not count as real elapsed time.

## Smallest adequate path and tradeoffs

Reuse the Domain/Access library, canonical identity reads, existing GitHub CLI transport, and trusted Actions patterns.
Legacy `wea assign` is not Access. Tide financial batches do not need an Access extension.
A comment-only store loses captured evidence after edits/deletion; a local-only store fails the requested GitHub recovery path.
The proposed journal adds a narrow writer and reconciliation code, while removing per-operation PRs and a local authoritative database.
GitHub availability remains necessary for issuance and fresh canonical readback.

Expected surfaces: CLI, Access adapter/journal replay, one workflow, focused tests, and approved operating/boundary documentation.
No scanner, task executor, admission, payment, or GitHub permission policy changes belong to this stage.
The useful parser repair belongs to the separately funded #997 cycle, after Access is ready; see [cycle.md](cycle.md).

The bounded pilot stops before a 501st decision. Comment reads support 20 full
pages of 100 comments plus a completion request, and fail explicitly if the
bounded capture cannot reach its end. Receipts count toward Issue comment volume.
Existing journal history remains readable at the decision limit. This is a capacity error, not expiry or revocation.
Exact deployment, CLI recovery and observation instructions are in `docs/ACCESS.md`.

## Proving and activation

Implementation ceiling: three new Python modules, one workflow, focused tests and existing routing/boundary documentation; estimate 800–1200 production lines. Revisit at more than three additional files or 150 lines beyond that estimate, or any task/financial write. Use standard library and existing Tide GitHub capture/identity reads. The intake Issue is selected by exact activation; #997 can host the private pilot without another Issue. Recovery is forward append/readback, never rewriting an interval. Proof hooks are the focused Access runtime/CLI tests, existing library and runtime-boundary suites, independent review, and a separate-process readback after activation. Until run, these are planned evidence only.

DA-01..08 require authority, concurrency, retry, replay, failure recovery, clock, expiry, isolation, and activation evidence.
The existing 28 library tests do not cover this handler.
Before activation, prove trusted execution, publication permissions, journal validation, and independent readback in the private root.
Bind exact reviewed protocol, journal genesis, intake Issue, and fresh-source cutoff to the operator's activation decision.
Previously posted declarations acquire no retrospective effects.
Disabling issuance preserves earlier grants and their original expiry.

Platform references checked 2026-09-18:

- [GitHub Actions events](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows): Issue comments can trigger a workflow defined on the default branch.
- [Git references API](https://docs.github.com/en/rest/git/refs): non-forced updates require fast-forward history.

These platform primitives support the proposal; they do not prove a working Access path in WEA.

## Steward addition, revision 0.3

The operator appointed Agent0 as Steward. The accepted manual responsibility and initial handoff are recorded in [steward.md](steward.md).
Do not add `steward` to `VerifiedAccessAuthority`, change registry v1, or infer financial or repository rights from that record.
A named Steward supplies context and handoff for this pilot; it is not a new protocol gate on every Access grant.
An automated appointment/succession protocol is outside this draft. No separate Steward service, identity, or grant is needed for this assignment.
DA-01..08 retain their 0.2 behavior; ST-01 adds the explicit role boundary, and C1-P01 includes the first handoff.

## Full cycle scope, revision 0.4

The operator now requests two Access grants plus WTA, result, and Release; see [cycle.md](cycle.md).
The proposed Access implementation is unchanged. Reuse existing Ranked/Tide/Release paths for task #997, with one 10 WEA prize.
There is no second financial writer, new competitive mode, or implicit funding from Access.
