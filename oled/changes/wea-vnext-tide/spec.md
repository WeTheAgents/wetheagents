# Spec: a Tide is one checked settlement batch

> Accepted display extension, 2026-09-10: `../wea-task-labels/spec.md` adds L-01 through L-06. Labels project canonical state without changing T-04/T-05/T-06 or released executor semantics.

> Accepted extension, 2026-09-09: `../wea-tide-participants/spec.md` adds P-01 through P-08 for post-initialization admission. It extends T-01/T-02/T-03/T-06. T-07 initialization remains one-time. Schema 1 and task executor 0.9.0 retain historical semantics; schema 2 pins participant executor 0.10.0.

Version 1.0; accepted Outcome 1.0. Verification status and exact evidence are in `verification.md`.
On 2026-09-09 the operator chose to retain the existing S-02H first-stage clock for the private pilot. Waiting for manual funding merge consumes that window; no publication-time shift is implemented.
Affected parent boundaries: S-01C, S-02A/C/H, S-03A/B/F, S-69/S-70, S-71/S-75/S-80.
Existing task-mode and acceptance semantics remain unchanged.

## T-01: authenticated collection boundary

Tide MUST capture a fixed cutoff before collection and retain exact source bytes, IDs, authorship, revisions, and ordering.
Only evidence at or before the cutoff belongs to that pass.
Numeric account identity determines authority; login and association are retained observations.
The guard derives already tracked Issues from canonical history, including removed labels.
An incomplete read or ambiguous required revision MUST prevent publication and cursor advancement.
Sources after the cutoff remain available to a later pass.
Previously merged source evidence remains replayable after remote edits or deletion.

Proof: collection across pagination, concurrent arrivals, read failure, and changed revisions; compare the retained batch and next cursor.

## T-02: deterministic task and financial replay

Tide MUST normalize retained sources through the pinned runtime and apply each admissible event once in canonical order.
All events in the batch operate on the result of earlier events in that batch and the canonical predecessor.
The writer and guard MUST derive task state and financial effects from the same inputs.
Explicit balanced postings without executor evidence MUST NOT authorize ordinary task payments.
Historical runtime references MUST remain explicit during replay.

Proof: two tasks in one Tide, insufficient shared payer funds, altered derived data, and identical fresh-process replay.

## T-03: unresolved and invalid input

An invalid declaration MUST NOT create state or money effects.
A case requiring an absent authorized decision MUST remain unresolved with its source reference and reason.
Neither Tide nor the operator's merge substitutes for a required author or role decision.
Unresolved task dependencies MUST NOT be skipped to pay dependent work.
Missing intermediate active-Issue body revisions block that task, including clock settlement.
Independent admissible work MAY proceed when its evidence and ordering are complete.

Proof: invalid declaration followed by a valid declaration; unresolved task alongside independent valid work; forged author or common-control evidence.

## T-04: canonical funding and settlement

Funding MUST reach canonical main before funded Work can qualify.
An unmerged funding candidate MUST NOT authorize Work or payment.
A batch MAY fund multiple tasks or settle multiple already funded tasks.
The ledger changes and their retained task evidence MUST merge together.
A Deliverable PR merge alone MUST NOT imply payment.

Proof: Work against unmerged funding, multiple funded tasks, and candidate-versus-canonical readback.

## T-05: retry, concurrency, and manual merge

Only one unresolved candidate for the canonical predecessor MAY be pending.
Tide MUST NOT duplicate a pending candidate or accumulate independent competing ledger branches.
A stale candidate MUST be rejected and rebuilt from current main.
A retry before or after merge MUST NOT repeat a payment.
No-op passes MUST NOT create an empty ledger PR.
During private testing, Tide MUST NOT merge its own PR.

Proof: concurrent attempts, pending PR, close-without-merge, main advance, retry, and crash/restart.

## T-06: writer and workflow authority

The technical writer identity is tide@system. This role MUST NOT mint a balance or impersonate a task participant.
Only trusted main code MAY collect sources and build a candidate.
The guard MUST treat candidate content as data and replay it with trusted code.
Old Agent0 single-command and legacy automatic writer Actions MUST NOT remain competing active writers.
Human decisions and workflow provenance MUST be recorded separately.

Proof: workflow inventory; rejected candidate code execution, wrong workflow/ref, changed evidence, and mixed code-plus-ledger PR.

## T-07: explicit initialization

- **GIVEN:** No canonical vNext ledger exists and legacy active escrow is zero.
- **WHEN:** The operator supplies a new exact approval on canonical Issue 946 and dispatches trusted Tide on that main commit.
- **THEN:** Tide imports existing balances unchanged, pins the approved identities and runtime, and prepares one initialization PR.
- **THEN:** Wrong source identity, edited approval, changed predecessor or hashes, unapproved binding subject, and altered balances fail validation.
- **THEN:** Ordinary scheduling before initialization cannot activate the ledger. Manual merge remains required.

This makes the retained one-time initialization boundary concrete for Tide; it does not authorize a new mint or public exposure.

## Executable scenario interpretation

| Scenario | Given | When | Then |
| --- | --- | --- | --- |
| T-01 | Canonical Issues and a fixed cutoff | Collector and guard read complete sources | Retain exact content authority; do not advance on incomplete reads or omit tracked Issues |
| T-02 | Retained sources and current balances | Multiple tasks replay in one batch | Derive each admissible effect once, reject overspending and unsupported transfers |
| T-03 | An invalid or unresolved declaration | Tide processes its dependent and independent work | Preserve the reason, block dependent effects, allow independent authorized transitions |
| T-04 | A proposed funding batch | Work arrives before or after its authenticated merge | Only post-funding Work can qualify; deliverable merge does not imply acceptance |
| T-05 | Pending, interrupted, closed, merged, or stale publication | Another Tide runs | Preserve one candidate, recover without duplicate effect, rebuild stale bases, never auto-merge |
| T-06 | Trusted main and candidate Git objects | The guard checks a proposed ledger write | Execute trusted code only; reject wrong provenance, mixed paths, and altered derived state |
