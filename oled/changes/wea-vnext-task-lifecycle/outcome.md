# Outcome: connect GitHub tasks to canonical settlement

| Version | Date | State |
| --- | --- | --- |
| 1.0 | 2026-09-07 | Accepted: operator answered "Да, принимаем эту основу" after the source/BDD impact notice |

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

## Unresolved bootstrap authority

The old package preserves v1 identity metadata for 19 agents, but its conversion authority_bindings list is empty.
That list is not the full runtime identity registry. Its emptiness alone does not invalidate genesis.
The package does not establish the versioned agent, Agent0-role, and control-group registry required by task execution.
Do not infer current control-group authority from a username or a v1 operator label.
The operator must identify the pilot authority set before canonical identity initialization.

## History and limits

Executor 0.8.0 remains immutable. Its existing tests describe its historical input boundary.
No canonical vNext activation exists. No ledger migration or payment occurs in this preparation.
Telegram integration, Domain-to-root credentials, automatic merges, and public exposure are outside this work.
