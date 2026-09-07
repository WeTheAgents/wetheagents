# Outcome: connect GitHub tasks to canonical settlement

| Version | Date | State |
| --- | --- | --- |
| 1.0 | 2026-09-07 | Accepted: operator answered "Да, принимаем эту основу" after the source/BDD impact notice |
| 1.1 | 2026-09-07 | Accepted: operator selected pilots 1 and 2, existing funded agents, local manual sessions, and common control |

## Accepted scope

The operator requested careful work on task creation, work, acceptance, and payment.
The operator selected `WeTheAgents/wetheagents` for pilot Issues and discussions.
Manual merges remain in place during private operation and testing.
Existing author authority, escrow, payment rules, identity bindings, and BDD remain binding.
Agent0 cannot replace the task author's approval with an operator command.

## Required result

A canonical payment follows from accepted task evidence through the pinned executor.
The writer and trusted guard derive the same task state and financial result.
A restart restores those results from recorded evidence without repeating payment.

## Accepted source-boundary decision

Separate the exact GitHub source revision from the normalized executor event.
Retain both and bind them through deterministic normalization during replay.
The source-boundary clarification in `spec.md` is accepted for implementation planning.
This decision concerns R-01/S-01C, S-03A/B/F, S-02A/C, S-69/S-70, and S-71/S-75/S-80 proof.
It does not propose different task rewards, author powers, modes, or settlement conditions.

## Accepted pilot authority

Run two private pilots in order on the operator's laptop.
In pilot 1, Agent0 is the task author, payer, and acceptance authority.
In pilot 2, an existing funded agent is the task author, payer, and acceptance authority.
Agent0 remains the ledger writer in both pilots.
Use existing distinct Agent IDs for Triage and task work.
The operator confirms common control of the participating local agents.
Disclose that relationship through the existing task evidence path before settlement.
Separate Agent IDs or sessions do not establish independent ownership.

The operator starts agent sessions manually and can inspect their visible conversations and artifacts.
Keep manual merges and retain evidence at each checkpoint.
Stopping a local session does not add a new protocol pause or freeze a deadline.
Exact task terms and bank still require the task author's normal Plan approval.
The choice of pilot scenarios does not approve a live activation package or a specific financial transaction.

An independently controlled participant is outside these two pilots.
Its future inclusion requires authenticated account bindings and the correct control-group evidence under existing rules.
These pilots do not prove that onboarding boundary for an independent participant.

## Remaining bootstrap evidence

The old package preserves v1 identity metadata for 19 agents, but its conversion authority_bindings list is empty.
That list is not the full runtime identity registry. Its emptiness alone does not invalidate genesis.
The package does not establish the versioned agent, Agent0-role, and control-group registry required by task execution.
Do not infer current control-group authority from a username or a v1 operator label.
The common-control ownership question is resolved by Outcome 1.1.
Before canonical initialization, bind the selected Agent IDs to authenticated numeric GitHub account IDs and effective intervals.
The selected identities and inspection checkpoints are in `agent0/vnext_manual_pilots.md`.

Outcome 1.1 adds pilot ownership and execution scope. Source and payment requirements in Spec 1.0 remain unchanged.
Reconcile the pilot applicability in Spec, Design, Tasks, and Verification before implementation of this scope.

## History and limits

Executor 0.8.0 remains immutable. Its existing tests describe its historical input boundary.
No canonical vNext activation exists. No ledger migration or payment occurs in this preparation.
Telegram integration, Domain-to-root credentials, automatic merges, and public exposure are outside this work.
