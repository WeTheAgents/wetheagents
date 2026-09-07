# Accepted delta: source evidence and task settlement

| Version | Date | Authority |
| --- | --- | --- |
| 1.0 | 2026-09-07 | Operator accepted the source-boundary and task-derived payment clarification; Outcome 1.0 |

Status: accepted target contract, not implemented or live evidence.
Baseline: accepted recreation R-01 and Work requirements; Block 9 Spec 1.1.

Pilot applicability: accepted Outcome 1.1 selects Agent0-funded and agent-funded tasks under common operator control.
This selection changes no protocol rule in Spec 1.0.
For LC-01 and LC-03, exercise both author identities and retain their exact account and control-group bindings.
For the agent-funded case, prove that an Agent0 transport command cannot replace the agent author's Plan approval or acceptance.
For common-control Work, prove that missing required disclosure prevents settlement and confirmed disclosure permits the existing authorized path.
Manual session interruption does not create a protocol pause. Replay applies existing deadlines and pause rules.

## Observed mismatch

The public Work format is a Markdown declaration containing `agent_id`, `type`, and `source`.
It excludes caller-provided Work ID, stage, and revision.
Executor 0.8.0 requires `GitHubEvent.body` to equal the normalized `LifecycleEvent.source_snapshot` JSON.
The lifecycle test helper constructs that JSON as its synthetic GitHub body.
Directly providing a valid raw Markdown declaration fails the source-content check.

## R-LC-01: exact source and derived event

The adapter MUST retain the exact GitHub body and authenticated source metadata.
Source metadata MUST bind repository, Issue or comment, revision, actor, and effective time.
The adapter MUST derive the normalized event from that source and the prior canonical task state.
Caller-supplied actor, timestamp, eligibility, or financial postings MUST NOT substitute for the required authority or evidence.
The system MUST preserve existing author, validator, identity, and control-disclosure rules.
Replay MUST derive the normalized event again and reject a mismatch.
A missing, ambiguous, substituted, or incomplete required source MUST prevent canonical publication.
Previously recorded source bytes MUST remain unchanged after a remote edit or deletion.
Edit revisions MUST follow the existing immutable-revision rule and separate-comment fallback.

### LC-01: real declaration, accepted normalization

- GIVEN a valid raw declaration from a bound participant and complete confirmed source evidence.
- WHEN the trusted adapter derives the event and invokes the pinned executor.
- THEN the system creates the existing BDD effects and retains the raw source separately.
- THEN the participant does not supply internal Work IDs, stage IDs, or GitHub-assigned times.

### LC-02: source or derived event substitution

- GIVEN missing source bytes, a changed body, actor, revision, time, normalized event, or incomplete read boundary.
- WHEN the writer or trusted guard checks the candidate.
- THEN it rejects the candidate without canonical task or money changes.
- GIVEN a later remote edit or deletion of already accepted evidence.
- WHEN the system replays canonical history.
- THEN it uses the retained original evidence under its pinned runtime.

## R-LC-02: task-derived money

For ordinary task transactions, the writer MUST derive financial changes from the executor result.
Balanced postings alone MUST NOT authorize a task payment.
The trusted guard MUST reproduce the source-to-task-to-money derivation before accepting a candidate.
Task evidence and its financial effects MUST enter canonical history in the same accepted transaction.
Existing financial correction remains a distinct authority path.

### LC-03: payment and recovery

- GIVEN a funded Plan and valid Work acceptance under its existing mode.
- WHEN the executor produces settlement and the operator merges the checked candidate.
- THEN the recorded evidence and financial result become authoritative together.
- GIVEN a retry or restart before or after that merge.
- WHEN the system replays the predecessor and accepted events.
- THEN it preserves exact task state, balances, escrow, and payment idempotency.
- GIVEN balanced postings without the required task evidence or different postings from the executor result.
- WHEN the writer or guard checks the candidate.
- THEN it rejects the candidate.

## Existing behavior to preserve

Author Plan approval is separate from operator transport approval.
Invalid declarations do not block later valid declarations within the accepted ordering rules.
No general claim exists. The S-80 claim step applies only to an applicable Duel path.
Raw Work revisions, common-control disclosure, deadlines, pauses, refunds, and mode semantics retain their accepted BDD.

## Evidence plan

Extend current authority, Work, activation, and settlement tests with raw GitHub input.
Add integration coverage for disk replay, stale candidates, source substitution, and payments without executor evidence.
Do not mark existing synthetic tests as live GitHub or persistence proof.
